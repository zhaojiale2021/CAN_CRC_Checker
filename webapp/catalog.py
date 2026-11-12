"""Project catalog — one entry per project directory with a ``config.json``.

The web UI never accepts filesystem paths: it shows the ids from this scan and
posts an id back. Path resolution stays server-side.

Layouts supported under the scan root:

* ``<group>/<name>/config.json`` — grouped (``group/name`` ids)
* ``<name>/config.json``         — flat (``<root-name>/<name>`` ids)

The scan root is ``projects/`` by default. Set ``CRC_CHECKER_PROJECTS_DIR`` to
scan another directory; when neither exists, the shipped ``examples/`` demo is
used.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = PROJECT_ROOT / "projects"
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# Scan cache: root -> (project-tree signature, external-DBC signature, projects).
_SCAN_CACHE: dict[str, tuple[tuple, tuple, list[Project]]] = {}
_SCAN_CACHE_MAX_ROOTS = 8
_SCAN_LOCK = threading.Lock()


def projects_root() -> Path:
    """Directory scanned by the web project list."""
    override = os.environ.get("CRC_CHECKER_PROJECTS_DIR", "")
    if override:
        return Path(override).resolve()
    return PROJECTS_DIR if PROJECTS_DIR.is_dir() else EXAMPLES_DIR


@dataclass
class Project:  # pylint: disable=too-many-instance-attributes
    """A project: its config plus the DBC/trace files shipped next to it."""

    id: str                       # "group/name" — the only handle the client sends
    oem: str                      # group name (or the scan-root name)
    model: str
    path: Path
    config_path: Path
    dbc_files: list[str] = field(default_factory=list)
    sample_traces: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def display_name(self) -> str:
        """Human-readable label for the UI."""
        return self.summary.get("name") or self.model

    def to_dict(self) -> dict:
        """JSON shape returned by ``GET /api/projects``."""
        return {
            "id": self.id,
            "oem": self.oem,
            "model": self.model,
            "name": self.display_name(),
            "dbc_files": self.dbc_files,
            "sample_traces": self.sample_traces,
            "summary": self.summary,
        }


def _read_config(config_path: Path) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _crc_label(crc: dict) -> str:
    """Describe the CRC configuration in one line for the project picker."""
    if not crc:
        return "RC only"
    if crc.get("auto_classify"):
        base = crc.get("preset") or "from DBC comments"
        return f"{base} (from DBC comments)"
    if crc.get("profile_by_width"):
        profiles = ", ".join(sorted(crc.get("profiles") or {})) or "built-in"
        return f"profile by CRC width ({profiles})"
    if crc.get("custom"):
        return crc["custom"].get("name") or "custom CRC"
    return crc.get("preset") or "RC only"


def _dataid_label(dataid: dict) -> str:
    if not dataid:
        return "none"
    source = Path(dataid.get("json") or dataid.get("xlsx") or "").name
    parts = [p for p in (source, dataid.get("mapping"), dataid.get("position")) if p]
    return " / ".join(parts) if parts else "yes"


def _summarize(config: dict) -> dict:
    """Pick the fields the project picker shows (raw config is not exposed)."""
    crc = config.get("crc") or {}
    rng = config.get("range") or {}
    dataid = config.get("dataid") or {}
    flt = config.get("filter") or {}
    return {
        "crc": _crc_label(crc),
        "crc_preset": crc.get("preset") or "",
        "crc_byte_swap": bool(crc.get("byte_swap")),
        "profile_by_width": bool(crc.get("profile_by_width")),
        "crc_skip": list(crc.get("skip") or []),
        "range": rng.get("mode") or "exclude_crc",
        "range_start": rng.get("start_byte", 0),
        "range_end": rng.get("end_byte", -1),
        "dataid": _dataid_label(dataid),
        "dbc_merge": bool(config.get("dbc_merge")),
        "default_max_frames": flt.get("max_frames"),
        "rc_max_valid": (config.get("rc") or {}).get("max_valid"),
    }


def _list_dbc_names(project_dir: Path, config: dict) -> list[str]:
    """DBC file names from the configured paths (falling back to ``dbc/``)."""
    configured = []
    if config.get("dbc"):
        configured.append(str(config["dbc"]))
    configured.extend(str(p) for p in (config.get("dbcs") or []))
    names: list[str] = []
    for raw in configured:
        path = Path(raw)
        if not path.is_absolute():
            path = project_dir / path
        if path.is_dir():
            names.extend(sorted(f.name for f in path.glob("*.dbc")))
        elif path.is_file():
            names.append(path.name)
    if not names:
        names = sorted(f.name for f in (project_dir / "dbc").glob("*.dbc"))
    return names


def _list_sample_traces(project_dir: Path) -> list[str]:
    trace_dir = project_dir / "trace"
    if not trace_dir.is_dir():
        return []
    return sorted(
        f.name for f in trace_dir.iterdir()
        if f.is_file() and f.suffix.lower() != ".dbc"
    )


def _project_for(group: str, model_dir: Path) -> Project:
    config_path = model_dir / "config.json"
    config = _read_config(config_path)
    return Project(
        id=f"{group}/{model_dir.name}",
        oem=group,
        model=model_dir.name,
        path=model_dir,
        config_path=config_path,
        dbc_files=_list_dbc_names(model_dir, config),
        sample_traces=_list_sample_traces(model_dir),
        summary=_summarize(config),
    )


def _dir_signature(base: Path) -> tuple:
    """Stat-only snapshot of the project tree, three levels deep.

    Layout is ``<root>/<group>/<project>/...``: a project's ``config.json``
    and its ``dbc/`` + ``trace/`` directories sit two levels below the scan
    root, so three stat levels cover every file the scan reads. Files are
    listed individually because a *directory's* mtime only moves on
    create/delete/rename — editing config.json in place changes the file's
    own mtime, not its parent's.
    """
    try:
        def snapshot(path: Path, depth: int) -> tuple:
            entries = []
            for child in sorted(path.iterdir()):
                try:
                    stat = child.stat()
                    # Size alongside mtime: on Windows two writes within one
                    # timer tick (~15ms) can carry the same mtime.
                    item = (child.name, stat.st_size, stat.st_mtime_ns)
                except OSError:
                    continue
                if depth > 1 and child.is_dir():
                    try:
                        item = (*item, snapshot(child, depth - 1))
                    except OSError:
                        pass
                entries.append(item)
            return tuple(entries)

        return snapshot(base, 4)
    except OSError:
        return ()


def _external_dbc_paths(base: Path) -> tuple[Path, ...]:
    """Return configured DBC paths that live outside the scanned tree."""
    paths = set()
    for entry in sorted(p for p in base.iterdir() if p.is_dir()):
        model_dirs = [entry] if (entry / "config.json").is_file() else sorted(
            p for p in entry.iterdir() if p.is_dir())
        for model_dir in model_dirs:
            config_path = model_dir / "config.json"
            if not config_path.is_file():
                continue
            config = _read_config(config_path)
            configured = ([config["dbc"]] if config.get("dbc") else [])
            configured.extend(config.get("dbcs") or [])
            for raw in configured:
                path = Path(str(raw))
                if not path.is_absolute():
                    path = model_dir / path
                path = path.resolve()
                try:
                    path.relative_to(model_dir.resolve())
                except ValueError:
                    paths.add(path)
    return tuple(sorted(paths))


def _paths_signature(paths: tuple[Path, ...]) -> tuple:
    """Stat external DBC files/directories and their immediate DBC children."""
    signatures = []
    for path in paths:
        try:
            stat = path.stat()
            item = (str(path), stat.st_mode, stat.st_size, stat.st_mtime_ns,
                    stat.st_ctime_ns)
        except OSError:
            item = (str(path), None)
        if path.is_dir():
            children = []
            try:
                for child in sorted(path.glob("*.dbc")):
                    try:
                        child_stat = child.stat()
                        children.append((child.name, child_stat.st_size,
                                         child_stat.st_mtime_ns, child_stat.st_ctime_ns))
                    except OSError:
                        continue
            except OSError:
                pass
            item = (*item, tuple(children))
        signatures.append(item)
    return tuple(signatures)


def scan_projects(root: Path | None = None) -> list[Project]:
    """Scan the projects directory and return every runnable project.

    Directories without a ``config.json`` are skipped (both as a project and
    as a group). Results are cached per root until the stat signature changes.
    """
    base = Path(root) if root else projects_root()
    if not base.is_dir():
        return []

    key = str(base.resolve())
    external_paths = _external_dbc_paths(base)
    project_signature = _dir_signature(base)
    external_signature = _paths_signature(external_paths)
    with _SCAN_LOCK:
        cached = _SCAN_CACHE.get(key)
        if cached is not None and (
                cached[0] == project_signature
                and cached[1] == external_signature):
            return cached[2]

    projects = _scan_projects_uncached(base)
    with _SCAN_LOCK:
        # Tests pass a fresh tmp root per case — keep the cache bounded.
        if key not in _SCAN_CACHE and len(_SCAN_CACHE) >= _SCAN_CACHE_MAX_ROOTS:
            _SCAN_CACHE.pop(next(iter(_SCAN_CACHE)))
        _SCAN_CACHE[key] = (project_signature, external_signature, projects)
    return projects


def _scan_projects_uncached(base: Path) -> list[Project]:
    """Read every project under ``base`` (config.json, DBC/trace listings)."""
    projects: list[Project] = []
    for entry in sorted(p for p in base.iterdir() if p.is_dir()):
        if (entry / "config.json").is_file():
            projects.append(_project_for(base.name, entry))
            continue
        for model_dir in sorted(p for p in entry.iterdir() if p.is_dir()):
            if (model_dir / "config.json").is_file():
                projects.append(_project_for(entry.name, model_dir))
    return projects


def get_project(project_id: str, root: Path | None = None) -> Project | None:
    """Look up one project by id (``None`` when unknown)."""
    for project in scan_projects(root):
        if project.id == project_id:
            return project
    return None
