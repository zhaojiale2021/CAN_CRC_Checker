"""Verification orchestration engine."""

from __future__ import annotations
from typing import TYPE_CHECKING
from crc_checker.trace.reader import TraceReader
from crc_checker.dbc.models import DBCProtectionMap
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.verify.models import VerifyReport
from crc_checker.protect.rolling_counter import RollingCounterVerifier

if TYPE_CHECKING:
    from crc_checker.protect.base import ProtectionAlgorithm


class VerifyEngine:
    """Orchestrates verification across all frames and protection algorithms.

    Assembles protection algorithms (CRC, Rolling Counter, etc.) and runs them
    against every frame in a trace, grouped by CAN ID.
    """

    def __init__(self,
                 protection_map: DBCProtectionMap,
                 algorithms: list[ProtectionAlgorithm] | None = None):
        self.protection_map = protection_map
        self.algorithms: list[ProtectionAlgorithm] = algorithms or []

    @classmethod
    def create_default(cls,
                       protection_map: DBCProtectionMap,
                       crc_params: CRCParams | None = None,
                       crc_range: CRCRange | None = None) -> "VerifyEngine":  # pylint: disable=unused-argument
        """Factory: create engine with default CRC + RC verifiers.

        Args:
            protection_map: Parsed DBC protection map.
            crc_params: CRC algorithm parameters (required for CRC verification).
            crc_range: Range of data to include in CRC calculation.

        Returns:
            Configured VerifyEngine instance.
        """
        algorithms: list = []

        if crc_params:
            from crc_checker.protect.checksum import CRCVerifier  # pylint: disable=import-outside-toplevel
            # Pass None to use auto-detect; explicit ranges are applied via protection_map
            algorithms.append(CRCVerifier(crc_params, None))

        algorithms.append(RollingCounterVerifier())

        return cls(protection_map, algorithms)

    @staticmethod
    def _filter_by_dlc(protections: list, frame) -> list:
        """Keep protection groups whose DLC fits the frame.

        A frame whose length differs from the DBC definition is a same-ID
        message from another bus (mixed traces: radar DBC vs vehicle CANFD,
        e.g. 64B P05 frames colliding with 30B radar P01 messages) — verify
        it with the wrong config and every frame fails. Groups with DLC 0
        (unknown) are never gated.
        """
        return [p for p in protections if not p.dlc or p.dlc == frame.dlc]

    def run(self, reader: TraceReader,  # pylint: disable=too-many-branches,too-many-locals
            frame_ids: list[int] | None = None,
            max_frames: int | None = None,
            progress_callback=None) -> VerifyReport:
        """Run verification on all frames in the trace.

        Args:
            reader: TraceReader yielding CanFrame objects.
            frame_ids: Optional list of CAN IDs to filter (None = all).
            max_frames: Optional limit on total frames processed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            VerifyReport with all verification results.
        """
        report = VerifyReport(
            dbc_path=self.protection_map.dbc_path,
            trace_path=reader.file_path,
        )
        # RC series are per-run: continuity state may span several trace files
        # (algorithms are reused), but each report's trend data must reflect
        # only its own trace.
        self._reset_rc_series()
        # Pre-populate frame names and DBC sources from protection map
        for fid, prots in self.protection_map.messages.items():
            if prots:
                report.set_frame_name(fid, prots[0].frame_name)
                if prots[0].dbc_source:
                    report.set_frame_dbc_source(fid, prots[0].dbc_source)

        target_ids = set(frame_ids) if frame_ids else set()
        frame_count = 0

        for frame in reader.frames():
            # Filter by CAN ID (empty set = no filter)
            if target_ids and frame.arbitration_id not in target_ids:
                continue

            # Checked before any `continue` below, so the cap is exact:
            # frames without a protection group must still count towards it.
            if max_frames and frame_count >= max_frames:
                break

            frame_count += 1
            report.total_frames += 1

            # Store frame data for hex-dump display (include channel)
            report.add_frame_data(frame.timestamp, frame.arbitration_id, frame.data,
                                  channel=frame.channel)

            # Find protection groups for this frame (channel-aware)
            protections = self.protection_map.get_protections(
                frame.arbitration_id, channel=frame.channel)
            if protections:
                matched = self._filter_by_dlc(protections, frame)
                if not matched:
                    report.dlc_mismatch_skipped += 1
                protections = matched
            if not protections:
                continue

            # Run each algorithm on each protection group
            for prot in protections:
                for algo in self.algorithms:
                    result = algo.verify(frame, prot)
                    if result is not None:
                        if isinstance(result, list):
                            report.verdicts.extend(result)
                            report.total_verdicts += len(result)
                        else:
                            report.verdicts.append(result)
                            report.total_verdicts += 1

            if progress_callback:
                progress_callback(frame_count, None)

        # Collect the RC value series (every frame) for the HTML trend charts
        self._collect_rc_series(report)

        return report

    def _reset_rc_series(self) -> None:
        """Drop RC series state (per-run; RC continuity state survives)."""
        for algo in self.algorithms:
            if isinstance(algo, RollingCounterVerifier):
                algo.reset_series()

    def _collect_rc_series(self, report: VerifyReport) -> None:
        """Copy the RC verifiers' per-signal value series onto the report."""
        for algo in self.algorithms:
            if isinstance(algo, RollingCounterVerifier):
                for key, points in algo.get_series().items():
                    report.rc_series.setdefault(key, []).extend(points)
                report.rc_series_meta.update(algo.get_series_meta())

    def run_stream(self, reader: TraceReader,
                   frame_ids: list[int] | None = None,
                   max_frames: int | None = None):
        """Stream verification results — yields VerifyVerdict as frames are processed.

        Useful for TUI/progress display while processing large files.
        """
        target_ids = set(frame_ids) if frame_ids else set()
        frame_count = 0

        for frame in reader.frames():
            if target_ids and frame.arbitration_id not in target_ids:
                continue

            if max_frames and frame_count >= max_frames:
                break
            frame_count += 1

            protections = self.protection_map.get_protections(
                frame.arbitration_id, channel=frame.channel)
            if protections:
                protections = self._filter_by_dlc(protections, frame)
            if not protections:
                continue

            for prot in protections:
                for algo in self.algorithms:
                    result = algo.verify(frame, prot)
                    if result is not None:
                        if isinstance(result, list):
                            yield from result
                        else:
                            yield result

    def reset(self):
        """Reset all stateful algorithms (e.g., RC state)."""
        for algo in self.algorithms:
            algo.reset()
