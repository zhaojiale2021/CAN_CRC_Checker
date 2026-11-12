"""Package-relative web resources and configurable runtime storage paths."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = PACKAGE_DIR / "static" / "dist"
PROJECT_ROOT = PACKAGE_DIR.parent


def data_dir() -> Path:
    """Return writable web storage root, overridable for installed deployments.

    ``CRC_CHECKER_DATA_DIR`` names the directory containing ``uploads/`` and
    ``runs/``. Source checkouts keep ``data/web``; installed wheels default to
    the OS user's writable application-data directory.
    """
    override = os.environ.get("CRC_CHECKER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if (PROJECT_ROOT / "frontend").is_dir():
        # Preserve the existing repository-local runtime directory for source runs.
        return PROJECT_ROOT / "data" / "web"
    # Installed wheels generally live in read-only site-packages. Use the OS
    # user's writable data location unless the deployment supplies an override.
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "crc-checker" / "web"
