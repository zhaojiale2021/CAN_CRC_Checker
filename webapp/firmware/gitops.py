"""Git operations on the firmware repository.

Only ever calls git with an argument array (no shell interpolation), and never
touches or returns credentials — ssh keys / credential helpers stay with git on
the server, like the reference tool's source mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

FETCH_TIMEOUT = 1800  # 首次镜像克隆/增量 fetch 上限(秒)
READ_TIMEOUT = 120

# git 输出恒为 UTF-8;按进程 locale(中文 Windows = GBK)解码会把含中文的
# 提交标题读成 None,必须显式指定编码(见 tests/test_webapp.py 的回归用例)。
_GIT_KWARGS = {"encoding": "utf-8", "errors": "replace"}


class GitError(Exception):
    """Git 命令失败;message 为可直接展示的诊断信息。"""


def run_git(args: List[str], git_dir: Optional[str] = None, cwd: Optional[str] = None,
            timeout: int = READ_TIMEOUT, binary: bool = False):
    """Run one git command. ``args`` is an array; never routed through a shell."""
    cmd = ["git"]
    if git_dir:
        cmd += ["--git-dir", str(git_dir)]
    try:
        proc = subprocess.run(cmd + args, capture_output=True, timeout=timeout,
                              cwd=cwd, check=True, **_GIT_KWARGS)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"Git 命令超时({timeout}s): git {' '.join(args[:3])} ...") from exc
    except subprocess.CalledProcessError as exc:
        err = ((exc.stderr or "") + (exc.stdout or "")).strip()
        raise GitError(f"Git 命令失败: git {' '.join(args)}\n{err}") from exc
    except OSError as exc:
        raise GitError(f"无法执行 git: {exc}") from exc
    return proc.stdout if binary else (proc.stdout or "").strip()


def ensure_repo(url: str, git_dir: str, timeout: int = FETCH_TIMEOUT) -> None:
    """Ensure a local mirror clone exists and is current.

    A fetch failure is tolerated (offline mirror deployments must keep working
    with already-fetched commits); a genuinely missing commit is reported later
    by :func:`resolve_commit`.
    """
    if not url:
        raise GitError("仓库未配置 URL(请在 config/firmware.yaml 中配置 url 或 path)")
    mirror = Path(git_dir)
    if not (mirror / "HEAD").exists():
        run_git(["clone", "--mirror", url, str(mirror)], timeout=timeout)
        return
    current = run_git(["config", "--get", "remote.origin.url"], git_dir=str(mirror))
    if current != url:
        run_git(["remote", "set-url", "origin", url], git_dir=str(mirror))
    try:
        run_git(["fetch", "origin", "--prune"], git_dir=str(mirror), timeout=timeout)
    except GitError:
        pass


def resolve_commit(git_dir: Optional[str], ref: str, cwd: Optional[str] = None) -> str:
    """ref(完整/短 SHA、分支、tag)→ 完整 commit SHA。

    非裸工作副本的远端分支位于 refs/remotes/origin/* 命名空间,因此裸分支名
    解析失败时回退尝试一次;解析失败附带相近分支名,而不是 git 原始 fatal。
    """
    if not ref or not str(ref).strip():
        raise GitError("commit 不能为空")
    ref = str(ref).strip()
    for candidate in (ref, f"refs/remotes/origin/{ref}"):
        try:
            out = run_git(["rev-parse", "--verify", "--end-of-options",
                           candidate + "^{commit}"], git_dir=git_dir, cwd=cwd)
        except GitError:
            continue
        if out:
            return out.splitlines()[0]
    raise GitError(
        f"无法解析 commit: {ref}(支持完整/短 SHA、分支、tag;"
        f"本地工作副本的远端分支也可写 origin/<分支>)" + _similar_refs(git_dir, ref, cwd))


def _similar_refs(git_dir: Optional[str], ref: str, cwd: Optional[str] = None,
                  limit: int = 8) -> str:
    """List branch names close to ``ref`` and append them to the error message."""
    try:
        out = run_git(["for-each-ref", "--format=%(refname:short)"],
                      git_dir=git_dir, cwd=cwd)
    except GitError:
        return ""
    segments = [s for s in ref.lower().split("/") if s]
    names = [n for n in out.splitlines() if n.strip()]

    def segs(name: str):
        return [s for s in name.lower().split("/") if s]

    matched = [n for n in names if all(s in segs(n) for s in segments)]
    if not matched and segments:
        matched = [n for n in names if segments[0] in segs(n)]
    if not matched:
        return ""
    return "\n相近分支参考: " + ", ".join(matched[:limit])


def list_tree(git_dir: Optional[str], sha: str, path: str = "",
              cwd: Optional[str] = None) -> Dict[str, str]:
    """List direct children of ``path`` at ``sha`` → {name: 'tree'|'blob'}.

    Git does not track empty directories, so empty dirs never appear here.
    """
    path = (path or "").strip("/")
    args = ["ls-tree", sha]
    if path:
        args += ["--", path + "/"]
    out = run_git(args, git_dir=git_dir, cwd=cwd)
    prefix = path + "/" if path else ""
    entries: Dict[str, str] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        meta, name = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 2 or not name.startswith(prefix):
            continue
        entries[name[len(prefix):]] = parts[1]  # blob | tree | commit(submodule)
    return entries


def read_blob(git_dir: Optional[str], sha: str, path: str,
              cwd: Optional[str] = None) -> str:
    """Read one file's text content at ``sha``."""
    return run_git(["show", f"{sha}:{path}"], git_dir=git_dir, cwd=cwd)


def last_commit(git_dir: Optional[str], ref: str, path: str,
                cwd: Optional[str] = None) -> Optional[dict]:
    """The most recent commit that touched ``path`` (the model's commit 节点).

    Returns {commit, subject, committed_at} or None when the path has no
    history at ``ref`` (e.g. the model does not exist at that node).
    """
    out = run_git(
        ["log", "-1", "--format=%H%x1f%s%x1f%cI", ref, "--", path],
        git_dir=git_dir, cwd=cwd)
    if not out:
        return None
    fields = out.split("\x1f")
    if len(fields) < 3:
        return None
    return {"commit": fields[0], "subject": fields[1], "committed_at": fields[2]}
