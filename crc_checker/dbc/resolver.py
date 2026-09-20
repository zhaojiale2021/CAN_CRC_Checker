"""Signal resolver — identifies CRC/Checksum and Rolling Counter signals by name pattern."""

from __future__ import annotations

import re
from crc_checker.dbc.models import SignalInfo, MessageProtection, DBCProtectionMap


# Default regex patterns for identifying protection signals
# Prefix-based naming: Checksum_XXX, CRC_XXX, RollingCounter_XXX (GWM and common)
# Suffix-based naming: XXX_CRC, XXX_Counter (GAC) — added via SUFFIX_PATTERNS
DEFAULT_PATTERNS: dict[str, str] = {
    "checksum":        r"(?i)^(checksum|check_sum|crc|e2e_crc)",
    "rolling_counter": (
        r"(?i)^(rolling.?counter|rolling_?cntr|rc_|live.?counter"
        r"|alive.?counter|alive_)"
    ),
}

# Additional suffix-based patterns for OEMs like GAC, Chery
SUFFIX_PATTERNS: dict[str, str] = {
    "checksum": (
        r"(?i)(_crc$|_checksum$|_e2e_crc$|_crc[0-9]*$"
        r"|_crc_[0-9]+$|_e2e_crc_[0-9]+$"
        r"|_crc[0-9]+_[0-9]+[a-z]*$"
        r"|_checksum[0-9]*$|_checksum_[0-9]+$"
        r"|_crccheck$"
        r"|_chks$|_chks[0-9]*$|chks$|chks[0-9]*$)"
    ),
    "rolling_counter": (
        r"(?i)(_counter$|_counter_[0-9]+$|_alive$|_alive_[0-9]+$"
        r"|_msgcntr$|_msgcntr[0-9]*$"
        r"|_messagecounter$|_messagecounter[0-9]*$"
        r"|_message_counter$|_message_counter[0-9]*$"
        r"|_alivecounter[0-9]*$|_alivecnt[0-9]*$"
        r"|_cntr$|_cntr[0-9]*$|cntr$|cntr[0-9]*$"
        r"|_rollgcntr$|_rollgcntr[0-9]*$"
        r"|_rollgcntr[0-9]+_[0-9]+[a-z]*$"
        r"|_rollingcounter$|_rollingcounter_[0-9]+$"
        r"|_rollingcounter[0-9]*$)"
    ),
}

