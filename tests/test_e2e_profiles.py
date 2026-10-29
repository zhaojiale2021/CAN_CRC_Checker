"""E2E profile / multi-instance tests.

Covers the pieces that let one engine serve a bus mixing two E2E profiles:

* Profile 5 / Profile 1 selection (by CRC width) with the per-profile DataID
  layout (append vs prepend) and byte-swap.
* Multi-CRC messages: two instances in one frame, each with its own DataID and
  CRC range.
* DataID rows keyed by the CRC signal name from a remark column.
"""

import pytest

from crc_checker.crc.classify import build_crc_params_from_comment, classify_crc_algo
from crc_checker.crc.profiles import (
    BUILTIN_PROFILES, E2EProfile, load_profiles, profile_key_from_hint,
    profile_key_from_width,
)
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.dbc.resolver import SignalResolver
from crc_checker.dataid.parser import (
    BUILTIN_MAPPINGS, DataIDMap, _add_dataid_row, _entry_names,
    normalize_signal_key,
)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

class TestProfiles:
    """E2E profile table: selection rules and config overrides."""

    def test_key_from_hint(self):
        """Profile hints from the DataID Remark column map to profile keys."""
        assert profile_key_from_hint("Profile 1A") == "p01"
        assert profile_key_from_hint("Profile Variant 1A") == "p01"
        assert profile_key_from_hint("E2E Profile 5") == "p05"
        assert profile_key_from_hint("") is None
        assert profile_key_from_hint("no digits here") is None

    def test_key_from_width(self):
        """Firmware rule: 2-byte CRC → Profile 5, 1-byte CRC → Profile 1."""
        assert profile_key_from_width(16) == "p05"
        assert profile_key_from_width(8) == "p01"
        assert profile_key_from_width(4) is None

    def test_builtin_defaults_keep_legacy_behaviour(self):
        """Built-in Profile 1 stays CRC8/SAE-J1850-ZERO with inherited range."""
        assert BUILTIN_PROFILES["p01"].preset == "CRC8/SAE-J1850-ZERO"
        assert BUILTIN_PROFILES["p01"].dataid_position == "prepend"
        assert BUILTIN_PROFILES["p01"].to_range() is None

    def test_override_with_nested_range(self):
        """Config overrides may set a nested range object (Profile 1)."""
        profiles = load_profiles({"p01": {
            "range": {"mode": "custom_range", "start_byte": 0, "end_byte": -1},
        }})
        profile = profiles["p01"]
        # Unlisted fields keep the built-in value
        assert profile.preset == "CRC8/SAE-J1850-ZERO"
        assert profile.dataid_position == "prepend"
        crc_range = profile.to_range()
        assert crc_range.mode == "custom_range"
        assert crc_range.end_byte == -1
        assert crc_range.dataid_position == "prepend"

    def test_firmware_p01_equals_sae_j1850_zero(self):
        """Profile 1 equals CRC8/SAE-J1850-ZERO.

        Common AUTOSAR Profile 1 implementations start the register at
        0xFF ^ 0xFF = 0x00 and XOR the result with 0xFF once more, so the net
        algorithm is init 0x00 / no final XOR.
        """
        preset = BUILTIN_PROFILES["p01"].to_params()
        assert (preset.polynomial, preset.initial_value, preset.final_xor) == (0x1D, 0x00, 0x00)

    def test_unknown_field_raises(self):
        """A typo in the profile config fails loudly instead of being ignored."""
        with pytest.raises(ValueError, match="unknown field"):
            load_profiles({"p01": {"presett": "CRC8/SAE-J1850"}})
        with pytest.raises(ValueError, match="unknown range field"):
            load_profiles({"p05": {"range": {"start": 0}}})

    def test_profile1_counter_max_is_14(self):
        """AUTOSAR P01 counters are 4-bit with 0..14 valid (15 = invalid)."""
        assert BUILTIN_PROFILES["p01"].counter_max_valid == 14
        assert BUILTIN_PROFILES["p05"].counter_max_valid is None

    def test_counter_max_is_overridable(self):
        """Config can change the per-profile counter limit."""
        profiles = load_profiles({"p01": {"counter_max_valid": 7}})
        assert profiles["p01"].counter_max_valid == 7

    def test_new_profile_key_is_created(self):
        """A profile key that is not built in starts from an empty profile."""
        profiles = load_profiles({"p11": {"preset": "CRC8/AUTOSAR", "crc_width": 8}})
        assert profiles["p11"].preset == "CRC8/AUTOSAR"


