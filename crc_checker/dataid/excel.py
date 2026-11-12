"""Excel workbook readers for DataID maps (.xlsx and legacy .xls)."""

# pylint: disable=import-outside-toplevel,consider-using-with,unused-import
from __future__ import annotations

import logging
import re

from crc_checker.dataid.mappings import ColumnMapping, resolve_mapping
from crc_checker.dataid.models import DataIDMap
from crc_checker.dataid.rows import (
    _add_dataid_row, _auto_detect_columns, _col_ref_to_index,
    _parse_message_id,
)

logger = logging.getLogger("crc_checker")


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _parse_xlsx_raw(xlsx_path: str, sheet_name: str,
                    mapping: ColumnMapping) -> DataIDMap:
    """Parse DataID Excel using raw zipfile+XML (no openpyxl).

    Falls back from openpyxl when the Excel file has incompatible styles.
    Supports .xlsx only (not .xls).
    """
    if mapping.dataid_format == "description_regex":
        # The message-list layout reads merged cells + free-text columns
        # through openpyxl; parsing it as hi/lo here would silently return
        # an empty (or garbage) map.
        raise ValueError(
            f"{xlsx_path}: the description_regex DataID layout requires a "
            "readable .xlsx (openpyxl); the raw fallback cannot parse it.")
    import zipfile
    import xml.etree.ElementTree as ET

    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

    with zipfile.ZipFile(xlsx_path) as z:
        # Parse shared strings
        ss_tree = None
        shared_strings: list[str] = []
        try:
            ss_tree = ET.parse(z.open('xl/sharedStrings.xml'))
            # One <si> element per string; a rich-text string spans several
            # <r>/<t> runs under the same <si>. Iterating <t> directly would
            # split rich-text cells into extra entries and shift every later
            # string index — concatenate each <si>'s runs instead.
            for si in ss_tree.findall('.//s:si', ns):
                texts = [t.text or '' for t in si.findall('.//s:t', ns)]
                shared_strings.append(''.join(texts))
        except KeyError:
            pass

        def _resolve_cell(cell_el) -> str | int | float | None:  # pylint: disable=too-many-return-statements
            """Resolve a cell element to its string/number value.

            Returns the same Python types ``openpyxl`` yields (str for shared /
            inline strings, int/float for numeric cells) so the raw fallback path
            parses numbers identically to the openpyxl path — a numeric cell held
            as text would otherwise be read as hex (int("616", 16) == 1558).
            """
            t = cell_el.get('t', '')
            v_el = cell_el.find('.//s:v', ns)
            is_el = cell_el.find('.//s:is', ns)
            if v_el is not None and v_el.text is not None:
                if t == 's':
                    idx = int(v_el.text)
                    if idx < len(shared_strings):
                        return shared_strings[idx]
                    return ''
                if t in ('b', 'e'):
                    # Boolean / error cell — not a DataID value.
                    return None
                # Numeric cell (t is '' or 'n' or 'str'): return a number.
                raw = v_el.text
                try:
                    return float(raw) if ('.' in raw or 'e' in raw.lower()) else int(raw)
                except ValueError:
                    return raw
            if is_el is not None:
                t_el = is_el.find('s:t', ns)
                return t_el.text if t_el is not None else ''
            return None

        # Find the correct sheet index
        wb_tree = ET.parse(z.open('xl/workbook.xml'))
        # Resolve the worksheet file through the workbook relationships. The
        # ``sheetId`` attribute is a stable workbook ID, not the file order:
        # after deleting/reordering sheets it can point at a different
        # ``sheetN.xml`` (or at a missing file). Relationship targets are
        # authoritative; fall back to sheetId/position for malformed packages.
        rel_ns = {
            'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        }
        targets: dict[str, str] = {}
        try:
            rels_tree = ET.parse(z.open('xl/_rels/workbook.xml.rels'))
            for rel in rels_tree.findall('.//r:Relationship', {
                    'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}):
                targets[rel.get('Id', '')] = rel.get('Target', '')
        except KeyError:
            pass

        sheet_idx = 0
        position = 0
        sheet_path = ""
        for s_el in wb_tree.findall('.//s:sheet', ns):
            position += 1
            if s_el.get('name', '') != sheet_name:
                continue
            target = targets.get(s_el.get(f'{{{rel_ns["r"]}}}id', ''), '')
            if target:
                sheet_path = target.lstrip('/')
                if not sheet_path.startswith('xl/'):
                    sheet_path = f'xl/{sheet_path}'
            else:
                # Fallback: sheetId is 1-based for well-formed workbooks.
                sheet_idx = int(s_el.get('sheetId', position))
                sheet_path = f'xl/worksheets/sheet{sheet_idx}.xml'
            break

        if not sheet_path:
            raise ValueError(f"Sheet '{sheet_name}' not found in {xlsx_path}")

        # Parse sheet data
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

            row = [cell_values.get(i) for i in range(max_col + 1)]
            _add_dataid_row(row, mapping, dataid_map)

        return dataid_map


# pylint: disable=unused-argument
def _parse_description_regex(ws, mapping, dataid_map, sheet_name, wb) -> DataIDMap:
    """Parse message-list Excel where DataID is in a description column.

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

        # Track current message ID and name (inherited from parent row).
        # Use the shared parser so numeric cells ("301") and string forms
        # ("0x100", "100" in message_id_base) all work; the old check only
        # accepted "0x…" strings and silently inherited the previous ID.
        msg_id_raw = row[mapping.col_message_id]
        if msg_id_raw is not None and str(msg_id_raw).strip():
            parsed_id = _parse_message_id(msg_id_raw, mapping.message_id_base)
            if parsed_id is not None:
                current_msg_id = parsed_id

        # Column D (index 3) typically contains the message name in this layout
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


def is_xls_file(path: str) -> bool:
    """True for legacy BIFF .xls files (OLE2 compound document magic)."""
    try:
        with open(path, "rb") as f:
            return f.read(8) == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
    except OSError:
        return False


def get_xls_sheet_names(path: str) -> list[str]:
    """Sheet names of a legacy .xls workbook (requires xlrd)."""
    import xlrd
    return list(xlrd.open_workbook(path).sheet_names())


def get_sheet_names(path: str) -> list[str]:
    """Sheet names of an .xlsx or .xls workbook."""
    if is_xls_file(path):
        return get_xls_sheet_names(path)
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as zf:
        wb_tree = ET.parse(zf.open('xl/workbook.xml'))
        return [s.get('name', '') for s in wb_tree.findall('.//s:sheet', ns)]


def _parse_xls(xls_path: str, sheet_name: str, mapping: ColumnMapping) -> DataIDMap:
    """Parse a legacy BIFF (.xls) DataID workbook via xlrd.

    Same column mapping as the .xlsx path — some suppliers ship their
    E2E DataID configuration only as legacy .xls.
    """
    if mapping.dataid_format == "description_regex":
        # The message-list layout reads merged cells + free-text columns
        # through openpyxl; parsing it as hi/lo here would silently return
        # an empty (or garbage) map.
        raise ValueError(
            f"'{xls_path}': the description_regex DataID layout requires an "
            ".xlsx workbook (openpyxl). Convert the file to .xlsx.")
    import xlrd
    book = xlrd.open_workbook(xls_path)
    if sheet_name not in book.sheet_names():
        available = ", ".join(book.sheet_names())
        raise ValueError(f"Sheet '{sheet_name}' not found. Available: {available}")

    sheet = book.sheet_by_name(sheet_name)
    rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]

    # Auto-detect columns from the header row (same rule as the xlsx paths)
    header_row_num = mapping.data_row_start - 1 if mapping.data_row_start > 1 else 1
    if header_row_num and header_row_num <= len(rows):
        mapping = _auto_detect_columns(mapping, rows[header_row_num - 1])

    dataid_map = DataIDMap(sheet_name=sheet_name)
    for row in rows[mapping.data_row_start - 1:]:
        _add_dataid_row(row, mapping, dataid_map)
    return dataid_map


def parse_dataid_xlsx(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        xlsx_path: str,
        sheet_name: str | None = None,
        mapping: ColumnMapping | str | None = None) -> DataIDMap:
    """Parse a DataID Excel file and return a DataIDMap.

    Args:
        xlsx_path: Path to the .xlsx file.
        sheet_name: Sheet name to read. If None, uses the first sheet.
        mapping: ColumnMapping instance, a name from
                 ``crc_checker/data/dataid_mappings.yaml``, or a JSON object
                 defining a custom ColumnMapping. ``None`` uses
                 ``hi_lo_two_cols``.

    Returns:
        DataIDMap with all parsed entries.
    """
    mapping = resolve_mapping(mapping)

    # Legacy BIFF .xls workbooks go through xlrd
    if is_xls_file(xlsx_path):
        if sheet_name is None:
            names = get_xls_sheet_names(xlsx_path)
            sheet_name = names[0] if names else "Sheet1"
        return _parse_xls(xlsx_path, sheet_name, mapping)

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

    # ── description_regex format: message-list layout ──
    if mapping.dataid_format == "description_regex":
        return _parse_description_regex(ws, mapping, dataid_map, sheet_name, wb)

    # Auto-detect columns from the header row (one row above data_row_start,
    # matching the raw-xlsx and .xls paths). Scanning row 1 unconditionally let
    # a title row hijack the Hi/Lo detection and dropped every entry.
    header_row_num = mapping.data_row_start - 1 if mapping.data_row_start > 1 else None
    if header_row_num:
        header_row = list(ws.iter_rows(
            min_row=header_row_num, max_row=header_row_num, values_only=True))
        if header_row:
            mapping = _auto_detect_columns(mapping, header_row[0])

    for row in ws.iter_rows(min_row=mapping.data_row_start, values_only=True):
        if not row:
            continue
        _add_dataid_row(list(row), mapping, dataid_map)

    wb.close()
    return dataid_map
