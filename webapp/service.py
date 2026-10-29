"""Run a project config against an uploaded trace and serialise the outcome.

The heavy lifting lives in :mod:`crc_checker.verify.runner` (the same code path
the CLI uses); this module only bridges it to the web: temp files, JSON shapes
and a small cache of finished runs so the HTML report stays downloadable.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from crc_checker.config import DEFAULT_MAX_FRAMES, RunConfig, load_config
from crc_checker.report.html import write_html
from crc_checker.report.trends import (RC_MAX_POINTS, _minmax_decimate,
                                       _split_trend_points, count_rc_episodes,
                                       rc_sample_stats)
from crc_checker.verify.models import VerifyReport, VerifyVerdict
from crc_checker.verify.runner import RunnerError, run_config
from webapp.catalog import Project

MAX_RUNS = 20                  # finished runs kept on disk (LRU)
MAX_FAILURE_ROWS = 2000        # failure rows serialised per trace
MAX_FRAME_ROWS = 500           # frames serialised per trace
MAX_SIGNAL_ROWS = 50           # distinct signals serialised per frame
MAX_RC_TRENDS = 60             # RC trend signals serialised per trace


class RunError(RuntimeError):
    """User-facing verification failure (bad config, unreadable trace, ...)."""


@dataclass
class RunOutcome:
    """One finished verification run: JSON payload + report location."""

    run_id: str
    created_at: float
    project_id: str
    trace_name: str
    payload: dict
    html_path: Path | None = None

    def to_dict(self) -> dict:
        """JSON shape returned by ``POST /api/verify``."""
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "trace_name": self.trace_name,
            "report_url": f"/api/runs/{self.run_id}/report.html" if self.html_path else "",
            **self.payload,
        }


# ---------------------------------------------------------------------------
# Report serialisation
# ---------------------------------------------------------------------------

def _decimate_trend_points(points: list) -> list:
    """Series points for the results view: pass points min/max-decimated
    (same caps as the HTML SVG), error points always kept.

    Returns [[t, value, fail, category], ...] in time order.
    """
    pass_pts, fail_pts = _split_trend_points(points)
    merged = ([(t, v, 0, "") for t, v in _minmax_decimate(pass_pts, RC_MAX_POINTS)]
              + [(t, v, 1, cat) for t, v, cat in fail_pts])
    merged.sort(key=lambda p: p[0])
    return [[t, v, fail, cat] for t, v, fail, cat in merged]


def _rc_trend_rows(report: VerifyReport) -> list[dict]:
    """Per-RC-signal trend data for the results-view charts (bounded)."""
    rows = []
    for (fid, ch, sig), points in report.rc_series.items():
        if not points:
            continue
        meta = report.rc_series_meta.get((fid, ch, sig), {})
        rows.append({
            "signal": sig,
            "frame_id": fid,
            "frame_id_hex": f"0x{fid:03X}",
            "frame_name": report.get_frame_name(fid),
            "channel": ch,
            "bit_max": (1 << meta.get("length", 4)) - 1,
            "max_valid": meta.get("max_valid"),
            "samples": len(points),
            "errors": sum(1 for p in points if not p[2]),
            # 连续异常段数:卡死计数器会连续失败上千帧,只有帧数会读成上千次
            # 独立错误(HTML 报告同口径,见 count_rc_episodes)。
            "episodes": count_rc_episodes(points),
            "t0": points[0][0],
            "tspan": points[-1][0] - points[0][0],
            "points": _decimate_trend_points(points),
        })
    # Signals with errors first, then by frame id / signal name
    rows.sort(key=lambda r: (-r["errors"], r["frame_id"], r["signal"]))
    return rows[:MAX_RC_TRENDS]


def _verdict_row(verdict: VerifyVerdict, report: VerifyReport) -> dict:
    """One flat verdict row for the failure table."""
    return {
        "frame_id": verdict.frame_id,
        "frame_id_hex": f"0x{verdict.frame_id:03X}",
        "frame_name": report.get_frame_name(verdict.frame_id),
        "timestamp": verdict.timestamp,
        "channel": report.get_frame_channel(verdict.timestamp, verdict.frame_id),
        "dbc_source": report.get_frame_dbc_source(verdict.frame_id),
        "signal": verdict.signal_name,
        "algorithm": verdict.algorithm,
        "crc_algorithm": verdict.crc_algorithm,
        "expected": verdict.expected_value,
        "expected_hex": f"0x{verdict.expected_value:X}",
        "actual": verdict.actual_value,
        "actual_hex": f"0x{verdict.actual_value:X}",
        "dataid": verdict.dataid,
        "dataid_name": verdict.dataid_name,
        "profile": verdict.dataid_profile,
        "detail": verdict.detail,
        "repeat_count": verdict.repeat_count,
    }


# pylint: disable=too-many-locals
def _frame_rows(report: VerifyReport) -> tuple[list[dict], bool]:
    """Per-message summary counted in FRAMES, not verdicts.

    RC 连续失败会被折叠成一条 verdict(报告不逐帧刷屏),所以数 verdict 会把
    「1800 帧失败」缩成「失败 1」,还会把 CRC 的逐帧 verdict 和折叠后的 RC
    verdict 加在一起(1801 + 2 = 1803):0x421 曾显示成「1802/1803、失败 1」
    。这里按 (frame_id, timestamp) 去重成帧 ——
    一条帧的所有校验都通过才算通过帧;RC 的逐帧结果来自 ``rc_series``。
    """
    frames: dict[int, dict] = {}
    outcomes: dict[int, dict[float, bool]] = {}

    def frame_entry(frame_id: int, timestamp: float) -> dict:
        frame = frames.get(frame_id)
        if frame is None:
            frame = {
                "frame_id": frame_id,
                "frame_id_hex": f"0x{frame_id:03X}",
                "frame_name": report.get_frame_name(frame_id),
                "dbc_source": report.get_frame_dbc_source(frame_id),
                "channel": report.get_frame_channel(timestamp, frame_id),
                "total": 0, "pass": 0, "fail": 0,
                "signals": {},
                "failures": [],
            }
            frames[frame_id] = frame
        return frame

    def signal_entry(frame: dict, verdict: VerifyVerdict) -> dict | None:
        signals = frame["signals"]
        entry = signals.get(verdict.signal_name)
        if entry is None and len(signals) < MAX_SIGNAL_ROWS:
            entry = {
                "signal": verdict.signal_name,
                "algorithm": verdict.algorithm,
                "crc_algorithm": verdict.crc_algorithm,
                "profile": verdict.dataid_profile,
                "dataid": verdict.dataid,
                "dataid_name": verdict.dataid_name,
                "total": 0, "pass": 0, "fail": 0,
                "last_detail": "",
            }
            signals[verdict.signal_name] = entry
        return entry

    # series 缺失时(理论上只有 run_stream)退回 verdict 计数,别把 RC 行清零
    count_rc_verdicts = not report.rc_series
    for verdict in report.verdicts:
        frame = frame_entry(verdict.frame_id, verdict.timestamp)
        results = outcomes.setdefault(verdict.frame_id, {})
        results[verdict.timestamp] = (results.get(verdict.timestamp, True)
                                      and verdict.is_pass)
        if not verdict.is_pass and len(frame["failures"]) < MAX_FAILURE_ROWS:
            frame["failures"].append(_verdict_row(verdict, report))

        entry = signal_entry(frame, verdict)
        if entry is not None:
            if verdict.algorithm == "crc" or count_rc_verdicts:
                entry["total"] += 1
                entry["pass" if verdict.is_pass else "fail"] += 1
            if not verdict.is_pass and verdict.detail:
                entry["last_detail"] = verdict.detail

    # RC 逐帧采样(折叠掉的失败帧只存在于 series 里)
    for (frame_id, _channel, signal_name), points in report.rc_series.items():
        for timestamp, _value, is_pass, _category in points:
            frame = frame_entry(frame_id, timestamp)
            results = outcomes.setdefault(frame_id, {})
            results[timestamp] = results.get(timestamp, True) and is_pass
            entry = frame["signals"].get(signal_name)
            if entry is None:
                if len(frame["signals"]) >= MAX_SIGNAL_ROWS:
                    continue
                entry = {
                    "signal": signal_name, "algorithm": "rolling_counter",
                    "crc_algorithm": "", "profile": None, "dataid": None,
                    "dataid_name": None, "total": 0, "pass": 0, "fail": 0,
                    "last_detail": "",
                }
                frame["signals"][signal_name] = entry
            entry["total"] += 1
            entry["pass" if is_pass else "fail"] += 1

    for frame_id, frame in frames.items():
        frame["total"] = len(outcomes[frame_id])
        frame["fail"] = sum(1 for ok in outcomes[frame_id].values() if not ok)
        frame["pass"] = frame["total"] - frame["fail"]

    ordered = sorted(frames.values(), key=lambda f: (-f["fail"], f["frame_id"]))
    truncated = len(ordered) > MAX_FRAME_ROWS
    if truncated:
        ordered = ordered[:MAX_FRAME_ROWS]
    for frame in ordered:
        frame["signals"] = sorted(
            frame["signals"].values(), key=lambda s: (-s["fail"], s["signal"]))
        frame["rate"] = frame["pass"] / frame["total"] if frame["total"] else 1.0
    return ordered, truncated


def report_to_dict(report: VerifyReport) -> dict:
    """Serialise one trace's report for the results view."""
    frames, frames_truncated = _frame_rows(report)
    failures: list[dict] = []
    for verdict in report.failed:
        if len(failures) >= MAX_FAILURE_ROWS:
            break
        failures.append(_verdict_row(verdict, report))

    crc_total = sum(1 for v in report.verdicts if v.algorithm == "crc")
    crc_pass = sum(1 for v in report.verdicts if v.algorithm == "crc" and v.is_pass)
    # RC 用采样口径(折叠掉的失败帧只存在于 series 里),否则卡片会和趋势图对不上
    rc_pass, rc_total = rc_sample_stats(report)

    return {
        "trace_path": report.trace_path,
        "total_frames": report.total_frames,
        "total_verdicts": report.total_verdicts,
        # 校验项口径:CRC 逐帧 verdict + RC 逐帧采样(不是折叠后的 verdict 数)
        "check_total": crc_total + rc_total,
        "check_pass": crc_pass + rc_pass,
        "check_fail": (crc_total - crc_pass) + (rc_total - rc_pass),
        "pass_count": report.pass_count,
        "fail_count": report.fail_count,
        "pass_rate": report.pass_rate,
        "crc_total": crc_total,
        "crc_pass": crc_pass,
        "crc_rate": crc_pass / crc_total if crc_total else 1.0,
        "rc_total": rc_total,
        "rc_pass": rc_pass,
        "rc_rate": rc_pass / rc_total if rc_total else 1.0,
        "failures": failures,
        "failures_truncated": report.fail_count > len(failures),
        "frames": frames,
        "frames_truncated": frames_truncated,
        "rc_trends": _rc_trend_rows(report),
        "dbc_paths": list(report.dbc_paths),
    }


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def resolve_max_frames(requested: int | None, config_value: int | None) -> int | None:
    """Resolve the frame cap: ``None`` = config/默认上限(6000), ``0`` = no limit."""
    if requested is None:
        if config_value is not None:
            return config_value
        return DEFAULT_MAX_FRAMES
    return None if requested <= 0 else requested