# ---------------------------------------------------------------------------
# Multi-CRC messages (E2E_1)
# ---------------------------------------------------------------------------

def _e2e_frame(frame_id=0x1AE, frame_name="Msg_E2E_1", dlc=64):
    """Msg_E2E_1 with two E2E instances (bytes 0..12 and 13..31)."""
    signals = [
        {"name": "E2E_1_CRC_1", "start_bit": 0, "length": 16, "byte_order": "big_endian",
         "comment": "E2E Profile 5 CRC"},
        {"name": "E2E_1_Counter_1", "start_bit": 16, "length": 8, "byte_order": "big_endian",
         "comment": "E2E Profile 5 Counter"},
        {"name": "E2E_1_CRC_2", "start_bit": 104, "length": 16, "byte_order": "big_endian",
         "comment": "E2E Profile 5 CRC"},
        {"name": "E2E_1_Counter_2", "start_bit": 120, "length": 8, "byte_order": "big_endian",
         "comment": "E2E Profile 5 Counter"},
        {"name": "E2E_1_DeploySt", "start_bit": 128, "length": 2, "byte_order": "big_endian"},
    ]
    return [{"frame_id": frame_id, "frame_name": frame_name, "dlc": dlc, "signals": signals}]


class TestMultiCrcMessage:
    """One message carrying two E2E instances must yield two protection groups."""

    def test_indexed_crc_signals_are_detected(self):
        """``_CRC_<n>`` suffix is a checksum signal, like ``_Counter_<n>``."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("E2E_1_CRC_1")
        assert resolver.is_checksum_signal("E2E_1_CRC_2")
        assert resolver.is_rolling_counter_signal("E2E_1_Counter_1")

    def test_indexed_suffix_keeps_instances_apart(self):
        """Suffix extraction keeps the E2E instance index."""
        assert SignalResolver.extract_suffix("E2E_1_CRC_1") == "E2E_1_1"
        assert SignalResolver.extract_suffix("E2E_1_Counter_1") == "E2E_1_1"
        assert SignalResolver.extract_suffix("E2E_1_CRC_2") == "E2E_1_2"
        # Unchanged for the underscore-less form (APA_CRC1)
        assert SignalResolver.extract_suffix("APA_CRC1") == "APA_1"

    def test_two_groups_with_paired_counters(self):
        """Each CRC pairs with its own counter; counters are not merged."""
        pm = SignalResolver().build_protection_map(_e2e_frame())
        groups = sorted(pm.messages[0x1AE], key=lambda g: g.pair_suffix)
        assert [g.pair_suffix for g in groups] == ["E2E_1_1", "E2E_1_2"]
        assert groups[0].checksum_signal.name == "E2E_1_CRC_1"
        assert groups[0].rolling_counter_signal.name == "E2E_1_Counter_1"
        assert groups[1].checksum_signal.name == "E2E_1_CRC_2"
        assert groups[1].rolling_counter_signal.name == "E2E_1_Counter_2"


# ---------------------------------------------------------------------------
# Radar (SGU/FR/FLR/RLR/RRR) signal naming
# ---------------------------------------------------------------------------

def _radar_frame(frame_id=0x202, frame_name="FR_Obj_01", dlc=32):
    """A radar object frame: checksum + block counter + alive counter."""
    signals = [
        {"name": "SGU1_Msg_CheckSum_Can03", "start_bit": 0, "length": 8,
         "byte_order": "big_endian"},
        {"name": "SGU1_BlockCounter_Can03", "start_bit": 8, "length": 4,
         "byte_order": "big_endian"},
        {"name": "SGU1_Msg_AliveCounter_Can03", "start_bit": 12, "length": 4,
         "byte_order": "big_endian"},
        {"name": "SGU1_Object_ID_Can03", "start_bit": 16, "length": 8,
         "byte_order": "big_endian"},
    ]
    return [{"frame_id": frame_id, "frame_name": frame_name, "dlc": dlc,
             "signals": signals}]


class TestRadarSignals:
    """ADAS radar frames: `_Msg_CheckSum_CanNN` / `_Msg_AliveCounter_CanNN`."""

    def test_bus_suffix_is_stripped(self):
        """The radar bus marker ("_Can03") is not part of the signal identity."""
        assert SignalResolver.strip_bus_suffix("SGU1_Msg_CheckSum_Can03") == (
            "SGU1_Msg_CheckSum")
        assert SignalResolver.strip_bus_suffix("FR_Msg_AliveCounter") == (
            "FR_Msg_AliveCounter")

    def test_checksum_and_counter_are_detected(self):
        """Both the checksum and the alive counter are recognised."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("SGU1_Msg_CheckSum_Can03")
        assert resolver.is_checksum_signal("FR_Msg_CheckSum")
        assert resolver.is_rolling_counter_signal("SGU1_Msg_AliveCounter_Can03")
        assert resolver.is_rolling_counter_signal("FLR_Msg_AliveCounter0")

    def test_block_counter_is_not_a_rolling_counter(self):
        """The block counter counts data blocks, not frames — it is not the RC."""
        resolver = SignalResolver()
        assert not resolver.is_rolling_counter_signal("SGU1_BlockCounter_Can03")
        assert not resolver.is_rolling_counter_signal("FR_BlockCounter")
        # The alive counter in the same frame still is one
        assert resolver.is_rolling_counter_signal("SGU1_Msg_AliveCounter_Can03")

    def test_radar_pair_forms_one_group(self):
        """Checksum and alive counter pair up under the same suffix."""
        pm = SignalResolver().build_protection_map(_radar_frame())
        groups = pm.messages[0x202]
        assert len(groups) == 1
        assert groups[0].checksum_signal.name == "SGU1_Msg_CheckSum_Can03"
        assert groups[0].rolling_counter_signal.name == "SGU1_Msg_AliveCounter_Can03"
        assert groups[0].pair_suffix == "SGU1_Msg"


