"""FirmwareStore — 按 repo+commit 解析与缓存固件 E2E 目录。

镜像克隆与增量 fetch 与参考工具的源码模式一致;scan/catalog 按
(repo, sha[, model]) 缓存,重复请求不重复读 blob。本地配置了 path 的仓库
直接用工作副本,免镜像克隆。
"""

from __future__ import annotations

import threading
from pathlib import Path

from webapp.firmware.config import FirmwareRepoCfg, MIRROR_DIR
from webapp.firmware.e2e import E2ECatalog, parse_model
from webapp.firmware.gitops import (
    GitError,
    ensure_repo,
    last_commit,
    list_tree,
    read_blob,
    resolve_commit,
    run_git,
)

_CALLOUT_PATH = "src/NetCom_Callout_Can.cpp"
_CFG_PATH = "src/NetE2E_Cfg.cpp"
# inc/net_cfg/NetE2E_Cfg.hpp 或生成器演进后的同级 NetE2E_Cfg.hpp
_HEADER_CANDIDATES = ("inc/net_cfg/NetE2E_Cfg.hpp", "NetE2E_Cfg.hpp")
_UNTABLED_REASON = ("net_cfg 生成物为 PduId 表驱动(无 CAN ID 注释),"
                    "CAN ID 需联 Com/CanIf 生成物才能解析,暂不支持源码模式;"
                    "请改用配置文件模式")


def _has_callout_headers(text: str) -> bool:
    """The callout comments (``/* Name: X, ID: 0xNN */``) carry the CAN IDs."""
    return "ID: 0x" in text and "Name: " in text


