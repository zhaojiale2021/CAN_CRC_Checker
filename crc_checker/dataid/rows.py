"""Shared DataID row parsing and workbook column detection."""

from __future__ import annotations

import re

from crc_checker.dataid.mappings import ColumnMapping
from crc_checker.dataid.models import DataIDMap


def _col_ref_to_index(ref: str) -> int:
    """Convert Excel column reference (e.g. 'A', 'AB') to 0-based index."""
    idx = 0
    for ch in ''.join(ch for ch in ref if ch.isalpha()).upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


# pylint: disable=too-many-locals,too-many-branches
def _auto_detect_columns(mapping: ColumnMapping, header_row: list) -> ColumnMapping:
    """Auto-detect column positions from header names.

    Matches common header patterns (English, Chinese, mixed).
    Returns a new ColumnMapping with resolved indices.
    """
    if mapping.use_header_names:
        return mapping.resolve_columns(header_row)

    # Try to auto-locate columns by common header name patterns
    # Note: keep patterns specific to avoid matching duplicate columns
    # (e.g. a "Message Name" column in a duplicate column group)
    sig_patterns = [
        "checksum signal name", "signalname", "signal name",
        "signals", "checksumsignal", "e2e checksum",
    ]
    id_patterns = [
        "message id", "messageid", "msg id", "can id", "canid",
        "pdu id", "pduid", "arbitration id",
    ]
    hi_patterns = [
        "dataid_hi", "data id hi", "dataid high",
        "data_id_hi", "data id (high byte)", "data_id (high byte)",
        "high byte of data id", "highbyte",
    ]
    lo_patterns = [
        "dataid_lo", "data id lo", "dataid low",
        "data_id_lo", "data id (low byte)", "data_id (low byte)",
        "low byte of data id", "lowbyte",
    ]
    did_combined = [
        "data_id_both", "dataid_both", "data_id",
        "data id (hex)", "data id (dec)",
    ]

    def _match(cell, patterns: list[str]) -> bool:
        if cell is None:
            return False
        s = str(cell).strip().lower().replace(" ", "").replace("_", "").replace("\n", "")
        for p in patterns:
            ps = p.replace(" ", "").replace("_", "")
            if s == ps or ps in s:
                return True
        return False

    sig_col = mapping.col_signal_name
    id_col = mapping.col_message_id
    hi_col = mapping.col_dataid_hi
    lo_col = mapping.col_dataid_lo
    remark_col = mapping.col_remark if mapping.col_remark >= 0 else -1

    for i, cell in enumerate(header_row):
        if cell is None:
            continue
        s = str(cell).strip()
        if not s:
            continue
        if _match(s, sig_patterns):
            sig_col = i
        elif _match(s, id_patterns):
            id_col = i
        # Hi/Lo before the bare "data_id" combined pattern: "DataID High Byte"
        # / "DataID Low Byte" headers contain "data_id" as a substring and were
        # hijacked by the combined branch (hi = the "low" column, lo = next).
        elif _match(s, hi_patterns):
            hi_col = i
        elif _match(s, lo_patterns):
            lo_col = i
        elif _match(s, did_combined):
            # Combined DataID column: Hi in this col, Lo in next
            hi_col = i
            lo_col = i + 1
        elif _match(s, ["remark", "remarks", "comment", "comments", "profile", "note"]):
            remark_col = i

    # A "(dec)" header declares decimal DataID text — without this the text
    # "84" would parse as 0x84 and every DataID would be wrong.
    dataid_base = 10 if any(
        isinstance(c, str) and "dec" in str(c).strip().lower()
        for c in header_row) else mapping.dataid_base

    return ColumnMapping(
        col_signal_name=sig_col,
        col_message_id=id_col,
        col_dataid_hi=hi_col,
        col_dataid_lo=lo_col,
        col_remark=remark_col,
        dataid_format=mapping.dataid_format,
        data_row_start=mapping.data_row_start,
        message_id_base=mapping.message_id_base,
        dataid_base=dataid_base,
        signal_name_filter=mapping.signal_name_filter,
        use_header_names=False,
    )


