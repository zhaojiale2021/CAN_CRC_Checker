"""Verification orchestration engine."""

from __future__ import annotations
from typing import TYPE_CHECKING
from crc_checker.trace.reader import TraceReader
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.verify.models import VerifyVerdict, VerifyReport

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
                       crc_range: CRCRange | None = None) -> "VerifyEngine":
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
            from crc_checker.protect.checksum import CRCVerifier
            # Pass None to use auto-detect; explicit ranges are applied via protection_map
            algorithms.append(CRCVerifier(crc_params, None))

        from crc_checker.protect.rolling_counter import RollingCounterVerifier
        algorithms.append(RollingCounterVerifier())

        return cls(protection_map, algorithms)

    def run(self, reader: TraceReader,
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
        # Pre-populate frame names and DBC sources from protection map
        for fid, prots in self.protection_map.messages.items():
            if prots:
                report.set_frame_name(fid, prots[0].frame_name)
                if prots[0].dbc_source:
                    report.set_frame_dbc_source(fid, prots[0].dbc_source)

        target_ids = set(frame_ids) if frame_ids else None
        frame_count = 0

        for frame in reader.frames():
            # Filter by CAN ID
            if target_ids and frame.arbitration_id not in target_ids:
                continue

            frame_count += 1
            report.total_frames += 1

            # Store frame data for hex-dump display (include channel)
            report.add_frame_data(frame.timestamp, frame.arbitration_id, frame.data,
                                  channel=frame.channel)

            # Find protection groups for this frame (channel-aware)
            protections = self.protection_map.get_protections(
                frame.arbitration_id, channel=frame.channel)
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

            if max_frames and frame_count >= max_frames:
                break

        return report

    def run_stream(self, reader: TraceReader,
                   frame_ids: list[int] | None = None,
                   max_frames: int | None = None):
        """Stream verification results — yields VerifyVerdict as frames are processed.

        Useful for TUI/progress display while processing large files.
        """
        target_ids = set(frame_ids) if frame_ids else None
        frame_count = 0

        for frame in reader.frames():
            if target_ids and frame.arbitration_id not in target_ids:
                continue

            frame_count += 1
            protections = self.protection_map.get_protections(frame.arbitration_id)
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

            if max_frames and frame_count >= max_frames:
                break

    def reset(self):
        """Reset all stateful algorithms (e.g., RC state)."""
        for algo in self.algorithms:
            algo.reset()
