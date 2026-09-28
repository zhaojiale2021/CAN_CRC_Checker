"""FastAPI application — REST API plus the built Vue frontend.

Design notes:
- Projects come from a server-side scan of ``customers/``; the browser only ever
  sends a project id, never a path.
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
from starlette.concurrency import run_in_threadpool

from webapp.catalog import PROJECT_ROOT, get_project, scan_projects
from webapp.service import RunStore, RunError, run_project
from webapp.version import deployment_version

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DATA_DIR = PROJECT_ROOT / "data" / "web"
UPLOADS_DIR = DATA_DIR / "uploads"
RUNS_DIR = DATA_DIR / "runs"

DEFAULT_MAX_UPLOAD_MB = 200
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._一-鿿 -]+")


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


def create_app(store: RunStore | None = None) -> FastAPI:
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

        raw_limit = max_frames.strip()
        try:
            frame_limit = int(raw_limit) if raw_limit else None
        except ValueError as exc:
            raise HTTPException(400, f"帧数上限必须是整数: {raw_limit}") from exc

        run_id = secrets.token_urlsafe(9)
        upload_dir = UPLOADS_DIR / run_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        trace_path = upload_dir / safe_filename(file.filename or "")

        limit = max_upload_bytes()
        written = 0
        try:
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

            outcome = await run_in_threadpool(
                run_project, project, trace_path, trace_path.name,
                frame_limit, only_failures.strip().lower() == "true",
                run_id, RUNS_DIR)
        except RunError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            # The trace is only needed while the run is in flight.
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
