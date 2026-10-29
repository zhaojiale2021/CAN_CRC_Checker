"""Signal resolver — identifies CRC/Checksum and Rolling Counter signals by name pattern.

The patterns themselves are configuration (``crc_checker/data/patterns.yaml``,
see :mod:`crc_checker.patterns`). This module only applies them:

* prefix names (``Checksum_*``, ``CRC_*``, ``RollingCounter_*``),
* suffix names (``*_CRC``, ``*_Checksum8``, ``*_Counter``),
* a trailing bus marker in sensor signal names (``*_Can03``).
"""

from __future__ import annotations

import re

from crc_checker.dbc.models import SignalInfo, MessageProtection, DBCProtectionMap
from crc_checker.patterns import DEFAULT_NAMING, NamingPatterns, join_patterns


# Kept as plain dicts for callers that imported them before patterns became
# configurable. New code should use :class:`crc_checker.patterns.NamingPatterns`.
DEFAULT_PATTERNS: dict[str, str] = {
    "checksum": join_patterns(DEFAULT_NAMING.checksum_prefix),
    "rolling_counter": join_patterns(DEFAULT_NAMING.rolling_counter_prefix),
}
SUFFIX_PATTERNS: dict[str, str] = {
    "checksum": join_patterns(DEFAULT_NAMING.checksum_suffix),
    "rolling_counter": join_patterns(DEFAULT_NAMING.rolling_counter_suffix),
}


