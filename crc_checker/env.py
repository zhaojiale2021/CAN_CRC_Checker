"""Environment lookup with legacy-name fallbacks.

The project was renamed from ``crc-checker`` to CanVouch. Existing shell
scripts and deployments may still export the old ``CRC_*`` names, so each new
``CANVOUCH_*`` variable falls back to its historical counterpart.
"""

from __future__ import annotations

import os


def getenv(name: str, *legacy: str, default: str = "") -> str:
    """Return the first non-empty value among ``name`` and its legacy names."""
    for key in (name, *legacy):
        value = os.environ.get(key)
        if value is not None and value != "":
            return value
    return default
