"""Tests for bit extraction/zeroing utilities and HTML highlight positions.

Covers the Motorola (big-endian) multi-byte traversal shared by
``_extract_motorola``, ``zero_signal_bits`` and the report highlight
position helper — the bug that left Profile 5 (16-bit CRC) with only
one of its two bytes highlighted.
"""

from crc_checker.bit_utils import (
    _canmatrix_to_physical_msb,
    extract_signal_bits,
    zero_signal_bits,
)
from crc_checker.report.html import _bit_to_byte_pos


class TestBitToBytePos:
    """Signal bit position -> (byte, bit) mapping used for highlighting."""

    def test_intel_16bit_spans_two_bytes(self):
        """little_endian start_bit=48 length=16 maps to bytes 6 and 7."""
        assert _bit_to_byte_pos(48, 0, "little_endian") == (6, 0)
        assert _bit_to_byte_pos(48, 15, "little_endian") == (7, 7)

    def test_motorola_16bit_profile5_spans_two_bytes(self):
        """Profile 5 CRC (canmatrix start_bit=0) maps 16 bits onto bytes 0-1."""
        assert _canmatrix_to_physical_msb(0) == 7
        assert _bit_to_byte_pos(0, 0, "big_endian") == (0, 7)
        assert _bit_to_byte_pos(0, 7, "big_endian") == (0, 0)
        assert _bit_to_byte_pos(0, 8, "big_endian") == (1, 7)
        assert _bit_to_byte_pos(0, 15, "big_endian") == (1, 0)
        # All 16 bits must land on exactly two bytes
        covered = {_bit_to_byte_pos(0, i, "big_endian")[0] for i in range(16)}
        assert covered == {0, 1}

    def test_motorola_unaligned_start_bit_crosses_three_bytes(self):
        """Unaligned canmatrix start_bit=316 maps 16 bits onto bytes 39-41."""
        assert _canmatrix_to_physical_msb(316) == 315
        assert _bit_to_byte_pos(316, 0, "big_endian") == (39, 3)
        assert _bit_to_byte_pos(316, 3, "big_endian") == (39, 0)
        assert _bit_to_byte_pos(316, 4, "big_endian") == (40, 7)
        assert _bit_to_byte_pos(316, 11, "big_endian") == (40, 0)
        assert _bit_to_byte_pos(316, 12, "big_endian") == (41, 7)
        assert _bit_to_byte_pos(316, 15, "big_endian") == (41, 4)


class TestZeroMotorola:
    """zero_signal_bits must clear every bit covered by a Motorola signal."""

    def test_profile5_16bit_clears_both_bytes(self):
        """Zeroing a 16-bit Motorola signal clears bytes 0 and 1 only."""
        data = bytearray([0x12, 0x34] + [0xFF] * 6)
        zero_signal_bits(data, 0, 16, "big_endian")
        assert data[0] == 0x00
        assert data[1] == 0x00
        assert data[2:] == bytearray([0xFF] * 6)

    def test_unaligned_16bit_clears_partial_bytes(self):
        """Unaligned start_bit=316 zeroes 4+8+4 bits across bytes 39-41."""
        data = bytearray([0xFF] * 64)
        zero_signal_bits(data, 316, 16, "big_endian")
        assert data[39] == 0xF0          # high 4 bits preserved
        assert data[40] == 0x00
        assert data[41] == 0x0F          # low 4 bits preserved

    def test_extract_zero_roundtrip(self):
        """Extracting after zeroing yields 0; other bytes untouched."""
        data = bytearray([0x12, 0x34, 0x56] + [0x00] * 5)
        zero_signal_bits(data, 0, 16, "big_endian")
        assert extract_signal_bits(bytes(data), 0, 16, "big_endian") == 0
        assert data[2] == 0x56
