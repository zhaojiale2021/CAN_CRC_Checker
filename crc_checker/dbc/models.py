"""Data models for DBC-parsed protection signal information."""

from __future__ import annotations

from dataclasses import dataclass, field
from crc_checker.crc.models import CRCParams, CRCRange


@dataclass
class SignalInfo:
    """Extracted information about a single protection signal from DBC."""
    name: str                # "Checksum_ACC1"
    start_bit: int           # bit position within payload
    length: int              # bit length (8 for CRC8, 4 for RC)
    byte_order: str = "little_endian"  # "little_endian" or "big_endian"


@dataclass
class MessageProtection:
    """Protection information for one CAN message.

    A message may have multiple protection groups (e.g., ACC1, ACC2).
    Each group is a (checksum, rolling_counter) pair identified by a common suffix.
    """
    frame_id: int
    frame_name: str
    dlc: int
    pair_suffix: str = ""                                      # e.g. "ACC1"
    checksum_signal: SignalInfo | None = None
    rolling_counter_signal: SignalInfo | None = None
    crc_params: CRCParams | None = None                        # Algorithm to use (set by user/config)
    crc_range: CRCRange | None = None                          # Data range for CRC (set by user/config)
    dataid: int | None = None                                  # 16-bit DataID (from AUTOSAR E2E config)
    frame_protection_count: int = 1                            # How many protection groups in this frame
    rc_max_valid: int | None = None                            # Max valid RC value before wrap (None = auto from bit length)


@dataclass
class DBCProtectionMap:
    """Complete map of all protection signals across all messages."""
    dbc_path: str
    messages: dict[int, list[MessageProtection]] = field(default_factory=dict)
    # key = frame_id, value = list of protection groups within that message

    def get_protections(self, frame_id: int) -> list[MessageProtection]:
        """Get all protection groups for a given CAN ID."""
        return self.messages.get(frame_id, [])

    def all_frame_ids(self) -> list[int]:
        """Get all CAN IDs that have protection signals."""
        return list(self.messages.keys())

    def apply_crc_params(self, params: CRCParams):
        """Apply the same CRC params to all protection groups."""
        for prot_list in self.messages.values():
            for prot in prot_list:
                prot.crc_params = params

    def apply_crc_range(self, crc_range: CRCRange):
        """Apply the same CRC range to all protection groups."""
        for prot_list in self.messages.values():
            for prot in prot_list:
                prot.crc_range = crc_range

    def apply_dataid_map(self, dataid_map):
        """Apply DataID values from a DataIDMap to matching protection groups.

        Matches by (frame_id, checksum_signal_name).
        """
        applied = 0
        for prot_list in self.messages.values():
            for prot in prot_list:
                if prot.checksum_signal:
                    dataid = dataid_map.get(prot.frame_id, prot.checksum_signal.name)
                    if dataid is not None:
                        prot.dataid = dataid
                        applied += 1
        return applied

    def apply_rc_config(self, max_valid: int | None = None):
        """Apply RC range config to all protection groups."""
        if max_valid is not None:
            for prot_list in self.messages.values():
                for prot in prot_list:
                    prot.rc_max_valid = max_valid
