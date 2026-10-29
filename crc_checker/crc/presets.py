"""Built-in CRC algorithm presets for automotive use."""

from crc_checker.crc.models import CRCParams

PRESETS: dict[str, CRCParams] = {
    "CRC8/AUTOSAR": CRCParams(
        width=8, polynomial=0x2F, initial_value=0xFF,
        final_xor=0xFF, reflect_in=False, reflect_out=False,
        name="CRC8/AUTOSAR",
    ),
    "CRC8/SAE-J1850": CRCParams(
        width=8, polynomial=0x1D, initial_value=0xFF,
        final_xor=0xFF, reflect_in=False, reflect_out=False,
        name="CRC8/SAE-J1850",
    ),
    "CRC8/SAE-J1850-ZERO": CRCParams(
        width=8, polynomial=0x1D, initial_value=0x00,
        final_xor=0x00, reflect_in=False, reflect_out=False,
        name="CRC8/SAE-J1850-ZERO",
    ),
    "CRC8/H2F": CRCParams(
        width=8, polynomial=0x2F, initial_value=0xFF,
        final_xor=0xFF, reflect_in=False, reflect_out=False,
        name="CRC8/H2F",
    ),
    "CRC16/ARC": CRCParams(
        width=16, polynomial=0x8005, initial_value=0x0000,
        final_xor=0x0000, reflect_in=True, reflect_out=True,
        name="CRC16/ARC",
    ),
    "CRC16/MODBUS": CRCParams(
        width=16, polynomial=0x8005, initial_value=0xFFFF,
        final_xor=0x0000, reflect_in=True, reflect_out=True,
        name="CRC16/MODBUS",
    ),
    "CRC16/CCITT": CRCParams(
        width=16, polynomial=0x1021, initial_value=0xFFFF,
        final_xor=0x0000, reflect_in=False, reflect_out=False,
        name="CRC16/CCITT (E2E Profile 5)",
    ),
    "CRC32/AUTOSAR": CRCParams(
        width=32, polynomial=0xF4ACFB13, initial_value=0xFFFFFFFF,
        final_xor=0xFFFFFFFF, reflect_in=True, reflect_out=True,
        name="CRC32/AUTOSAR",
    ),
    "CRC32/ETHERNET": CRCParams(
        width=32, polynomial=0x04C11DB7, initial_value=0xFFFFFFFF,
        final_xor=0xFFFFFFFF, reflect_in=True, reflect_out=True,
        name="CRC32/ETHERNET",
    ),
    "XOR8": CRCParams(
        width=8, polynomial=0x00, initial_value=0x00,
        final_xor=0x00, reflect_in=False, reflect_out=False,
        name="XOR8 (Simple Checksum)",
    ),
    # Non-CRC checksums — see crc/classify.py
    "SUM8": CRCParams(
        width=8, polynomial=0x00, initial_value=0x00,
        final_xor=0x00, reflect_in=False, reflect_out=False,
        name="SUM8 (sum of bytes AND 0xFF, no final XOR)",
        checksum_type="sum",
    ),
    "SUM8/XOR-FF": CRCParams(
        width=8, polynomial=0x00, initial_value=0x00,
        final_xor=0xFF, reflect_in=False, reflect_out=False,
        name="SUM8/XOR-FF (sum of bytes AND 0xFF, then XOR 0xFF)",
        checksum_type="sum_xor",
    ),
    "XOR8/SEED": CRCParams(
        width=8, polynomial=0x00, initial_value=0x00,
        final_xor=0x00, reflect_in=False, reflect_out=False,
        name="XOR8/SEED (byte-wise XOR with constant seed)",
        checksum_type="xor_seed",
    ),
}


# Which presets have been checked against captured CAN data in this repository.
# "validated" means at least one real trace reproduced the expected values for
# that algorithm; everything else is shipped for completeness but has not been
# verified with real data. See docs/supported-algorithms.md.
VALIDATION: dict[str, tuple[str, str]] = {
    "CRC8/AUTOSAR": ("unverified", "no captured trace in this repository"),
    "CRC8/SAE-J1850": ("validated", "captured CAN traces, per-message classification"),
    "CRC8/SAE-J1850-ZERO": ("validated", "captured CAN traces, E2E Profile 1"),
    "CRC8/H2F": ("unverified", "no captured trace in this repository"),
    "CRC16/ARC": ("unverified", "no captured trace in this repository"),
    "CRC16/MODBUS": ("unverified", "no captured trace in this repository"),
    "CRC16/CCITT": ("validated", "captured CAN traces, E2E Profile 5"),
    "CRC32/AUTOSAR": ("unverified", "no captured trace in this repository"),
    "CRC32/ETHERNET": ("unverified", "no captured trace in this repository"),
    "XOR8": ("unverified", "no captured trace in this repository"),
    "SUM8": ("validated", "plain additive sum verified; wider variants unverified"),
    "SUM8/XOR-FF": ("validated", "captured CAN traces"),
    "XOR8/SEED": ("validated", "captured CAN traces"),
}

VALIDATED = "validated"
UNVERIFIED = "unverified"


def get_validation(name: str) -> tuple[str, str]:
    """Return ``(status, note)`` for a preset.

    ``status`` is ``"validated"`` (checked against captured CAN data) or
    ``"unverified"`` (shipped but not verified with real data).
    """
    params = get_preset(name)
    for key, preset in PRESETS.items():
        if preset is params:
            return VALIDATION.get(key, (UNVERIFIED, "unknown"))
    return (UNVERIFIED, "unknown")


def get_preset(name: str) -> CRCParams:
    """Get a preset by name (case-insensitive, hyphens/underscores interchangeable)."""
    normalized = name.upper().replace("-", "/").replace("_", "/")
    for key, params in PRESETS.items():
        if key.upper().replace("-", "/").replace("_", "/") == normalized:
            return params
    available = ", ".join(PRESETS.keys())
    raise KeyError(f"Unknown CRC preset '{name}'. Available: {available}")


def list_presets() -> list[str]:
    """Return list of available preset names."""
    return list(PRESETS.keys())
