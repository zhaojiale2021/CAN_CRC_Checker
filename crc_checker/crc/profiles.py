"""AUTOSAR E2E profile definitions — per-group CRC algorithm, range and DataID layout.

GAC (广汽) mixes two profiles inside one DBC and one bus:

* Profile 5 — 16-bit CRC16/CCITT, DataID appended little-endian, protect
  ``min(frame_len, 56)`` bytes (CAN FD 64 B frames protect bytes 0..55).
* Profile 1 — 8-bit CRC8/SAE-J1850 (poly 0x1D, init 0xFF, final XOR 0xFF),
  DataID prepended little-endian, CRC in the first byte of the protected view.

The firmware picks the profile from the **CRC signal width** (2 bytes → P05,
1 byte → P01), not from the DBC comment — see mcu_app_j6 commit ``31bd82bcf``
"select E2E profile by CRC signal size, not CAN channel" and
``components/E2E/src/E2E_P05.c`` / ``E2E_P01.c``.

Profiles are applied per protection group (``DBCProtectionMap.apply_profiles``)
so a project can mix P05 and P01 messages, and so the DataID position can
differ per group (append for P05, prepend for P01) — something a single global
``dataid.position`` in the JSON config cannot express.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace

from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset


@dataclass(frozen=True)
class E2EProfile:  # pylint: disable=too-many-instance-attributes
    """Algorithm + frame layout of one AUTOSAR E2E profile.

    ``range_mode == ""`` means "inherit the global range from the config"
    (used by the built-in Profile 1 so legacy GWM/BAIC configs keep their
    existing range handling).
    """
    key: str
    name: str
    preset: str                     # CRC preset name
    crc_width: int = 16             # CRC signal width in bits (profile selection)
    dataid_position: str = "append"    # "append" (P05) | "prepend" (P01)
    dataid_byte_order: str = "lo_hi"   # "lo_hi" | "hi_lo"
    byte_swap: bool = False            # swap computed CRC bytes before compare
    range_mode: str = ""               # "" = inherit | exclude_crc | custom_range
    range_start: int = 0
    range_end: int = -1                # -1 = end of payload
    counter_max_valid: int | None = None   # max rolling counter value (None = 2^n - 1)

    def to_params(self) -> CRCParams:
        """CRC parameters for this profile."""
        return get_preset(self.preset)

    def to_range(self) -> CRCRange | None:
        """Explicit CRC range for this profile (None = inherit the config range)."""
        if not self.range_mode:
            return None
        dataid_layout = {
            "dataid_position": self.dataid_position,
            "dataid_byte_order": self.dataid_byte_order,
            "crc_byte_swap": self.byte_swap,
        }
        return CRCRange(mode=self.range_mode, start_byte=self.range_start,
                        end_byte=self.range_end, **dataid_layout)


# Field names accepted in a profile override (validated by load_profiles)
_PROFILE_FIELDS = frozenset(f.name for f in fields(E2EProfile))


# Built-in profiles. The defaults keep previously shipped behaviour: GWM/BAIC
# "Profile 1A" is CRC8/SAE-J1850-ZERO with a prepended DataID; Profile 5 is
# CRC16/CCITT with the DataID appended and a 0..56 byte segment.
BUILTIN_PROFILES: dict[str, E2EProfile] = {
    "p01": E2EProfile(
        key="p01", name="Profile 1", preset="CRC8/SAE-J1850-ZERO", crc_width=8,
        dataid_position="prepend", byte_swap=False,
        # AUTOSAR P01: 4-bit counter, 0..14 valid — 15 means "invalid"
        counter_max_valid=14,
    ),
    "p05": E2EProfile(
        key="p05", name="Profile 5", preset="CRC16/CCITT", crc_width=16,
        dataid_position="append", byte_swap=True,
        range_mode="custom_range", range_start=0, range_end=56,
    ),
}

# "Profile 1A", "Profile Variant 1A", "E2E Profile 5" → the digit is the profile number
_PROFILE_NUMBER = re.compile(r'PROFILE[^0-9]{0,12}([0-9]+)', re.IGNORECASE)
# CRC signal names as used in the DataID Remark column ("SRS_1_CRC2", "ADC_1_CRC")
_CRC_SIGNAL_NAME = re.compile(r'^[A-Za-z0-9_]*[_]CRC[_]?[0-9]*$', re.IGNORECASE)

# Range fields accepted in a profile override's nested "range" object
_RANGE_FIELDS = {
    "mode": "range_mode",
    "start_byte": "range_start",
    "end_byte": "range_end",
}


def profile_key_from_hint(hint: str) -> str | None:
    """Map a profile hint string to a profile key ("Profile 1A" → "p01")."""
    if not hint:
        return None
    match = _PROFILE_NUMBER.search(hint)
    if not match:
        return None
    return f"p{int(match.group(1)):02d}"


def profile_key_from_width(width: int) -> str | None:
    """Map a CRC signal width in bits to a profile key (16 → "p05", 8 → "p01")."""
    return {8: "p01", 16: "p05"}.get(width)


def is_crc_signal_name(name: str) -> bool:
    """True when ``name`` looks like a CRC signal (used for DataID Remark names)."""
    return bool(name) and bool(_CRC_SIGNAL_NAME.match(name.strip()))


def load_profiles(overrides: dict | None = None) -> dict[str, E2EProfile]:
    """Built-in profiles merged with config overrides.

    Args:
        overrides: ``{"p01": {"preset": "CRC8/SAE-J1850", "range": {"mode": ...}}}``.
            Unknown field names raise ValueError so typos in config.json fail loudly.

    Returns:
        Dict of profile key → E2EProfile.
    """
    profiles = dict(BUILTIN_PROFILES)
    for key, field_values in (overrides or {}).items():
        profile_key = str(key).lower()
        base = profiles.get(profile_key, E2EProfile(key=profile_key, name=str(key), preset=""))
        updates = {}
        for field_name, value in (field_values or {}).items():
            if field_name == "range":
                if not isinstance(value, dict):
                    raise ValueError(f"profile '{key}': 'range' must be an object")
                for range_key, range_value in value.items():
                    if range_key not in _RANGE_FIELDS:
                        raise ValueError(
                            f"profile '{key}': unknown range field '{range_key}'")
                    updates[_RANGE_FIELDS[range_key]] = range_value
                continue
            if field_name not in _PROFILE_FIELDS:
                raise ValueError(f"profile '{key}': unknown field '{field_name}'")
            updates[field_name] = value
        profiles[profile_key] = replace(base, **updates)
    return profiles
