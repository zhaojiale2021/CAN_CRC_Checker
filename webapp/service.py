"""Run a project config against an uploaded trace and serialise the outcome.

The heavy lifting lives in :mod:`crc_checker.verify.runner` (the same code path
the CLI uses); this module only bridges it to the web: temp files, JSON shapes
and a small cache of finished runs so the HTML report stays downloadable.
"""

from __future__ import annotations

import json
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from crc_checker.config import RunConfig, load_config
from crc_checker.report.html import write_html
from crc_checker.verify.models import VerifyReport, VerifyVerdict
from crc_checker.verify.runner import RunnerError, run_config
from webapp.catalog import Project

MAX_RUNS = 20                  # finished runs kept on disk (LRU)
MAX_FAILURE_ROWS = 2000        # failure rows serialised per trace
MAX_FRAME_ROWS = 500           # frames serialised per trace
MAX_SIGNAL_ROWS = 50           # distinct signals serialised per frame


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
    }


def _frame_rows(report: VerifyReport) -> tuple[list[dict], bool]:
    """Aggregate verdicts per frame (id/name/channel/rates + failure rows)."""
    frames: dict[int, dict] = {}
    for verdict in report.verdicts:
        frame = frames.get(verdict.frame_id)
        if frame is None:
            frame = {
                "frame_id": verdict.frame_id,
                "frame_id_hex": f"0x{verdict.frame_id:03X}",
                "frame_name": report.get_frame_name(verdict.frame_id),
                "dbc_source": report.get_frame_dbc_source(verdict.frame_id),
                "channel": report.get_frame_channel(verdict.timestamp, verdict.frame_id),
                "total": 0, "pass": 0, "fail": 0,
                "signals": {},
                "failures": [],
            }
            frames[verdict.frame_id] = frame

        frame["total"] += 1
        if verdict.is_pass:
            frame["pass"] += 1
        else:
            frame["fail"] += 1
            if len(frame["failures"]) < MAX_FAILURE_ROWS:
                frame["failures"].append(_verdict_row(verdict, report))

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
        if entry is not None:
            entry["total"] += 1
            entry["pass" if verdict.is_pass else "fail"] += 1
            if not verdict.is_pass and verdict.detail:
                entry["last_detail"] = verdict.detail

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
    rc_total = sum(1 for v in report.verdicts if v.algorithm != "crc")
    rc_pass = sum(1 for v in report.verdicts if v.algorithm != "crc" and v.is_pass)

    return {
        "trace_path": report.trace_path,
        "total_frames": report.total_frames,
        "total_verdicts": report.total_verdicts,
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
        "dbc_paths": list(report.dbc_paths),
    }


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def resolve_max_frames(requested: int | None, config_value: int | None) -> int | None:
    """Resolve the frame cap: ``None`` = config default, ``0`` = no limit."""
    if requested is None:
        return config_value
    return None if requested <= 0 else requested


def make_run_payload(setup: dict, project: dict, reports: list[dict],
                     elapsed_ms: int, source: dict | None = None) -> dict:
    """共用结果结构 —— 两种映射来源(配置文件 / 固件源码)同一形状。

    ``source`` 只在固件源码模式携带(commit 节点 + 每报文 E2E 明细)。
    """
    payload = {
        "elapsed_ms": elapsed_ms,
        "setup": setup,
        "project": project,
        "reports": reports,
    }
    if source is not None:
        payload["source"] = source
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
    if report_dir is not None and reports:
        report_dir.mkdir(parents=True, exist_ok=True)
        html_path = report_dir / f"{run_id}.html"
        try:
            write_html(reports[0], str(html_path), only_failures)
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
    )
    return RunOutcome(run_id=run_id, created_at=time.time(), project_id=project.id,
                      trace_name=display_name, payload=payload, html_path=html_path)


# ---------------------------------------------------------------------------
# Run cache (finished runs, so the report stays downloadable)
# ---------------------------------------------------------------------------

@dataclass
class RunStore:
    """Keeps the last ``max_runs`` finished runs' reports, newest first."""

    runs_dir: Path
    max_runs: int = MAX_RUNS
    _runs: dict[str, RunOutcome] = field(default_factory=dict)

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
            if stale.html_path and stale.html_path.exists():
                try:
                    stale.html_path.unlink()
                except OSError:
                    pass


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
