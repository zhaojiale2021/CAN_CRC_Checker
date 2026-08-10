"""Signal resolver — identifies CRC/Checksum and Rolling Counter signals by name pattern."""

from __future__ import annotations

import re
from crc_checker.dbc.models import SignalInfo, MessageProtection, DBCProtectionMap


# Default regex patterns for identifying protection signals
# Prefix-based naming: Checksum_XXX, CRC_XXX, RollingCounter_XXX (GWM and common)
# Suffix-based naming: XXX_CRC, XXX_Counter (GAC) — added via SUFFIX_PATTERNS
DEFAULT_PATTERNS: dict[str, str] = {
    "checksum":        r"(?i)^(checksum|check_sum|crc|e2e_crc)",
    "rolling_counter": r"(?i)^(rolling.?counter|rolling_?cntr|rc_|live.?counter|alive.?counter)",
}

# Additional suffix-based patterns for OEMs like GAC, Chery
SUFFIX_PATTERNS: dict[str, str] = {
    "checksum": (
        r"(?i)(_crc$|_checksum$|_e2e_crc$|_crc[0-9]*$"
        r"|_crc[0-9]+_[0-9]+[a-z]*$"
        r"|_checksum[0-9]*$)"
    ),
    "rolling_counter": (
        r"(?i)(_counter$|_counter_[0-9]+$|_alive$|_alive_[0-9]+$"
        r"|_msgcntr$|_msgcntr[0-9]*$"
        r"|_messagecounter$|_messagecounter[0-9]*$"
        r"|_alivecounter$|_alivecnt$"
        r"|_rollgcntr$|_rollgcntr[0-9]*$"
        r"|_rollgcntr[0-9]+_[0-9]+[a-z]*$"
        r"|_rollingcounter$|_rollingcounter_[0-9]+$"
        r"|_rollingcounter[0-9]*$)"
    ),
}


