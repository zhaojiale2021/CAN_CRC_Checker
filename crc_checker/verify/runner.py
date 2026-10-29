"""Reusable verification runner — the single code path behind the CLI and the web app.

``crc-check run`` and the web ``/api/verify`` endpoint must build the protection
map in exactly the same order (DBC selection → DataID → CRC profile config),
otherwise the two front ends would disagree on the same input. This module owns
that order; the CLI keeps only argument parsing and printing, and the web layer
keeps only transport concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crc_checker.config import RunConfig, apply_crc_config
from crc_checker.crc.models import CRCParams
from crc_checker.dbc.models import ChannelProtectionMap, DBCProtectionMap
from crc_checker.dbc.parser import (
    parse_all_dbc,
    sample_trace_channels,
    select_best_dbc_per_channel,
)
from crc_checker.protect.checksum import CRCVerifier
from crc_checker.protect.rolling_counter import RollingCounterVerifier
from crc_checker.trace.reader import TraceReader
from crc_checker.verify.engine import VerifyEngine
from crc_checker.verify.models import VerifyReport


class RunnerError(ValueError):
    """User-facing setup failure (no DBC, no channel match, missing trace)."""


@dataclass
class ProtectionSetup:  # pylint: disable=too-many-instance-attributes
    """Protection map plus what was loaded on the way (for logs, UI and reports)."""

    protection_map: DBCProtectionMap | ChannelProtectionMap
    dbc_names: list[str] = field(default_factory=list)
    channels: dict[int, str] = field(default_factory=dict)  # channel -> DBC file name
    channel_matches: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    dataid_entries: int = 0
    dataid_sheet: str = ""
    dataid_fallback: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # human-readable run diagnostics


def build_patterns(cfg: RunConfig) -> dict[str, str] | None:
    """Build the signal-name regex overrides from ``signals.*`` (None = auto-detect)."""
    if not cfg.checksum_pattern and not cfg.rc_pattern:
        return None
    patterns: dict[str, str] = {}
    if cfg.checksum_pattern:
        patterns["checksum"] = cfg.checksum_pattern
    if cfg.rc_pattern:
        patterns["rolling_counter"] = cfg.rc_pattern
    return patterns


def build_algorithms(crc_params: CRCParams | None) -> list:
    """Build the protection algorithm list (CRC when configured, always RC)."""
    algorithms: list = [RollingCounterVerifier()]
    if crc_params:
        algorithms.insert(0, CRCVerifier(crc_params, None))
    return algorithms


def _select_dbcs(
    cfg: RunConfig, dbc_maps: list[DBCProtectionMap], trace_sample: str | None,
    notes: list[str],
) -> tuple[DBCProtectionMap | ChannelProtectionMap, dict[int, DBCProtectionMap]]:
    """Pick the protection map: single DBC, merged, or one DBC per trace channel.

    Returns the map together with the per-channel DBC split (empty for the
    single/merged cases, which have no channel dimension).
    """
    if len(dbc_maps) == 1:
        notes.append(f"Using DBC: {Path(dbc_maps[0].dbc_paths[0]).name}")
        return dbc_maps[0], {}

    if cfg.dbc_merge:
        # When every channel can carry frames from every DBC, per-channel
        # selection would drop a DBC — merge them into one map instead.
        merged = dbc_maps[0]
        for other in dbc_maps[1:]:
            merged.merge(other)
        notes.append(f"Merged {len(dbc_maps)} DBCs into one protection map")
        return merged, {}

    if not trace_sample:
        raise RunnerError("Need a trace file to select a DBC per channel.")

    ch_ids = sample_trace_channels(trace_sample, max_frames=1000)
    ch_dbc = select_best_dbc_per_channel(dbc_maps, ch_ids)
    if not ch_dbc:
        raise RunnerError("No DBC matches any trace channel.")

    channel_map = ChannelProtectionMap()
    for ch, pm in ch_dbc.items():
        channel_map.set_channel(ch, pm)
    return channel_map, ch_dbc


def _apply_dataid(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    cfg: RunConfig,
    protection_map: DBCProtectionMap | ChannelProtectionMap,
    ch_dbc: dict[int, DBCProtectionMap],
    notes: list[str],
) -> tuple[int, str, int]:
    """Apply DataID entries; per-channel DBCs load their own sheet, CH0 backfills.

    Returns (entries applied, sheet name, number of fallback entries applied).
    """
    if not (cfg.dataid_xlsx or cfg.dataid_json):
        return 0, "", 0

    entries = 0
    sheet = ""
    fallback = 0

    if isinstance(protection_map, ChannelProtectionMap) and ch_dbc:
        ch0_map = None
        for ch, pm in sorted(ch_dbc.items()):
            ch_dbc_name = Path(pm.dbc_paths[0]).name if pm.dbc_paths else ""
            ch_dataid = cfg.load_dataid(dbc_name=ch_dbc_name)
            if ch_dataid and len(ch_dataid) > 0:
                pm.apply_dataid_map(ch_dataid)
                entries += len(ch_dataid)
                if ch == 0:
                    ch0_map = ch_dataid
                if not sheet and ch_dataid.sheet_name:
                    sheet = ch_dataid.sheet_name
                notes.append(f"CH{ch} DataID: {len(ch_dataid)} entries "
                             f"(sheet: {ch_dataid.sheet_name})")
        # CH1/CH2 borrow CH0's DataID for messages without their own sheet.
        if ch0_map:
            for ch, pm in sorted(ch_dbc.items()):
                if ch == 0:
                    continue
                fallback += pm.apply_dataid_map_fallback(ch0_map)
            if fallback:
                notes.append(f"DataID fallback from CH0: {fallback} entries")
        return entries, sheet, fallback

    dbc_name = ""
    dbc_paths = protection_map.dbc_paths
    if dbc_paths:
        dbc_name = Path(list(dbc_paths)[0]).name
    dataid_map = cfg.load_dataid(dbc_name=dbc_name)
    if dataid_map:
        protection_map.apply_dataid_map(dataid_map)
        entries = len(dataid_map)
        sheet = dataid_map.sheet_name or ""
        notes.append(f"DataID: {entries} entries (sheet: {sheet})")
    return entries, sheet, 0


def build_protection_map(cfg: RunConfig,  # pylint: disable=too-many-locals
                         trace_sample: str | None = None) -> ProtectionSetup:
    """Parse DBCs and apply DataID + CRC configuration.

    Mirrors the order used by ``crc-check run`` (see ``apply_crc_config``).

    Args:
        cfg: Run configuration (paths already resolved).
        trace_sample: First trace file, used to pick a DBC per channel. Only
            needed when several DBCs are configured and ``dbc_merge`` is off.

    Raises:
        RunnerError: no DBC configured, or no DBC matches the trace channels.
    """
    try:
        dbc_paths = cfg.get_dbc_paths()
    except FileNotFoundError as exc:
        raise RunnerError(str(exc)) from exc
    if not dbc_paths:
        raise RunnerError("No DBC files found. Check 'dbc' or 'dbcs' in the config.")

    notes: list[str] = [f"DBC files: {len(dbc_paths)} file(s)"]
    notes.extend(f"  {path}" for path in dbc_paths)

    try:
        dbc_maps = parse_all_dbc(dbc_paths, build_patterns(cfg),
                                 naming=cfg.build_naming_patterns())
    except FileNotFoundError as exc:
        raise RunnerError(str(exc)) from exc
    protection_map, ch_dbc = _select_dbcs(cfg, dbc_maps, trace_sample, notes)

    channels: dict[int, str] = {}
    channel_matches: dict[int, tuple[int, int, int]] = {}
    if ch_dbc and trace_sample:
        ch_ids = sample_trace_channels(trace_sample, max_frames=1000)
        for ch, pm in sorted(ch_dbc.items()):
            name = Path(pm.dbc_paths[0]).name if pm.dbc_paths else ""
            channels[ch] = name
            matched = len(set(pm.all_frame_ids()) & ch_ids.get(ch, set()))
            channel_matches[ch] = (matched, len(pm.all_frame_ids()),
                                   len(ch_ids.get(ch, set())))
            notes.append(
                f"CH{ch} -> {name} ({matched}/{len(pm.all_frame_ids())} IDs, "
                f"{len(ch_ids.get(ch, set()))} trace IDs)")

    dataid_entries, dataid_sheet, dataid_fallback = _apply_dataid(
        cfg, protection_map, ch_dbc, notes)

    if cfg.dataid_default is not None:
        applied = protection_map.apply_dataid_default(cfg.dataid_default)
        if applied:
            notes.append(f"DataID default (0x{cfg.dataid_default:04X}): "
                         f"{applied} groups")

    counts = apply_crc_config(cfg, protection_map)
    for key, label in (
        ("profiles", "E2E profiles applied"),
        ("range_overrides", "CRC range overrides applied"),
        ("skip", "CRC skip list removed"),
        ("auto_classify", "CRC auto-classify (DBC comments)"),
        ("overrides", "CRC overrides applied"),
    ):
        if counts.get(key):
            notes.append(f"{label}: {counts[key]} groups")

    return ProtectionSetup(
        protection_map=protection_map,
        dbc_names=[Path(p).name for p in dbc_paths],
        channels=channels,
        channel_matches=channel_matches,
        dataid_entries=dataid_entries,
        dataid_sheet=dataid_sheet,
        dataid_fallback=dataid_fallback,
        counts=counts,
        notes=notes,
    )


def run_trace(protection_map, algorithms: list, trace_path: str,  # pylint: disable=too-many-arguments,too-many-positional-arguments
              frame_ids: list[int] | None = None,
              max_frames: int | None = None,
              progress_callback=None) -> VerifyReport:
    """Verify one trace file and return its report."""
    engine = VerifyEngine(protection_map, algorithms)
    with TraceReader(trace_path) as reader:
        report = engine.run(reader, frame_ids=frame_ids, max_frames=max_frames,
                            progress_callback=progress_callback)
    report.dbc_paths = protection_map.dbc_paths
    return report


def run_config(cfg: RunConfig, trace_paths: list[str] | None = None,
               progress_callback=None) -> tuple[ProtectionSetup, list[VerifyReport]]:
    """Build the protection map from ``cfg`` and verify every configured trace.

    Args:
        cfg: Run configuration.
        trace_paths: Trace files to verify; defaults to ``cfg.get_trace_paths()``.
        progress_callback: Optional ``callback(done, total)`` per trace file.

    Returns:
        (setup, reports) — one report per trace file, in input order.
    """
    if cfg.crc_auto_classify and not cfg.crc_preset and not cfg.crc_custom:
        # Comment-driven classification needs a fallback algorithm.
        cfg.crc_preset = "CRC8/SAE-J1850"

    paths = list(trace_paths) if trace_paths else cfg.get_trace_paths()
    if not paths:
        raise RunnerError("No trace files to verify.")

    setup = build_protection_map(cfg, trace_sample=paths[0])
    algorithms = build_algorithms(cfg.build_crc_params())

    reports = []
    for index, trace_path in enumerate(paths):
        reports.append(run_trace(setup.protection_map, algorithms, trace_path,
                                 frame_ids=cfg.frame_ids, max_frames=cfg.max_frames))
        if progress_callback:
            progress_callback(index + 1, len(paths))
    return setup, reports
