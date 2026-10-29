"""CRC engine module."""

from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset, list_presets, PRESETS
from crc_checker.crc.engine import CRCEngine

__all__ = ["CRCParams", "CRCRange", "CRCEngine", "get_preset", "list_presets", "PRESETS"]
