"""FastAPI application — REST API plus the built Vue frontend.

Design notes:
- Projects come from a server-side scan of ``projects/`` (or the directory in
  ``CRC_CHECKER_PROJECTS_DIR``); the browser only ever sends a project id,
  never a path.
- Uploaded traces land in ``data/web/uploads/<run_id>/`` and are deleted right
  after the run; the rendered HTML report is kept (bounded, LRU) so it can be
  downloaded or reopened.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
from concurrent.futures import ThreadPoolExecutor  # pylint: disable=no-name-in-module
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from crc_checker.config import DEFAULT_MAX_FRAMES
from crc_checker.verify.cancellation import VerificationCancelled
from crc_checker.crc.presets import get_preset, get_validation, list_presets
from webapp.paths import FRONTEND_DIST, data_dir
from webapp.catalog import Project, get_project, scan_projects
from webapp.service import (JobRegistry, RunStore, RunError, run_project)
from webapp.version import deployment_version

logger = logging.getLogger("crc_checker.web")

# Static resources and runtime paths come from webapp.paths.
DATA_DIR = data_dir()
UPLOADS_DIR = DATA_DIR / "uploads"  # compatibility alias for existing callers
RUNS_DIR = DATA_DIR / "runs"       # compatibility alias for existing callers

DEFAULT_MAX_UPLOAD_MB = 200
MAX_DBC_UPLOADS = 10
TRACE_SUFFIXES = frozenset({".blf", ".asc", ".mf4", ".trc", ".csv", ".log", ".txt"})
DBC_SUFFIXES = frozenset({".dbc"})
DATAID_SUFFIXES = frozenset({".json", ".xlsx", ".xls"})
# Sections the manual-upload form may fill in. Everything path-bearing is set
# server-side from the uploads, so the browser still never sends a path.
MANUAL_SECTIONS = ("crc", "range", "dataid", "filter", "signals", "rc", "output")
MANUAL_SCALARS = ("dbc_merge",)
MANUAL_FORBIDDEN = (
    ("dataid", "xlsx"),
    ("dataid", "json"),
    ("dataid", "mapping_file"),
    ("signals", "patterns_file"),
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._一-鿿 -]+")
# Windows device names are not valid file names even with an extension
# (``CON``, ``NUL.blf``, ``COM1`` …); opening them targets the device.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _drop_bind_any_banner(record: logging.LogRecord) -> bool:
    """Hide uvicorn's "Uvicorn running on http://0.0.0.0:PORT" line.

    ``0.0.0.0`` is a bind address, not one a browser can open; the launchers
    print the addresses that actually work. Records from other hosts pass
    through untouched.
    """
    message = record.getMessage()
    return not (message.startswith("Uvicorn running on") and "0.0.0.0" in message)


def max_upload_bytes() -> int:
    """Upload cap in bytes (``CRC_WEB_MAX_UPLOAD_MB`` overrides the default)."""
    raw = os.environ.get("CRC_WEB_MAX_UPLOAD_MB", "")
    try:
        megabytes = int(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return max(megabytes, 1) * 1024 * 1024


def safe_filename(name: str) -> str:
    """Reduce an upload name to a safe basename (keeps CJK, strips separators).

    Upload names may carry the uploader's Windows path; backslashes are
    normalised to slashes *before* the basename is taken so this works the
    same on a Linux server (where ``C:\\logs\\x.blf`` would otherwise be a
    legal single filename).
    """
    base = Path((name or "").replace("\\", "/")).name.strip()
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    # ``CON``/``NUL.blf``/``COM1`` resolve to devices on Windows, not files.
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned or "trace.blf"


def _parse_frame_limit(max_frames: str) -> int | None:
    """``""`` = config default, ``0`` = unlimited, ``N`` = first N frames.

    Invalid values are a 400, not a 500.
    """
    raw = max_frames.strip()
    try:
        value = int(raw) if raw else None
    except ValueError as exc:
        raise HTTPException(400, f"帧数上限必须是整数: {raw}") from exc
    if value is not None and value < 0:
        # Negative used to fall through to "unlimited", silently disabling the
        # cap for an invalid request.
        raise HTTPException(400, f"帧数上限不能为负数: {value}")
    return value


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() == "true"


def _manual_config(raw: str, dbc_paths: list[Path], trace_path: Path,
                   dataid_path: Path | None) -> dict:
    """Build the run config for a manual upload.

    The browser fills in the algorithm/range/DataID/filter sections; every
    filesystem path is overwritten with the server-side upload location, so a
    hand-written ``config`` can never point the server at another file.
    """
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"配置 JSON 解析失败: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "配置必须是 JSON 对象")

    unknown = sorted(set(data) - set(MANUAL_SECTIONS) - set(MANUAL_SCALARS))
    if unknown:
        raise HTTPException(400, f"网页版不支持这些配置项: {', '.join(unknown)}")
    for section in MANUAL_SECTIONS:
        if section in data and not isinstance(data[section], dict):
            raise HTTPException(400, f"配置项 {section} 必须是 JSON 对象")
    for scalar in MANUAL_SCALARS:
        if scalar in data and not isinstance(data[scalar], bool):
            raise HTTPException(400, f"配置项 {scalar} 必须是布尔值")
    for section, key in MANUAL_FORBIDDEN:
        if key in (data.get(section) or {}):
            raise HTTPException(400, f"网页版不接受 {section}.{key},请使用上传文件")

    if dataid_path is not None:
        dataid = data.setdefault("dataid", {})
        if dataid_path.suffix.lower() == ".json":
            dataid["json"] = str(dataid_path)
        else:
            dataid["xlsx"] = str(dataid_path)

    output = data.setdefault("output", {})
    output.pop("file", None)
    output["format"] = "html"

    data["dbc"] = ""
    data["dbcs"] = [str(path) for path in dbc_paths]
    data["traces"] = [str(trace_path)]
    return data


def _manual_project(upload_dir: Path, config_path: Path,
                    dbc_paths: list[Path]) -> Project:
    """Synthetic project entry so the shared runner/report path stays unchanged."""
    return Project(
        id="manual",
        oem="manual",
        model="手动配置",
        path=upload_dir,
        config_path=config_path,
        dbc_files=[path.name for path in dbc_paths],
        sample_traces=[],
        summary={},
    )


def create_app(store: RunStore | None = None) -> FastAPI:  # pylint: disable=too-many-statements,too-many-locals
    """Build the ASGI app (``store`` is injectable for tests)."""
    api = FastAPI(title="CAN CRC Checker (Web)")
    data_root = data_dir()
    uploads_dir = data_root / "uploads"
    runs_dir = store.runs_dir if store is not None else data_root / "runs"
    run_store = store if store is not None else RunStore(runs_dir)
    job_registry = JobRegistry()
    worker_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crc-job")
    api.state.job_registry = job_registry
    api.state.worker_pool = worker_pool
    api.state.run_store = run_store
    api.state.uploads_dir = uploads_dir
    # Uploads are deleted in each job's terminal cleanup. A crash or killed
    # process leaves them behind forever, so clear staging on startup.
    shutil.rmtree(uploads_dir, ignore_errors=True)

    @api.on_event("shutdown")
    def shutdown_workers() -> None:
        """Cancel queued jobs, signal active runs, and clean staged uploads."""
        job_ids = job_registry.cancel_all()
        worker_pool.shutdown(wait=False, cancel_futures=True)
        for job_id in job_ids:
            state = job_registry.get(job_id)
            if state is not None and state["status"] == "cancelled":
                shutil.rmtree(uploads_dir / job_id, ignore_errors=True)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def enqueue(project: Project, trace_path: Path, trace_name: str,
                frame_limit: int | None, only_failures: bool, run_id: str,
                upload_dir: Path | None) -> dict:
        """Register and schedule a staged run; caller owns staging on errors."""
        job = job_registry.create(run_id)
        if job is None:
            raise HTTPException(503, "校验任务队列已满,请稍后重试")

        def worker() -> None:
            if not job_registry.start(job.job_id):
                if upload_dir is not None:
                    shutil.rmtree(upload_dir, ignore_errors=True)
                return
            try:
                outcome = run_project(
                    project, trace_path, trace_name, frame_limit, only_failures,
                    job.job_id, run_store.runs_dir,
                    frame_progress_callback=lambda done, _total:
                        job_registry.progress(job.job_id, done),
                    cancellation_token=job.token)
                published = job_registry.finish_success(
                    job.job_id, outcome.to_dict(), lambda: run_store.add(outcome))
                if not published:
                    run_store.discard(outcome)
            except VerificationCancelled as exc:
                job_registry.finish(
                    job.job_id, "cancelled", error="任务已取消",
                    processed_frames=exc.processed_frames)
            except RunError as exc:
                job_registry.finish(job.job_id, "failed", error=str(exc))
            except Exception:  # noqa: BLE001 - shield unexpected worker failures  # pylint: disable=broad-exception-caught
                logger.exception("Unexpected verification job failure: %s", job.job_id)
                job_registry.finish(job.job_id, "failed",
                                    error="服务器内部错误,请重试或查看服务端日志")
            finally:
                if upload_dir is not None:
                    shutil.rmtree(upload_dir, ignore_errors=True)

        try:
            worker_pool.submit(worker)
        except RuntimeError as exc:
            job_registry.finish(job.job_id, "failed", error="任务无法启动,请重试")
            if upload_dir is not None:
                shutil.rmtree(upload_dir, ignore_errors=True)
            raise HTTPException(503, "校验任务无法启动,请重试") from exc
        return {"job_id": job.job_id, "status": "queued"}

    @api.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse:
        """Last-resort 500 for anything the routes did not anticipate.

        Mirrors the CLI's rule that a traceback must never reach the user:
        the response is a generic message, the detail goes to the server log
        only. (Starlette logs the exception again after the response — the
        duplication is expected.)
        """
        logger.error("Unhandled error on %s %s: %s",
                     request.method, request.url.path, exc)
        return JSONResponse(status_code=500,
                            content={"message": "服务器内部错误,请重试或查看服务端日志"})

    @api.get("/api/limits")
    def limits() -> dict:
        """Upload caps and defaults the page would otherwise hardcode.

        Single source of truth: when the server's cap changes (e.g. via
        ``CRC_WEB_MAX_UPLOAD_MB``), the page follows instead of lying.
        """
        return {
            "max_upload_mb": max_upload_bytes() // (1024 * 1024),
            "max_dbc_files": MAX_DBC_UPLOADS,
            "manual_default_frames": DEFAULT_MAX_FRAMES,
        }

    @api.get("/api/projects")
    def list_projects() -> dict:
        """Projects discovered under the projects directory."""
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

    @api.get("/api/presets")
    def crc_presets() -> dict:
        """Built-in CRC / checksum algorithms, with validation status."""
        presets = []
        for name in list_presets():
            params = get_preset(name)
            status, note = get_validation(name)
            presets.append({
                "name": name,
                "width": params.width,
                "checksum_type": params.checksum_type,
                "validated": status == "validated",
                "note": note,
            })
        return {"presets": presets}

    async def _save_upload(file: UploadFile, run_id: str,
                           subdir: str = "",
                           allowed: frozenset = TRACE_SUFFIXES,
                           label: str = "trace") -> Path:
        """Stream one upload into ``data/web/uploads/<run_id>/`` (size-capped)."""
        upload_dir = uploads_dir / run_id / subdir
        upload_dir.mkdir(parents=True, exist_ok=True)
        name = safe_filename(file.filename or "")
        if Path(name).suffix.lower() not in allowed:
            raise HTTPException(400, f"{label} 文件类型不支持: {name}")
        target = upload_dir / name
        if target.exists():
            raise HTTPException(400, f"{label} 文件名重复: {name}")
        limit = max_upload_bytes()
        written = 0
        with open(target, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        413, f"文件超过上限 {limit // (1024 * 1024)}MB,"
                             f"请截取日志后重试")
                handle.write(chunk)
        if written == 0:
            raise HTTPException(400, f"上传的 {label} 文件为空")
        return target

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
        upload_dir = uploads_dir / run_id
        try:
            trace_path = await _save_upload(file, run_id)
            result = enqueue(project, trace_path, trace_path.name, frame_limit,
                             _parse_bool(only_failures), run_id, upload_dir)
        except BaseException:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise
        return JSONResponse(status_code=202, content=result)

    @api.post("/api/verify-manual")
    async def verify_manual(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
        dbcs: list[UploadFile] = File(...),
        trace: UploadFile = File(...),
        config: str = Form("{}"),
        dataid: Optional[UploadFile] = File(None),
        max_frames: str = Form(""),
        only_failures: str = Form("false"),
    ) -> dict:
        """Verify an uploaded trace with uploaded DBC files and a page-filled config."""
        if not dbcs:
            raise HTTPException(400, "至少上传一个 DBC 文件")
        if len(dbcs) > MAX_DBC_UPLOADS:
            raise HTTPException(
                400, f"一次最多上传 {MAX_DBC_UPLOADS} 个 DBC 文件")
        frame_limit = _parse_frame_limit(max_frames)

        run_id = secrets.token_urlsafe(9)
        upload_dir = uploads_dir / run_id
        try:
            dbc_paths = []
            for item in dbcs:
                dbc_paths.append(
                    await _save_upload(item, run_id, "dbc", DBC_SUFFIXES, "DBC"))
            trace_path = await _save_upload(trace, run_id)
            dataid_path = None
            if dataid is not None:
                dataid_path = await _save_upload(
                    dataid, run_id, allowed=DATAID_SUFFIXES, label="DataID")

            config_data = _manual_config(config, dbc_paths, trace_path, dataid_path)
            config_path = upload_dir / "config.json"
            config_path.write_text(
                json.dumps(config_data, ensure_ascii=False), encoding="utf-8")
            project = _manual_project(upload_dir, config_path, dbc_paths)
            result = enqueue(project, trace_path, trace_path.name, frame_limit,
                             _parse_bool(only_failures), run_id, upload_dir)
        except BaseException:
            if not job_registry.get(run_id):
                shutil.rmtree(upload_dir, ignore_errors=True)
            raise
        return JSONResponse(status_code=202, content=result)

    @api.post("/api/verify-sample")
    async def verify_sample(
        project_id: str = Form(...),
        trace_name: str = Form(...),
        max_frames: str = Form(""),
        only_failures: str = Form("false"),
    ) -> dict:
        """Verify a trace shipped with a project, without uploading it.

        The browser still sends no path: ``trace_name`` must be one of the
        names the catalog listed for this project.
        """
        project = get_project(project_id)
        if project is None:
            raise HTTPException(404, f"未知项目: {project_id}")
        if trace_name not in project.sample_traces:
            raise HTTPException(404, f"项目内没有示例 trace: {trace_name}")
        trace_path = Path(project.path) / "trace" / trace_name
        if not trace_path.is_file():
            raise HTTPException(404, f"示例 trace 不存在: {trace_name}")
        frame_limit = _parse_frame_limit(max_frames)

        run_id = secrets.token_urlsafe(9)
        result = enqueue(project, trace_path, trace_name, frame_limit,
                         _parse_bool(only_failures), run_id, None)
        return JSONResponse(status_code=202, content=result)

    @api.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        """Return asynchronous job status and its result when complete."""
        state = job_registry.get(job_id)
        if state is None:
            raise HTTPException(404, "校验任务不存在或已过期")
        return state

    @api.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        """Request cooperative cancellation for an active verification."""
        status = job_registry.cancel(job_id)
        if status is None:
            if job_registry.get(job_id) is None:
                raise HTTPException(404, "校验任务不存在或已过期")
            raise HTTPException(409, "校验任务已结束,无法取消")
        return {"job_id": job_id,
                "status": "cancelled" if status == "queued" else status,
                "cancel_requested": True}

    @api.get("/api/runs/{run_id}/{filename}.html")
    def run_report(run_id: str, filename: str) -> FileResponse:
        """Download a report or split part while protecting it from eviction."""
        lease = run_store.acquire_report(run_id, filename)
        if lease is None:
            raise HTTPException(404, "报告不存在或已过期,请重新校验")
        try:
            return FileResponse(
                str(lease.path), media_type="text/html", filename=lease.download_name,
                background=BackgroundTask(lease.release))
        except Exception:
            lease.release()
            raise

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

# uvicorn configures its loggers before importing the app, so a filter added
# here is already in place when the startup banner is logged.
logging.getLogger("uvicorn.error").addFilter(_drop_bind_any_banner)
