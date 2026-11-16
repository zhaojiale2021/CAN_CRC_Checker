"""Custom CRC parameter parsing shared by the CLI and the config loader."""

from __future__ import annotations

from crc_checker.core.models import CRCParams


def _as_int(value, default):
    """Accept an int or a ``0x`` string for a numeric CRC parameter."""
    if value is None:
        return default
    if isinstance(value, str):
        return int(value, 16)
    return value


def parse_custom_crc(data: dict) -> CRCParams:
    """Build :class:`CRCParams` from a ``crc.custom`` JSON object.

    Raises:
        ValueError: missing ``width``/``poly`` or an invalid value.
    """
    missing = {"width", "poly"} - set(data)
    if missing:
        raise ValueError(
            "crc.custom is missing required field(s): " + ", ".join(sorted(missing)))
    return CRCParams(
        width=_as_int(data["width"], 8),
        polynomial=_as_int(data["poly"], 0),
        initial_value=_as_int(data.get("init"), 0),
        final_xor=_as_int(data.get("xor"), 0),
        reflect_in=bool(data.get("reflect_in", False)),
        reflect_out=bool(data.get("reflect_out", False)),
        name=str(data.get("name", "custom")),
        checksum_type=str(data.get("type", "crc")),
    )