class SignalResolver:
    """Identifies protection signals within CAN messages by name matching.

    Supports both prefix-based (``Checksum_XXX``, ``CRC_XXX``) and suffix-based
    (``XXX_CRC``, ``XXX_Counter``, ``XXX_Checksum8``) naming conventions.

    Prefix patterns are always checked first. Suffix patterns are also always
    checked as a fallback, so mixed-naming DBCs (e.g. GWM ADAS2 with both
    ``Checksum_RSDS_R_5`` and ``RSDS_L_SGU1_Checksum8``) are fully detected.

    The ``use_suffix`` flag controls only ``detect_naming_convention``, which
    determines whether the DBC is *primarily* suffix-based (GAC-style).
    """

    def __init__(self, patterns: dict[str, str] | None = None,
                 use_suffix: bool = False):
        self._custom_patterns = patterns
        self._use_suffix = use_suffix
        if patterns:
            self._checksum_re = re.compile(patterns.get("checksum", ""))
            self._rc_re = re.compile(patterns.get("rolling_counter", ""))
        else:
            self._checksum_re = re.compile(DEFAULT_PATTERNS["checksum"])
            self._rc_re = re.compile(DEFAULT_PATTERNS["rolling_counter"])

    def is_checksum_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches checksum/CRC pattern.

        Checks both prefix-based (``Checksum_*``, ``CRC_*``) and suffix-based
        (``*_CRC``, ``*_ChecksumN``) naming conventions so that mixed-naming
        DBCs (e.g. GWM ADAS2 with both ``Checksum_RSDS_R_5`` and
        ``RSDS_L_SGU1_Checksum8``) are fully detected.
        """
        if self._custom_patterns:
            return bool(self._checksum_re.search(signal_name))
        if self._checksum_re.match(signal_name):
            return True
        # Always check suffix patterns as well (not gated by use_suffix).
        # Suffix-only signals like RSDS_L_SGU1_Checksum8 may coexist with
        # prefix-based signals in the same DBC.
        return bool(re.search(SUFFIX_PATTERNS["checksum"], signal_name))

    def is_rolling_counter_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches rolling counter pattern.

        Checks both prefix-based (``RollingCounter_*``, ``RC_*``) and
        suffix-based (``*_Counter``, ``*_RollingCounterN``) naming
        conventions so that mixed-naming DBCs are fully detected.
        """
        if self._custom_patterns:
            return bool(self._rc_re.search(signal_name))
        if self._rc_re.match(signal_name):
            return True
        # Always check suffix patterns as well (not gated by use_suffix).
        return bool(re.search(SUFFIX_PATTERNS["rolling_counter"], signal_name))

    @staticmethod
    def detect_naming_convention(frames: list[dict]) -> bool:
        """Auto-detect whether the DBC uses suffix-based naming (GAC-style).

        Returns True only when there are NO prefix-based matches but there ARE
        suffix-based matches. This avoids false positives from signals like
        ``Sync_CRC`` that happen to end with ``_CRC`` but are not protection signals.

        GWM-style: all protection signals use prefix (Checksum_*, CRC_*)
        GAC-style: no prefix matches, all use suffix (XXX_CRC, XXX_Counter)
        """
        cs_re = re.compile(DEFAULT_PATTERNS["checksum"])
        rc_re = re.compile(DEFAULT_PATTERNS["rolling_counter"])
        prefix_count = 0
        suffix_only_count = 0

        for frame in frames:
            for sig in frame.get("signals", []):
                name = sig["name"]
                has_prefix = bool(cs_re.match(name) or rc_re.match(name))
                has_suffix = bool(
                    re.search(SUFFIX_PATTERNS["checksum"], name) or
                    re.search(SUFFIX_PATTERNS["rolling_counter"], name)
                )
                if has_prefix:
                    prefix_count += 1
                elif has_suffix:
                    suffix_only_count += 1

        # Only use suffix if there are zero prefix matches AND at least
        # 3 suffix-only matches (avoids false positives like Sync_CRC)
        min_suffix = 3
        return prefix_count == 0 and suffix_only_count >= min_suffix

    @staticmethod
    def extract_suffix(signal_name: str) -> str:
        """Extract the suffix for pairing CRC and RC signals.

        Prefix-based naming (GWM-style):
          "Checksum_ACC1" → "ACC1"
          "RollingCounter_IFC2" → "IFC2"

        Suffix-based naming (GAC-style):
          "CCU_1_CRC" → "CCU_1"
          "CCU_1_Counter" → "CCU_1"
          "CCU_1_CRC_1" → "CCU_1"  (variant with index)
        """
        # Remove common prefixes (GWM-style)
        for prefix in ["Checksum_", "CheckSum_", "CRC_", "E2E_CRC_",
                       "RollingCounter_", "RollingCounter", "Rolling_Counter_",
                       "RollingCntr_", "RC_", "LiveCounter_", "AliveCounter_"]:
            if signal_name.startswith(prefix):
                return signal_name[len(prefix):]

        # Remove common suffixes (GAC-style)
        suffix_match = re.search(
            r'_(CRC|Counter|Alive|Checksum|RollgCntr|RollingCounter|'
            r'MsgCntr|MessageCounter|AliveCounter|AliveCnt)'
            r'([0-9]*)(_[0-9]+[a-z]*)?$',
            signal_name, re.IGNORECASE
        )
        if suffix_match:
            prefix = signal_name[:suffix_match.start()]
            # Append CRC index if present (e.g. APA_CRC1 → APA_1, APA_CRC2 → APA_2)
            crc_index = suffix_match.group(2)
            if crc_index:
                prefix = f"{prefix}_{crc_index}"
            return prefix

        # Fallback: take part between first and last underscore
        if "_" in signal_name:
            parts = signal_name.rsplit("_", 1)
            return parts[0]
        return signal_name

    def build_protection_map(self, frames: list[dict]) -> DBCProtectionMap:  # pylint: disable=too-many-locals
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
        prot_map = DBCProtectionMap()

        for frame in frames:
            frame_id = frame["frame_id"]
            frame_name = frame["frame_name"]
            dlc = frame["dlc"]

            # Find all checksum and RC signals in this frame
            checksum_signals: list[SignalInfo] = []
            rc_signals: list[SignalInfo] = []
            checksum_comments: dict[str, str] = {}

            for sig in frame.get("signals", []):
                sig_info = SignalInfo(
                    name=sig["name"],
                    start_bit=sig.get("start_bit", 0),
                    length=sig.get("length", 0),
                    byte_order=sig.get("byte_order", "little_endian"),
                )
                if self.is_checksum_signal(sig["name"]):
                    checksum_signals.append(sig_info)
                    # Remember the DBC comment (algorithm description) for
                    # auto-classification (fx12fl). Keep it on the signal and
                    # copy it onto the protection group below.
                    checksum_comments[sig["name"]] = sig.get("comment", "")
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
                groups[suffix].checksum_comment = checksum_comments.get(cs.name, "")

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
