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
import json
import logging

logger = logging.getLogger("crc_checker")


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

    def to_json(self, file_path: str, source: str = "", mapping: str = "",
                sheets: list[str] | None = None) -> None:
        """Serialize DataIDMap to a standardized JSON file.

        Args:
            file_path: Output JSON file path.
            source: Original Excel file path (for traceability).
            mapping: Column mapping name used.
            sheets: Sheet names that were parsed.
        """
        data = {
            "format": "dataid_map_v1",
            "source": source,
            "mapping": mapping,
            "sheets": sheets or ([self.sheet_name] if self.sheet_name else []),
            "entries": [
                {"frame_id": f"0x{fid:03X}", "signal_name": sig, "dataid": f"0x{did:04X}"}
                for (fid, sig), did in sorted(self._map.items())
            ],
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, file_path: str) -> "DataIDMap":
        """Load a DataIDMap from a standardized JSON file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            DataIDMap with all entries loaded.

        Raises:
            ValueError: If the format version is unsupported.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fmt = data.get("format", "")
        if fmt != "dataid_map_v1":
            raise ValueError(
                f"Unsupported DataID JSON format: '{fmt}'. Expected 'dataid_map_v1'."
            )

        sheets = data.get("sheets", [])
        sheet_name = sheets[0] if sheets else ""
        result = cls(sheet_name=sheet_name)
        for entry in data.get("entries", []):
            fid = entry["frame_id"]
            did = entry["dataid"]
            if isinstance(fid, str):
                fid = int(fid, 16)
            if isinstance(did, str):
                did = int(did, 16)
            result.add(
                frame_id=fid,
                signal_name=entry["signal_name"],
                dataid=did,
            )
        return result

    def update(self, other: "DataIDMap") -> int:
        """Merge another DataIDMap into this one.

        Duplicate keys are overwritten by the other (last-wins).

        Returns:
            Number of entries overwritten.
        """
        overwritten = 0
        for key, value in other._map.items():
            if key in self._map:
                overwritten += 1
            self._map[key] = value
        return overwritten


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
    col_signal_name: int | str = 1   # Column index or header name for signal name
    col_message_id: int | str = 3    # Column index or header name for CAN ID
    col_dataid_hi: int | str = 12    # Column index or header name for DataID high byte
    col_dataid_lo: int | str = 13    # Column index or header name for DataID low byte
    dataid_format: str = "hi_lo_two_cols"
    data_row_start: int = 3          # 1-based row where data begins
    message_id_base: int = 16        # Radix for message ID parsing (16 = hex, 10 = decimal)
    signal_name_filter: list[str] | None = None
    use_header_names: bool = False   # If True, col_* fields are header names, not indices
    # Default filter: common checksum signal prefixes
    _DEFAULT_FILTER = ("checksum", "crc", "check_sum", "e2e_crc")

    def __post_init__(self):
        if self.signal_name_filter is None:
            self.signal_name_filter = list(self._DEFAULT_FILTER)

    def resolve_columns(self, header_row: list) -> "ColumnMapping":
        """Convert header names to column indices. Returns self if already index-based."""
        if not self.use_header_names:
            return self

        def _find(name: int | str) -> int:
            if isinstance(name, int):
                return name
            for i, cell in enumerate(header_row):
                if cell is not None and str(cell).strip().lower() == name.lower():
                    return i
            return -1

        return ColumnMapping(
            col_signal_name=_find(self.col_signal_name),
            col_message_id=_find(self.col_message_id),
            col_dataid_hi=_find(self.col_dataid_hi),
            col_dataid_lo=_find(self.col_dataid_lo),
            dataid_format=self.dataid_format,
            data_row_start=self.data_row_start,
            message_id_base=self.message_id_base,
            signal_name_filter=self.signal_name_filter,
            use_header_names=False,
        )


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


def _auto_detect_columns(mapping: ColumnMapping, header_row: list) -> ColumnMapping:
    """Auto-detect column positions from header names.

    Matches common header patterns (English, Chinese, mixed).
    Returns a new ColumnMapping with resolved indices.
    """
    if mapping.use_header_names:
        return mapping.resolve_columns(header_row)

    # Try to auto-locate columns by common header name patterns
    SIG_PATTERNS = [
        "checksum signal name", "signalname", "signal name",
        "signals", "checksumsignal", "e2e checksum",
    ]
    ID_PATTERNS = [
        "message id", "messageid", "msg id", "can id", "canid",
        "pdu id", "pduid", "arbitration id",
    ]
    HI_PATTERNS = [
        "dataid_hi", "data id hi", "dataid high",
        "data_id_hi", "data id (high byte)", "data_id (high byte)",
        "high byte of data id", "highbyte",
    ]
    LO_PATTERNS = [
        "dataid_lo", "data id lo", "dataid low",
        "data_id_lo", "data id (low byte)", "data_id (low byte)",
        "low byte of data id", "lowbyte",
    ]
    DID_COMBINED = [
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

    for i, cell in enumerate(header_row):
        if cell is None:
            continue
        s = str(cell).strip()
        if not s:
            continue
        if _match(s, SIG_PATTERNS):
            sig_col = i
        elif _match(s, ID_PATTERNS):
            id_col = i
        elif _match(s, DID_COMBINED):
            # Combined DataID column: Hi in this col, Lo in next
            hi_col = i
            lo_col = i + 1
        elif _match(s, HI_PATTERNS):
            hi_col = i
        elif _match(s, LO_PATTERNS):
            lo_col = i

    return ColumnMapping(
        col_signal_name=sig_col,
        col_message_id=id_col,
        col_dataid_hi=hi_col,
        col_dataid_lo=lo_col,
        dataid_format=mapping.dataid_format,
        data_row_start=mapping.data_row_start,
        message_id_base=mapping.message_id_base,
        signal_name_filter=mapping.signal_name_filter,
        use_header_names=False,
    )


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

    # Auto-detect columns from header row (row 1 or data_row_start - 1)
    header_row_num = 1 if mapping.data_row_start > 1 else None
    if header_row_num:
        header_row = list(ws.iter_rows(min_row=header_row_num, max_row=header_row_num, values_only=True))
        if header_row:
            mapping = _auto_detect_columns(mapping, header_row[0])

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


def match_sheet_to_dbc(dbc_name: str, sheet_names: list[str]) -> str | None:
    """Find the sheet name that best matches a DBC filename.

    Uses token matching + substring bonus.
    Returns the best-matching sheet, or None if no match.
    """
    import re

    def _weight(tok: str) -> float:
        # Alphabetic tokens are stronger signals than pure numbers
        if tok.isdigit():
            return 0.4
        return 1.0

    def _tokenize(name: str) -> tuple[set[str], str]:
        # Remove extension
        cleaned = re.sub(r'\.(dbc|xlsx)$', '', name, flags=re.IGNORECASE).lower()
        tokens = set()
        for part in re.split(r'[\s_\-\.]+', cleaned):
            part = part.strip()
            if part:
                tokens.add(part)
        return tokens, cleaned

    dbc_tokens, dbc_clean = _tokenize(dbc_name)
    if not dbc_tokens:
        return None

    best, best_score = None, -1.0
    for sname in sheet_names:
        sheet_tokens, sheet_clean = _tokenize(sname)
        # Exact token matches (primary)
        exact_set = dbc_tokens & sheet_tokens
        exact = sum(_weight(t) for t in exact_set)
        bonus = 0.0
        # Substring bonus: only for tokens >= 4 chars, not exact matches,
        # and not substrings of any token on the other side.
        for st in sheet_tokens:
            if len(st) >= 4 and st not in exact_set and st in dbc_clean:
                if not any(st in dt for dt in dbc_tokens if len(dt) > len(st)):
                    bonus += 0.3 * _weight(st)
        for dt in dbc_tokens:
            if len(dt) >= 4 and dt not in exact_set and dt in sheet_clean:
                if not any(dt in st for st in sheet_tokens if len(st) > len(dt)):
                    bonus += 0.3 * _weight(dt)
        score = exact + bonus
        if score > best_score:
            best, best_score = sname, score

    return best


def parse_dataid_xlsx_multi(xlsx_path: str,
                             sheet_names: list[str] | None = None,
                             mapping: ColumnMapping | str | None = None) -> DataIDMap:
    """Parse multiple sheets from a DataID Excel file and merge into one DataIDMap.

    Args:
        xlsx_path: Path to the .xlsx file.
        sheet_names: Sheet names to parse. If None, parse all sheets.
        mapping: ColumnMapping, builtin name, or JSON string.

    Returns:
        Merged DataIDMap with entries from all sheets.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    all_sheets = sheet_names if sheet_names else list(wb.sheetnames)
    wb.close()

    combined: DataIDMap | None = None
    parsed_sheets: list[str] = []

    for sname in all_sheets:
        try:
            dm = parse_dataid_xlsx(xlsx_path, sname, mapping=mapping)
            if len(dm) == 0:
                continue
            parsed_sheets.append(sname)
            if combined is None:
                combined = dm
            else:
                overwritten = combined.update(dm)
                if overwritten > 0:
                    logger.warning(
                        f"DataID sheet '{sname}': {overwritten} duplicate(s) overwritten"
                    )
        except ValueError:
            continue  # skip sheets that don't match

    if combined is not None:
        combined.sheet_name = ", ".join(parsed_sheets)
    return combined or DataIDMap()


# Backward-compatible alias
def parse_dataid_xlsx_legacy(xlsx_path: str, sheet_name: str | None = None) -> DataIDMap:
    """Original interface — uses greatwall_j6m column mapping."""
    return parse_dataid_xlsx(xlsx_path, sheet_name, mapping="greatwall_j6m")
