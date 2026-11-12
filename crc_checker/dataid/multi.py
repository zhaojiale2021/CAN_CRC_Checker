"""Parse and merge DataID maps across workbook sheets."""

from __future__ import annotations

import logging

from crc_checker.dataid.excel import get_sheet_names, parse_dataid_xlsx
from crc_checker.dataid.mappings import DEFAULT_MAPPING_NAME, ColumnMapping
from crc_checker.dataid.models import DataIDMap

logger = logging.getLogger("crc_checker")


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
    # Get sheet names (handles both .xlsx and legacy .xls)
    existing_sheets = get_sheet_names(xlsx_path)

    if sheet_names:
        missing = [s for s in sheet_names if s not in existing_sheets]
        all_sheets = [s for s in sheet_names if s in existing_sheets]
        if not all_sheets:
            # A typo in dataid.sheet used to parse nothing and return an empty
            # map silently, disabling every DataID (CRC then failed on every
            # frame). Fail loudly instead.
            raise ValueError(
                f"Sheet(s) not found: {', '.join(missing)}. "
                f"Available: {', '.join(existing_sheets)}")
        if missing:
            logger.warning("DataID sheet(s) not found, skipped: %s",
                           ", ".join(missing))
    else:
        all_sheets = existing_sheets

    combined: DataIDMap | None = None
    parsed_sheets: list[str] = []

    for sname in all_sheets:
        try:
            dm = parse_dataid_xlsx(xlsx_path, sname, mapping=mapping)
        except ValueError as exc:
            # A sheet exists but uses a different layout; keep the others but
            # say so instead of silently dropping it.
            logger.warning("DataID sheet '%s' skipped: %s", sname, exc)
            continue
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

    if combined is not None:
        combined.sheet_name = ", ".join(parsed_sheets)
    return combined or DataIDMap()


# Backward-compatible alias
def parse_dataid_xlsx_legacy(xlsx_path: str, sheet_name: str | None = None) -> DataIDMap:
    """Original interface — uses the default column mapping."""
    return parse_dataid_xlsx(xlsx_path, sheet_name, mapping=DEFAULT_MAPPING_NAME)
