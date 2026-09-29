"""FastAPI application — REST API plus the built Vue frontend.

Design notes:
- Projects come from a server-side scan of ``customers/``; the browser only ever
  sends a project id, never a path.
- Firmware source mode (mcu_app_j6 commit 节点) resolves the E2E table from the
  firmware repo server-side; the browser sends repository_id + commit + model id.
- Uploaded traces land in ``data/web/uploads/<run_id>/`` and are deleted right
  after the run; the rendered HTML report is kept (bounded, LRU) so it can be
  downloaded or reopened.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from webapp.catalog import PROJECT_ROOT, get_project, scan_projects
from webapp.firmware.config import get_firmware_repo, load_firmware_repos
from webapp.firmware.gitops import GitError
from webapp.firmware.service import FirmwareRunError, run_firmware
from webapp.firmware.store import FirmwareStore
from webapp.service import RunStore, RunError, run_project
from webapp.version import deployment_version

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DATA_DIR = PROJECT_ROOT / "data" / "web"
UPLOADS_DIR = DATA_DIR / "uploads"
RUNS_DIR = DATA_DIR / "runs"

DEFAULT_MAX_UPLOAD_MB = 200
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._一-鿿 -]+")

FIRMWARE_STORE = FirmwareStore()


class FirmwareScanReq(BaseModel):
    """Body of ``POST /api/firmware/scan``."""

    repository_id: str
    commit: str


def max_upload_bytes() -> int:
    """Upload cap in bytes (``CRC_WEB_MAX_UPLOAD_MB`` overrides the default)."""
    raw = os.environ.get("CRC_WEB_MAX_UPLOAD_MB", "")
    try:
        megabytes = int(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return max(megabytes, 1) * 1024 * 1024


def safe_filename(name: str) -> str:
    """Reduce an upload name to a safe basename (keeps CJK, strips separators)."""
    base = Path(name or "").name.strip().replace("\\", "_").replace("/", "_")
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return cleaned or "trace.blf"


def _parse_frame_limit(max_frames: str) -> int | None:
    """``""``=配置默认, ``0``=不限, ``N``=前 N 帧;非法值是 400 不是 500。"""
    raw = max_frames.strip()
    try:
        return int(raw) if raw else None
    except ValueError as exc:
        raise HTTPException(400, f"帧数上限必须是整数: {raw}") from exc


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() == "true"


def create_app(store: RunStore | None = None) -> FastAPI:  # pylint: disable=too-many-statements
    """Build the ASGI app (``store`` is injectable for tests)."""
    api = FastAPI(title="CAN CRC Checker (Web)")
    run_store = store if store is not None else RunStore(RUNS_DIR)

    @api.get("/api/projects")
    def list_projects() -> dict:
        """Customer projects discovered under ``customers/<oem>/<model>/``."""
        projects = scan_projects()
        return {
            "projects": [p.to_dict() for p in projects],
            "count": len(projects),
        }

    @api.get("/api/version")
    def version() -> JSONResponse:
        """Running commit vs. deploy-directory commit (never cached)."""
        return JSONResponse(deployment_version.info(),
                            headers={"Cache-Control": "no-store"})

    @api.get("/api/firmware/repositories")
    def firmware_repositories() -> dict:
        """Configured firmware repos (URL/本地路径不透出,凭证在服务端 git 里)."""
        repos = load_firmware_repos()
        return {"repositories": [r.to_dict() for r in repos], "count": len(repos)}

    @api.post("/api/firmware/scan")
    def firmware_scan(req: FirmwareScanReq) -> dict:
        """Scan a firmware commit for per-model net_cfg directories.

        每个车型带 ``last_commit``(该车型 net_cfg 的最近一次提交,即它对应的
        commit 节点)与 ``supported``(生成物可否直接解析,不可时给原因)。
        """
        repo = get_firmware_repo(req.repository_id)
        if repo is None:
            raise HTTPException(404, f"未知固件仓库: {req.repository_id}")
        try:
            return FIRMWARE_STORE.scan(repo, req.commit)
        except GitError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def _save_upload(file: UploadFile, run_id: str) -> Path:
        """Stream one upload into ``data/web/uploads/<run_id>/`` (size-capped)."""
        upload_dir = UPLOADS_DIR / run_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        trace_path = upload_dir / safe_filename(file.filename or "")
        limit = max_upload_bytes()
        written = 0
        with open(trace_path, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        413, f"文件超过上限 {limit // (1024 * 1024)}MB,"
                             f"请截取日志后重试")
                handle.write(chunk)
        if written == 0:
            raise HTTPException(400, "上传的 trace 文件为空")
        return trace_path

    @api.post("/api/verify")
    async def verify(  # pylint: disable=too-many-locals
        project_id: str = Form(...),
        file: UploadFile = File(...),
        max_frames: str = Form(""),
        only_failures: str = Form("false"),
    ) -> dict:
        """Verify one uploaded trace against a project's config."""
        project = get_project(project_id)
        if project is None:
            raise HTTPException(404, f"未知项目: {project_id}")
        frame_limit = _parse_frame_limit(max_frames)

        run_id = secrets.token_urlsafe(9)
        upload_dir = UPLOADS_DIR / run_id
        try:
            trace_path = await _save_upload(file, run_id)
            outcome = await run_in_threadpool(
                run_project, project, trace_path, trace_path.name,
                frame_limit, _parse_bool(only_failures), run_id, RUNS_DIR)
        except RunError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            # The trace is only needed while the run is in flight.
            shutil.rmtree(upload_dir, ignore_errors=True)

        run_store.add(outcome)
        return outcome.to_dict()

    @api.post("/api/firmware/verify")
    async def firmware_verify(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
        repository_id: str = Form(...),
        commit: str = Form(...),
        model_id: str = Form(...),
        file: UploadFile = File(...),
        max_frames: str = Form(""),
        only_failures: str = Form("false"),
    ) -> dict:
        """Verify one uploaded trace against the firmware's actual E2E.

        与 /api/verify 共用上传/报告/结果结构;映射来源是
        ``repository_id + commit`` 节点下该车型的 net_cfg 生成物。
        """
        repo = get_firmware_repo(repository_id)
        if repo is None:
            raise HTTPException(404, f"未知固件仓库: {repository_id}")
        frame_limit = _parse_frame_limit(max_frames)

        run_id = secrets.token_urlsafe(9)
        upload_dir = UPLOADS_DIR / run_id
        try:
            trace_path = await _save_upload(file, run_id)

            def _run() -> dict:
                scan = FIRMWARE_STORE.scan(repo, commit)
                model = next((m for m in scan["models"] if m["id"] == model_id), None)
                if model is None:
                    raise FirmwareRunError(f"该 commit 下没有车型 {model_id}")
                if not model.get("supported"):
                    raise FirmwareRunError(
                        f"{model_id} 的 net_cfg 生成物暂不支持源码模式:"
                        f"{model.get('reason', '')}")
                return run_firmware(
                    FIRMWARE_STORE, repo, commit, model, trace_path,
                    trace_path.name, frame_limit, _parse_bool(only_failures),
                    run_id, RUNS_DIR)

            outcome = await run_in_threadpool(_run)
        except (FirmwareRunError, GitError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            shutil.rmtree(upload_dir, ignore_errors=True)

        run_store.add(outcome)
        return outcome.to_dict()

    @api.get("/api/runs/{run_id}/report.html")
    def run_report(run_id: str) -> FileResponse:
        """Download the self-contained HTML report of a finished run."""
        outcome = run_store.get(run_id)
        if outcome is None or not outcome.html_path:
            raise HTTPException(404, "报告不存在或已过期,请重新校验")
        if not outcome.html_path.exists():
            raise HTTPException(404, "报告文件已被清理,请重新校验")
        return FileResponse(str(outcome.html_path), media_type="text/html",
                            filename=f"crc_report_{run_id}.html")

    if FRONTEND_DIST.is_dir():
        # Mounted last so every /api route above wins.
        api.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="web")
    else:
        @api.get("/", response_class=HTMLResponse)
        def frontend_missing() -> str:
            return ("<h1>CAN CRC Checker (Web)</h1>"
                    "<p>前端尚未构建:在 <code>frontend/</code> 执行 "
                    "<code>npm install &amp;&amp; npm run build</code>,"
                    "或直接使用 <code>/docs</code> 里的 API。</p>")

    return api


app = create_app()