# ---------------------------------------------------------------------------
# apply_profiles / apply_range_overrides / apply_skip
# ---------------------------------------------------------------------------

def _prot(frame_id, frame_name, checksum, length=16,  # pylint: disable=too-many-arguments,too-many-positional-arguments
          start_bit=0, profile=""):
    """Build a minimal protection group."""
    prot = MessageProtection(frame_id=frame_id, frame_name=frame_name, dlc=64)
    prot.pair_suffix = frame_name
    prot.checksum_signal = SignalInfo(name=checksum, start_bit=start_bit, length=length)
    prot.crc_profile = profile
    return prot


MIXED_PROFILES = load_profiles({"p01": {
    "range": {"mode": "custom_range", "start_byte": 0, "end_byte": -1},
}})


class TestApplyProfiles:
    """Profile 5 / Profile 1 mix on one bus."""

    def test_select_by_width(self):
        """2-byte CRC → Profile 5 (append + swap), 1-byte → Profile 1 (prepend)."""
        pm = DBCProtectionMap()
        p16 = _prot(0x193, "ADC_1", "ADC_1_CRC", length=16)
        p8 = _prot(0x3BD, "CCU_ZCUL_HOD_1", "HOD_1_CRC", length=8)
        pm.messages = {0x193: [p16], 0x3BD: [p8]}
        assert pm.apply_profiles(MIXED_PROFILES, select_by_width=True) == 2
        assert p16.crc_params.name == "CRC16/CCITT (E2E Profile 5)"
        assert p16.crc_range.dataid_position == "append"
        assert p16.crc_range.crc_byte_swap is True
        assert p8.crc_params.name == "CRC8/SAE-J1850-ZERO"
        assert p8.crc_range.dataid_position == "prepend"
        assert p8.crc_range.crc_byte_swap is False
        assert p8.e2e_profile == "Profile 1"

    def test_profile_sets_counter_limit(self):
        """apply_profiles carries the profile's counter limit onto the group."""
        pm = DBCProtectionMap()
        p01 = _prot(0x396, "CCU_PADS_1", "UINM_PADS_1_CRC", length=8)
        p01.rolling_counter_signal = SignalInfo(
            name="UINM_PADS_1_Counter", start_bit=8, length=4)
        p05 = _prot(0x193, "ADC_1", "ADC_1_CRC", length=16)
        pm.messages = {0x396: [p01], 0x193: [p05]}
        pm.apply_profiles(MIXED_PROFILES, select_by_width=True)
        assert p01.rc_max_valid == 14
        assert p05.rc_max_valid is None    # 8-bit counter keeps 2^n - 1

    def test_explicit_hint_wins_over_width(self):
        """A DataID Remark profile hint beats the width rule."""
        pm = DBCProtectionMap()
        prot = _prot(0x3BD, "CCU_ZCUL_HOD_1", "HOD_1_CRC", length=8, profile="Profile 5")
        pm.messages = {0x3BD: [prot]}
        pm.apply_profiles(MIXED_PROFILES, select_by_width=True)
        assert prot.crc_params.name == "CRC16/CCITT (E2E Profile 5)"

    def test_groups_without_checksum_are_skipped(self):
        """RC-only groups keep the global settings."""
        pm = DBCProtectionMap()
        prot = MessageProtection(frame_id=0x500, frame_name="ONLY_RC", dlc=8)
        prot.rolling_counter_signal = SignalInfo(name="ONLY_RC_Counter", start_bit=0, length=4)
        pm.messages = {0x500: [prot]}
        assert pm.apply_profiles(MIXED_PROFILES, select_by_width=True) == 0
        assert prot.crc_params is None


