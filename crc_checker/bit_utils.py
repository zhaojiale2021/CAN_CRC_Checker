"""Bit extraction utilities for CAN signal values.

Handles both Intel (@1, little-endian) and Motorola (@0, big-endian) layouts.

Key insight for Motorola signals with canmatrix:
  canmatrix's get_startbit() stores the MSB position in an inverted bit-within-byte
  numbering (bit 0 = physical bit 7, bit 7 = physical bit 0).

  To extract correctly for Motorola, we first convert the canmatrix start_bit back
  to the DBC raw MSB position (which matches the physical byte bit numbering 7→0),
  then read bits downward (MSB to LSB).
"""


def _canmatrix_to_physical_msb(can_start_bit: int) -> int:
    """Convert canmatrix's internal start_bit to the physical MSB position.

    canmatrix inverts the bit-within-byte: physical_bit = 7 - can_bit.
    Example: can_start_bit=316 (byte 39, can_bit 4) → physical MSB=315 (byte 39, bit 3).
    """
    byte_idx = can_start_bit // 8
    can_bit = can_start_bit % 8
    physical_bit = 7 - can_bit
    return byte_idx * 8 + physical_bit


def extract_signal_bits(data: bytes, start_bit: int, length: int,
                        byte_order: str = "little_endian") -> int:
    """Extract a signal value from CAN payload bytes.

    Args:
        data: Raw CAN payload bytes.
        start_bit: Bit position from canmatrix's get_startbit().
        length: Number of bits in the signal.
        byte_order: "little_endian" (Intel/@1) or "big_endian" (Motorola/@0).

    Returns:
        Extracted integer value.
    """
    if byte_order == "big_endian":
        return _extract_motorola(data, start_bit, length)
    return _extract_intel(data, start_bit, length)


def zero_signal_bits(data: bytearray, start_bit: int, length: int,
                     byte_order: str = "little_endian"):
    """Zero out a signal's bits in a CAN payload bytearray.

    Args:
        data: Mutable CAN payload bytearray.
        start_bit: Bit position from canmatrix's get_startbit().
        length: Number of bits to zero.
        byte_order: "little_endian" or "big_endian".
    """
    if byte_order == "big_endian":
        _zero_motorola(data, start_bit, length)
    else:
        _zero_intel(data, start_bit, length)


# ---------------------------------------------------------------------------
# Intel (@1) — start_bit is LSB, bits increment
# ---------------------------------------------------------------------------

def _extract_intel(data: bytes, start_bit: int, length: int) -> int:
    value = 0
    for i in range(length):
        bit_pos = start_bit + i
        byte_idx = bit_pos // 8
        bit_idx = bit_pos % 8
        if byte_idx < len(data):
            if data[byte_idx] & (1 << bit_idx):
                value |= 1 << i
    return value


def _zero_intel(data: bytearray, start_bit: int, length: int):
    for i in range(length):
        bit_pos = start_bit + i
        byte_idx = bit_pos // 8
        bit_idx = bit_pos % 8
        if byte_idx < len(data):
            data[byte_idx] &= ~(1 << bit_idx)


# ---------------------------------------------------------------------------
# Motorola (@0) — start_bit is MSB, bits decrement
# ---------------------------------------------------------------------------

def _extract_motorola(data: bytes, can_start_bit: int, length: int) -> int:
    """Motorola (big-endian) extraction.

    In Motorola layout, the MSB is at the specified physical bit position.
    Bits go from MSB to LSB downward, crossing byte boundaries at bit 7→0.

    For multi-byte signals, bytes are in big-endian order (most significant
    byte at the lowest address/index).

    Example: start_bit=0, length=16 on data [0x08, 0xA4] → 0x08A4.
    """
    # Convert canmatrix's inverted start_bit to physical MSB position
    physical_msb_byte = can_start_bit // 8
    physical_msb_bit = 7 - (can_start_bit % 8)  # canmatrix inverts bit numbering

    value = 0
    remaining = length
    byte_idx = physical_msb_byte

    # First byte: bits from physical_msb_bit down to 0
    if byte_idx < len(data):
        bits_in_first_byte = physical_msb_bit + 1
        mask = (1 << bits_in_first_byte) - 1
        contrib = data[byte_idx] & mask
        if remaining <= bits_in_first_byte:
            # All bits fit in the first byte
            shift = bits_in_first_byte - remaining
            return contrib >> shift
        value = contrib
        remaining -= bits_in_first_byte
        byte_idx += 1

    # Middle bytes: all 8 bits each
    while remaining >= 8 and byte_idx < len(data):
        value = (value << 8) | data[byte_idx]
        remaining -= 8
        byte_idx += 1

    # Last byte: partial (remaining < 8)
    if remaining > 0 and byte_idx < len(data):
        shift = 8 - remaining
        contrib = data[byte_idx] >> shift
        value = (value << remaining) | (contrib & ((1 << remaining) - 1))

    return value


def _zero_motorola(data: bytearray, can_start_bit: int, length: int):
    """Zero bits in Motorola layout.

    Bits run from the MSB downward; after bit 0 of the first byte the
    sequence continues at bit 7 of the next byte (same traversal as
    ``_extract_motorola``).
    """
    physical_msb_byte = can_start_bit // 8
    physical_msb_bit = 7 - (can_start_bit % 8)
    remaining = length
    byte_idx = physical_msb_byte

    # First byte: bits physical_msb_bit..0
    if byte_idx < len(data):
        bits_in_first_byte = physical_msb_bit + 1
        take = min(bits_in_first_byte, remaining)
        shift = bits_in_first_byte - take
        data[byte_idx] &= ~(((1 << take) - 1) << shift)
        remaining -= take
        byte_idx += 1

    # Middle bytes: all 8 bits each
    while remaining >= 8 and byte_idx < len(data):
        data[byte_idx] = 0
        remaining -= 8
        byte_idx += 1

    # Last byte: partial (remaining < 8), top `remaining` bits
    if remaining > 0 and byte_idx < len(data):
        mask = ((1 << remaining) - 1) << (8 - remaining)
        data[byte_idx] &= ~mask
