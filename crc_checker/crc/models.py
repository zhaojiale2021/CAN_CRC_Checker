"""CRC algorithm parameter models."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    crc_byte_swap: bool = False  # True = byte-swap computed CRC before comparison (Profile 5)

    @classmethod
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def for_segment(cls, checksum_start_bit: int, segment_size: int = 8,
                    dataid: int | None = None,
                    dataid_position: str = "prepend",
                    dataid_byte_order: str = "lo_hi") -> "CRCRange":
        """Create a CRCRange that covers the segment containing the checksum signal.

        The segment is an aligned block of `segment_size` bytes. The checksum
        is at the first byte of the segment (typically).

        Args:
            checksum_start_bit: canmatrix start_bit of the checksum signal.
            segment_size: bytes per segment (default 8 for CAN FD multiplexing).
            dataid: optional DataID for AUTOSAR E2E.
            dataid_position: "prepend" (GWM) or "append" (E2E Profile 5/1).
            dataid_byte_order: "lo_hi" or "hi_lo".
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
        )