class TestRangeOverrides:
    """Second E2E segment of Msg_E2E_1 (bytes 13..31) needs a per-group range."""

    def _pm(self):
        pm = DBCProtectionMap()
        p1 = _prot(0x1AE, "Msg_E2E_1", "E2E_1_CRC_1", start_bit=0)
        p2 = _prot(0x1AE, "Msg_E2E_1", "E2E_1_CRC_2", start_bit=104)
        pm.messages = {0x1AE: [p1, p2]}
        return pm, p1, p2

    def test_signal_name_key_hits_one_group(self):
        """A signal-name key only overrides that E2E instance."""
        pm, p1, p2 = self._pm()
        pm.apply_profiles(MIXED_PROFILES, select_by_width=True)
        applied = pm.apply_range_overrides({
            "E2E_1_CRC_2": {"mode": "custom_range", "start_byte": 13, "end_byte": 32},
        })
        assert applied == 1
        assert p2.crc_range.start_byte == 13
        assert p2.crc_range.end_byte == 32
        # DataID layout is inherited from the profile
        assert p2.crc_range.dataid_position == "append"
        assert p1.crc_range.start_byte == 0

    def test_frame_id_key_hits_all_groups(self):
        """A frame-id key applies to every group of the frame."""
        pm, p1, p2 = self._pm()
        assert pm.apply_range_overrides({"0x1AE": {"start_byte": 2}}) == 2
        assert (p1.crc_range.start_byte, p2.crc_range.start_byte) == (2, 2)


class TestApplySkip:
    """Signals that look protected but are not (CCU_TimeSync SYNC_FC_CRC)."""

    def test_skip_by_signal_name(self):
        """Only the named group is removed."""
        pm = DBCProtectionMap()
        pm.messages = {
            0x400: [_prot(0x400, "CCU_TimeSync", "SYNC_FC_CRC", length=8)],
            0x193: [_prot(0x193, "ADC_1", "ADC_1_CRC")],
        }
        assert pm.apply_skip(["SYNC_FC_CRC"]) == 1
        assert 0x400 not in pm.messages
        assert 0x193 in pm.messages

    def test_skip_by_frame_id_and_name(self):
        """Frame ids (hex or decimal) and frame names are accepted."""
        pm = DBCProtectionMap()
        pm.messages = {
            0x400: [_prot(0x400, "CCU_TimeSync", "SYNC_FC_CRC", length=8)],
            0x193: [_prot(0x193, "ADC_1", "ADC_1_CRC")],
        }
        assert pm.apply_skip(["0x400"]) == 1
        assert pm.apply_skip(["ADC_1"]) == 1
        assert not pm.messages


# ---------------------------------------------------------------------------
# DataID: multi-CRC rows
# ---------------------------------------------------------------------------