def _parse_dataid_value(hi_val, lo_val, fmt: str, base: int = 16) -> int | None:
    """Parse raw Excel cell values into a 16-bit DataID integer.

    ``base`` applies to TEXT cells only (numeric cells are already binary);
    it defaults to hex for backward compatibility and is set to 10 by the
    column auto-detection when the header says "(dec)".
    """
    def _to_int(v):
        if v is None:
            return None
        if isinstance(v, str):
            text = v.strip()
            if text.lower().startswith("0x"):
                text, base_ = text[2:], 16
            else:
                base_ = base
            try:
                return int(text, base_)
            except ValueError:
                return None
        if isinstance(v, (int, float)):
            return int(v)
        return None

    if fmt == "hi_lo_two_cols":
        hi = _to_int(hi_val)
        lo = _to_int(lo_val)
        if hi is not None and lo is not None:
            return (hi << 8) | lo
    elif fmt == "two_cols_lsb_first":
        lo = _to_int(hi_val)   # first column is low byte
        hi = _to_int(lo_val)   # second column is high byte
        if hi is not None and lo is not None:
            return (hi << 8) | lo
    elif fmt == "single_16bit":
        v = _to_int(hi_val)
        if v is not None:
            return v & 0xFFFF
    elif fmt == "single_8bit":
        v = _to_int(hi_val)
        if v is not None:
            return v & 0xFF
    return None


def _parse_message_id(value, base: int = 16) -> int | None:  # pylint: disable=too-many-return-statements
    """Parse a CAN ID cell ("0x268", "268" in hex, or a numeric cell)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.lower().startswith("0x"):
            try:
                return int(text, 16)
            except ValueError:
                return None
        if all(c in '0123456789abcdefABCDEF' for c in text):
            try:
                return int(text, base)
            except ValueError:
                return None
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _entry_names(signal_name: str, remark: str) -> list[str]:
    """Names a DataID row is registered under.

    The message name is always registered, and when the Remark column names a
    CRC signal ("CCU_1_CRC1", "CCU_1_CRC2", "CCU_1_CRC3" for the same message)
    that name is registered
    too — otherwise the rows of a multi-CRC message overwrite each other and
    only the last one survives.
    """
    names = [signal_name]
    remark = (remark or "").strip()
    if (remark and remark.lower() != (signal_name or "").lower()
            and re.match(r'^[A-Za-z0-9_]*[_]CRC[_]?[0-9]*$', remark, re.IGNORECASE)):
        names.append(remark)
    return names


def _add_dataid_row(row: list, mapping: ColumnMapping, dataid_map: DataIDMap) -> bool:
    """Parse one spreadsheet row (list of cells) into the DataID map.

    Shared by the openpyxl, raw-xlsx and xlrd (.xls) readers.

    Returns:
        True when the row produced a DataID entry.
    """
    # pylint: disable=too-many-return-statements,too-many-locals
    # A negative column index means "header name not found" (use_header_names
    # layouts) — reading row[-1] would silently take the last cell and produce
    # a wrong mapping, so give up on the row instead.
    if (mapping.col_signal_name < 0 or mapping.col_message_id < 0
            or mapping.col_dataid_hi < 0):
        return False
    max_col_needed = max(
        mapping.col_signal_name,
        mapping.col_message_id,
        mapping.col_dataid_hi,
        mapping.col_dataid_lo if mapping.col_dataid_lo >= 0 else 0,
        mapping.col_remark if mapping.col_remark >= 0 else 0,
    )
    if len(row) <= max_col_needed:
        return False

    signal_name = row[mapping.col_signal_name]
    dataid_hi = row[mapping.col_dataid_hi]
    dataid_lo = row[mapping.col_dataid_lo] if mapping.col_dataid_lo >= 0 else None

    # Skip header/sub-header rows
    if dataid_hi is None and dataid_lo is None:
        return False
    if isinstance(dataid_hi, str) and dataid_hi.lower() in (
            "high_byte", "dataid", "data_id", "data id"):
        return False
    if not isinstance(signal_name, str):
        return False
    # Excel cells carry stray whitespace (some tables have trailing spaces on
    # "ZCUR_8 " / "SBM_5 "; the BEV sheet title uses non-breaking spaces).
    # Without stripping, the entry never matches the DBC name and the message
    # silently gets no DataID (CRC then fails on every frame).
    signal_name = signal_name.strip()

    # Filter by signal name keyword (supports both prefix and suffix naming)
    if mapping.signal_name_filter:
        name_lower = signal_name.lower()
        if not any(pfx in name_lower for pfx in mapping.signal_name_filter):
            return False

    frame_id = _parse_message_id(row[mapping.col_message_id], mapping.message_id_base)
    if frame_id is None:
        return False

    dataid = _parse_dataid_value(dataid_hi, dataid_lo, mapping.dataid_format,
                                 mapping.dataid_base)
    if dataid is None:
        return False

    # Remark column: profile marker ("Profile Variant 1A") or CRC signal name
    remark = ""
    if 0 <= mapping.col_remark < len(row) and isinstance(row[mapping.col_remark], str):
        remark = row[mapping.col_remark].strip()
    profile = remark if "profile" in remark.lower() else ""

    for name in _entry_names(signal_name, remark):
        dataid_map.add(frame_id, name, dataid, profile)
    return True
