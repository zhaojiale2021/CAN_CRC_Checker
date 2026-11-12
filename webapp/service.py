"""Run a project config against an uploaded trace and serialise the outcome.

The heavy lifting lives in :mod:`crc_checker.verify.runner` (the same code path
the CLI uses); this module only bridges it to the web: temp files, JSON shapes
and a small cache of finished runs so the HTML report stays downloadable.
"""

from __future__ import annotations

import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from crc_checker.config import DEFAULT_MAX_FRAMES, RunConfig, load_config
from crc_checker.report.html import write_html
from crc_checker.report.trends import (RC_MAX_POINTS, _minmax_decimate,
                                       _split_trend_points, count_rc_episodes,
                                       crc_sample_stats, rc_sample_stats)
from crc_checker.verify.cancellation import CancellationToken
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


JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
MAX_JOBS = 100


@dataclass
class VerificationJob:
    """Thread-safe-registry record for one asynchronous verification."""

    job_id: str
    token: CancellationToken = field(default_factory=CancellationToken)
    status: str = "queued"
    processed_frames: int = 0
    error: str | None = None
    result: dict | None = None
    created_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        """JSON state exposed by the jobs API."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "processed_frames": self.processed_frames,
            "error": self.error,
            "result": self.result,
        }


class JobRegistry:
    """Bounded, per-app job state with atomic transitions and snapshots."""

    def __init__(self, max_jobs: int = MAX_JOBS):
        self.max_jobs = max_jobs
        self._jobs: dict[str, VerificationJob] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str | None = None) -> VerificationJob | None:
        """Create a queued job, evicting old terminal entries when full."""
        with self._lock:
            if len(self._jobs) >= self.max_jobs:
                terminal = sorted(
                    (job for job in self._jobs.values()
                     if job.status in {"succeeded", "failed", "cancelled"}),
                    key=lambda job: job.created_at)
                for job in terminal:
                    self._jobs.pop(job.job_id, None)
                    if len(self._jobs) < self.max_jobs:
                        break
            if len(self._jobs) >= self.max_jobs:
                return None
            identifier = job_id or secrets.token_urlsafe(9)
            if identifier in self._jobs:
                return None
            job = VerificationJob(identifier)
            self._jobs[identifier] = job
            return job

    def job_ids(self) -> list[str]:
        """Return a stable list of retained job identifiers."""
        with self._lock:
            return list(self._jobs)

    def get(self, job_id: str) -> dict | None:
        """Return a consistent state snapshot or ``None`` for an unknown job."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job is not None else None

    def start(self, job_id: str) -> bool:
        """Move a queued job to running exactly once."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "queued":
                return False
            if job.token.is_cancelled:
                job.status = "cancelled"
                job.error = "任务已取消"
                return False
            job.status = "running"
            return True

    def progress(self, job_id: str, processed_frames: int) -> None:
        """Accept progress only while the matching job is running."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status == "running":
                job.processed_frames = max(job.processed_frames, processed_frames)

    # pylint: disable=too-many-arguments
    def finish(self, job_id: str, status: str, *, error: str | None = None,
                result: dict | None = None, processed_frames: int | None = None) -> None:
        """Set one terminal state; late callbacks cannot mutate it."""
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError(f"Not a terminal job status: {status}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return
            if processed_frames is not None:
                job.processed_frames = max(job.processed_frames, processed_frames)
            job.status = status
            job.error = error
            job.result = result

    def finish_success(self, job_id: str, result: dict, publish: Callable[[], None]) -> bool:
        """Publish the run and mark success atomically against cancellation."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return False
            if job.token.is_cancelled:
                job.status = "cancelled"
                job.error = "任务已取消"
                job.result = None
                return False
            publish()
            job.status = "succeeded"
            job.error = None
            job.result = result
            return True

    def cancel(self, job_id: str) -> str | None:
        """Request cancellation for active jobs; return status or ``None``."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return None
            if job.status == "queued":
                job.status = "cancelled"
                job.error = "任务已取消"
                return "queued"
            job.token.cancel()
            return job.status

    def cancel_all(self) -> list[str]:
        """Request cancellation for every active job and return their ids."""
        with self._lock:
            identifiers = []
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    identifiers.append(job.job_id)
                    if job.status == "queued":
                        job.status = "cancelled"
                        job.error = "任务已取消"
                    else:
                        job.token.cancel()
            return identifiers


@dataclass
class RunOutcome:
    """One finished verification run: JSON payload + report location."""

    run_id: str
    created_at: float
    project_id: str
    trace_name: str
    payload: dict
    html_path: Path | None = None
    last_access: float = 0.0  # LRU order, set by RunStore.add/get

    def to_dict(self) -> dict:
        """JSON shape returned by ``POST /api/verify``."""
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "trace_name": self.trace_name,
            "report_url": f"/api/runs/{self.run_id}/report.html" if self.html_path else "",
            **self.payload,
        }