class SignalResolver:
    """Identifies protection signals within CAN messages by name matching.

    Supports prefix-based (``Checksum_XXX``, ``CRC_XXX``) and suffix-based
    (``XXX_CRC``, ``XXX_Counter``) naming conventions. Prefix and suffix rules
    are always both checked, so mixed-naming DBCs are fully detected. The
    ``use_suffix`` flag only records the dominant convention found by
    :meth:`detect_naming_convention`.

    A custom ``checksum``/``rolling_counter`` regex (from
    ``signals.checksum_pattern`` / ``signals.rc_pattern``) replaces all built-in
    matching for that category and is applied with ``re.search``.
    """

    def __init__(self, patterns: dict[str, str] | None = None,
                 use_suffix: bool = False,
                 naming: NamingPatterns | None = None):
        self._use_suffix = use_suffix
        self.naming = naming or DEFAULT_NAMING
        patterns = patterns or {}
        self._custom_checksum = patterns.get("checksum") or None
        self._custom_rc = patterns.get("rolling_counter") or None
        self._checksum_re = (re.compile(self._custom_checksum)
                             if self._custom_checksum else None)
        self._rc_re = (re.compile(self._custom_rc)
                       if self._custom_rc else None)

    @staticmethod
    def strip_bus_suffix(signal_name: str,
                         naming: NamingPatterns | None = None) -> str:
        """Drop a trailing sensor bus marker (``_Can03``) from a signal name."""
        return (naming or DEFAULT_NAMING).bus_suffix_re.sub('', signal_name)

    def is_checksum_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches a checksum/CRC pattern."""
        if self._checksum_re is not None:
            return bool(self._checksum_re.search(signal_name))
        name = self.strip_bus_suffix(signal_name, self.naming)
        return bool(self.naming.checksum_re.match(name)
                    or self.naming.checksum_suffix_re.search(name))

    def is_rolling_counter_signal(self, signal_name: str) -> bool:
        """Check if a signal name matches a rolling-counter pattern.

        Block counters are deliberately excluded: they count data blocks, not
        frames, so they must not be tracked as rolling counters.
        """
        if self._rc_re is not None:
            return bool(self._rc_re.search(signal_name))
        name = self.strip_bus_suffix(signal_name, self.naming)
        if self.naming.exclude_re.search(name):
            return False
        return bool(self.naming.rolling_counter_re.match(name)
                    or self.naming.rolling_counter_suffix_re.search(name))

    @staticmethod
    def detect_naming_convention(frames: list[dict],
                                 naming: NamingPatterns | None = None) -> bool:
        """Auto-detect whether the DBC is primarily suffix-based.

        Returns True only when there are NO prefix-based matches but there ARE
        at least ``detect.min_suffix_matches`` suffix-based matches. This avoids
        false positives from signals like ``Sync_CRC``.
        """
        naming = naming or DEFAULT_NAMING
        prefix_count = 0
        suffix_only_count = 0

        for frame in frames:
            for sig in frame.get("signals", []):
                name = sig["name"]
                has_prefix = bool(
                    naming.checksum_re.match(name)
                    or naming.rolling_counter_re.match(name))
                has_suffix = bool(
                    naming.checksum_suffix_re.search(name)
                    or naming.rolling_counter_suffix_re.search(name))
                if has_prefix:
                    prefix_count += 1
                elif has_suffix:
                    suffix_only_count += 1

        return (prefix_count == 0
                and suffix_only_count >= naming.min_suffix_matches)

    @staticmethod
    def extract_suffix(signal_name: str,
                       naming: NamingPatterns | None = None) -> str:
        """Extract the suffix used to pair checksum and RC signals.

        Prefix-based naming:
          "Checksum_ACC1" → "ACC1"
          "RollingCounter_IFC2" → "IFC2"

        Suffix-based naming:
          "CCU_1_CRC" → "CCU_1"
          "CCU_1_CRC_1" → "CCU_1_1"  (second E2E instance, index kept)
          "SGU1_Msg_CheckSum_Can03" → "SGU1_Msg"  (bus marker stripped)
        """
        signal_name = SignalResolver.strip_bus_suffix(signal_name, naming)
        # Remove common prefixes (prefix-based naming)
        for prefix in ["Checksum_", "Checksum", "CheckSum_", "CheckSum", "CRC_", "CRC",
                       "E2E_CRC_",
                       "RollingCounter_", "RollingCounter", "Rolling_Counter_",
                       "RollingCntr_", "RC_", "LiveCounter_", "AliveCounter_"]:
            if signal_name.startswith(prefix):
                return signal_name[len(prefix):]

        # Remove common suffixes. The underscore-less Chks/Cntr forms
        # ("ADC_ADAS1Chks") are stripped too.
        suffix_match = re.search(
            r'(?:_(CRC|Counter|Alive|Checksum|RollgCntr|RollingCounter|'
            r'MsgCntr|MessageCounter|Message_Counter|AliveCounter|AliveCnt|'
            r'CRCCheck)|'
            r'(?:Chks|Cntr))([0-9]*)(_[0-9]+[a-z]*)?$',
            signal_name, re.IGNORECASE
        )
        if suffix_match:
            prefix = signal_name[:suffix_match.start()]
            # Append the CRC index if present (APA_CRC1 → APA_1). An index
            # separated by an underscore ("CCU_1_CRC_2") keeps two E2E
            # instances of one message apart.
            crc_index = suffix_match.group(2)
            instance = (suffix_match.group(3) or "").lstrip("_")
            index = crc_index or instance
            if index:
                prefix = f"{prefix}_{index}"
            return prefix

        # Fallback: take the part before the last underscore.
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
                    # Keep the DBC comment (algorithm description) for
                    # auto-classification.
                    checksum_comments[sig["name"]] = sig.get("comment", "")
                if self.is_rolling_counter_signal(sig["name"]):
                    rc_signals.append(sig_info)

            if not checksum_signals and not rc_signals:
                continue

            groups: dict[str, MessageProtection] = {}

            for cs in checksum_signals:
                suffix = self.extract_suffix(cs.name, self.naming)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                groups[suffix].checksum_signal = cs
                groups[suffix].checksum_comment = checksum_comments.get(cs.name, "")

            for rc in rc_signals:
                suffix = self.extract_suffix(rc.name, self.naming)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                groups[suffix].rolling_counter_signal = rc

            group_list = list(groups.values())
            group_list = self._merge_single_unpaired(group_list)
            for group in group_list:
                group.frame_protection_count = len(group_list)
            prot_map.messages[frame_id] = group_list

        return prot_map

    @staticmethod
    def _merge_single_unpaired(
            group_list: list[MessageProtection]) -> list[MessageProtection]:
        """Pair a lone checksum group with a lone RC group in the same frame.

        Suffix extraction pairs signals by their shared name, but some DBCs use
        unrelated names (checksum ``CRC`` + counter ``ALIVE_FOO``). When a frame
        ends up with exactly one checksum-only group and one RC-only group, they
        belong together.
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
