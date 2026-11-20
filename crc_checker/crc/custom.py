"""Custom CRC parameter parsing shared by the CLI and the config loader."""

from __future__ import annotations

from crc_checker.core.models import CRCParams


def _as_int(value, default, label="value"):
    """Accept an int or a ``0x``-prefixed string for a numeric CRC parameter.

    A bare string like ``"471"`` is ambiguous (decimal 471 or hex 0x471) and
    used to be silently read as hex; reject it instead of computing a wrong
    CRC that looks like a firmware bug.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"crc.custom.{label} must be an integer or a 0x string")
    if isinstance(value, str):
        text = value.strip()
        if not text.lower().startswith("0x"):
            raise ValueError(
                f"crc.custom.{label} string must start with 0x (got {value!r})")
        try:
            return int(text, 16)
        except ValueError as exc:
            raise ValueError(
                f"crc.custom.{label} is not valid hex: {value!r}") from exc
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
        width=_as_int(data["width"], 8, "width"),
        polynomial=_as_int(data["poly"], 0, "poly"),
        initial_value=_as_int(data.get("init"), 0, "init"),
        final_xor=_as_int(data.get("xor"), 0, "xor"),
        reflect_in=bool(data.get("reflect_in", False)),
        reflect_out=bool(data.get("reflect_out", False)),
        name=str(data.get("name", "custom")),
        checksum_type=str(data.get("type", "crc")),
    )