class ReportLease:  # pylint: disable=too-few-public-methods
    """Keep a report and its split parts alive through response streaming."""

    def __init__(self, store: RunStore, outcome: RunOutcome, path: Path,
                 download_name: str):
        self.path = path
        self.download_name = download_name
        self._store = store
        self._outcome = outcome
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        """Release this lease once; safe for response and error cleanup paths."""
        with self._lock:
            if self._released:
                return
            self._released = True
            self._store.release_report(self._outcome)


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
            # Episode count: a stuck counter fails thousands of frames in a
            # row, which would read as thousands of independent errors (same
            # accounting as the HTML report, see count_rc_episodes).
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
        "channel": verdict.channel,
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


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _frame_rows(report: VerifyReport) -> tuple[list[dict], bool]:
    """Per-message summary counted in FRAMES, not verdicts.

    Frames are keyed by ``(frame_id, channel)``: a gateway trace can carry the
    same CAN ID on two buses, and merging them produces a wrong pass rate and
    a misleading channel tag.

    RC failures fold into one verdict (reports don't spam one line per
    frame), so counting verdicts would shrink repeated failures into one. Frame
    samples are identified by timestamp plus occurrence number so distinct frames
    with identical timestamps are still counted separately.
    """
    frames: dict[tuple[int, int], dict] = {}
    outcomes: dict[tuple[int, int], dict[tuple[float, int], bool]] = {}
    occurrences: dict[tuple[int, int, float, str], int] = {}

    def outcome_key(frame_id: int, channel: int, timestamp: float,
                    signal_name: str) -> tuple[float, int]:
        """Assign duplicate signal timestamps distinct occurrence indices."""
        base = (frame_id, channel, timestamp, signal_name)
        index = occurrences.get(base, 0)
        occurrences[base] = index + 1
        return timestamp, index

    def frame_entry(frame_id: int, _timestamp: float, channel: int = 0) -> dict:
        key = (frame_id, channel)
        frame = frames.get(key)
        if frame is None:
            frame = {
                "frame_id": frame_id,
                "frame_id_hex": f"0x{frame_id:03X}",
                "frame_name": report.get_frame_name(frame_id),
                "dbc_source": report.get_frame_dbc_source(frame_id),
                "channel": channel,
                "total": 0, "pass": 0, "fail": 0,
                "signals": {},
                "failures": [],
            }
            frames[key] = frame
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

    # Without the series (theoretically only run_stream) fall back to verdict
    # counts rather than zeroing the RC rows.
    count_rc_verdicts = not report.rc_series
    for verdict in report.verdicts:
        frame = frame_entry(verdict.frame_id, verdict.timestamp, verdict.channel)
        # Folded RC verdicts describe failure episodes, not frame samples; the
        # series below is authoritative when available. Keep their detail rows
        # but do not add a second outcome for the same RC samples.
        is_rc_episode = verdict.algorithm != "crc" and not count_rc_verdicts
        if not is_rc_episode:
            results = outcomes.setdefault((verdict.frame_id, verdict.channel), {})
            key = outcome_key(verdict.frame_id, verdict.channel, verdict.timestamp,
                              verdict.signal_name)
            results[key] = results.get(key, True) and verdict.is_pass
        if not verdict.is_pass and len(frame["failures"]) < MAX_FAILURE_ROWS:
            frame["failures"].append(_verdict_row(verdict, report))

        entry = signal_entry(frame, verdict)
        if entry is not None:
            if verdict.algorithm == "crc" or count_rc_verdicts:
                entry["total"] += 1
                entry["pass" if verdict.is_pass else "fail"] += 1
            if not verdict.is_pass and verdict.detail:
                entry["last_detail"] = verdict.detail

    # Per-frame RC samples (folded failing frames exist only in the series)
    for (frame_id, _channel, signal_name), points in report.rc_series.items():
        for timestamp, _value, is_pass, _category in points:
            frame = frame_entry(frame_id, timestamp, _channel)
            results = outcomes.setdefault((frame_id, _channel), {})
            key = outcome_key(frame_id, _channel, timestamp, signal_name)
            results[key] = results.get(key, True) and is_pass
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

    for key, frame in frames.items():
        frame["total"] = len(outcomes[key])
        frame["fail"] = sum(1 for ok in outcomes[key].values() if not ok)
        frame["pass"] = frame["total"] - frame["fail"]

    ordered = sorted(frames.values(),
                     key=lambda f: (-f["fail"], f["frame_id"], f["channel"]))
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

    crc_pass, crc_total = crc_sample_stats(report)
    # RC is counted by sample (folded failing frames exist only in the
    # series); otherwise the card would disagree with the trend charts.
    rc_pass, rc_total = rc_sample_stats(report)

    return {
        "trace_path": report.trace_path,
        "total_frames": report.total_frames,
        "total_verdicts": report.total_verdicts,
        "trace_truncated": report.frames_truncated,
        "trace_frame_limit": report.frame_limit,
        # Check accounting: CRC per-frame verdicts + RC per-frame samples
        # (not the folded verdict counts).
        "check_total": crc_total + rc_total,
        "check_pass": crc_pass + rc_pass,
        "check_fail": (crc_total - crc_pass) + (rc_total - rc_pass),
        # Public aggregate counts follow per-frame/sample accounting; folded
        # verdict counts remain available in total_verdicts and failures.
        "pass_count": crc_pass + rc_pass,
        "fail_count": (crc_total - crc_pass) + (rc_total - rc_pass),
        "pass_rate": ((crc_pass + rc_pass) / (crc_total + rc_total)
                      if crc_total + rc_total else 1.0),
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
        # File names only — the browser never receives server filesystem paths.
        # Normalize separators first: on POSIX ``Path(r"C:\x\y.dbc").name`` is
        # the whole string, so a Windows path would leak through.
        "dbc_paths": [Path(str(p).replace("\\", "/")).name
                      for p in report.dbc_paths],
    }


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def resolve_max_frames(requested: int | None, config_value: int | None) -> int | None:
    """Resolve the frame cap: ``None`` = config default (6000), ``0`` = no limit."""
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
    frame_progress_callback: Callable[[int, int | None], None] | None = None,
    cancellation_token: CancellationToken | None = None,
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
        frame_progress_callback: Optional per-frame progress observer.
        cancellation_token: Optional cooperative cancellation signal.

    Raises:
        RunError: config or trace could not be used.
        VerificationCancelled: the run was cancelled cooperatively.
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
        setup, reports = run_config(
            cfg, [str(trace_path)],
            frame_progress_callback=frame_progress_callback,
            cancellation_token=cancellation_token)
    except RunnerError as exc:
        raise RunError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise RunError(f"校验执行失败: {exc}") from exc

    display_name = trace_name or trace_path.name
    for report in reports:
        report.trace_path = display_name

    run_id = run_id or secrets.token_urlsafe(9)
    html_path = None
    report_note = ""
    if report_dir is not None and reports:
        # One subdirectory per run: the report main file and its split parts
        # only ever land in their own directory, so the route cannot reach
        # another run's files (cleanup removes the whole directory).
        run_dir = Path(report_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        html_path = run_dir / f"{run_id}.html"
        try:
            report_note = write_html(reports[0], str(html_path), only_failures,
                                     max_sections=cfg.max_report_sections)
        except OSError:
            html_path = None
            # Every file of this run lives in its own subdirectory — drop the
            # partially written main file and chunks instead of leaking them
            # until the next restart's purge.
            shutil.rmtree(run_dir, ignore_errors=True)

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
            "config_warnings": list(cfg.warnings),
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
    """Report main file + split parts (``<stem>_p2.html``…), for deletion.

    Split parts follow a naming convention (see
    ``crc_checker.report.html._split_part_path``); the regex matches it
    exactly so a run whose name happens to contain ``_p`` is not hit.
    """
    pattern = re.compile(rf"{re.escape(html_path.stem)}_p\d+\.html$")
    return [html_path] + [p for p in html_path.parent.glob(f"{html_path.stem}_p*.html")
                          if pattern.search(p.name)]


@dataclass
class RunStore:
    """Keeps the last ``max_runs`` finished runs' reports, newest first.

    Eviction is LRU: ``get()`` touches ``last_access`` and ``sweep()`` evicts
    the least recently *used* run (a report that keeps being downloaded is
    not dropped just because it is old).

    All dict access is locked: runs execute in the threadpool
    (``run_in_threadpool``), so ``add``/``get``/``sweep`` can run concurrently.
    """

    runs_dir: Path
    max_runs: int = MAX_RUNS
    _runs: dict[str, RunOutcome] = field(default_factory=dict)
    _active_leases: dict[int, int] = field(default_factory=dict, repr=False)
    _pending_cleanup: dict[int, RunOutcome] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        """Purge the report directory (run index is memory-only).

        After a restart the old reports are unreachable anyway. Without the
        purge they accumulate forever — a frame-unlimited big trace alone can
        produce a dozen 30MB split parts (measured 2026-10-20: data/web/runs
        had grown to 11GB / 834 files).
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
        """Record a finished run and evict the least recently used beyond max."""
        outcome.last_access = outcome.created_at
        with self._lock:
            self._runs[outcome.run_id] = outcome
            self._sweep_locked()

    def get(self, run_id: str) -> RunOutcome | None:
        """Look up a run id (``None`` when unknown); refreshes LRU order."""
        with self._lock:
            outcome = self._runs.get(run_id)
            if outcome is not None:
                outcome.last_access = time.time()
            return outcome

    def acquire_report(self, run_id: str, filename: str) -> ReportLease | None:
        """Resolve and lease a report atomically, returning ``None`` if absent.

        ``filename`` is ``report``/the report stem or a split-part stem such
        as ``<run_id>_p2``. The lease prevents eviction from deleting any part
        of the response while Starlette is streaming it.
        """
        with self._lock:
            outcome = self._runs.get(run_id)
            if outcome is None or not outcome.html_path:
                return None

            path = outcome.html_path
            label = f"crc_report_{run_id}.html"
            if filename not in ("report", path.stem):
                match = re.fullmatch(rf"{re.escape(run_id)}_p(\d+)", filename)
                if match is None:
                    return None
                part_no = int(match.group(1))
                path = path.with_name(f"{run_id}_p{part_no}.html")
                label = f"crc_report_{run_id}_p{part_no}.html"

            if not path.is_file():
                return None
            outcome.last_access = time.time()
            outcome_key = id(outcome)
            self._active_leases[outcome_key] = self._active_leases.get(outcome_key, 0) + 1
            return ReportLease(self, outcome, path, label)

    def release_report(self, outcome: RunOutcome) -> None:
        """Public report-lease release entry point."""
        self._release_report(outcome)

    def _release_report(self, outcome: RunOutcome) -> None:
        """Drop a lease and clean an evicted run after its last response."""
        cleanup = None
        outcome_key = id(outcome)
        with self._lock:
            count = self._active_leases.get(outcome_key, 0)
            if count <= 1:
                self._active_leases.pop(outcome_key, None)
                cleanup = self._pending_cleanup.pop(outcome_key, None)
            else:
                self._active_leases[outcome_key] = count - 1
        if cleanup is not None:
            self._delete_outcome_reports(cleanup)

    def _delete_outcome_reports(self, outcome: RunOutcome) -> None:
        """Delete all report parts and the per-run directory, if any."""
        if not outcome.html_path:
            return
        for path in _report_files(outcome.html_path):
            try:
                path.unlink()
            except OSError:
                pass
        parent = outcome.html_path.parent
        if parent != self.runs_dir and parent.is_dir():
            shutil.rmtree(parent, ignore_errors=True)

    def discard(self, outcome: RunOutcome) -> None:
        """Remove an unpublished outcome's reports without touching leases."""
        self._delete_outcome_reports(outcome)

    def __len__(self) -> int:
        """Number of cached runs (diagnostics / tests)."""
        with self._lock:
            return len(self._runs)

    def sweep(self) -> None:
        """Drop reports of evicted runs (keeps the store and disk bounded)."""
        with self._lock:
            self._sweep_locked()

    def _sweep_locked(self) -> None:
        """Evict beyond ``max_runs``; caller must hold ``self._lock``."""
        if len(self._runs) <= self.max_runs:
            return
        ordered = sorted(self._runs.values(), key=lambda r: r.last_access)
        for stale in ordered[:len(self._runs) - self.max_runs]:
            self._runs.pop(stale.run_id, None)
            if not stale.html_path:
                continue
            outcome_key = id(stale)
            if self._active_leases.get(outcome_key, 0):
                # FileResponse may still be streaming the main report or a
                # split part. Keep the whole run directory until its last
                # response releases the lease.
                self._pending_cleanup[outcome_key] = stale
            else:
                self._delete_outcome_reports(stale)
