"""Tests for fx12fl checksum auto-classification from DBC signal comments.

Mirrors Fx12flHooks.classify_crc_algo / parse_crc_seed in the mcu_app_j6
com_code_generator.
"""

from crc_checker.crc.classify import (
    classify_crc_algo, parse_crc_seed, build_crc_params_from_comment,
)
from crc_checker.crc.presets import get_preset


class TestClassifyCrcAlgo:
    """Comment -> algorithm class mapping."""

    def test_crc8_comments(self):
        """J1850 CRC-8 and plain 'CRC' comments classify as crc8."""
        assert classify_crc_algo("CRC (SAE J1850 CRC-8)") == "crc8"
        assert classify_crc_algo("Checksum(SAE J1850 CRC-8)") == "crc8"
        assert classify_crc_algo("CRC") == "crc8"
        assert classify_crc_algo("checksum") == "crc8"

    def test_sum_xor_comments(self):
        """Sum-of-bytes AND 0xFF XOR 0xFF comments classify as sum_xor."""
        assert classify_crc_algo(
            "((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF"
        ) == "sum_xor"
        # odd spacing from the OEM DBC
        assert classify_crc_algo(
            "((Byte0+Byte1+ Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF"
        ) == "sum_xor"

    def test_xor_seed_comments(self):
        """Byte-wise XOR with 0xNN constants classifies as xor_seed."""
        assert classify_crc_algo(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1 XOR Byte2 XOR Byte3 XOR Byte4 "
            "XOR Byte5 XOR Byte6"
        ) == "xor_seed"

    def test_unclassified(self):
        """Unrelated comments (or empty) yield no classification."""
        assert classify_crc_algo("") == ""
        assert classify_crc_algo("wheel speed") == ""
        assert classify_crc_algo("target deceleration value") == ""


class TestParseCrcSeed:
    """0xNN literal XOR -> seed."""

    def test_yas1(self):
        """YAS_1 constants 0x01 ^ 0x27 -> seed 0x26."""
        assert parse_crc_seed(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1"
        ) == 0x26

    def test_yas2(self):
        """YAS_2 constants 0x01 ^ 0x28 -> seed 0x29."""
        assert parse_crc_seed(
            "0x01 XOR 0x28 XOR Byte0 XOR Byte1"
        ) == 0x29

    def test_no_constants(self):
        """No 0xNN literals -> seed 0."""
        assert parse_crc_seed("CRC") == 0
        assert parse_crc_seed("") == 0


class TestBuildParams:
    """build_crc_params_from_comment -> CRCParams."""

    def test_sum_xor_params(self):
        """sum_xor comment builds a SUM8/XOR-FF-style param set."""
        params = build_crc_params_from_comment(
            "((Byte0+Byte1+Byte2) AND 0xFF) XOR 0xFF")
        assert params is not None
        assert params.checksum_type == "sum_xor"
        assert params.final_xor == 0xFF

    def test_xor_seed_params(self):
        """xor_seed comment builds XOR8/SEED params with parsed seed."""
        params = build_crc_params_from_comment(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1")
        assert params.checksum_type == "xor_seed"
        assert params.initial_value == 0x26

    def test_crc8_keeps_default(self):
        """crc8 comment returns the caller-provided default params."""
        default = get_preset("CRC8/SAE-J1850")
        params = build_crc_params_from_comment(
            "Checksum(SAE J1850 CRC-8)", default)
        assert params is default

    def test_crc8_defaults_to_j1850(self):
        """crc8 comment without a default falls back to CRC8/SAE-J1850."""
        params = build_crc_params_from_comment("CRC")
        assert params is get_preset("CRC8/SAE-J1850")

    def test_unclassified_returns_none(self):
        """Unclassified comments return None so the caller keeps its default."""
        assert build_crc_params_from_comment("some comment") is None
        assert build_crc_params_from_comment("") is None
