"""CRC/Checksum verification algorithm."""

from __future__ import annotations
from dataclasses import replace
from crc_checker.protect.base import ProtectionAlgorithm
from crc_checker.trace.models import CanFrame
from crc_checker.dbc.models import MessageProtection
from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.bit_utils import extract_signal_bits
from crc_checker.verify.models import VerifyVerdict


class CRCVerifier(ProtectionAlgorithm):
    """Verifies CRC/Checksum values in CAN frames.

    Extracts the actual CRC value from the frame payload, computes the expected
    value using the configured CRC algorithm, and compares them.
    """

    algorithm_type = "crc"

    def __init__(self, params: CRCParams, crc_range: CRCRange | None = None):
        self.engine = CRCEngine(params)
        self.params = params
        self._explicit_range = crc_range  # None = auto-detect

    def verify(self, frame: CanFrame, protection: MessageProtection) -> VerifyVerdict | None:
        """Verify CRC for a frame."""
        cs_signal = protection.checksum_signal
        if cs_signal is None:
            return None

        # Determine CRC parameters (use message-level override if set, else default)
        params = protection.crc_params or self.params

        # Determine CRC range: explicit > message-level > auto-detect
        crc_range = protection.crc_range or self._explicit_range
        if crc_range is None:
            # Auto-detect:
            # - CAN FD (DLC > 8) with DataID → segment mode (8-byte blocks)
            # - Standard CAN or no DataID → exclude CRC field (full payload)
            if protection.dataid is not None and frame.dlc > 8:
                crc_range = CRCRange.for_segment(
                    cs_signal.start_bit, dataid=protection.dataid)
            else:
                crc_range = CRCRange(mode="exclude_crc")
        elif crc_range.mode == "exclude_crc" and protection.dataid is not None and frame.dlc > 8:
            # Override: if explicit range is default exclude_crc but we have DataID + CAN FD,
            # use segment mode instead (the explicit default shouldn't override smarter behavior)
            crc_range = CRCRange.for_segment(
                cs_signal.start_bit, dataid=protection.dataid,
                dataid_position=crc_range.dataid_position,
                dataid_byte_order=crc_range.dataid_byte_order)

        # Inject DataID into CRC range if available on this protection group
        if protection.dataid is not None and crc_range.dataid is None:
            crc_range = replace(crc_range, dataid=protection.dataid)

        # Propagate DataID position/byte_order from protection-level range
        if protection.dataid is not None and protection.crc_range:
            for attr in ("dataid_position", "dataid_byte_order"):
                p_val = getattr(protection.crc_range, attr)
                if getattr(crc_range, attr) != p_val:
                    crc_range = replace(crc_range, **{attr: p_val})

        # Rebuild engine if params differ from initialized
        engine = self.engine if params == self.params else CRCEngine(params)

        # Extract actual value from payload (using correct Motorola/Intel bit order)
        actual_value = extract_signal_bits(
            frame.data, cs_signal.start_bit, cs_signal.length, cs_signal.byte_order
        )
        # b81vs-style non-CRC 8-bit checksums on >8-bit signals: the firmware
        # (crc_calculatecrcxor) compares only the byte at crc_index (e.g. a
        # 16-bit Checksum<ID> field where only the low byte carries the value
        # and the high byte is ignored), so align the actual value to that byte.
        if (cs_signal.length > 8 and params.checksum_type != "crc"
                and params.width < 16):
            crc_byte = cs_signal.start_bit // 8
            actual_value = frame.data[crc_byte] if crc_byte < len(frame.data) else 0

        # Compute expected value
        expected_value = engine.compute_for_frame(
            frame, crc_range, cs_signal.start_bit, cs_signal.length, cs_signal.byte_order
        )

        # Apply byte-swap for comparison if configured (Profile 5: CRC computed LE,
        # but DBC defines signal as BE; OEM byte-swaps before transmission)
        if crc_range.crc_byte_swap and cs_signal.length > 8:
            expected_value = ((expected_value & 0xFF) << 8) | ((expected_value >> 8) & 0xFF)

        is_pass = expected_value == actual_value
        detail = ""
        if not is_pass:
            detail = (f"CRC mismatch in {protection.frame_name} "
                      f"({protection.pair_suffix}): "
                      f"expected 0x{expected_value:02X}, got 0x{actual_value:02X}")

        return VerifyVerdict(
            frame_id=frame.arbitration_id,
            timestamp=frame.timestamp,
            algorithm=self.algorithm_type,
            signal_name=cs_signal.name,
            expected_value=expected_value,
            actual_value=actual_value,
            is_pass=is_pass,
            detail=detail,
            start_bit=cs_signal.start_bit,
            length=cs_signal.length,
            byte_order=cs_signal.byte_order,
            dataid=protection.dataid,
            dataid_name=protection.dataid_name,
            dataid_profile=protection.crc_profile,
            crc_algorithm=params.name,
        )