class TestDataIDMultiCrcRows:
    """A DataID row may name a CRC signal (Remark) instead of the message."""

    def test_normalize_signal_key(self):
        """Underscores and case do not matter when matching names."""
        assert normalize_signal_key("E2E_1_CRC_2") == "e2e1crc2"
        assert normalize_signal_key("E2E_1_CRC2") == "e2e1crc2"

    def test_entry_names_adds_remark_crc_signal(self):
        """The CRC signal from the Remark column is registered as an extra key."""
        assert _entry_names("E2E_1", "E2E_1_CRC2") == ["E2E_1", "E2E_1_CRC2"]
        assert _entry_names("E2E_1", "Profile Variant 1A") == ["E2E_1"]
        assert _entry_names("E2E_1", "E2E_1") == ["E2E_1"]

    def test_normalized_lookup(self):
        """Remark "E2E_1_CRC2" is found from the DBC signal "E2E_1_CRC_2"."""
        dm = DataIDMap()
        dm.add(0x1AE, "E2E_1_CRC2", 0x0414)
        assert dm.get_normalized(0x1AE, "E2E_1_CRC_2") == 0x0414
        assert dm.get_normalized(0x1AE, "E2E_1_CRC1") is None

    def test_apply_dataid_map_assigns_per_instance_dataid(self):
        """Each E2E instance of one message gets its own DataID."""
        pm = DBCProtectionMap()
        p1 = _prot(0x1AE, "Msg_E2E_1", "E2E_1_CRC_1")
        p2 = _prot(0x1AE, "Msg_E2E_1", "E2E_1_CRC_2")
        pm.messages = {0x1AE: [p1, p2]}
        dm = DataIDMap()
        dm.add(0x1AE, "E2E_1", 0x0404)          # message-name row (last-wins bait)
        dm.add(0x1AE, "E2E_1_CRC2", 0x0414)     # Remark row for instance 2
        pm.apply_dataid_map(dm)
        assert p2.dataid == 0x0414
        assert p1.dataid == 0x0404

    def test_add_row_reads_remark_and_registers_both_names(self):
        """Rows are registered under the message name and the Remark CRC name."""
        dm = DataIDMap()
        mapping = BUILTIN_MAPPINGS["single_16bit"]
        assert _add_dataid_row(
            [None, "E2E", "E2E_1", "0x1AE", "0x0414", "E2E_1_CRC2", None], mapping, dm)
        assert dm.get(0x1AE, "E2E_1") == 0x0414
        assert dm.get(0x1AE, "E2E_1_CRC2") == 0x0414

    def test_cell_whitespace_is_stripped(self):
        """Trailing spaces in a name cell must not lose the DataID.

        Some workbooks store names with a trailing space; without stripping,
        those messages silently got no DataID and every CRC verdict failed.
        """
        dm = DataIDMap()
        mapping = BUILTIN_MAPPINGS["single_16bit"]
        assert _add_dataid_row([None, "CCU", "ZCUR_8 ", "0x156", "0x011D", None, None],
                               mapping, dm)
        assert dm.get(0x156, "ZCUR_8") == 0x011D
        # CCU_ZCUR_8_CRC pairs under suffix "ZCUR_8" → found by strategy 3
        assert dm.get(0x156, "ZCUR_8") is not None
        assert dm.get(0x156, "ZCUR_8 ") is None


class TestProfileCommentClassification:
    """DBC comments can name E2E profiles instead of CRC polynomials."""

    def test_profile5_comment_is_not_crc8(self):
        """'E2E Profile 5 CRC' must not fall through to the generic CRC-8 class."""
        assert classify_crc_algo("E2E Profile 5 CRC") == "p05"
        assert build_crc_params_from_comment("E2E Profile 5 CRC") is None

    def test_auto_classify_keeps_profile_groups(self):
        """apply_comment_classification leaves profile-driven groups alone."""
        pm = DBCProtectionMap()
        prot = _prot(0x193, "ADC_1", "ADC_1_CRC")
        prot.checksum_comment = "E2E Profile 5 CRC"
        pm.messages = {0x193: [prot]}
        pm.apply_profiles(MIXED_PROFILES, select_by_width=True)
        pm.apply_comment_classification(None)
        assert prot.crc_params.name == "CRC16/CCITT (E2E Profile 5)"

    def test_profile1a_hint_still_wins(self):
        """The Profile 1A class is unchanged."""
        assert classify_crc_algo("E2E Profile 1A CRC") == "p01"
        assert build_crc_params_from_comment("E2E Profile 1A CRC").name == \
            "CRC8/SAE-J1850-ZERO"


class TestProfileRangeInterplay:
    """Profile ranges must survive the exclude_crc → segment upgrade."""

    @staticmethod
    def _p01_with_range() -> E2EProfile:
        return E2EProfile(
            key="p01", name="Profile 1", preset="CRC8/SAE-J1850-ZERO",
            dataid_position="prepend",
            range_mode="custom_range", range_start=0, range_end=-1)

    def test_profile1_range_is_not_upgraded_to_segment(self):
        """Profile 1 on CAN FD keeps its explicit range (no segment mode)."""
        crc_range = self._p01_with_range().to_range()
        assert crc_range.mode == "custom_range"
        assert crc_range.dataid_position == "prepend"

    def test_profile_without_range_inherits_config(self):
        """A profile without a range leaves the global config range in place."""
        profile = E2EProfile(key="p01", name="Profile 1", preset="CRC8/SAE-J1850-ZERO")
        assert profile.to_range() is None
