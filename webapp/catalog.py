"""Project catalog — one entry per ``customers/<oem>/<model>/`` directory.

The web UI never accepts filesystem paths: it shows the ids from this scan and
posts an id back. Path resolution stays server-side, exactly like the reference
tool's source-scan mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CUSTOMERS_DIR = PROJECT_ROOT / "customers"

# Config keys that are documentation only (see crc_checker.config.generate_example_config).
_COMMENT_PREFIX = "_"


@dataclass
class Project:  # pylint: disable=too-many-instance-attributes
    """A customer project: its config plus the DBC/trace files shipped next to it."""

    id: str                       # "gac/eea40" — the only handle the client ever sends
    oem: str
    model: str
    path: Path
    config_path: Path
    dbc_files: list[str] = field(default_factory=list)
    sample_traces: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def display_name(self) -> str:
        """Human-readable label for the UI."""
        return self.summary.get("name") or f"{self.oem.upper()} {self.model}"

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
        return "仅 Rolling Counter"
    if crc.get("auto_classify"):
        base = crc.get("preset") or "按 DBC 注释分类"
        return f"{base}(按 DBC 注释分类)"
    if crc.get("profile_by_width"):
        profiles = ", ".join(sorted(crc.get("profiles") or {})) or "内置"
        return f"按 CRC 位宽选 Profile({profiles})"
    if crc.get("custom"):
        return crc["custom"].get("name") or "自定义 CRC"
    return crc.get("preset") or "仅 Rolling Counter"


def _dataid_label(dataid: dict) -> str:
    if not dataid:
        return "无"
    source = Path(dataid.get("json") or dataid.get("xlsx") or "").name
    parts = [p for p in (source, dataid.get("mapping"), dataid.get("position")) if p]
    return " / ".join(parts) if parts else "有"


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


def scan_projects(root: Path | None = None) -> list[Project]:
    """Scan ``customers/<oem>/<model>/config.json`` and return the project list.

    Directories without a ``config.json`` are skipped — they are not runnable
    projects (the GAC platform dirs each carry one, so nothing else is lost).
    """
    base = Path(root) if root else CUSTOMERS_DIR
    if not base.is_dir():
        return []

    projects: list[Project] = []
    for oem_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for model_dir in sorted(p for p in oem_dir.iterdir() if p.is_dir()):
            config_path = model_dir / "config.json"
            if not config_path.is_file():
                continue
            config = _read_config(config_path)
            project_id = f"{oem_dir.name}/{model_dir.name}"
            projects.append(Project(
                id=project_id,
                oem=oem_dir.name,
                model=model_dir.name,
                path=model_dir,
                config_path=config_path,
                dbc_files=_list_dbc_names(model_dir, config),
                sample_traces=_list_sample_traces(model_dir),
                summary=_summarize(config),
            ))
    return projects


def get_project(project_id: str, root: Path | None = None) -> Project | None:
    """Look up one project by id (``None`` when unknown)."""
    for project in scan_projects(root):
        if project.id == project_id:
            return project
    return None
