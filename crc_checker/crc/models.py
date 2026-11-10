"""CRC algorithm parameter models."""

from __future__ import annotations

from dataclasses import dataclass, field

VALID_RANGE_MODES = frozenset({
    "full_payload", "exclude_crc", "custom_range", "segment",
})
_CHECKSUM_TYPES = frozenset({"crc", "sum", "sum_xor", "xor_seed"})


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class CRCParams:
    """Complete CRC algorithm parameters."""
    width: int              # 8, 16, 32
    polynomial: int         # e.g. 0x2F for CRC8/AUTOSAR
    initial_value: int      # e.g. 0xFF
    final_xor: int          # e.g. 0xFF
    reflect_in: bool = False
    reflect_out: bool = False
    name: str = ""
    # "crc" | "sum" | "sum_xor" | "xor_seed" (non-CRC checksums)
    checksum_type: str = "crc"

    def __post_init__(self):
        # The lookup table shifts by (width - 8); widths below 8 raise an
        # obscure "negative shift count" from deep inside table construction.
        if not 8 <= self.width <= 32:
            raise ValueError(
                f"CRC width must be between 8 and 32 bits, got {self.width}")
        if self.checksum_type not in _CHECKSUM_TYPES:
            raise ValueError(
                f"Unknown checksum type '{self.checksum_type}'. "
                f"Expected one of: {', '.join(sorted(_CHECKSUM_TYPES))}")


@dataclass
class CRCRange:
    """Defines which bytes of the CAN payload participate in CRC calculation."""
    mode: str = "full_payload"   # "full_payload" | "exclude_crc" | "custom_range" | "segment"
    start_byte: int = 0
    end_byte: int = -1           # -1 means end of payload
    segment_size: int = 8        # bytes per segment (for "segment" mode)
    exclude_signals: list = field(default_factory=list)
    dataid: int | None = None    # 16-bit DataID value from AUTOSAR E2E config
    dataid_position: str = "prepend"  # "prepend" (before payload) | "append" (after payload)
    dataid_byte_order: str = "lo_hi"  # "lo_hi" (low byte first) | "hi_lo" (high byte first)
    dataid_width: int = 2        # bytes of DataID entering the CRC: 2 = both, 1 = low only (P02)
    crc_byte_swap: bool = False  # True = byte-swap computed CRC before comparison (Profile 5)

    @classmethod
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def for_segment(cls, checksum_start_bit: int, segment_size: int = 8,
                    dataid: int | None = None,
                    dataid_position: str = "prepend",
                    dataid_byte_order: str = "lo_hi",
                    dataid_width: int = 2,
                    crc_byte_swap: bool = False) -> "CRCRange":
        """Create a CRCRange that covers the segment containing the checksum signal.

        The segment is an aligned block of `segment_size` bytes. The checksum
        is at the first byte of the segment (typically).

        Args:
            checksum_start_bit: canmatrix start_bit of the checksum signal.
            segment_size: bytes per segment (default 8 for CAN FD multiplexing).
            dataid: optional DataID for AUTOSAR E2E.
            dataid_position: "prepend" (Profile 1) or "append" (Profile 5).
            dataid_byte_order: "lo_hi" or "hi_lo".
            dataid_width: bytes of DataID entering the CRC (P02 = 1 byte).
            crc_byte_swap: True = byte-swap computed CRC before comparison.
        """
        seg_start_byte = (checksum_start_bit // (segment_size * 8)) * segment_size
        return cls(
            mode="segment",
            start_byte=seg_start_byte,
            end_byte=seg_start_byte + segment_size,
            segment_size=segment_size,
            dataid=dataid,
            dataid_position=dataid_position,
            dataid_byte_order=dataid_byte_order,
            dataid_width=dataid_width,
            crc_byte_swap=crc_byte_swap,
        )
