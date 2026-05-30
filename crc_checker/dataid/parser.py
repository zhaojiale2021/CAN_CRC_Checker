"""DataID Excel parser — extracts DataID mappings for E2E protection groups.

The Excel file maps (MessageID, ChecksumSignalName) → 16-bit DataID.
DataID is prepended to payload data before CRC calculation as per AUTOSAR E2E spec.

## Extensibility for different Excel formats

Different OEMs/suppliers use different Excel layouts for DataID tables.
Use `ColumnMapping` to configure column indices and data format without
modifying this module. Built-in presets cover common formats; custom
mappings can be passed via CLI (`--dataid-columns` JSON) or programmatically.
"""

from __future__ import annotations
from dataclasses import dataclass


class DataIDMap:
    """Maps (frame_id, checksum_signal_name) → 16-bit DataID value."""

    def __init__(self, sheet_name: str = ""):
        self.sheet_name = sheet_name
        self._map: dict[tuple[int, str], int] = {}  # (frame_id, signal_name) → dataid

    def add(self, frame_id: int, signal_name: str, dataid: int):
        """Register a DataID for a specific checksum signal."""
        self._map[(frame_id, signal_name)] = dataid

    def get(self, frame_id: int, signal_name: str) -> int | None:
        """Get DataID for a frame/signal pair, or None if not found."""
        return self._map.get((frame_id, signal_name))

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: tuple[int, str]) -> bool:
        return key in self._map


# ---------------------------------------------------------------------------
# Column mapping — defines where each piece of data lives in the Excel sheet
# ---------------------------------------------------------------------------

@dataclass
class ColumnMapping:
    """Defines the Excel column layout for DataID extraction.

    Each field is a 0-based column index. Set to -1 to skip that field.
    `dataid_format` controls how the DataID bytes are interpreted:
      - "hi_lo_two_cols" : High byte in one column, Low byte in another (default)
      - "single_16bit"   : Single column with 16-bit hex value (e.g. "0x0054")
      - "single_8bit"    : Single column with 8-bit value (use 0 for high byte)
      - "two_cols_lsb_first" : Like hi_lo but low byte comes first

    `data_row_start` is the 1-based row number where data begins (after headers).
    `signal_name_filter` is a list of prefixes used to identify checksum rows.
      Set to None to accept all rows that have a DataID value.
    """
    col_signal_name: int = 1         # Column for signal name (e.g. "Checksum_ACC1")
    col_message_id: int = 3          # Column for CAN ID (e.g. "0x143")
    col_dataid_hi: int = 12          # Column for DataID high byte
    col_dataid_lo: int = 13          # Column for DataID low byte
    dataid_format: str = "hi_lo_two_cols"
    data_row_start: int = 3          # 1-based row where data begins
    message_id_base: int = 16        # Radix for message ID parsing (16 = hex, 10 = decimal)
    signal_name_filter: list[str] | None = None
    # Default filter: common checksum signal prefixes
    _DEFAULT_FILTER = ("checksum", "crc", "check_sum", "e2e_crc")

    def __post_init__(self):
        if self.signal_name_filter is None:
            self.signal_name_filter = list(self._DEFAULT_FILTER)


# Built-in presets for known OEM formats
# Contributions welcome — add your format here or pass via CLI.
BUILTIN_MAPPINGS: dict[str, ColumnMapping] = {
    # Great Wall Motors J6M E2E DataID format
    # Columns: B=SignalName, D=MessageID, M=DataID_Hi, N=DataID_Lo
    "greatwall_j6m": ColumnMapping(
        col_signal_name=1,
        col_message_id=3,
        col_dataid_hi=12,
        col_dataid_lo=13,
        dataid_format="hi_lo_two_cols",
        data_row_start=3,
        message_id_base=16,
    ),
    # Generic format: A=SignalName, B=MessageID, C=DataID(16bit hex)
    "generic_abc": ColumnMapping(
        col_signal_name=0,
        col_message_id=1,
        col_dataid_hi=2,       # same column for single_16bit
        col_dataid_lo=-1,      # unused
        dataid_format="single_16bit",
        data_row_start=2,
        message_id_base=16,
    ),
    # Simple format: A=MessageID, B=SignalName, C=DataID(8bit)
    "simple_8bit": ColumnMapping(
        col_signal_name=1,
        col_message_id=0,
        col_dataid_hi=2,
        col_dataid_lo=-1,
        dataid_format="single_8bit",
        data_row_start=2,
        message_id_base=10,
    ),
}