# pylint: disable=too-many-arguments,too-many-positional-arguments
def make_run_payload(setup: dict, project: dict, reports: list[dict],
                     elapsed_ms: int, report_note: str = "") -> dict:
    """Build the JSON payload returned by ``POST /api/verify``.

    ``report_note`` is the HTML report's downgrade/truncation notice
    (empty string = none).
    """
    payload = {
        "elapsed_ms": elapsed_ms,
        "setup": setup,
        "project": project,
        "reports": reports,
        "report_note": report_note,
    }
    return payload


def run_project(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    project: Project,
    trace_path: Path,
    trace_name: str = "",
    max_frames: int | None = None,
    only_failures: bool = False,
    run_id: str | None = None,
    report_dir: Path | None = None,
) -> RunOutcome:
    """Verify one trace file against a project's config.

    Args:
        project: Project whose ``config.json`` drives the run.
        trace_path: Trace file on disk (an uploaded temp file).
        trace_name: Original upload name, shown in the report.
        max_frames: Override the config's ``filter.max_frames``
            (``None`` = config default, ``0`` = no limit).
        only_failures: Render the HTML report with failures only.
        run_id: Pre-allocated id (tests pass one; the API generates it).
        report_dir: Where to write ``<run_id>.html`` (skipped when ``None``).

    Raises:
        RunError: config or trace could not be used.
    """
    started = time.monotonic()
    try:
        cfg: RunConfig = load_config(str(project.config_path))
    except (OSError, ValueError) as exc:
        raise RunError(f"配置文件读取失败: {exc}") from exc

    cfg.traces = [str(trace_path)]
    cfg.max_frames = resolve_max_frames(max_frames, cfg.max_frames)
    cfg.only_failures = only_failures

    try:
        setup, reports = run_config(cfg, [str(trace_path)])
    except RunnerError as exc:
        raise RunError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - trace/DBC parse errors are user-facing
        raise RunError(f"校验执行失败: {exc}") from exc

    display_name = trace_name or trace_path.name
    for report in reports:
        report.trace_path = display_name

    run_id = run_id or secrets.token_urlsafe(9)
    html_path = None
    report_note = ""
    if report_dir is not None and reports:
        # 每个 run 一个子目录:报告主文件与分片只落在自己的目录里,路由不会
        # 命中其它 run 的文件(清理时整个目录一起删)。
        run_dir = Path(report_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        html_path = run_dir / f"{run_id}.html"
        try:
            report_note = write_html(reports[0], str(html_path), only_failures,
                                     max_sections=cfg.max_report_sections)
        except OSError:
            html_path = None

    payload = make_run_payload(
        setup={
            "dbc_names": setup.dbc_names,
            "channels": {str(ch): name for ch, name in setup.channels.items()},
            "channel_matches": {str(ch): list(v) for ch, v in setup.channel_matches.items()},
            "dataid_entries": setup.dataid_entries,
            "dataid_sheet": setup.dataid_sheet,
            "dataid_fallback": setup.dataid_fallback,
            "counts": setup.counts,
            "notes": setup.notes,
            "max_frames": cfg.max_frames,
            "runs": len(reports),
        },
        project=project.to_dict(),
        reports=[report_to_dict(report) for report in reports],
        elapsed_ms=int((time.monotonic() - started) * 1000),
        report_note=report_note,
    )
    return RunOutcome(run_id=run_id, created_at=time.time(), project_id=project.id,
                      trace_name=display_name, payload=payload, html_path=html_path)


# ---------------------------------------------------------------------------
# Run cache (finished runs, so the report stays downloadable)
# ---------------------------------------------------------------------------

def _report_files(html_path: Path) -> list[Path]:
    """报告主文件 + 分片文件(``<stem>_p2.html``…),删除时要一起删。

    分片只按约定命名(见 `crc_checker.report.html._split_part_path`),用正则
    精确匹配,别误伤名字里带 ``_p`` 的其它 run。
    """
    pattern = re.compile(rf"{re.escape(html_path.stem)}_p\d+\.html$")
    return [html_path] + [p for p in html_path.parent.glob(f"{html_path.stem}_p*.html")
                          if pattern.search(p.name)]


@dataclass
class RunStore:
    """Keeps the last ``max_runs`` finished runs' reports, newest first."""

    runs_dir: Path
    max_runs: int = MAX_RUNS
    _runs: dict[str, RunOutcome] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """清空报告目录:run 索引只在内存里,重启后旧报告本来就下不到。

        不清会越攒越多 —— 不限帧的大 trace 单次运行就有十几个 30MB 分片
        (2026-10-20 实测 data/web/runs 攒到 11GB / 834 个文件)。
        """
        self.purge_disk()

    def purge_disk(self) -> None:
        """Delete report files under ``runs_dir`` (startup + tests)."""
        if not self.runs_dir.is_dir():
            return
        for path in self.runs_dir.iterdir():
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.suffix == ".html":
                try:
                    path.unlink()
                except OSError:
                    pass

    def add(self, outcome: RunOutcome) -> None:
        """Record a finished run and evict the oldest beyond ``max_runs``."""
        self._runs[outcome.run_id] = outcome
        self.sweep()

    def get(self, run_id: str) -> RunOutcome | None:
        """Look up a run id (``None`` when unknown)."""
        return self._runs.get(run_id)

    def sweep(self) -> None:
        """Drop reports of evicted runs (keeps the store and disk bounded)."""
        if len(self._runs) <= self.max_runs:
            return
        ordered = sorted(self._runs.values(), key=lambda r: r.created_at)
        for stale in ordered[:len(self._runs) - self.max_runs]:
            self._runs.pop(stale.run_id, None)
            if not stale.html_path:
                continue
            for path in _report_files(stale.html_path):
                try:
                    path.unlink()
                except OSError:
                    pass
            parent = stale.html_path.parent
            if parent != self.runs_dir and parent.is_dir():
                shutil.rmtree(parent, ignore_errors=True)


def write_json(path: Path, payload: dict) -> None:
    """Atomic JSON write (temp file + replace), used for run metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    tmp.replace(path)


def clear_dir(path: Path) -> None:
    """Remove a directory tree, ignoring failures (best-effort cleanup)."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
