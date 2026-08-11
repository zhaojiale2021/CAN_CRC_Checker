"""Smoke tests for CRC engine correctness against known vectors."""

import pytest
from crc_checker.crc.classify import build_crc_params_from_comment
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

    def test_b81vs_16bit_checksum_actual_alignment(self):
        """b81vs 16-bit Checksum<ID>: firmware compares only the crc_index byte.

        A 16-bit Motorola signal at byte1: frame CRC byte1=0x53, byte2 (high
        byte) is ignored by crc_calculatecrcxor — the verifier must compare
        expected against byte1, not the full 16-bit field.
        """
        # pylint: disable=import-outside-toplevel
        from crc_checker.protect.checksum import CRCVerifier
        from crc_checker.dbc.models import MessageProtection, SignalInfo
        from crc_checker.crc.models import CRCRange
        from crc_checker.trace.models import CanFrame

        # 8-byte frame; Checksum450 is a 16-bit Motorola signal starting at
        # byte1 (sb=8). Data bytes: byte0=0x11, byte1=0x23 (CRC), byte2-7 fill.
        data = bytes([0x11, 0x23, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77])
        # expected = (sum of bytes except byte1) ^ 0xFF
        exp = (sum(b for i, b in enumerate(data) if i != 1) & 0xFF) ^ 0xFF
        assert exp == 0x23  # frame CRC matches -> PASS

        verifier = CRCVerifier(get_preset("SUM8/XOR-FF"))
        prot = MessageProtection(
            frame_id=0x1C2, frame_name="RSDS_L_AD1", dlc=8, pair_suffix="RSDS_L_AD1",
            checksum_signal=SignalInfo(
                name="Checksum450", start_bit=8, length=16, byte_order="big_endian"),
            crc_params=get_preset("SUM8/XOR-FF"),
            crc_range=CRCRange(mode="exclude_crc"),
        )
        frame = CanFrame(timestamp=0.0, arbitration_id=0x1C2, dlc=8, data=data)
        verdict = verifier.verify(frame, prot)
        assert verdict is not None
        assert verdict.is_pass, (
            f"expected 0x{verdict.expected_value:02X}, "
            f"got 0x{verdict.actual_value:02X}")
        assert verdict.actual_value == 0x23  # aligned to the crc_index byte


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
