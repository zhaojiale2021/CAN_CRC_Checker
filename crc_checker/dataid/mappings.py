"""Configurable Excel column mappings for DataID workbooks."""

from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache
import json
from pathlib import Path

import yaml


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
    dataid_base: int = 16            # Radix for TEXT DataID cells (16 = hex, 10 = decimal)
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
            dataid_base=self.dataid_base,
            signal_name_filter=self.signal_name_filter,
            use_header_names=False,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "ColumnMapping":
        """Build a mapping from a dict (YAML entry or ``dataid.mapping`` JSON)."""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(
                f"Unknown ColumnMapping field(s): {', '.join(unknown)}")
        return cls(**data)


# Default column layouts live in ``crc_checker/data/dataid_mappings.yaml`` so a
# new workbook format is a configuration change, not a code change.
DEFAULT_MAPPINGS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "dataid_mappings.yaml")
DEFAULT_MAPPING_NAME = "hi_lo_two_cols"


@lru_cache(maxsize=16)
def load_dataid_mappings(path: str | Path | None = None) -> dict[str, ColumnMapping]:
    """Load named column mappings from a YAML file (default: packaged file)."""
    source = Path(path) if path else DEFAULT_MAPPINGS_FILE
    if not source.is_file():
        if path:
            raise FileNotFoundError(f"DataID mapping file not found: {source}")
        # Minimal fallback so a stripped install still parses the default layout.
        return {DEFAULT_MAPPING_NAME: ColumnMapping()}
    with open(source, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    entries = data.get("mappings") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise ValueError(f"DataID mapping file has no 'mappings' map: {source}")
    mappings: dict[str, ColumnMapping] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError(f"DataID mapping {name!r} must be a mapping")
        mappings[str(name)] = ColumnMapping.from_dict(entry)
    return mappings


# Kept for callers that imported the name; loaded from the YAML file.
BUILTIN_MAPPINGS = load_dataid_mappings()


def resolve_mapping(mapping: ColumnMapping | str | dict | None) -> ColumnMapping:
    """Resolve a mapping name / JSON string / dict / instance to a ColumnMapping."""
    if isinstance(mapping, ColumnMapping):
        return mapping
    if isinstance(mapping, dict):
        # ``dataid.mapping`` documents "name ... or JSON object"; a dict used
        # to reach ``mapping in BUILTIN_MAPPINGS`` and raise TypeError.
        return ColumnMapping.from_dict(mapping)
    if mapping is None:
        return BUILTIN_MAPPINGS[DEFAULT_MAPPING_NAME]
    if mapping in BUILTIN_MAPPINGS:
        return BUILTIN_MAPPINGS[mapping]
    try:
        return ColumnMapping.from_dict(json.loads(mapping))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Unknown mapping '{mapping}'. Available: "
            f"{', '.join(sorted(BUILTIN_MAPPINGS))}. Or pass a JSON object "
            f"with ColumnMapping fields. Error: {exc}"
        ) from exc
