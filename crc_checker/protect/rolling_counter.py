"""Rolling Counter verification algorithm."""

from __future__ import annotations
from crc_checker.protect.base import ProtectionAlgorithm
from crc_checker.trace.models import CanFrame
from crc_checker.dbc.models import MessageProtection
from crc_checker.bit_utils import extract_signal_bits
from crc_checker.verify.models import VerifyVerdict


class RollingCounterVerifier(ProtectionAlgorithm):
    """Verifies Rolling Counter (Alive Counter) continuity in CAN frames.

    Tracks per-(frame_id, signal) state across consecutive frames and detects:
    - PASS: counter increments by 1 (mod 2^length)
    - STALE: counter repeats (same as previous)
    - SKIP: counter jumps by more than 1
    - RESET: counter wraps to 0 unexpectedly

    A broken counter repeats its failure on every frame (e.g. stuck at 14, or
    constant 15 while max_valid=14). Consecutive failing frames are folded into
    ONE verdict — the first one, annotated with ``×N (until t=...)`` — so an
    episode is reported once, not once per frame. Every frame's value is still
    recorded in the per-signal series (see :meth:`get_series`) for the HTML
    trend charts.
    """

    algorithm_type = "rolling_counter"

    def __init__(self):
        # (frame_id, channel, signal_name) -> prev_value
        self._state: dict[tuple[int, int, str], int] = {}
        # track first occurrence
        self._first_seen: dict[tuple[int, int, str], bool] = {}
        # (frame_id, channel, signal_name) -> [(timestamp, value, is_pass, category)]
        self._series: dict[tuple[int, int, str], list[tuple]] = {}
        # key -> {"length": bit length, "max_valid": wrap limit} (for the trend charts)
        self._series_meta: dict[tuple[int, int, str], dict] = {}
        # key -> open error episode (first verdict + repeat count)
        self._open_fail: dict[tuple[int, int, str], dict] = {}

    def reset(self):
        """Clear all accumulated RC state."""
        self._state.clear()
        self._first_seen.clear()
        self._reset_run()

    def reset_series(self):
        """Drop per-run series + open episodes (continuity state survives).

        Called per report run: RC continuity state may legitimately span
        several trace files, but each report's trend data must reflect only
        its own trace.
        """
        self._reset_run()

    def _reset_run(self):
        self._series.clear()
        self._series_meta.clear()
        self._open_fail.clear()

    def get_series(self) -> dict[tuple[int, int, str], list[tuple]]:
        """Per-signal value series recorded during the run.

        Returns a dict keyed by (frame_id, channel, signal_name); each value is
        a list of (timestamp, value, is_pass, category) tuples, one per frame.
        """
        return self._series

    def get_series_meta(self) -> dict[tuple[int, int, str], dict]:
        """Per-signal chart metadata (bit length + max valid) for :meth:`get_series`."""
        return self._series_meta

    @staticmethod
    def _category(detail: str) -> str:
        """Short verdict category ("STALE"/"RESET"/"INVALID"/"SKIP") from detail."""
        return detail.split(":", 1)[0] if detail else ""

    def verify(self, frame: CanFrame, protection: MessageProtection) -> VerifyVerdict | None:  # pylint: disable=too-many-locals
        """Verify rolling counter for a frame."""
        rc_signal = protection.rolling_counter_signal
        if rc_signal is None:
            return None

        actual_value = extract_signal_bits(
            frame.data, rc_signal.start_bit, rc_signal.length, rc_signal.byte_order
        )

        key = (frame.arbitration_id, frame.channel, rc_signal.name)
        bit_max = (1 << rc_signal.length) - 1
        # rc_max_valid: max value before wrapping (e.g., 14 means valid range 0-14, 15=invalid)
        max_valid = protection.rc_max_valid if protection.rc_max_valid is not None else bit_max

        # First time seeing this signal — no baseline to compare
        if key not in self._first_seen:
            self._first_seen[key] = True
            self._state[key] = actual_value
            valid_note = f" (valid range: 0-{max_valid})" if max_valid < bit_max else ""
            self._series.setdefault(key, []).append((frame.timestamp, actual_value, True, ""))
            self._series_meta[key] = {"length": rc_signal.length, "max_valid": max_valid}
            return VerifyVerdict(
                frame_id=frame.arbitration_id,
                timestamp=frame.timestamp,
                algorithm=self.algorithm_type,
                signal_name=rc_signal.name,
                expected_value=actual_value,
                actual_value=actual_value,
                is_pass=True,
                detail=f"First occurrence — baseline set to {actual_value}{valid_note}",
                start_bit=rc_signal.start_bit,
                length=rc_signal.length,
                byte_order=rc_signal.byte_order,
                dataid=protection.dataid,
                dataid_name=protection.dataid_name,
                dataid_profile=protection.crc_profile,
            )

        prev_value = self._state[key]
        expected_value = (prev_value + 1) if prev_value < max_valid else 0

        # Determine verdict
        if actual_value == expected_value:
            is_pass = True
            detail = ""
        elif actual_value == prev_value:
            is_pass = False
            detail = (f"STALE: counter stuck at {actual_value} "
                      f"(expected {expected_value}, previous {prev_value})")
        elif prev_value == max_valid and actual_value == 0:
            # Normal wrap: max_valid -> 0
            is_pass = True
            detail = ""
        elif actual_value == 0 and prev_value != max_valid:
            is_pass = False
            detail = (f"RESET: counter wrapped to 0 unexpectedly "
                      f"(previous was {prev_value}, expected {expected_value})")
        elif actual_value > max_valid:
            is_pass = False
            detail = f"INVALID: value {actual_value} exceeds max valid {max_valid}"
        else:
            is_pass = False
            gap = (actual_value - prev_value - 1) % (max_valid + 1)  # pylint: disable=superfluous-parens
            detail = (f"SKIP: counter jumped from {prev_value} to {actual_value} "
                      f"(gap of {gap + 1}, expected {expected_value})")

        # Update state
        self._state[key] = actual_value

        category = self._category(detail)
        self._series.setdefault(key, []).append(
            (frame.timestamp, actual_value, is_pass, category))

        # Consecutive failing frames fold into ONE verdict (the first), so a
        # stuck/invalid counter is recorded once per episode, not per frame.
        verdict = VerifyVerdict(
            frame_id=frame.arbitration_id,
            timestamp=frame.timestamp,
            algorithm=self.algorithm_type,
            signal_name=rc_signal.name,
            expected_value=expected_value,
            actual_value=actual_value,
            is_pass=is_pass,
            detail=detail,
            start_bit=rc_signal.start_bit,
            length=rc_signal.length,
            byte_order=rc_signal.byte_order,
            dataid=protection.dataid,
            dataid_name=protection.dataid_name,
            dataid_profile=protection.crc_profile,
        )
        if not is_pass:
            episode = self._open_fail.get(key)
            if episode is not None:
                episode["count"] += 1
                folded = episode["verdict"]
                folded.repeat_count = episode["count"]
                folded.detail = (f"{episode['base']} · ×{episode['count']} "
                                 f"(until {frame.timestamp:.6f}s)")
                return None
            self._open_fail[key] = {"base": detail, "verdict": verdict, "count": 1}
        else:
            self._open_fail.pop(key, None)

        return verdict
