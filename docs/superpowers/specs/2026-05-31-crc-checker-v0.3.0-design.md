# CAN CRC Checker — Multi-DBC, DataID Preprocess, HTML Report Fix

**Date**: 2026-05-31
**Status**: Approved
**Project**: `crc_check`
**Parent**: [2026-05-30-crc-checker-design.md](2026-05-30-crc-checker-design.md)

## Overview

Three features for v0.3.0:

1. **Multi-DBC support** — Accept a directory of `.dbc` files; merge all into one `DBCProtectionMap` with first-match-wins semantics
2. **DataID preprocessing** — Export parsed DataID mappings to a standardized JSON format for fast reload; auto-generate on first run
3. **HTML report fixes** — PASS signals show green highlights in hex-dump; all-PASS frames expanded by default; frame name bold like CAN ID

---

## Feature 1: Multi-DBC Support (Directory Mode)

### Current State

`RunConfig.dbc: str` — single `.dbc` file path. `DBCParser.parse()` takes one file.

### New Behavior

`RunConfig.dbc` accepts:
- A single `.dbc` file path (existing behavior, backward compatible)
- A directory path — recursively (or top-level) collects all `*.dbc` files
- An array via the new `dbcs` field in JSON config

### Merge Strategy

Independent mapping, first-match-wins:
1. DBC files sorted alphabetically by filename
2. Parse each DBC sequentially into its own `DBCProtectionMap`
3. Merge into a combined map — if a `frame_id` already exists from a prior DBC, skip it (the first DBC that defines a frame wins)
4. Log a warning (verbose mode) when a frame_id conflict is skipped

### Data Model Changes

**`RunConfig`** (`config.py`):
- `dbc: str` → keeps working for single file or directory path
- NEW `dbcs: list[str]` — explicit list of DBC paths (files or directories)
- `resolve_paths()` handles directory expansion: if a path is a directory, `glob("*.dbc")` and add all results

**`DBCProtectionMap`** (`dbc/models.py`):
- `dbc_path: str` → `dbc_paths: list[str]`
- NEW `merge(other: DBCProtectionMap) -> int` — merge another map, skip existing frame_ids, return count of skipped conflicts

**`DBCParser`** (`dbc/parser.py`):
- NEW `parse_multiple(paths: list[str]) -> DBCProtectionMap` — calls `parse()` for each and merges

**`VerifyReport`** (`verify/models.py`):
- `dbc_path: str` → keep for backward compat (joined display string of all DBC paths)
- NEW `dbc_paths: list[str]` — list of all DBC source files

### Config JSON Format

```json
{
  "dbc": "dbc/",                         // directory → all *.dbc inside
  "dbcs": ["dbc/adas.dbc", "dbc/gw.dbc"] // explicit list (optional, merged with dbc)
}
```

Backward compat: `"dbc": "path/to/single.dbc"` still works exactly as before.

### CLI Changes

`crc-check verify --dbc` currently accepts a single path. Change to `multiple=True` so it can be repeated, and also accept directories:

```
--dbc PATH  (repeatable, each can be a file or directory)
```

### Edge Cases

- Empty directory (no `.dbc` files): error, "No .dbc files found in <dir>"
- Duplicate frame_id across DBCs: first wins, verbose log shows which DBC supplied it
- DBC with no protection signals: merged silently, contributes no entries

---

## Feature 2: DataID Preprocessing

### Current State

Every run parses Excel via `openpyxl` — slow for large sheets, and requires the Excel file to be present. `parse_dataid_xlsx()` reads directly from `.xlsx`.

### New Behavior

Two-phase workflow:

**Phase 1 — Preprocess** (manual or automatic):
1. Parse Excel with `openpyxl` + `ColumnMapping`
2. Export to standardized JSON via `DataIDMap.to_json(path)`

**Phase 2 — Fast load** (subsequent runs):
1. Load from JSON via `DataIDMap.from_json(path)`
2. Skip `openpyxl` entirely

**Auto mode**: If `dataid_json` is specified but the file doesn't exist, and `dataid_xlsx` is provided, auto-generate the JSON on first run, then use it.

### DataIDMap JSON Format

```json
{
  "format": "dataid_map_v1",
  "source": "dbc/长城J6M_E2E 算法之data id _V2.5.xlsx",
  "mapping": "greatwall_j6m",
  "sheets": ["DBC_V2.5 ADAS1", "DBC_V2.5 ADAS2"],
  "entries": [
    {"frame_id": 323, "signal_name": "Checksum_ACC1", "dataid": 84},
    {"frame_id": 665, "signal_name": "Checksum_IFC2", "dataid": 85}
  ]
}
```

