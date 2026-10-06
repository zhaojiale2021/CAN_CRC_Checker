"""Firmware repository configuration — ``config/firmware.yaml`` plus env overrides.

A repo entry is addressed either by a local working copy (``path``, the common
case on a developer/deploy machine that already has mcu_app_j6 checked out) or
by a remote URL that the service mirror-clones into ``data/firmware/git/``.
Credentials stay with git on the server either way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIRMWARE_YAML = PROJECT_ROOT / "config" / "firmware.yaml"
MIRROR_DIR = PROJECT_ROOT / "data" / "firmware" / "git"


@dataclass
class FirmwareRepoCfg:
    """One firmware repository (id, display name, and how to reach it)."""

    id: str
    name: str
    url: str = ""        # remote URL for server-side mirror clones
    path: str = ""       # local working copy (wins over url when it exists)

    def local_root(self) -> Path | None:
        """The configured local checkout, or None (then the mirror is used)."""
        if not self.path:
            return None
        root = Path(self.path)
        return root if (root / ".git").exists() else None

    def to_dict(self) -> dict:
        """JSON shape for the API (never exposes local paths or credentials)."""
        return {"id": self.id, "name": self.name,
                "source": "local" if self.local_root() else "mirror"}


def _repo_env_key(repo_id: str, field: str) -> str:
    return "CRC_FIRMWARE_REPO_" + "".join(
        c if c.isalnum() else "_" for c in repo_id.upper()) + f"_{field}"


def _repo_from_entry(entry: dict) -> FirmwareRepoCfg:
    return FirmwareRepoCfg(
        id=str(entry.get("id", "")).strip(),
        name=str(entry.get("name") or entry.get("id", "")).strip(),
        url=str(entry.get("url", "")).strip(),
        path=str(entry.get("path", "")).strip(),
    )


def load_firmware_repos(config_path: Path | None = None,
                        env: dict | None = None) -> list[FirmwareRepoCfg]:
    """Load configured firmware repositories (missing file → empty list).

    Environment variable ``CRC_FIRMWARE_REPO_<ID>_PATH`` overrides the local
    path of one repo (empty string counts as unset), so machine-specific paths
    can stay out of git via .env — same idea as the reference tool's
    SOURCE_REPO_*_URL override.
    """
    path = Path(config_path) if config_path else FIRMWARE_YAML
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    entries = data.get("firmware_repositories") or []
    environment = env if env is not None else os.environ
    repos: list[FirmwareRepoCfg] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        repo = _repo_from_entry(entry)
        override = environment.get(_repo_env_key(repo.id, "PATH"), "")
        if override:
            repo.path = override
        repos.append(repo)
    return repos


def get_firmware_repo(repo_id: str,
                      config_path: Path | None = None,
                      env: dict | None = None) -> FirmwareRepoCfg | None:
    """Look up one firmware repository by id (None when unknown)."""
    for repo in load_firmware_repos(config_path, env):
        if repo.id == repo_id:
            return repo
    return None
