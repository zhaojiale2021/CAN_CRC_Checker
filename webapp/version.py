"""部署版本(commit 节点)读取。

服务加载时固定"运行版本",部署目录的版本每次查询单独读取 —— 这样执行
``git pull`` 但没重启服务时,页面能提示"目录版本 ≠ 运行版本"。
Git 不可用(无 ``.git``、没装 git)时返回"版本未知",不影响校验功能。
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 只有这些路径下的改动才算"版本有修改"。Web 运行产物(data/、report*.html、
# __pycache__)被 .gitignore 忽略,本就不会出现在 status 里。
# customers/ 也算:换一版 DBC 会改变校验结论,属于"结果可复现"的一部分。
RUNTIME_PATHS = (
    "crc_checker", "cli", "webapp",
    "frontend/src", "frontend/dist", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.js",
    "customers", "requirements.txt", "run_web.sh", "run_web.bat",
)

# Git 调用必须短:它是同步 HTTP 请求的一部分,不能让页面卡住。
_GIT_TIMEOUT = 3


def _git(root: Path, *args: str) -> str:
    """Run one git command against ``root`` and return stripped stdout."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    ).stdout.strip()


def read_revision(root: Path) -> dict:
    """Read ``{commit, branch, subject, committed_at, dirty}`` for a checkout.

    Any failure (no repository, git missing, timeout) yields all-None fields
    instead of raising — "版本未知" must never break the page.
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
            "path": str(self.root),
        }


# Import once together with the service code: HEAD at process start, not per request.
deployment_version = DeploymentVersion()
