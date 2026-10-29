"""Protection algorithm plugins."""

from crc_checker.protect.base import ProtectionAlgorithm
from crc_checker.protect.checksum import CRCVerifier
from crc_checker.protect.rolling_counter import RollingCounterVerifier

__all__ = ["ProtectionAlgorithm", "CRCVerifier", "RollingCounterVerifier"]
