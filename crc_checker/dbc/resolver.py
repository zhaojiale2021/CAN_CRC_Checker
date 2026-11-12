"""Signal resolver — identifies CRC/Checksum and Rolling Counter signals by name pattern.

The patterns themselves are configuration (``crc_checker/data/patterns.yaml``,
see :mod:`crc_checker.patterns`). This module only applies them:

* prefix names (``Checksum_*``, ``CRC_*``, ``RollingCounter_*``),
* suffix names (``*_CRC``, ``*_Checksum8``, ``*_Counter``),
* a trailing bus marker in sensor signal names (``*_Can03``).
"""

from __future__ import annotations

import logging
import re

from crc_checker.dbc.models import SignalInfo, MessageProtection, DBCProtectionMap
from crc_checker.patterns import DEFAULT_NAMING, NamingPatterns, join_patterns

logger = logging.getLogger("crc_checker")

# E2E instance index at the end of a matched suffix (``_CRC_2`` → ``2``,
# ``_CRC2_3`` → ``2`` to keep the historical pairing behaviour).
_PAIR_INDEX = re.compile(r"([0-9]+)(?:_[0-9]+[a-z]*)?$")


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

        The configured patterns (``patterns.yaml`` or ``signals.patterns_file``)
        drive both detection *and* pairing — a custom regex must not fall back
        to a parallel hard-coded name list, or the two can disagree and pair
        the wrong signals.

        Prefix-based naming:
          "Checksum_ACC1" → "ACC1"
          "RollingCounter_IFC2" → "IFC2"

        Suffix-based naming:
          "CCU_1_CRC" → "CCU_1"
          "CCU_1_CRC_1" → "CCU_1_1"  (E2E instance index kept, so the two
          "CCU_1_CRC_2" → "CCU_1_2"   instances stay separate groups)
          "SGU1_Msg_CheckSum_Can03" → "SGU1_Msg"  (bus marker stripped)
        """
        naming = naming or DEFAULT_NAMING
        signal_name = SignalResolver.strip_bus_suffix(signal_name, naming)

        # Prefix-based: strip whatever the configured prefix regex matched.
        for prefix_re in (naming.checksum_re, naming.rolling_counter_re):
            match = prefix_re.match(signal_name)
            if match and match.end() > 0:
                return signal_name[match.end():].lstrip("_")

        # Suffix-based: the configured suffix regex tells us where the pair
        # name ends; keep a trailing E2E instance index as part of the name.
        for suffix_re in (naming.checksum_suffix_re,
                          naming.rolling_counter_suffix_re):
            match = suffix_re.search(signal_name)
            if match is None:
                continue
            base = signal_name[:match.start()]
            index = _PAIR_INDEX.search(signal_name[match.start():])
            if base and index:
                return f"{base}_{index.group(1)}"
            return base

        # Fallback: take the part before the last underscore.
        if "_" in signal_name:
            parts = signal_name.rsplit("_", 1)
            return parts[0]
        return signal_name

    def build_protection_map(self, frames: list[dict]) -> DBCProtectionMap:  # pylint: disable=too-many-locals,too-many-branches
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
                if not suffix and self._custom_checksum:
                    logger.warning(
                        "0x%03X %s: custom checksum pattern leaves '%s' with no "
                        "pair suffix; it will not pair with a counter",
                        frame_id, frame_name, cs.name)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                elif groups[suffix].checksum_signal is not None:
                    # Two checksums collapsing onto one suffix (e.g. bus
                    # markers stripped) means one of them is never verified.
                    logger.warning(
                        "0x%03X %s: checksum '%s' overwrites '%s' "
                        "(same pair suffix '%s')",
                        frame_id, frame_name, cs.name,
                        groups[suffix].checksum_signal.name, suffix)
                groups[suffix].checksum_signal = cs
                groups[suffix].checksum_comment = checksum_comments.get(cs.name, "")

            for rc in rc_signals:
                suffix = self.extract_suffix(rc.name, self.naming)
                if not suffix and self._custom_rc:
                    logger.warning(
                        "0x%03X %s: custom counter pattern leaves '%s' with no "
                        "pair suffix; it will not pair with a checksum",
                        frame_id, frame_name, rc.name)
                if suffix not in groups:
                    groups[suffix] = MessageProtection(
                        frame_id=frame_id, frame_name=frame_name,
                        dlc=dlc, pair_suffix=suffix,
                    )
                elif groups[suffix].rolling_counter_signal is not None:
                    logger.warning(
                        "0x%03X %s: rolling counter '%s' overwrites '%s' "
                        "(same pair suffix '%s')",
                        frame_id, frame_name, rc.name,
                        groups[suffix].rolling_counter_signal.name, suffix)
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