- `entries` is the union of all sheets — flat list, no per-sheet grouping needed at runtime
- `format` field for future version detection
- `source`, `mapping`, `sheets` are metadata for traceability only

### Data Model Changes

**`DataIDMap`** (`dataid/parser.py`):
- NEW `to_json(file_path: str) -> None` — serialize to JSON
- NEW `from_json(file_path: str) -> DataIDMap` classmethod — deserialize from JSON
- NEW `update(other: DataIDMap) -> None` — merge another DataIDMap into this one (for multi-sheet)

**`RunConfig`** (`config.py`):
- NEW `dataid_json: str = ""` — path to preprocessed DataID JSON

### Config JSON Format

```json
{
  "dataid": {
    "xlsx": "dbc/dataid.xlsx",
    "sheet": "DBC_V2.5 ADAS1",
    "mapping": "greatwall_j6m",
    "json": "dbc/dataid.json"
  }
}
```

`sheet` can also be an array for multi-sheet:
```json
{
  "dataid": {
    "xlsx": "dbc/dataid.xlsx",
    "sheet": ["DBC_V2.5 ADAS1", "DBC_V2.5 ADAS2"],
    "json": "dbc/dataid.json"
  }
}
```

### Runtime Logic (in `load_config()` / `run_cmd()`)

```
if dataid_json is set:
    if file exists:
        → DataIDMap.from_json(dataid_json)  # fast path
    elif dataid_xlsx is set:
        → parse_dataid_xlsx(...) for each sheet
        → merge all sheets
        → DataIDMap.to_json(dataid_json)    # auto-generate
        → use the DataIDMap
    else:
        → error: "dataid_json specified but file missing and no xlsx to generate from"
elif dataid_xlsx is set:
    → parse_dataid_xlsx(...)  # slow path, backward compatible
else:
    → no DataID
```

### New CLI Command

```
crc-check preprocess-dataid \
    --xlsx path/to/dataid.xlsx \
    --sheet "Sheet1" --sheet "Sheet2" \
    --mapping greatwall_j6m \
    --output dataid.json
```

Options:
- `--xlsx` (required): path to Excel file
- `--sheet` (multiple, optional): sheet names (default: all sheets)
- `--mapping` (optional): builtin name or JSON string (default: greatwall_j6m)
- `--output` (required): output JSON path

### Edge Cases

- Multi-sheet with duplicate `(frame_id, signal_name)` keys: last sheet wins, warning logged
- Empty sheet: skipped silently
- JSON format version mismatch: error with helpful message

---

## Feature 3: HTML Report Fixes

### Current State

Two issues in `report/html.py`:

1. **PASS hex-byte highlights**: The code builds `byte_styles` for all verdicts (both PASS and FAIL), and CSS classes `crc-pass` / `rc-pass` exist. However, the collapse logic at line 231 `collapsed = "" if crc_err + rc_err > 0 else " collapsed"` means all-PASS frames are hidden by default — giving the impression that PASS frames lack detail.

2. **Frame name styling**: `.frame-header .name` has `color: #8899aa; font-size: 12px` — dimmed and small, unlike the CAN ID which is bold at 15px.

### Changes

**`report/html.py` — `_build_frame_html()`**:

1. Collapse logic:
   - When building frames for display: all-PASS frames default to **expanded** (remove the `collapsed` class condition)
   - The filter bar's "Errors only" button still hides all-PASS frames via JS
   - Rationale: user explicitly chose `only_failures=false` to see everything, so show everything expanded

2. Frame name style:
   ```css
   .frame-header .name {
     font-weight: bold;
     font-size: 15px;
     color: #e0e0e0;
   }
   ```
   Match the `.frame-header .id` style exactly.

**`report/html.py` — `write_html()`**:

No logic change needed — the function already passes all verdicts when `only_failures=False`. The `_build_frame_html()` fix handles display.

### Verification Checklist

- [ ] `only_failures=false` → all frames visible and expanded, PASS signals have green hex borders
- [ ] `only_failures=true` → only failed frames shown (unchanged behavior)
- [ ] Frame name "MyFrame" appears bold, same size/weight as "0x143"
- [ ] Hex-dump: CRC byte shows green border + tooltip on PASS, red on FAIL
- [ ] Hex-dump: RC nibble shows green underline on PASS, red on FAIL
- [ ] Filter buttons (All/Errors/Expand/Collapse) still work correctly

---

## Non-Goals

- DBC dependency resolution / inheritance
- DataID JSON incremental updates (regenerate full file each time)
- CAN FD-specific changes beyond existing support
