"""Signal resolver — identifies CRC/Checksum and Rolling Counter signals by name pattern."""

from __future__ import annotations

import re
from crc_checker.dbc.models import SignalInfo, MessageProtection, DBCProtectionMap


# Default regex patterns for identifying protection signals
DEFAULT_PATTERNS: dict[str, str] = {
    "checksum":        r"(?i)^(checksum|check_sum|crc|e2e_crc)",
    "rolling_counter": r"(?i)^(rolling.?counter|rolling_?cntr|rc_|live.?counter|alive.?counter)",
}


class SignalResolver:
    """Identifies protection signals within CAN messages by name matching."""

    def __init__(self, patterns: dict[str, str] | None = None):
        self.patterns = patterns or DEFAULT_PATTERNS.copy()
        self._checksum_re = re.compile(self.patterns["checksum"])
        self._rc_re = re.compile(self.patterns["rolling_counter"])

    def is_checksum_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches checksum/CRC pattern."""
        return bool(self._checksum_re.match(signal_name))

    def is_rolling_counter_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches rolling counter pattern."""
        return bool(self._rc_re.match(signal_name))

    @staticmethod
    def extract_suffix(signal_name: str) -> str:
        """Extract the suffix after the protection type prefix.

        E.g., "Checksum_ACC1" -> "ACC1"
              "RollingCounter_IFC2" -> "IFC2"
              "Checksum_ACC14" -> "ACC14"
        """
        # Remove common prefixes
        for prefix in ["Checksum_", "CheckSum_", "CRC_", "E2E_CRC_",
                       "RollingCounter_", "RollingCounter", "Rolling_Counter_",
                       "RollingCntr_", "RC_", "LiveCounter_", "AliveCounter_"]:
            if signal_name.startswith(prefix):
                return signal_name[len(prefix):]
        # Fallback: take everything after the last underscore
        if "_" in signal_name:
            return signal_name.rsplit("_", 1)[-1]
        return signal_name

    def build_protection_map(self, frames: list[dict]) -> DBCProtectionMap:
        """Build a DBCProtectionMap from parsed DBC frame/signal data.

        Args:
            frames: List of dicts with keys:
                - frame_id: int
                - frame_name: str
                - dlc: int
                - signals: list of dicts with name, start_bit, length, byte_order

        Returns:
            DBCProtectionMap with all identified protection groups.
        """
        prot_map = DBCProtectionMap(dbc_path="")

        for frame in frames:
            frame_id = frame["frame_id"]
            frame_name = frame["frame_name"]
            dlc = frame["dlc"]

            # Find all checksum and RC signals in this frame
            checksum_signals: list[SignalInfo] = []
            rc_signals: list[SignalInfo] = []

            for sig in frame.get("signals", []):
                sig_info = SignalInfo(
                    name=sig["name"],
                    start_bit=sig.get("start_bit", 0),
                    length=sig.get("length", 0),
                    byte_order=sig.get("byte_order", "little_endian"),
                )
                if self.is_checksum_signal(sig["name"]):
                    checksum_signals.append(sig_info)
                if self.is_rolling_counter_signal(sig["name"]):
                    rc_signals.append(sig_info)

            if not checksum_signals and not rc_signals:
                continue

            # Pair checksum and RC signals by suffix
            groups: dict[str, MessageProtection] = {}

            for cs in checksum_signals:
                suffix = self.extract_suffix(cs.name)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                groups[suffix].checksum_signal = cs

            for rc in rc_signals:
                suffix = self.extract_suffix(rc.name)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                groups[suffix].rolling_counter_signal = rc

            group_list = list(groups.values())
            # Set the count for each group so auto-detect can decide segment vs full
            for g in group_list:
                g.frame_protection_count = len(group_list)
            prot_map.messages[frame_id] = group_list

        return prot_map
