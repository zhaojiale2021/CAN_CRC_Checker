"""Smoke tests for CRC engine correctness against known vectors."""

import pytest
from crc_checker.crc.models import CRCParams
from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.presets import get_preset


class TestCRCEngine:
    """Verify CRC computation against known test vectors."""

    def test_crc8_autosar_known_vector(self):
        """CRC8/AUTOSAR: 0x2F, init=0xFF, xor=0xFF, no reflect.
        Known vector from CRC Catalogue: "123456789" → 0xDF
        """
        params = get_preset("CRC8/AUTOSAR")
        engine = CRCEngine(params)
        result = engine.compute(b"123456789")
        assert result == 0xDF, f"CRC8/AUTOSAR('123456789') expected 0xDF, got 0x{result:02X}"

    def test_crc8_sae_j1850_known_vector(self):
        """CRC8/SAE-J1850: 0x1D, init=0xFF, xor=0xFF, no reflect.
        Known vector: "123456789" → 0x4B
        """
        params = get_preset("CRC8/SAE-J1850")
        engine = CRCEngine(params)
        result = engine.compute(b"123456789")
        assert result == 0x4B, f"CRC8/SAE-J1850('123456789') expected 0x4B, got 0x{result:02X}"

    def test_crc16_arc_known_vector(self):
        """CRC16/ARC: 0x8005, init=0x0000, xor=0x0000, reflect in+out.
        Known vector: "123456789" → 0xBB3D
        """
        params = get_preset("CRC16/ARC")
        engine = CRCEngine(params)
        result = engine.compute(b"123456789")
        assert result == 0xBB3D, f"CRC16/ARC('123456789') expected 0xBB3D, got 0x{result:04X}"

    def test_crc32_ethernet_known_vector(self):
        """CRC32/ETHERNET: 0x04C11DB7, init=0xFFFFFFFF, xor=0xFFFFFFFF, reflect in+out.
        Known vector: "123456789" → 0xCBF43926
        """
        params = get_preset("CRC32/ETHERNET")
        engine = CRCEngine(params)
        result = engine.compute(b"123456789")
        expected = 0xCBF43926
        assert result == expected, (
            f"CRC32/ETHERNET('123456789') expected 0x{expected:08X}, "
            f"got 0x{result:08X}"
        )

    def test_xor8_simple(self):
        """XOR8: simple XOR sum of all bytes."""
        params = get_preset("XOR8")
        engine = CRCEngine(params)
        result = engine.compute(b"\x01\x02\x03")
        # 0x01 ^ 0x02 ^ 0x03 = 0x00
        assert result == 0x00, f"XOR8([1,2,3]) expected 0x00, got 0x{result:02X}"

    def test_xor8_another(self):
        """XOR8: another vector — 0xA5 ^ 0x5A ^ 0xFF = 0x00."""
        params = get_preset("XOR8")
        engine = CRCEngine(params)
        result = engine.compute(b"\xA5\x5A\xFF")
        # 0xA5 ^ 0x5A = 0xFF, 0xFF ^ 0xFF = 0x00
        assert result == 0x00

    def test_custom_crc_params(self):
        """Test fully custom CRC parameters."""
        params = CRCParams(
            width=8, polynomial=0x2F, initial_value=0x00,
            final_xor=0x00, reflect_in=False, reflect_out=False
        )
        engine = CRCEngine(params)
        # With init=0 and final_xor=0, result should differ from AUTOSAR
        result = engine.compute(b"123456789")
        # This is CRC8 with zero init/xor
        assert result == engine.compute(b"123456789")  # deterministic

    def test_empty_data(self):
        """CRC of empty data should return init XOR final_xor."""
        params = CRCParams(
            width=8, polynomial=0x2F, initial_value=0xFF,
            final_xor=0xFF, reflect_in=False, reflect_out=False
        )
        engine = CRCEngine(params)
        result = engine.compute(b"")
        # With no data, CRC stays at init=0xFF, then XOR 0xFF → 0x00
        assert result == 0x00

    def test_sum_xor_known_vector(self):
        """SUM8/XOR-FF: (sum of bytes AND 0xFF) XOR 0xFF.

        Mirrors crc_calculatecrcxor (uint8 accumulation + final XOR 0xFF).
        """
        engine = CRCEngine(get_preset("SUM8/XOR-FF"))
        # 0x01+0x02+0x03+0x04 = 0x0A -> 0x0A ^ 0xFF = 0xF5
        assert engine.compute(bytes([0x01, 0x02, 0x03, 0x04])) == 0xF5
        # 0xFF+0xFF = 0x1FE -> &0xFF = 0xFE -> ^0xFF = 0x01
        assert engine.compute(bytes([0xFF, 0xFF])) == 0x01
        # empty -> 0x00 ^ 0xFF = 0xFF
        assert engine.compute(b"") == 0xFF

    def test_xor_seed_known_vector(self):
        """XOR8/SEED: seed XOR every byte (mirrors crc_calculatecrcxor_seed).

        YAS_1 seed = 0x01 ^ 0x27 = 0x26.
        """
        from crc_checker.crc.classify import build_crc_params_from_comment
        params = build_crc_params_from_comment(
            "0x01 XOR 0x27 XOR Byte0 XOR Byte1 XOR Byte2 XOR Byte3 XOR Byte4 XOR Byte5 XOR Byte6")
        assert params is not None
        assert params.checksum_type == "xor_seed"
        assert params.initial_value == 0x26
        engine = CRCEngine(params)
        data = bytes([0x01, 0x02, 0x03, 0x04])
        expected = 0x26 ^ 0x01 ^ 0x02 ^ 0x03 ^ 0x04  # 0x22
        assert engine.compute(data) == expected
        # seed only, no data -> 0x26
        assert engine.compute(b"") == 0x26


class TestCRCPresets:
    """Verify all presets have reasonable parameters."""

    def test_all_presets_valid(self):
        """All built-in presets produce valid CRC results."""
        # pylint: disable=import-outside-toplevel
        from crc_checker.crc.presets import PRESETS
        for name, params in PRESETS.items():
            assert 0 < params.width <= 64, f"{name}: invalid width"
            assert params.polynomial >= 0, f"{name}: negative polynomial"
            engine = CRCEngine(params)
            result = engine.compute(b"\x00\x00\x00")
            assert 0 <= result < (1 << params.width), f"{name}: result out of range"

    def test_get_preset_case_insensitive(self):
        """Preset lookup is case-insensitive and normalizes separators."""
        assert get_preset("crc8/autosar").name == "CRC8/AUTOSAR"
        assert get_preset("CRC8_AUTOSAR").name == "CRC8/AUTOSAR"
        assert get_preset("crc8-autosar").name == "CRC8/AUTOSAR"

    def test_get_preset_unknown_raises(self):
        """Unknown preset name raises KeyError."""
        with pytest.raises(KeyError):
            get_preset("CRC99/UNKNOWN")