class FirmwareStore:
    """Firmware repositories + per-commit E2E catalogs (cached)."""

    def __init__(self, mirror_dir: Path | None = None):
        self.mirror_dir = Path(mirror_dir) if mirror_dir else MIRROR_DIR
        self._accessors: dict[str, tuple[str | None, str | None]] = {}
        self._git_locks: dict[str, threading.Lock] = {}
        self._scan_cache: dict[tuple[str, str], dict] = {}
        self._catalog_cache: dict[tuple[str, str, str], E2ECatalog] = {}

    # -- repo addressing ----------------------------------------------------

    def accessor(self, repo: FirmwareRepoCfg) -> tuple[str | None, str | None]:
        """(git_dir, cwd) addressing the repo: local path wins, else mirror clone."""
        cached = self._accessors.get(repo.id)
        if cached:
            return cached
        root = repo.local_root()
        if root is not None:
            accessor = (None, str(root))
        else:
            mirror = self.mirror_dir / f"{repo.id}.git"
            with self._git_lock(repo.id):
                ensure_repo(repo.url, str(mirror))
            accessor = (str(mirror), None)
        self._accessors[repo.id] = accessor
        return accessor

    def _git_lock(self, repo_id: str) -> threading.Lock:
        return self._git_locks.setdefault(repo_id, threading.Lock())

    def resolve(self, repo: FirmwareRepoCfg, ref: str) -> str:
        """Resolve a branch/tag/SHA into the full commit SHA."""
        git_dir, cwd = self.accessor(repo)
        return resolve_commit(git_dir, ref, cwd=cwd)

    def list_refs(self, repo: FirmwareRepoCfg) -> list[str]:
        """All branch/tag names (for the UI's commit hints)."""
        git_dir, cwd = self.accessor(repo)
        out = run_git(["for-each-ref", "--format=%(refname:short)", "--sort=refname"],
                      git_dir=git_dir, cwd=cwd)
        return [line for line in out.splitlines() if line.strip()]

    def last_commit(self, repo: FirmwareRepoCfg, ref: str, path: str) -> dict | None:
        """The model's commit 节点:最近一次改动该车型 net_cfg 的提交。"""
        git_dir, cwd = self.accessor(repo)
        return last_commit(git_dir, ref, path, cwd=cwd)

    # -- scan ---------------------------------------------------------------

    def scan(self, repo: FirmwareRepoCfg, ref: str) -> dict:
        """Scan a commit's tree for per-model net_cfg directories.

        Returns {repository, resolved_commit, models, diagnostics}; per model:
        id, name, oem, path, whether source mode supports it (and why not), and
        the last commit that touched its net_cfg.
        """
        sha = self.resolve(repo, ref)
        key = (repo.id, sha)
        if key not in self._scan_cache:
            self._scan_cache[key] = self._scan_commit(repo, sha)
        payload = self._scan_cache[key]
        return {"repository": repo.to_dict(), "resolved_commit": sha, **payload}

    def _scan_commit(self, repo: FirmwareRepoCfg, sha: str) -> dict:
        git_dir, cwd = self.accessor(repo)
        models: list[dict] = []
        diagnostics: list[dict] = []
        for cpj_name in sorted(list_tree(git_dir, sha, cwd=cwd)):
            if not cpj_name.startswith("cpj_"):
                continue
            for model_name, model_path in self._model_dirs(git_dir, cwd, sha, cpj_name):
                models.append(self._describe_model(git_dir, cwd, sha,
                                                   cpj_name, model_name, model_path))
        if not models:
            diagnostics.append({
                "level": "warning",
                "message": "该 commit 下没有找到 cpj_*/net_cfg/<车型> 目录",
            })
        return {"models": models, "diagnostics": diagnostics}

    @staticmethod
    def _model_dirs(git_dir, cwd, sha: str, cpj_name: str) -> list[tuple[str, str]]:
        """(model_name, net_cfg_path) pairs: ``cpj_<oem>/net_cfg/<m>`` plus the
        ``cpj_<oem>/veh_<m>/net_cfg`` layout used by some Chery models."""
        found: list[tuple[str, str]] = []
        children = list_tree(git_dir, sha, cpj_name, cwd=cwd)
        for name, kind in sorted(children.items()):
            if name == "net_cfg" and kind == "tree":
                for model_name, kind2 in sorted(
                        list_tree(git_dir, sha, f"{cpj_name}/net_cfg", cwd=cwd).items()):
                    if kind2 == "tree":
                        found.append((model_name, f"{cpj_name}/net_cfg/{model_name}"))
            elif name.startswith("veh_") and kind == "tree":
                net_cfg = f"{cpj_name}/{name}/net_cfg"
                if list_tree(git_dir, sha, net_cfg, cwd=cwd):
                    found.append((name[len("veh_"):], net_cfg))
        return found

    def _describe_model(self, git_dir, cwd, sha: str, oem: str,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                        model_name: str, model_path: str) -> dict:
        callout = self._read_optional(git_dir, cwd, sha, f"{model_path}/{_CALLOUT_PATH}")
        supported = bool(callout) and _has_callout_headers(callout)
        try:
            node = last_commit(git_dir, sha, model_path, cwd=cwd)
        except GitError:
            node = None
        return {
            "id": f"{oem}/{model_name}",
            "name": model_name,
            "oem": oem,
            "path": model_path,
            "supported": supported,
            "reason": "" if supported else _UNTABLED_REASON,
            "callout_path": f"{model_path}/{_CALLOUT_PATH}" if callout else "",
            "last_commit": node,
        }

    def _read_optional(self, git_dir, cwd, sha: str, path: str) -> str:
        try:
            return read_blob(git_dir, sha, path, cwd=cwd)
        except GitError:
            return ""

    # -- catalog ------------------------------------------------------------

    def catalog(self, repo: FirmwareRepoCfg, sha: str, model: dict) -> E2ECatalog:
        """Parse one model's E2E catalog at a commit (cached by repo+sha+model)."""
        key = (repo.id, sha, model["id"])
        if key in self._catalog_cache:
            return self._catalog_cache[key]
        git_dir, cwd = self.accessor(repo)
        callout = self._read_optional(git_dir, cwd, sha, f"{model['path']}/{_CALLOUT_PATH}")
        cfg = self._read_optional(git_dir, cwd, sha, f"{model['path']}/{_CFG_PATH}")
        header = ""
        for candidate in _HEADER_CANDIDATES:
            header = self._read_optional(git_dir, cwd, sha, f"{model['path']}/{candidate}")
            if header:
                break
        if not callout:
            raise GitError(f"该 commit 下没有 callout 生成物: {model['path']}/{_CALLOUT_PATH}")
        parsed = parse_model(callout, cfg, header,
                             config_path=f"{repo.id}@{sha[:8]}:{model['path']}")
        self._catalog_cache[key] = parsed
        return parsed