def _parse_dataid_value(hi_val, lo_val, fmt: str) -> int | None:
    """Parse raw Excel cell values into a 16-bit DataID integer."""
    def _to_int(v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return int(v, 16)
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


def parse_dataid_xlsx(xlsx_path: str,
                      sheet_name: str | None = None,
                      mapping: ColumnMapping | str | None = None) -> DataIDMap:
    """Parse a DataID Excel file and return a DataIDMap.

    Args:
        xlsx_path: Path to the .xlsx file.
        sheet_name: Sheet name to read. If None, uses the first sheet.
        mapping: ColumnMapping instance, name of a builtin mapping (e.g. "greatwall_j6m"),
                 or a JSON string defining a custom ColumnMapping.
                 If None, defaults to "greatwall_j6m".

    Returns:
        DataIDMap with all parsed entries.
    """
    import json
    import openpyxl

    # Resolve mapping
    if mapping is None:
        mapping = BUILTIN_MAPPINGS["greatwall_j6m"]
    elif isinstance(mapping, str):
        # Try builtin name first, then JSON
        if mapping in BUILTIN_MAPPINGS:
            mapping = BUILTIN_MAPPINGS[mapping]
        else:
            # Parse as JSON: {"col_signal_name":1, "col_message_id":3, ...}
            try:
                data = json.loads(mapping)
                mapping = ColumnMapping(**data)
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(
                    f"Unknown mapping '{mapping}'. "
                    f"Available builtins: {list(BUILTIN_MAPPINGS.keys())}. "
                    f"Or pass a JSON string with ColumnMapping fields. Error: {e}"
                )

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    if sheet_name is None:
        sheet_name = wb.sheetnames[0]

    if sheet_name not in wb.sheetnames:
        available = ", ".join(wb.sheetnames)
        raise ValueError(f"Sheet '{sheet_name}' not found. Available: {available}")

    ws = wb[sheet_name]
    dataid_map = DataIDMap(sheet_name=sheet_name)

    for row in ws.iter_rows(min_row=mapping.data_row_start, values_only=True):
        if not row:
            continue

        # Read cells according to column mapping
        max_col_needed = max(
            mapping.col_signal_name,
            mapping.col_message_id,
            mapping.col_dataid_hi,
            mapping.col_dataid_lo if mapping.col_dataid_lo >= 0 else 0,
        )
        if len(row) <= max_col_needed:
            continue

        signal_name = row[mapping.col_signal_name]
        message_id_str = row[mapping.col_message_id]
        dataid_hi = row[mapping.col_dataid_hi]
        dataid_lo = row[mapping.col_dataid_lo] if mapping.col_dataid_lo >= 0 else None

        # Skip header/sub-header rows
        if dataid_hi is None and dataid_lo is None:
            continue
        if isinstance(dataid_hi, str) and dataid_hi.lower() in ("high_byte", "dataid", "data_id"):
            continue
        if not isinstance(signal_name, str):
            continue

        # Filter by signal name prefix
        if mapping.signal_name_filter:
            name_lower = signal_name.lower()
            if not any(name_lower.startswith(pfx) for pfx in mapping.signal_name_filter):
                continue

        # Parse message ID
        try:
            if isinstance(message_id_str, str):
                frame_id = int(message_id_str, mapping.message_id_base)
            elif isinstance(message_id_str, (int, float)):
                frame_id = int(message_id_str)
            else:
                continue
        except (ValueError, TypeError):
            continue

        # Parse DataID
        dataid = _parse_dataid_value(dataid_hi, dataid_lo, mapping.dataid_format)
        if dataid is not None:
            dataid_map.add(frame_id, signal_name, dataid)

    wb.close()
    return dataid_map


# Backward-compatible alias
def parse_dataid_xlsx_legacy(xlsx_path: str, sheet_name: str | None = None) -> DataIDMap:
    """Original interface — uses greatwall_j6m column mapping."""
    return parse_dataid_xlsx(xlsx_path, sheet_name, mapping="greatwall_j6m")
