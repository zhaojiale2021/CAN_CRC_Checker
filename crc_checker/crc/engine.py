"""Parameterized CRC computation engine using lookup tables.

Supports CRC8/16/32 with both reflected (right-shifting) and non-reflected
(left-shifting) algorithms, plus XOR checksums.
"""

from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.trace.models import CanFrame


class CRCEngine:
    """Parameterized CRC calculator supporting CRC8/16/32 with lookup tables."""

    def __init__(self, params: CRCParams):
        self.params = params
        self._mask = (1 << params.width) - 1
        self._table = self._build_table()

    def _reflect_bits(self, value: int, bit_width: int) -> int:
        """Reverse bits for given bit width."""
        result = 0
        for i in range(bit_width):
            if value & (1 << i):
                result |= 1 << (bit_width - 1 - i)
        return result

    def _build_table(self) -> list[int]:
        """Build 256-entry lookup table.

        For reflect_in=False: uses left-shifting algorithm.
        For reflect_in=True: uses right-shifting algorithm with reflected polynomial.
        """
        table = []
        poly = self.params.polynomial
        width = self.params.width
        mask = self._mask

        if self.params.reflect_in:
            # Reflected (right-shifting) algorithm
            # Use reflected polynomial
            reflected_poly = self._reflect_bits(poly, width)
            for i in range(256):
                crc = i
                for _ in range(8):
                    if crc & 1:
                        crc = (crc >> 1) ^ reflected_poly
                    else:
                        crc >>= 1
                table.append(crc & mask)
        else:
            # Non-reflected (left-shifting) algorithm
            for i in range(256):
                value = i << (width - 8)
                for _ in range(8):
                    if value & (1 << (width - 1)):
                        value = ((value << 1) ^ poly) & mask
                    else:
                        value = (value << 1) & mask
                table.append(value & mask)

        return table

    def compute(self, data: bytes) -> int:
        """Compute CRC over arbitrary bytes."""
        mask = self._mask
        width = self.params.width

        if self.params.polynomial == 0:
            # XOR8 simple checksum
            result = 0
            for byte in data:
                result ^= byte
            return result & mask

        if self.params.reflect_in:
            crc = self._compute_reflected(data)
            # Reflected algorithm inherently produces reflected output;
            # reflect_out is already satisfied by the algorithm itself.
        else:
            crc = self._compute_non_reflected(data)
            if self.params.reflect_out:
                crc = self._reflect_bits(crc, width)

        crc ^= self.params.final_xor
        return crc & mask

    def _compute_reflected(self, data: bytes) -> int:
        """Right-shifting (reflected) CRC computation."""
        crc = self.params.initial_value & self._mask
        for byte in data:
            idx = (crc ^ byte) & 0xFF
            crc = ((crc >> 8) ^ self._table[idx]) & self._mask
        return crc

    def _compute_non_reflected(self, data: bytes) -> int:
        """Left-shifting (non-reflected) CRC computation."""
        crc = self.params.initial_value & self._mask
        width = self.params.width
        for byte in data:
            if width <= 8:
                idx = (crc ^ byte) & 0xFF
                crc = self._table[idx] & self._mask
            else:
                idx = ((crc >> (width - 8)) ^ byte) & 0xFF
                crc = ((crc << 8) ^ self._table[idx]) & self._mask
        return crc

    def compute_for_frame(self, frame: CanFrame, crc_range: CRCRange,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                          checksum_start_bit: int, checksum_length: int,
                          byte_order: str = "little_endian") -> int:  # pylint: disable=unused-argument
        """Compute CRC for a CAN frame.

        The CRC byte itself is excluded from the input data (not zeroed).
        If crc_range.dataid is set, the 16-bit DataID bytes are added
        to the payload data per AUTOSAR E2E convention.

        DataID positioning is controlled by crc_range.dataid_position:
          - "prepend": DataID goes before payload (default, GWM-style)
          - "append":  DataID goes after payload (AUTOSAR E2E Profile 5/1)

        Byte order is controlled by crc_range.dataid_byte_order:
          - "lo_hi": low byte first (default)
          - "hi_lo": high byte first (E2E 反序)

        Args:
            frame: The CAN frame with payload data.
            crc_range: Defines which bytes participate in the CRC.
            checksum_start_bit: Start bit of the CRC field within payload.
            checksum_length: Length in bits of the CRC field.
            byte_order: "little_endian" (Intel) or "big_endian" (Motorola).
        """
        data = bytearray(frame.data)

        # Compute the CRC byte position(s) so we can exclude them
        crc_byte_start = checksum_start_bit // 8
        crc_byte_end = (checksum_start_bit + checksum_length + 7) // 8

        # Determine which bytes to use for CRC (exclude CRC bytes)
        compute_bytes = self._extract_range(bytes(data), crc_range, len(data),
                                            crc_byte_start, crc_byte_end)

        # Prepend DataID if present (AUTOSAR E2E) — low byte first
        if crc_range.dataid is not None:
            dataid_lo = crc_range.dataid & 0xFF
            dataid_hi = (crc_range.dataid >> 8) & 0xFF
            if crc_range.dataid_byte_order == "hi_lo":
                dataid_bytes = bytes([dataid_hi, dataid_lo])
            else:
                dataid_bytes = bytes([dataid_lo, dataid_hi])
            if crc_range.dataid_position == "append":
                compute_bytes = compute_bytes + dataid_bytes
            else:
                compute_bytes = dataid_bytes + compute_bytes

        return self.compute(compute_bytes)

    def _extract_range(self, data: bytes, crc_range: CRCRange, full_length: int,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                       crc_byte_start: int = 0, crc_byte_end: int = 1) -> bytes:
        """Extract bytes for CRC, excluding the CRC field bytes."""
        if crc_range.mode in ("full_payload", "exclude_crc"):
            # Exclude CRC byte(s) from full payload
            return data[:crc_byte_start] + data[crc_byte_end:]
        if crc_range.mode == "custom_range":
            end = crc_range.end_byte if crc_range.end_byte >= 0 else full_length
            payload = data[crc_range.start_byte:end]
            # Exclude CRC byte(s) relative to the range
            rel_start = crc_byte_start - crc_range.start_byte
            rel_end = crc_byte_end - crc_range.start_byte
            if 0 <= rel_start < len(payload):
                return payload[:rel_start] + payload[rel_end:]
            return payload
        if crc_range.mode == "segment":
            if crc_range.end_byte >= 0:
                end = crc_range.end_byte
            else:
                end = crc_range.start_byte + crc_range.segment_size
            payload = data[crc_range.start_byte:end]
            # Exclude CRC byte (first byte of segment) from input
            return payload[1:]  # skip CRC byte, use rest of segment
        return data