# ADAS radar frames (SGU/FR/FLR/RLR/RRR sensor protocols) put the source bus in
# the signal name: "SGU1_Msg_CheckSum_Can03" next to "SGU1_Msg_AliveCounter_Can03".
# The trailing bus marker is stripped before pattern matching so the checksum and
# its counter pair up (and so the $ anchors below still work).
_BUS_SUFFIX_RE = re.compile(r'_Can[0-9]+$', re.IGNORECASE)


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
        self._use_suffix = use_suffix
        # Custom patterns are per-key: supplying only "rolling_counter" must
        # keep the default checksum detection (and vice versa). A missing key
        # used to compile an empty regex that matched EVERY signal.
        patterns = patterns or {}
        self._custom_checksum = patterns.get("checksum") or None
        self._custom_rc = patterns.get("rolling_counter") or None
        self._checksum_re = re.compile(
            self._custom_checksum or DEFAULT_PATTERNS["checksum"])
        self._rc_re = re.compile(
            self._custom_rc or DEFAULT_PATTERNS["rolling_counter"])

    @staticmethod
    def strip_bus_suffix(signal_name: str) -> str:
        """Drop a trailing radar bus marker ("_Can03") from a signal name."""
        return _BUS_SUFFIX_RE.sub('', signal_name)

    def is_checksum_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches checksum/CRC pattern.

        Checks both prefix-based (``Checksum_*``, ``CRC_*``) and suffix-based
        (``*_CRC``, ``*_ChecksumN``) naming conventions so that mixed-naming
        DBCs (e.g. GWM ADAS2 with both ``Checksum_RSDS_R_5`` and
        ``RSDS_L_SGU1_Checksum8``) are fully detected.
        """
        if self._custom_checksum:
            return bool(self._checksum_re.search(signal_name))
        signal_name = self.strip_bus_suffix(signal_name)
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

        ``*_BlockCounter`` is deliberately *not* a rolling counter: radar/ADAS
        frames carry a block counter (per data block) next to the alive counter,
        and only the alive counter counts frames.
        """
        if self._custom_rc:
            return bool(self._rc_re.search(signal_name))
        signal_name = self.strip_bus_suffix(signal_name)
        if re.search(r'block_?counter', signal_name, re.IGNORECASE):
            return False
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
          "CCU_1_CRC_1" → "CCU_1_1"  (second E2E instance, index kept)
          "CCU_1_CRC_2" → "CCU_1_2"
          "SGU1_Msg_CheckSum_Can03" → "SGU1_Msg"  (radar bus marker stripped)
        """
        signal_name = SignalResolver.strip_bus_suffix(signal_name)
        # Remove common prefixes (GWM-style / BAIC checksum<ID> naming)
        for prefix in ["Checksum_", "Checksum", "CheckSum_", "CheckSum", "CRC_", "CRC",
                       "E2E_CRC_",
                       "RollingCounter_", "RollingCounter", "Rolling_Counter_",
                       "RollingCntr_", "RC_", "LiveCounter_", "AliveCounter_"]:
            if signal_name.startswith(prefix):
                return signal_name[len(prefix):]

        # Remove common suffixes (GAC-style / b81vs). b81vs uses underscore-less
        # Chks/Cntr directly appended to the name (ADC_ADAS1Chks), which must
        # also be stripped (with the leading underscore variants).
        suffix_match = re.search(
            r'(?:_(CRC|Counter|Alive|Checksum|RollgCntr|RollingCounter|'
            r'MsgCntr|MessageCounter|Message_Counter|AliveCounter|AliveCnt|'
            r'CRCCheck)|'
            r'(?:Chks|Cntr))([0-9]*)(_[0-9]+[a-z]*)?$',
            signal_name, re.IGNORECASE
        )
        if suffix_match:
            prefix = signal_name[:suffix_match.start()]
            # Append CRC index if present (e.g. APA_CRC1 → APA_1, APA_CRC2 → APA_2)
            crc_index = suffix_match.group(2)
            # Index separated by an underscore (GAC "SRS_1_CRC_2") keeps the two
            # E2E instances of one message apart — otherwise CRC_1 and CRC_2
            # collapse into a single group and the later signal wins.
            instance = (suffix_match.group(3) or "").lstrip("_")
            index = crc_index or instance
            if index:
                prefix = f"{prefix}_{index}"
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
            group_list = self._merge_single_unpaired(group_list)
            # Set the count for each group so auto-detect can decide segment vs full
            for g in group_list:
                g.frame_protection_count = len(group_list)
            prot_map.messages[frame_id] = group_list

        return prot_map

    @staticmethod
    def _merge_single_unpaired(
            group_list: list[MessageProtection]) -> list[MessageProtection]:
        """Pair a lone checksum group with a lone RC group in the same frame.

        Suffix extraction pairs checksum and RC signals by their shared name
        prefix, but some OEMs use unrelated names (t1lfl1 IHU_MFS_2: checksum
        ``CRC`` + counter ``ALIVE_MFS_2``). When a frame ends up with exactly
        one checksum-only group and one RC-only group, they belong together.
        """
        if len(group_list) != 2:
            return group_list
        cs_only = [g for g in group_list
                   if g.checksum_signal and not g.rolling_counter_signal]
        rc_only = [g for g in group_list
                   if g.rolling_counter_signal and not g.checksum_signal]
        if len(cs_only) == 1 and len(rc_only) == 1:
            target = cs_only[0]
            target.rolling_counter_signal = rc_only[0].rolling_counter_signal
            if not target.pair_suffix:
                target.pair_suffix = rc_only[0].pair_suffix
            return [target]
        return group_list
