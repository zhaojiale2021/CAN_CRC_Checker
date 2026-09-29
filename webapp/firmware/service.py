"""固件源码模式的校验服务:上传 trace → 该 commit 的固件 E2E 映射 → 校验。

复用 webapp.service 的报告序列化与 RunOutcome;固件映射由
webapp.firmware.catalog 按通道分配生成 —— 配置文件模式与固件模式共用
同一个校验引擎与同一个结果结构,前端两种来源可以对比着看。
"""

from __future__ import annotations

import time
from pathlib import Path

from crc_checker.crc.presets import get_preset
from crc_checker.dbc.parser import sample_trace_channels
from crc_checker.verify.runner import RunnerError, build_algorithms, run_trace
from webapp.firmware.catalog import build_channel_map
from webapp.firmware.config import FirmwareRepoCfg
from webapp.firmware.e2e import FirmwareE2E
from webapp.firmware.store import FirmwareStore
from webapp.service import (
    RunOutcome,
    make_run_payload,
    report_to_dict,
    resolve_max_frames,
)

MAX_SOURCE_ENTRIES = 400   # per-message table rows serialised


class FirmwareRunError(RuntimeError):
    """User-facing firmware-mode failure (bad repo/commit/model/trace)."""


def _entries_table(entries: list[FirmwareE2E],
                   limit: int = MAX_SOURCE_ENTRIES) -> dict:
    """固件 E2E 明细表(截断到 limit 行,总数与是否截断一并返回)。"""
    rows = [entry.to_dict() for entry in entries[:limit]]
    return {"rows": rows, "total": len(entries), "truncated": len(entries) > limit}


def run_firmware(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    store: FirmwareStore,
    repo_cfg: FirmwareRepoCfg,
    commit: str,
    model: dict,
    trace_path: Path,
    trace_name: str = "",
    max_frames: int | None = None,
    only_failures: bool = False,
    run_id: str | None = None,
    report_dir: Path | None = None,
) -> RunOutcome:
    """Verify one trace against the firmware's actual E2E at ``commit``.

    Synchronous (the API runs it in a threadpool, like the config-file mode).

    Raises:
        FirmwareRunError: 仓库、commit、车型目录或 trace 无法使用。
    """
    # pylint: disable=import-outside-toplevel
    from webapp.firmware.gitops import GitError

    started = time.monotonic()
    try:
        sha = store.resolve(repo_cfg, commit)
        catalog = store.catalog(repo_cfg, sha, model)
    except GitError as exc:
        raise FirmwareRunError(str(exc)) from exc

    try:
        # 通道分配要用 trace 采样:总线的报文落在哪个通道,按 ID 命中率判断。
        channel_ids = sample_trace_channels(str(trace_path), max_frames=1000)
        protection_map, bus_channels, diagnostics = build_channel_map(catalog, channel_ids)
    except (ValueError, OSError) as exc:
        raise FirmwareRunError(f"trace 采样失败: {exc}") from exc

    # 每个保护组自带 crc_params(p01/p05 各自的算法),这里的默认参数只为把
    # CRCVerifier 建起来 —— build_algorithms(None) 只会造 RC 校验器。
    algorithms = build_algorithms(get_preset("CRC8/SAE-J1850-ZERO"))
    max_frames_resolved = resolve_max_frames(max_frames, None)

    try:
        report = run_trace(protection_map, algorithms, str(trace_path),
                           max_frames=max_frames_resolved)
    except (RunnerError, ValueError, OSError) as exc:
        raise FirmwareRunError(f"校验执行失败: {exc}") from exc

    display_name = trace_name or trace_path.name
    report.trace_path = display_name

    html_path = None
    if report_dir is not None and run_id:
        report_dir.mkdir(parents=True, exist_ok=True)
        html_path = report_dir / f"{run_id}.html"
        try:
            from crc_checker.report.html import write_html
            write_html(report, str(html_path), only_failures)
        except OSError:
            html_path = None

    payload = make_run_payload(
        setup={
            "dbc_names": [model["path"]],
            "channels": {str(ch): "/".join(b for b, c in bus_channels.items() if c == ch)
                         for ch in sorted(set(bus_channels.values()))},
            "channel_matches": {},
            "dataid_entries": sum(1 for e in catalog.entries if e.dataid is not None),
            "dataid_sheet": "",
            "dataid_fallback": 0,
            "counts": {},
            "notes": [d["message"] for d in diagnostics],
            "max_frames": max_frames_resolved,
            "runs": 1,
            "mode": "firmware",
        },
        project={
            "id": f"firmware:{model['id']}",
            "oem": model.get("oem", ""),
            "model": model.get("name", ""),
            "name": f"{repo_cfg.name} · {model['id']}",
            "dbc_files": [],
            "sample_traces": [],
            "summary": {},
        },
        reports=[report_to_dict(report)],
        elapsed_ms=int((time.monotonic() - started) * 1000),
        source={
            "mode": "firmware",
            "repository": repo_cfg.to_dict(),
            "commit": sha,
            "requested_ref": commit,
            "model_id": model["id"],
            "model_path": model["path"],
            "last_commit": model.get("last_commit"),
            "supported": model.get("supported"),
            "entries": _entries_table(catalog.entries),
            "bus_channels": dict(bus_channels),
            "diagnostics": diagnostics,
        })
    return RunOutcome(run_id=run_id or "", created_at=time.time(),
                      project_id=model["id"], trace_name=display_name,
                      payload=payload, html_path=html_path)
