"""Backward-compatible DataID parser import surface.

Implementation is split across map models, column mappings, shared row
parsing, Excel readers, sheet matching, and multi-sheet merging. Keep public
and private helper imports here for existing ``crc_checker.dataid.parser``
callers.
"""

from crc_checker.dataid.models import DataIDMap, normalize_signal_key
from crc_checker.dataid.mappings import (
    BUILTIN_MAPPINGS,
    DEFAULT_MAPPING_NAME,
    DEFAULT_MAPPINGS_FILE,
    ColumnMapping,
    load_dataid_mappings,
    resolve_mapping,
)
from crc_checker.dataid.rows import (
    _add_dataid_row,
    _auto_detect_columns,
    _col_ref_to_index,
    _entry_names,
    _parse_dataid_value,
    _parse_message_id,
)
from crc_checker.dataid.excel import (
    _parse_description_regex,
    _parse_xls,
    _parse_xlsx_raw,
    get_sheet_names,
    get_xls_sheet_names,
    is_xls_file,
    logger,
    parse_dataid_xlsx,
)
from crc_checker.dataid.matching import match_sheet_to_dbc
from crc_checker.dataid.multi import parse_dataid_xlsx_legacy, parse_dataid_xlsx_multi

__all__ = [
    "logger",
    "BUILTIN_MAPPINGS",
    "ColumnMapping",
    "DataIDMap",
    "DEFAULT_MAPPING_NAME",
    "DEFAULT_MAPPINGS_FILE",
    "_add_dataid_row",
    "_auto_detect_columns",
    "_col_ref_to_index",
    "_entry_names",
    "_parse_dataid_value",
    "_parse_description_regex",
    "_parse_message_id",
    "_parse_xls",
    "_parse_xlsx_raw",
    "get_sheet_names",
    "get_xls_sheet_names",
    "is_xls_file",
    "load_dataid_mappings",
    "match_sheet_to_dbc",
    "normalize_signal_key",
    "parse_dataid_xlsx",
    "parse_dataid_xlsx_legacy",
    "parse_dataid_xlsx_multi",
    "resolve_mapping",
]
