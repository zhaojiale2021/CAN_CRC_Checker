"""Tests for checksum auto-classification from DBC signal comments."""

from crc_checker.crc.classify import (
    classify_crc_algo, parse_crc_seed, build_crc_params_from_comment,
    parse_dataid_from_comment, parse_sum_byte_range,
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
        # odd spacing from a real DBC
        assert classify_crc_algo(
            "((Byte0+Byte1+ Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF"
        ) == "sum_xor"

    def test_plain_sum_comments(self):
        """A bare "and 0xFF" (no XOR) classifies as a plain additive sum;
        only "XOR (0xFF)" comments become sum_xor."""
        assert classify_crc_algo(
            "Checksum = (byte0+byte1+...+byte6）and 0xFF"
        ) == "sum"
        assert classify_crc_algo(
            "Checksum = (byte1+byte2+...+byte 7）and 0xFF"
        ) == "sum"

    def test_sum_with_final_xor(self):
        """A sum with a final "XOR (0xFF)" stays sum_xor."""
        assert classify_crc_algo(
            "Checksum = (byte0 + byte 1 + ...+ byte 6) XOR (0xFF)"
        ) == "sum_xor"

    def test_xor_seed_comments(self):
        """Byte-wise XOR with 0xNN constants classifies as xor_seed."""
        assert classify_crc_algo(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1 XOR Byte2 XOR Byte3 XOR Byte4 "
            "XOR Byte5 XOR Byte6"
        ) == "xor_seed"

    def test_profile1a_comment(self):
        """A Profile 1A comment classifies as p01 (not crc8)."""
        assert classify_crc_algo(
            "CRC checksum. DataID and the following 7 bytes are included in "
            "CRC checksum calculation. Refer to E2E Spec.（Profile：1A；DataID：0x00EB）"
        ) == "p01"

    def test_external_algorithm_skips(self):
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
    """DataID extraction from Profile 1A comments."""

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
        """A sum_xor comment builds SUM8/XOR-FF params (final XOR 0xFF)."""
        params = build_crc_params_from_comment(
            "((Byte0+Byte1+Byte2) AND 0xFF) XOR 0xFF")
        assert params is not None
        assert params.checksum_type == "sum_xor"
        assert params.final_xor == 0xFF

    def test_plain_sum_params(self):
        """A plain-sum comment builds SUM8 params (no final XOR)."""
        params = build_crc_params_from_comment(
            "Checksum = (byte0+byte1+...+byte6）and 0xFF")
        assert params is not None
        assert params is get_preset("SUM8")
        assert params.checksum_type == "sum"
        assert params.final_xor == 0

    def test_profile1a_params(self):
        """Profile 1A -> CRC8/SAE-J1850-ZERO params."""
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


class TestParseSumByteRange:
    """Covered byte range of a sum checksum, as named by its DBC comment."""

    def test_first_segment(self):
        """'byte1+byte2+…+byte 7' -> (1, 7); the ellipsis is a full-width char."""
        assert parse_sum_byte_range(
            "Checksum = (byte1+byte2+…+byte 7）and 0xFF") == (1, 7)

    def test_later_segment(self):
        """Multi-segment frames name absolute positions (byte17..byte23)."""
        assert parse_sum_byte_range(
            "Checksum = (byte17+byte18+…+byte 23）and 0xFF") == (17, 23)

    def test_ascii_punctuation(self):
        """byte0..byte6 listed with plain ASCII punctuation."""
        assert parse_sum_byte_range(
            "((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF"
        ) == (0, 6)

    def test_no_byte_list(self):
        """A comment without a byte list yields None (caller keeps the default)."""
        assert parse_sum_byte_range("CRC8算法另附文件") is None
        assert parse_sum_byte_range("") is None
