"""Tests for fx12fl checksum auto-classification from DBC signal comments.

Mirrors Fx12flHooks.classify_crc_algo / parse_crc_seed in the mcu_app_j6
com_code_generator.
"""

from crc_checker.crc.classify import (
    classify_crc_algo, parse_crc_seed, build_crc_params_from_comment,
    parse_dataid_from_comment,
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

    def test_multiproject_comment_uses_eea401_branch(self):
        """Chery two-branch comment: the HH12_PT_26 project uses SUM8/XOR-FF,
        but EEA4.01 projects (fx12fl's architecture) use SAE J1850 CRC-8."""
        assert classify_crc_algo(
            "HH12_PT_26款项目:((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) "
            "AND 0xFF) XOR 0xFF\nEEA4.01其他项目:SAE J1850 CRC-8"
        ) == "crc8"

    def test_b81vs_sum_comments(self):
        """b81vs plain sum (no XOR 0xFF) also classifies as sum_xor."""
        assert classify_crc_algo(
            "Checksum = (byte0+byte1+...+byte6）and 0xFF"
        ) == "sum_xor"
        assert classify_crc_algo(
            "Checksum = (byte1+byte2+...+byte 7）and 0xFF"
        ) == "sum_xor"

    def test_xor_seed_comments(self):
        """Byte-wise XOR with 0xNN constants classifies as xor_seed."""
        assert classify_crc_algo(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1 XOR Byte2 XOR Byte3 XOR Byte4 "
            "XOR Byte5 XOR Byte6"
        ) == "xor_seed"

    def test_b81vs_profile1a(self):
        """b81vs Profile 1A comment classifies as p01 (not crc8)."""
        assert classify_crc_algo(
            "CRC checksum. DataID and the following 7 bytes are included in "
            "CRC checksum calculation. Refer to E2E Spec.（Profile：1A；DataID：0x00EB）"
        ) == "p01"

    def test_b81vs_skip(self):
        """External-spec comments classify as skip."""
        assert classify_crc_algo("CRC8 算法另附文件") == "skip"
        assert classify_crc_algo("校验算法另附") == "skip"

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


class TestParseDataId:
    """b81vs DataID extraction from Profile 1A comments."""

    def test_fullwidth_colon(self):
        """'DataID：0x00EB' with full-width colon -> 0xEB."""
        assert parse_dataid_from_comment(
            "CRC checksum. ...（Profile：1A；DataID：0x00EB）"
        ) == 0xEB

    def test_ascii_colon(self):
        """'DataID: 0x1A2B' with ascii colon -> 0x1A2B."""
        assert parse_dataid_from_comment(
            "Profile 1A DataID: 0x1A2B"
        ) == 0x1A2B

    def test_no_dataid(self):
        """No DataID literal -> None."""
        assert parse_dataid_from_comment("Checksum = (byte0+...) and 0xFF") is None
        assert parse_dataid_from_comment("") is None


class TestBuildParams:
    """build_crc_params_from_comment -> CRCParams."""

    def test_sum_xor_params(self):
        """fx12fl sum_xor comment builds SUM8/XOR-FF params (final XOR 0xFF)."""
        params = build_crc_params_from_comment(
            "((Byte0+Byte1+Byte2) AND 0xFF) XOR 0xFF")
        assert params is not None
        assert params.checksum_type == "sum_xor"
        assert params.final_xor == 0xFF

    def test_b81vs_sum_params(self):
        """b81vs plain-sum comment builds SUM8/XOR-FF params (firmware XORs 0xFF)."""
        params = build_crc_params_from_comment(
            "Checksum = (byte0+byte1+...+byte6）and 0xFF")
        assert params is not None
        assert params.checksum_type == "sum_xor"
        assert params.final_xor == 0xFF
        assert params is get_preset("SUM8/XOR-FF")

    def test_b81vs_profile1a_params(self):
        """b81vs Profile 1A -> CRC8/SAE-J1850-ZERO params."""
        params = build_crc_params_from_comment(
            "CRC checksum. ...（Profile：1A；DataID：0x00EB）")
        assert params is get_preset("CRC8/SAE-J1850-ZERO")

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

    def test_skip_returns_none(self):
        """skip comments return None (caller keeps the default algorithm)."""
        assert build_crc_params_from_comment("CRC8 算法另附文件") is None
