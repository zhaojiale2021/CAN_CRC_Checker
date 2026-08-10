"""DataID Excel parser — extracts DataID mappings for E2E protection groups.

The Excel file maps (MessageID, ChecksumSignalName) → 16-bit DataID.
DataID is prepended to payload data before CRC calculation per AUTOSAR E2E spec.

## Extensibility for different Excel formats

Different OEMs/suppliers use different Excel layouts for DataID tables.
Use `ColumnMapping` to configure column indices and data format without
modifying this module. Built-in presets cover common formats; custom
mappings can be passed via CLI (`--dataid-columns` JSON) or programmatically.
"""
# pylint: disable=import-outside-toplevel
# pylint: disable=consider-using-with

from __future__ import annotations
from dataclasses import dataclass
import json
import logging
import re

logger = logging.getLogger("crc_checker")


class DataIDMap:
    """Maps (frame_id, checksum_signal_name) → 16-bit DataID value.

    Also stores optional profile info per entry (e.g. "Profile 1A" for GAC EEA4).
    """

    def __init__(self, sheet_name: str = ""):
        self.sheet_name = sheet_name
        self._map: dict[tuple[int, str], int] = {}  # (frame_id, signal_name) → dataid
        self._profiles: dict[tuple[int, str], str] = {}  # (frame_id, signal_name) → profile
        self._frame_names: dict[tuple[int, str], str] = {}  # (frame_id, signal_name) → msg name

    def add(self, frame_id: int, signal_name: str, dataid: int, profile: str = ""):
        """Register a DataID for a specific checksum signal.

        Args:
            frame_id: CAN arbitration ID.
            signal_name: Signal name from DBC (checksum or message name).
            dataid: 16-bit DataID value.
            profile: Optional profile hint (e.g. "Profile 1A", "Profile 5").
        """
        self._map[(frame_id, signal_name)] = dataid
        if profile:
            self._profiles[(frame_id, signal_name)] = profile

    def get(self, frame_id: int, signal_name: str) -> int | None:
        """Get DataID for a frame/signal pair, or None if not found."""
        return self._map.get((frame_id, signal_name))

    def get_profile(self, frame_id: int, signal_name: str) -> str | None:
        """Get profile hint for a frame/signal pair, or None."""
        return self._profiles.get((frame_id, signal_name))

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
        entries = []
        for (fid, sig), did in sorted(self._map.items()):
            entry = {
                "frame_id": f"0x{fid:03X}",
                "dataid": f"0x{did:04X}",
            }
            if sig:
                entry["signal_name"] = sig
            profile = self._profiles.get((fid, sig), "")
            if profile:
                entry["profile"] = profile
            frame_name = self._frame_names.get((fid, sig), "")
            if frame_name:
                entry["frame_name"] = frame_name
            entries.append(entry)
        data = {
            "format": "dataid_map_v2",
            "source": source,
            "mapping": mapping,
            "sheets": sheets or ([self.sheet_name] if self.sheet_name else []),
            "entries": entries,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, file_path: str) -> "DataIDMap":
        """Load a DataIDMap from a standardized JSON file.

        Supports v1 and v2 formats.

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
        if fmt not in ("dataid_map_v1", "dataid_map_v2"):
            raise ValueError(
                f"Unsupported DataID JSON format: '{fmt}'. "
                f"Expected 'dataid_map_v1' or 'dataid_map_v2'."
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
                signal_name=entry.get("signal_name", ""),
                dataid=did,
                profile=entry.get("profile", ""),
            )
            # Store frame_name if present (v2)
            fname = entry.get("frame_name", "")
            if fname:
                key = (fid, entry.get("signal_name", ""))
                result._frame_names[key] = fname
        return result

    def update(self, other: "DataIDMap") -> int:
        """Merge another DataIDMap into this one.

        Duplicate keys are overwritten by the other (last-wins).

        Returns:
            Number of entries overwritten.
        """
        overwritten = 0
        for key, value in other._map.items():  # pylint: disable=protected-access
            if key in self._map:
                overwritten += 1
            self._map[key] = value
        # Merge profiles and frame names
        for key, profile in other._profiles.items():  # pylint: disable=protected-access
            if profile:
                self._profiles[key] = profile
        for key, fname in other._frame_names.items():  # pylint: disable=protected-access
            if fname:
                self._frame_names[key] = fname
        return overwritten


# ---------------------------------------------------------------------------
# Column mapping — defines where each piece of data lives in the Excel sheet
# ---------------------------------------------------------------------------

@dataclass
class ColumnMapping:  # pylint: disable=too-many-instance-attributes
    """Defines the Excel column layout for DataID extraction.

    Each field is a 0-based column index. Set to -1 to skip that field.
    `dataid_format` controls how the DataID bytes are interpreted:
      - "hi_lo_two_cols" : High byte in one column, Low byte in another (default)
      - "single_16bit"   : Single column with 16-bit hex value (e.g. "0x0054")
      - "single_8bit"    : Single column with 8-bit value (use 0 for high byte)
      - "two_cols_lsb_first" : Like hi_lo but low byte comes first

    `data_row_start` is the 1-based row number where data begins (after headers).
    `signal_name_filter` is a list of keywords used to identify checksum rows.
      Signal names are matched case-insensitively by substring (e.g. "checksum"
      matches both ``Checksum_RSDS_R_2`` and ``RSDS_L_SGU1_Checksum1``).
      Set to None to accept all rows that have a DataID value.
    `col_remark` is an optional column for remarks (e.g. profile info).
    """
    col_signal_name: int | str = 1   # Column index or header name for signal name
    col_message_id: int | str = 3    # Column index or header name for CAN ID
    col_dataid_hi: int | str = 12    # Column index or header name for DataID high byte
    col_dataid_lo: int | str = 13    # Column index or header name for DataID low byte
    col_remark: int | str = -1       # Optional: column for remark/profile info
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
        # Empty list [] means accept all rows — don't replace with default

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
            col_remark=_find(self.col_remark),
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
    # GAC EEA4 E2E DataID format
    # Columns: C=MsgName, D=MsgID(hex), E=DataID(16bit hex), F=Remark(Profile info)
    # Header in row 2, data starts at row 3
    "gac_eea4": ColumnMapping(
        col_signal_name=2,
        col_message_id=3,
        col_dataid_hi=4,       # single_16bit: DataID in one column
        col_dataid_lo=-1,      # unused
        col_remark=5,          # Remark column (Profile 1A markers)
        dataid_format="single_16bit",
        data_row_start=3,
        message_id_base=16,
        signal_name_filter=[],  # Empty → accept all rows (GAC uses msg names, not CRC sig names)
    ),
    # Chery T1JFL3 message-list format
    # Each SIGNAL is a row; Message ID (col A) inherited from parent rows
    # DataID extracted from Signal Description (col AD) via regex
    # Columns: A=MsgID, L=SignalName, AD=SignalDescription
    "chery_t1jfl3": ColumnMapping(
        col_signal_name=11,      # Column L: Signal Name
        col_message_id=0,        # Column A: Msg ID (present on first row only)
        col_dataid_hi=29,        # Column AD: Signal Description (DataID extracted by regex)
        col_dataid_lo=-1,        # unused
        col_remark=29,           # Same column for profile extraction
        dataid_format="description_regex",
        data_row_start=1,
        message_id_base=16,
        signal_name_filter=[],   # Accept all rows; DataID regex handles filtering
        use_header_names=False,
    ),
}


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
    # (e.g. "Message Name" in GWM Excel's duplicate column group K-L)
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
        elif _match(s, did_combined):
            # Combined DataID column: Hi in this col, Lo in next
            hi_col = i
            lo_col = i + 1
        elif _match(s, hi_patterns):
            hi_col = i
        elif _match(s, lo_patterns):
            lo_col = i

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
        elif _match(s, did_combined):
            # Combined DataID column: Hi in this col, Lo in next
            hi_col = i
            lo_col = i + 1
        elif _match(s, hi_patterns):
            hi_col = i
        elif _match(s, lo_patterns):
            lo_col = i
        elif _match(s, ["remark", "remarks", "comment", "comments", "profile", "note"]):
            remark_col = i

    return ColumnMapping(
        col_signal_name=sig_col,
        col_message_id=id_col,
        col_dataid_hi=hi_col,
        col_dataid_lo=lo_col,
        col_remark=remark_col,
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


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _parse_xlsx_raw(xlsx_path: str, sheet_name: str,
                    mapping: ColumnMapping) -> DataIDMap:
    """Parse DataID Excel using raw zipfile+XML (no openpyxl).

    Falls back from openpyxl when the Excel file has incompatible styles.
    Supports .xlsx only (not .xls).
    """
    import zipfile
    import xml.etree.ElementTree as ET

    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

    with zipfile.ZipFile(xlsx_path) as z:
        # Parse shared strings
        ss_tree = None
        shared_strings: list[str] = []
        try:
            ss_tree = ET.parse(z.open('xl/sharedStrings.xml'))
            for si in ss_tree.findall('.//s:t', ns):
                shared_strings.append(si.text or '')
        except KeyError:
            pass

        def _resolve_cell(cell_el) -> str | None:
            """Resolve a cell element to its string/number value."""
            t = cell_el.get('t', '')
            v_el = cell_el.find('.//s:v', ns)
            is_el = cell_el.find('.//s:is', ns)
            if v_el is not None and v_el.text is not None:
                if t == 's':
                    idx = int(v_el.text)
                    if idx < len(shared_strings):
                        return shared_strings[idx]
                    return ''
                return v_el.text
            if is_el is not None:
                t_el = is_el.find('s:t', ns)
                return t_el.text if t_el is not None else ''
            return None

        # Find the correct sheet index
        wb_tree = ET.parse(z.open('xl/workbook.xml'))
        sheet_idx = 0
        for s_el in wb_tree.findall('.//s:sheet', ns):
            name = s_el.get('name', '')
            if name == sheet_name:
                # sheetId is 1-based, sheet files are 1-based
                sheet_idx_str = s_el.get('sheetId', '1')
                sheet_idx = int(sheet_idx_str)
                break
        if sheet_idx == 0:
            # Fallback: try match by position
            sheets_list = wb_tree.findall('.//s:sheet', ns)
            for i, s_el in enumerate(sheets_list):
                if s_el.get('name', '') == sheet_name:
                    sheet_idx = i + 1
                    break

        # Parse sheet data
        sheet_path = f'xl/worksheets/sheet{sheet_idx}.xml'
        try:
            sheet_tree = ET.parse(z.open(sheet_path))
        except KeyError:
            raise ValueError(f"Sheet '{sheet_name}' not found in {xlsx_path}") from None

        dataid_map = DataIDMap(sheet_name=sheet_name)

        # Parse header row for auto-detection
        # Header is typically data_row_start - 1 (e.g. row 2 when data starts at row 3)
        header_row_num = mapping.data_row_start - 1 if mapping.data_row_start > 1 else 1
        header_row_data: list = []
        for row_el in sheet_tree.findall('.//s:row', ns):
            row_num = int(row_el.get('r', '0'))
            if row_num == header_row_num:
                # Build header row from cells
                max_col = 0
                cell_values: dict[int, str | None] = {}
                for c_el in row_el.findall('s:c', ns):
                    col_idx = _col_ref_to_index(c_el.get('r', ''))
                    val = _resolve_cell(c_el)
                    cell_values[col_idx] = val
                    max_col = max(max_col, col_idx)
                header_row_data = [cell_values.get(i, '') for i in range(max_col + 1)]
                mapping = _auto_detect_columns(mapping, header_row_data)
                break  # header row found, stop scanning

        # Parse data rows
        for row_el in sheet_tree.findall('.//s:row', ns):
            row_num = int(row_el.get('r', '0'))
            if row_num < mapping.data_row_start:
                continue

            max_col = 0
            cell_values: dict[int, str | None] = {}
            for c_el in row_el.findall('s:c', ns):
                col_idx = _col_ref_to_index(c_el.get('r', ''))
                val = _resolve_cell(c_el)
                cell_values[col_idx] = val
                max_col = max(max_col, col_idx)

            # Extract values using column mapping
            max_col_needed = max(
                mapping.col_signal_name,
                mapping.col_message_id,
                mapping.col_dataid_hi,
                mapping.col_dataid_lo if mapping.col_dataid_lo >= 0 else 0,
                mapping.col_remark if mapping.col_remark >= 0 else 0,
            )
            if max_col < max_col_needed:
                continue

            signal_name = cell_values.get(mapping.col_signal_name)
            message_id_str = cell_values.get(mapping.col_message_id)
            dataid_hi = cell_values.get(mapping.col_dataid_hi)
            dataid_lo = cell_values.get(
                mapping.col_dataid_lo) if mapping.col_dataid_lo >= 0 else None

            # Skip header/sub-header rows
            if dataid_hi is None and dataid_lo is None:
                continue
            if isinstance(dataid_hi, str) and dataid_hi.lower() in (
                "high_byte", "dataid", "data_id", "data id"):
                continue
            if not isinstance(signal_name, str):
                continue

            # Filter by signal name keyword (supports both prefix and suffix naming)
            if mapping.signal_name_filter:
                name_lower = signal_name.lower()
                if not any(pfx in name_lower
                          for pfx in mapping.signal_name_filter):
                    continue

            # Parse message ID
            try:
                msg_id_raw = message_id_str.strip() if message_id_str else ""
                if msg_id_raw.startswith("0x") or msg_id_raw.startswith("0X"):
                    frame_id = int(msg_id_raw, 16)
                elif all(c in '0123456789abcdefABCDEF' for c in msg_id_raw):
                    # Pure hex without 0x prefix
                    frame_id = int(msg_id_raw, mapping.message_id_base)
                else:
                    continue
            except (ValueError, TypeError):
                continue

            # Parse DataID
            dataid = _parse_dataid_value(dataid_hi, dataid_lo, mapping.dataid_format)
            if dataid is not None:
                # Parse remark for profile info
                profile = ""
                remark_col = getattr(mapping, 'col_remark', -1)
                if remark_col >= 0:
                    remark_val = cell_values.get(remark_col)
                    if remark_val and isinstance(remark_val, str):
                        remark_val = remark_val.strip()
                        if "profile" in remark_val.lower():
                            profile = remark_val
                dataid_map.add(frame_id, signal_name, dataid, profile)

        return dataid_map


# pylint: disable=unused-argument
def _parse_description_regex(ws, mapping, dataid_map, sheet_name, wb) -> DataIDMap:
    """Parse Chery-style message-list Excel where DataID is in a description column.

    Each signal is a row. Message ID and Message Name only appear on
    the first signal row of each message; subsequent rows inherit them.
    DataID is extracted from the description column (mapping.col_dataid_hi)
    using regex: DataID:0xXXXX.
    """
    current_msg_id = None
    current_msg_name = ""

    for row in ws.iter_rows(min_row=mapping.data_row_start, values_only=True):
        if not row:
            continue

        max_col = max(mapping.col_message_id, mapping.col_signal_name,
                      mapping.col_dataid_hi)
        if len(row) <= max_col:
            continue

        # Track current message ID and name (inherited from parent row)
        msg_id_raw = row[mapping.col_message_id]
        if msg_id_raw is not None:
            msg_id_str = str(msg_id_raw).strip()
            if msg_id_str.lower().startswith("0x"):
                try:
                    current_msg_id = int(msg_id_str, 16)
                except ValueError:
                    pass

        # Column D (index 3) typically contains the message name in Chery format
        if len(row) > 3 and row[3] is not None:
            msg_name = str(row[3]).strip()
            if msg_name:
                current_msg_name = msg_name

        if current_msg_id is None:
            continue

        signal_name = row[mapping.col_signal_name]
        if not isinstance(signal_name, str) or not signal_name.strip():
            continue

        # Filter by signal name keyword (supports both prefix and suffix naming)
        if mapping.signal_name_filter:
            name_lower = signal_name.lower()
            if not any(pfx in name_lower for pfx in mapping.signal_name_filter):
                continue

        # Extract DataID from description column using regex
        desc_col = mapping.col_dataid_hi
        if len(row) > desc_col and row[desc_col] is not None:
            desc = str(row[desc_col])
            did_match = re.search(r'DataID:?\s*(0x[0-9A-Fa-f]+)', desc, re.IGNORECASE)
            profile_match = re.search(r'(Profile\s*[0-9A-Za-z]+)', desc, re.IGNORECASE)

            if did_match and 'No AS' not in desc.rsplit('DataID:', 1)[-1][:30]:
                did_val = int(did_match.group(1), 16)
                profile = profile_match.group(1).replace(' ', '') if profile_match else ''
                dataid_map.add(current_msg_id, signal_name, did_val, profile)
                # Store frame_name if available
                if current_msg_name:
                    key = (current_msg_id, signal_name)
                    # pylint: disable=protected-access
                    dataid_map._frame_names[key] = current_msg_name

    wb.close()
    return dataid_map


def parse_dataid_xlsx(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        xlsx_path: str,
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
                ) from e

    # Determine sheet name if not provided
    if sheet_name is None:
        # Quick check via raw zip to find sheet names (avoids openpyxl)
        import zipfile
        import xml.etree.ElementTree as ET
        ns_s = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        # pylint: disable=consider-using-with
        with zipfile.ZipFile(xlsx_path) as zf:
            wb_tree = ET.parse(zf.open('xl/workbook.xml'))
            sheets = wb_tree.findall('.//s:sheet', ns_s)
            sheet_name = sheets[0].get('name', '') if sheets else "Sheet1"

    # Try openpyxl first, fall back to raw zipfile parsing
    import openpyxl  # pylint: disable=import-outside-toplevel
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    except (TypeError, KeyError, AttributeError) as e:
        logger.warning(
            "openpyxl failed to load '%s' (%s), falling back to raw parser",
            xlsx_path, e)
        return _parse_xlsx_raw(xlsx_path, sheet_name, mapping)

    if sheet_name not in wb.sheetnames:
        available = ", ".join(wb.sheetnames)
        wb.close()
        raise ValueError(f"Sheet '{sheet_name}' not found. Available: {available}")

    ws = wb[sheet_name]
    dataid_map = DataIDMap(sheet_name=sheet_name)

    # ── description_regex format: Chery message-list layout ──
    if mapping.dataid_format == "description_regex":
        return _parse_description_regex(ws, mapping, dataid_map, sheet_name, wb)

    # Auto-detect columns from header row (row 1 by default)
    header_row_num = 1 if mapping.data_row_start > 1 else None
    if header_row_num:
        header_row = list(ws.iter_rows(
            min_row=header_row_num, max_row=header_row_num, values_only=True))
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
            mapping.col_remark if mapping.col_remark >= 0 else 0,
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

        # Filter by signal name keyword (supports both prefix and suffix naming)
        if mapping.signal_name_filter:
            name_lower = signal_name.lower()
            if not any(pfx in name_lower for pfx in mapping.signal_name_filter):
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
            # Parse remark for profile info
            profile = ""
            remark_col = getattr(mapping, 'col_remark', -1)
            if 0 <= remark_col < len(row):
                remark_val = row[remark_col]
                if remark_val and isinstance(remark_val, str):
                    remark_val = remark_val.strip()
                    if "profile" in remark_val.lower():
                        profile = remark_val
            dataid_map.add(frame_id, signal_name, dataid, profile)

    wb.close()
    return dataid_map


def match_sheet_to_dbc(dbc_name: str, sheet_names: list[str]) -> str | None:  # pylint: disable=too-many-locals
    """Find the sheet name that best matches a DBC filename.

    Uses token matching + substring bonus.
    Returns the best-matching sheet, or None if no match.

    Fallback: if no token matches, prefers sheets containing "Config"
    over "History" / "Revision".
    """

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

    # Fallback: if no token match, prefer sheets containing "Config" over "History"
    if best_score <= 0:
        for sname in sheet_names:
            sname_lower = sname.lower()
            if "config" in sname_lower and "history" not in sname_lower:
                return sname
        # Last resort: first sheet that's not "History"/"Revision"
        for sname in sheet_names:
            sname_lower = sname.lower()
            if "history" not in sname_lower and "revision" not in sname_lower:
                return sname

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
    # pylint: disable=import-outside-toplevel
    import zipfile
    import xml.etree.ElementTree as ET

    # Get sheet names via raw zipfile (avoids openpyxl)
    ns_s = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    # pylint: disable=consider-using-with
    with zipfile.ZipFile(xlsx_path) as zf:
        wb_tree = ET.parse(zf.open('xl/workbook.xml'))
        all_sheets = [s.get('name', '') for s in wb_tree.findall('.//s:sheet', ns_s)]

    if sheet_names:
        all_sheets = [s for s in all_sheets if s in sheet_names]
        if not all_sheets:
            all_sheets = sheet_names  # try as-is, let downstream fail

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
                        "DataID sheet '%s': %s duplicate(s) overwritten",
                        sname, overwritten,
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
