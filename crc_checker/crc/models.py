"""CRC parameter models (re-exported from :mod:`crc_checker.core.models`).

The definitions moved to ``crc_checker.core`` so the DBC and trace layers can
share them without importing this package. This module keeps the historical
import path working for callers and tests.
"""

from crc_checker.core.models import (  # noqa: F401  (re-export)
    CHECKSUM_TYPES,
    VALID_RANGE_MODES,
    CRCParams,
    CRCRange,
)

# Backwards-compatible private alias used by older code/tests.
_CHECKSUM_TYPES = CHECKSUM_TYPES

__all__ = ["CRCParams", "CRCRange", "VALID_RANGE_MODES", "CHECKSUM_TYPES"]
