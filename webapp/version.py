"""Deployment revision (commit) reporting.

The service pins its *running* revision at import time; the deploy
directory's revision is re-read on every query — so after a ``git pull``
without a restart, the page can show "directory revision ≠ running
revision". When git is unavailable (no ``.git``, git not installed) the
fields come back unknown; verification itself is unaffected.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Only changes under these paths count as "the version changed". Web runtime
# artifacts (data/, report*.html, __pycache__) are .gitignore'd and never
# appear in status anyway. projects/ + examples/ count too: a different DBC
# revision changes verification results and is part of reproducibility.
RUNTIME_PATHS = (
    "crc_checker", "cli", "webapp",
    "frontend/src", "frontend/dist", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.js",
    "projects", "examples", "requirements.txt", "run_web.sh", "run_web.bat",
)

# Git calls must stay short: they run inside a synchronous HTTP request and
# must not stall the page.
_GIT_TIMEOUT = 3


def _git(root: Path, *args: str) -> str:
    """Run one git command against ``root`` and return stripped stdout.

    Git always writes UTF-8; decoding with the process locale (GBK on a Chinese
    Windows host) would blow up on a commit subject like "修复…" and leave
    ``stdout`` as None, so the encoding is pinned explicitly.
    """
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, timeout=_GIT_TIMEOUT,
        encoding="utf-8", errors="replace",
    ).stdout.strip()


def read_revision(root: Path) -> dict:
    """Read ``{commit, branch, subject, committed_at, dirty}`` for a checkout.

    Any failure (no repository, git missing, timeout) yields all-None fields
    instead of raising — an unknown revision must never break the page.
    """
    unknown = {"commit": None, "branch": None, "subject": None,
               "committed_at": None, "dirty": None}
    if not (Path(root) / ".git").exists():
        return unknown
    try:
        commit = _git(root, "rev-parse", "--verify", "HEAD")
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        subject = _git(root, "log", "-1", "--format=%s")
        committed_at = _git(root, "log", "-1", "--format=%cI")
        dirty = bool(_git(root, "status", "--porcelain",
                          "--untracked-files=normal", "--", *RUNTIME_PATHS))
    except (OSError, subprocess.SubprocessError):
        return unknown
    return {
        "commit": commit,
        "branch": branch,
        "subject": subject,
        "committed_at": committed_at,
        "dirty": dirty,
    }


class DeploymentVersion:  # pylint: disable=too-few-public-methods
    """The service's running commit (pinned) vs. the deploy directory's (live)."""

    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = Path(root)
        # Import-time snapshot: the code actually loaded by this process.
        self.running = read_revision(self.root)
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def info(self) -> dict:
        """Return the ``/api/version`` payload (checkout is re-read every call)."""
        checkout = read_revision(self.root)
        changed = None
        if self.running.get("commit") and checkout.get("commit"):
            changed = (self.running.get("commit") != checkout.get("commit")
                       or bool(checkout.get("dirty")) != bool(self.running.get("dirty")))
        return {
            "running": self.running,
            "checkout": checkout,
            "checkout_changed": changed,
            "started_at": self.started_at,
        }


# Import once together with the service code: HEAD at process start, not per request.
deployment_version = DeploymentVersion()
