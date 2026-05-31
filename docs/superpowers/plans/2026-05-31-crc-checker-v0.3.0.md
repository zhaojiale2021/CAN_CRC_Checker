# CAN CRC Checker v0.3.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-DBC directory support, DataID preprocessing with JSON export/auto-generate, and HTML report fixes (PASS highlights, frame name bold, all-PASS expanded).

**Architecture:** Three independent feature tracks that touch overlapping files. Multi-DBC extends `DBCProtectionMap` with a `merge()` method and `DBCParser.parse_multiple()`. DataID preprocessing adds `DataIDMap.to_json/from_json()` serialization plus auto-generate logic in `load_config()`. HTML fixes are localized to `report/html.py` CSS and collapse logic.

**Tech Stack:** Python 3.10+, dataclasses, canmatrix, openpyxl, click, pytest

**Spec:** [docs/superpowers/specs/2026-05-31-crc-checker-v0.3.0-design.md](../specs/2026-05-31-crc-checker-v0.3.0-design.md)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `crc_checker/dbc/models.py` | Modify | Add `dbc_paths`, `merge()` to `DBCProtectionMap` |
| `crc_checker/dbc/parser.py` | Modify | Add `parse_multiple()`, directory expansion |
| `crc_checker/dataid/parser.py` | Modify | Add `to_json()`, `from_json()`, `update()` to `DataIDMap`; multi-sheet helper |
| `crc_checker/dataid/__init__.py` | Modify | Export new symbols |
| `crc_checker/config.py` | Modify | Add `dbcs`, `dataid_json` to `RunConfig`; multi-sheet `dataid_sheet`; smart resolve logic |
| `crc_checker/verify/models.py` | Modify | Add `dbc_paths` to `VerifyReport` |
| `crc_checker/report/html.py` | Modify | Fix collapse, CSS for frame name, info-bar for multi-DBC |
| `cli/main.py` | Modify | `--dbc` multiple, `preprocess-dataid` command, `run_cmd` dataid auto-generate |
| `tests/test_dbc_resolver.py` | Modify | Add merge + multi-DBC tests |
| `tests/test_dataid.py` | Create | Test JSON round-trip, multi-sheet merge, from_json |

---

### Task 1: DBCProtectionMap — add dbc_paths and merge()

**Files:**
- Modify: `crc_checker/dbc/models.py`

- [ ] **Step 1: Change `dbc_path` to `dbc_paths` list and add `merge()`**

Replace the `dbc_path: str` field and add `merge()`:

```python
# In DBCProtectionMap, change:
@dataclass
class DBCProtectionMap:
    """Complete map of all protection signals across all messages."""
    dbc_path: str                                                    # OLD
    messages: dict[int, list[MessageProtection]] = field(default_factory=dict)

# To:
@dataclass
class DBCProtectionMap:
    """Complete map of all protection signals across all messages."""
    dbc_paths: list[str] = field(default_factory=list)               # NEW
    messages: dict[int, list[MessageProtection]] = field(default_factory=dict)

    @property
    def dbc_path(self) -> str:
        """Backward-compat: joined display string of all DBC paths."""
        return ", ".join(self.dbc_paths)
```

Add `merge()` method to `DBCProtectionMap`:

```python
    def merge(self, other: "DBCProtectionMap") -> int:
        """Merge another DBCProtectionMap into this one.

        First-match-wins: if a frame_id already exists, skip it.

        Returns:
            Number of frame_ids skipped due to conflict.
        """
        skipped = 0
        for frame_id, prot_list in other.messages.items():
            if frame_id in self.messages:
                skipped += 1
            else:
                self.messages[frame_id] = prot_list
        self.dbc_paths.extend(other.dbc_paths)
        return skipped
```

- [ ] **Step 2: Run existing tests to confirm backward compat**

```bash
pytest tests/test_dbc_resolver.py -v
```

Expected: All existing tests PASS (the `dbc_path` property returns `""` for empty list, which is what tests see).

---

### Task 2: DBCParser — add parse_multiple() with directory expansion

**Files:**
- Modify: `crc_checker/dbc/parser.py`

- [ ] **Step 1: Add `parse_multiple()` classmethod and `_collect_dbc_files()` helper**

```python
# Add import at top:
from pathlib import Path

# Add to DBCParser class:
    @staticmethod
    def _collect_dbc_files(paths: list[str]) -> list[str]:
        """Expand a list of paths (files or directories) into a flat list of .dbc files.

        Directories are scanned for *.dbc (top-level only), sorted alphabetically.
        """
        result: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                dbc_files = sorted(path.glob("*.dbc"))
                if not dbc_files:
                    raise FileNotFoundError(f"No .dbc files found in directory: {p}")
                result.extend(str(f) for f in dbc_files)
            elif path.is_file():
                result.append(str(path))
            else:
                raise FileNotFoundError(f"DBC path not found: {p}")
        return result

    def parse_multiple(self, paths: list[str]) -> DBCProtectionMap:
        """Parse multiple DBC files/directories and merge into one protection map.

        First-match-wins: the first DBC that defines a frame_id wins.
        """
        dbc_files = self._collect_dbc_files(paths)
        if not dbc_files:
            raise ValueError("No DBC files specified.")

        combined = self.parse(dbc_files[0])
        for dbc_file in dbc_files[1:]:
            other = self.parse(dbc_file)
            skipped = combined.merge(other)
            if skipped > 0:
                import logging
                logging.getLogger("crc_checker").debug(
                    f"DBC merge: skipped {skipped} duplicate frame_id(s) from {dbc_file}"
                )
        return combined
```

- [ ] **Step 2: Update `parse_dbc()` convenience function to handle list input**

```python
def parse_dbc(dbc_path: str | list[str], patterns: dict[str, str] | None = None) -> DBCProtectionMap:
    """Convenience function to parse DBC file(s) and get the protection map.

    Args:
        dbc_path: Single .dbc file, directory, or list of paths.
        patterns: Optional signal name regex overrides.
    """
    parser = DBCParser(patterns)
    if isinstance(dbc_path, list):
        return parser.parse_multiple(dbc_path)
    path = Path(dbc_path)
    if path.is_dir():
        return parser.parse_multiple([dbc_path])
    return parser.parse(dbc_path)
```

Need to add `from pathlib import Path` at top of parser.py if not already present.

- [ ] **Step 3: Run existing tests**

```bash
pytest tests/test_dbc_resolver.py -v
```

Expected: All PASS.

---

### Task 3: DataIDMap — add to_json(), from_json(), update()

**Files:**
- Modify: `crc_checker/dataid/parser.py`
- Modify: `crc_checker/dataid/__init__.py`

- [ ] **Step 1: Add serialization methods to DataIDMap**

Add these methods inside the `DataIDMap` class in `crc_checker/dataid/parser.py`:

```python
    def to_json(self, file_path: str, source: str = "", mapping: str = "",
                sheets: list[str] | None = None) -> None:
        """Serialize DataIDMap to a standardized JSON file.

        Args:
            file_path: Output JSON file path.
            source: Original Excel file path (for traceability).
            mapping: Column mapping name used.
            sheets: Sheet names that were parsed.
        """
        import json
        data = {
            "format": "dataid_map_v1",
            "source": source,
            "mapping": mapping,
            "sheets": sheets or ([self.sheet_name] if self.sheet_name else []),
            "entries": [
                {"frame_id": fid, "signal_name": sig, "dataid": did}
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
        import json
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
            result.add(
                frame_id=entry["frame_id"],
                signal_name=entry["signal_name"],
                dataid=entry["dataid"],
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
```

- [ ] **Step 2: Add multi-sheet parse helper function**

Add this function to `crc_checker/dataid/parser.py`:

```python
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
    all_sheets = sheet_names if sheet_names else wb.sheetnames
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
                    import logging
                    logging.getLogger("crc_checker").warning(
                        f"DataID sheet '{sname}': {overwritten} duplicate(s) overwritten"
                    )
        except ValueError:
            continue  # skip sheets that don't match

    return combined or DataIDMap()
```

- [ ] **Step 3: Update `__init__.py` exports**

In `crc_checker/dataid/__init__.py`, add the new exports:

```python
"""DataID module."""

from crc_checker.dataid.parser import (
    DataIDMap,
    ColumnMapping,
    BUILTIN_MAPPINGS,
    parse_dataid_xlsx,
    parse_dataid_xlsx_multi,       # NEW
)

__all__ = [
    "DataIDMap",
    "ColumnMapping",
    "BUILTIN_MAPPINGS",
    "parse_dataid_xlsx",
    "parse_dataid_xlsx_multi",
]
```

- [ ] **Step 4: Run existing tests**

```bash
pytest tests/ -v
```

Expected: All PASS.

---

### Task 4: RunConfig — add dbcs, dataid_json, multi-sheet support

**Files:**
- Modify: `crc_checker/config.py`

- [ ] **Step 1: Add new fields to RunConfig**

In `crc_checker/config.py`, modify the `RunConfig` dataclass:

```python
@dataclass
class RunConfig:
    """All parameters for a CRC verification run."""
    dbc: str = ""                               # Path to DBC file or directory (required)
    dbcs: list[str] = field(default_factory=list)  # NEW: explicit list of DBC paths
    traces: list[str] = field(default_factory=list)
    crc_preset: str = ""
    crc_custom: dict | None = None
    range_mode: str = "exclude_crc"
    range_start: int = 0
    range_end: int = -1
    dataid_xlsx: str = ""
    dataid_sheet: str = ""                       # comma-separated or single sheet name
    dataid_mapping: str = ""
    dataid_json: str = ""                        # NEW: preprocessed DataID JSON path
    frame_ids: list[int] | None = None
    max_frames: int | None = None
    checksum_pattern: str | None = None
    rc_pattern: str | None = None
    output_format: str = "table"
    output_file: str = ""
    only_failures: bool = False
    rc_max_valid: int | None = None
    _resolved_paths: dict = field(default_factory=dict, repr=False)
```

- [ ] **Step 2: Update `resolve_paths()` for directory expansion and dataid_json**

Replace the `resolve_paths` method:

```python
    def resolve_paths(self, base_dir: str | None = None):
        """Resolve relative paths against config file location or CWD."""
        base = Path(base_dir) if base_dir else Path.cwd()

        def _resolve(p: str) -> str:
            if not p:
                return p
            path = Path(p)
            if path.is_absolute():
                return str(path)
            resolved = (base / path).resolve()
            return str(resolved) if resolved.exists() else str(resolved)

        self.dbc = _resolve(self.dbc) if self.dbc else self.dbc
        self.dbcs = [_resolve(p) for p in self.dbcs]
        self.traces = [_resolve(t) for t in self.traces]
        if self.dataid_xlsx:
            self.dataid_xlsx = _resolve(self.dataid_xlsx)
        if self.dataid_json:
            self.dataid_json = _resolve(self.dataid_json)

    def get_dbc_paths(self) -> list[str]:
        """Get the flat list of DBC paths (after directory expansion)."""
        from crc_checker.dbc.parser import DBCParser
        paths = []
        if self.dbc:
            paths.append(self.dbc)
        paths.extend(self.dbcs)
        return DBCParser._collect_dbc_files(paths) if paths else []
```

- [ ] **Step 3: Update `load_config()` to parse new fields**

In `load_config()`, update the DBC section:

```python
    # DBC
    cfg.dbc = data.get("dbc", "")
    # NEW: dbcs array
    dbcs_raw = data.get("dbcs", [])
    if isinstance(dbcs_raw, str):
        dbcs_raw = [dbcs_raw]
    cfg.dbcs = dbcs_raw

    traces_raw = data.get("traces", [])
    if isinstance(traces_raw, str):
        traces_raw = [traces_raw]
    cfg.traces = traces_raw

    if not cfg.dbc and not cfg.dbcs:
        raise ValueError("Config must specify 'dbc' or 'dbcs' path.")
```

Update the DataID section:

```python
    # DataID
    did = data.get("dataid", {})
    if did:
        cfg.dataid_xlsx = did.get("xlsx", "")
        # Support both string and array for sheet
        sheet_raw = did.get("sheet", "")
        if isinstance(sheet_raw, list):
            cfg.dataid_sheet = ",".join(sheet_raw)
        else:
            cfg.dataid_sheet = sheet_raw
        cfg.dataid_mapping = did.get("mapping", "")
        cfg.dataid_json = did.get("json", "")              # NEW
```

- [ ] **Step 4: Add `load_dataid()` helper to RunConfig**

```python
    def load_dataid(self) -> "DataIDMap | None":
        """Load DataID map using smart auto-generate logic.

        Priority:
        1. dataid_json exists → fast load from JSON
        2. dataid_json specified but missing + dataid_xlsx present → parse xlsx, save JSON, use it
        3. dataid_xlsx only → slow path (backward compat)
        4. Neither → None
        """
        from crc_checker.dataid.parser import DataIDMap, parse_dataid_xlsx, parse_dataid_xlsx_multi
        import logging
        log = logging.getLogger("crc_checker")

        # Fast path: JSON exists
        if self.dataid_json and Path(self.dataid_json).exists():
            log.debug(f"Loading DataID from JSON: {self.dataid_json}")
            return DataIDMap.from_json(self.dataid_json)

        # Auto-generate: JSON specified but missing, xlsx available
        if self.dataid_json and self.dataid_xlsx:
            log.info(f"Generating DataID JSON: {self.dataid_json}")
            sheets = [s.strip() for s in self.dataid_sheet.split(",") if s.strip()] if self.dataid_sheet else None
            mapping = self.dataid_mapping or None
            dm = parse_dataid_xlsx_multi(self.dataid_xlsx, sheets, mapping=mapping)
            if len(dm) > 0:
                dm.to_json(
                    self.dataid_json,
                    source=self.dataid_xlsx,
                    mapping=self.dataid_mapping,
                    sheets=sheets,
                )
                log.info(f"DataID JSON saved: {self.dataid_json} ({len(dm)} entries)")
            return dm

        # Slow path: xlsx only (backward compat)
        if self.dataid_xlsx:
            sheets = [s.strip() for s in self.dataid_sheet.split(",") if s.strip()] if self.dataid_sheet else None
            mapping = self.dataid_mapping or None
            if sheets and len(sheets) > 1:
                return parse_dataid_xlsx_multi(self.dataid_xlsx, sheets, mapping=mapping)
            return parse_dataid_xlsx(self.dataid_xlsx, sheets[0] if sheets else None, mapping=mapping)

        return None
```

Need to add `from pathlib import Path` at top of config.py.

- [ ] **Step 5: Update `generate_example_config()`**

Update the example config to show new fields:

```python
    example = {
        "_comment": "CAN CRC Checker configuration file. Remove _comment fields before use.",
        "dbc": "dbc/",
        "dbcs": [],
        "traces": ["test_data/trace.blf"],
        ...
        "dataid": {
            "_comment": "Optional E2E DataID. Use 'json' for fast preprocessed format.",
            "xlsx": "dbc/dataid.xlsx",
            "sheet": ["DBC_V2.5 ADAS1", "DBC_V2.5 ADAS2"],
            "mapping": "greatwall_j6m",
            "json": "dbc/dataid.json"
        },
        ...
    }
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -v
```

Expected: All PASS.

---

### Task 5: VerifyReport — add dbc_paths field

**Files:**
- Modify: `crc_checker/verify/models.py`

- [ ] **Step 1: Add dbc_paths to VerifyReport**

```python
@dataclass
class VerifyReport:
    """Aggregated verification report for a complete trace run."""
    verdicts: list[VerifyVerdict] = field(default_factory=list)
    dbc_path: str = ""                              # keep for backward compat (display string)
    dbc_paths: list[str] = field(default_factory=list)  # NEW: all DBC source files
    trace_path: str = ""
    total_frames: int = 0
    total_verdicts: int = 0
    _frame_data: dict = field(default_factory=dict)
    _frame_names: dict = field(default_factory=dict)
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/ -v
```

Expected: All PASS (dbc_path default "" still works everywhere).

---

### Task 6: HTML Report Fixes

**Files:**
- Modify: `crc_checker/report/html.py`

- [ ] **Step 1: Fix frame name CSS — bold like CAN ID**

In the `CSS` string, find `.frame-header .name` and change:

```css
/* OLD */
.frame-header .name { color: #8899aa; font-size: 12px; margin-left: 2px; }

/* NEW */
.frame-header .name { font-weight: bold; font-size: 15px; color: #e0e0e0; margin-left: 2px; }
```

- [ ] **Step 2: Fix collapse logic — all-PASS frames expanded by default**

In `_build_frame_html()`, change line 231:

```python
# OLD
collapsed = "" if crc_err + rc_err > 0 else " collapsed"

# NEW — always expanded; user can use filter buttons to collapse
collapsed = ""
```

- [ ] **Step 3: Update info-bar to show multiple DBC paths**

In `write_html()`, change the info-bar DBC display:

```python
# OLD
DBC: {report.dbc_path}<br>

# NEW
DBC: {', '.join(report.dbc_paths) if report.dbc_paths else report.dbc_path}<br>
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```

Expected: All PASS.

---

### Task 7: CLI — update verify command for multi-DBC

**Files:**
- Modify: `cli/main.py`

- [ ] **Step 1: Make `--dbc` accept multiple values and directories**

```python
@cli.command()
@click.option("--dbc", "dbc_paths", multiple=True,
              type=click.Path(exists=True), help="Path to DBC file(s) or directory (repeatable)")
```

Remove the `required=True` since we now validate after collection. Update the `verify` function signature: replace `dbc` param with `dbc_paths`.

- [ ] **Step 2: Update DBC parsing in verify command**

```python
    # Parse DBC (support multiple files + directory)
    all_dbc = list(dbc_paths)
    if not all_dbc:
        raise click.UsageError("At least one --dbc path is required.")

    if verbose:
        click.echo(f"Parsing DBC: {', '.join(all_dbc)}")
    protection_map = parse_dbc(all_dbc if len(all_dbc) > 1 else all_dbc[0], patterns)
```

- [ ] **Step 3: Set dbc_paths on report**

After engine.run(), add:

```python
            report.dbc_paths = protection_map.dbc_paths
```

- [ ] **Step 4: Run CLI smoke test**

```bash
crc-check verify --help
```

Expected: `--dbc` shown as multiple option.

---

### Task 8: CLI — update run command for config-based multi-DBC + DataID

**Files:**
- Modify: `cli/main.py`

- [ ] **Step 1: Update run_cmd to use get_dbc_paths() and load_dataid()**

In `run_cmd()`, replace the DBC and DataID loading:

```python
    # OLD DBC loading:
    protection_map = parse_dbc(cfg.dbc, patterns)

    # NEW DBC loading:
    dbc_paths = cfg.get_dbc_paths()
    if not dbc_paths:
        raise click.UsageError("No DBC files found. Check 'dbc' or 'dbcs' in config.")
    if verbose:
        click.echo(f"DBC files: {len(dbc_paths)} file(s)")
        for p in dbc_paths:
            click.echo(f"  {p}")
    protection_map = parse_dbc(dbc_paths, patterns)
```

Replace the DataID loading:

```python
    # OLD:
    dataid_map = None
    if cfg.dataid_xlsx and os.path.exists(cfg.dataid_xlsx):
        from crc_checker.dataid import parse_dataid_xlsx
        dataid_map = parse_dataid_xlsx(cfg.dataid_xlsx,
                                       cfg.dataid_sheet or None,
                                       mapping=cfg.dataid_mapping or None)

    # NEW:
    dataid_map = cfg.load_dataid()
```

After engine.run(), set dbc_paths on report:

```python
            report.dbc_paths = protection_map.dbc_paths
```

- [ ] **Step 2: Update verbose output for DataID**

```python
    if dataid_map and verbose:
        click.echo(f"DataID: {len(dataid_map)} entries loaded")
```

---

### Task 9: CLI — add preprocess-dataid command

**Files:**
- Modify: `cli/main.py`

- [ ] **Step 1: Add the command**

```python
@cli.command("preprocess-dataid")
@click.option("--xlsx", required=True, type=click.Path(exists=True),
              help="Path to DataID Excel file")
@click.option("--sheet", "sheets", multiple=True, default=None,
              help="Sheet name(s) to parse (repeatable; default: all sheets)")
@click.option("--mapping", default="greatwall_j6m",
              help="Column mapping: builtin name or JSON string")
@click.option("--output", "-o", required=True, type=click.Path(),
              help="Output JSON file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def preprocess_dataid(xlsx, sheets, mapping, output, verbose):
    """Preprocess DataID Excel into standardized JSON for fast reload.

    Parse one or more sheets from a DataID Excel file and export a
    unified JSON that subsequent 'crc-check run' can load directly,
    skipping the slow openpyxl step.

    \b
    Example:
      crc-check preprocess-dataid --xlsx dataid.xlsx --sheet "Sheet1" --sheet "Sheet2" -o dataid.json
    """
    from crc_checker.dataid import parse_dataid_xlsx_multi

    sheet_list = list(sheets) if sheets else None

    if verbose:
        click.echo(f"Parsing: {xlsx}")
        click.echo(f"Mapping: {mapping}")
        if sheet_list:
            click.echo(f"Sheets: {', '.join(sheet_list)}")
        else:
            click.echo("Sheets: all")

    dm = parse_dataid_xlsx_multi(xlsx, sheet_list, mapping=mapping)

    if len(dm) == 0:
        click.echo("Warning: No DataID entries found.", err=True)

    parsed_sheets = sheet_list or ["<auto>"]
    dm.to_json(output, source=xlsx, mapping=mapping, sheets=parsed_sheets)
    click.echo(f"DataID JSON written to {output} ({len(dm)} entries)")
```

---

### Task 10: Tests — DBC merge and multi-DBC

**Files:**
- Modify: `tests/test_dbc_resolver.py`

- [ ] **Step 1: Add merge test**

```python
    def test_merge_first_wins(self):
        """First DBC's frame_id takes priority, second is skipped."""
        from crc_checker.dbc.models import DBCProtectionMap

        map1 = DBCProtectionMap(dbc_paths=["a.dbc"])
        map1.messages[0x100] = [
            MessageProtection(frame_id=0x100, frame_name="FrameA", dlc=8, pair_suffix="X")
        ]

        map2 = DBCProtectionMap(dbc_paths=["b.dbc"])
        map2.messages[0x100] = [
            MessageProtection(frame_id=0x100, frame_name="FrameA_Dup", dlc=8, pair_suffix="Y")
        ]
        map2.messages[0x200] = [
            MessageProtection(frame_id=0x200, frame_name="FrameB", dlc=8, pair_suffix="Z")
        ]

        skipped = map1.merge(map2)
        assert skipped == 1
        assert 0x100 in map1.messages
        assert 0x200 in map1.messages
        # First DBC's definition wins
        assert map1.messages[0x100][0].frame_name == "FrameA"
        assert map1.dbc_paths == ["a.dbc", "b.dbc"]
```

- [ ] **Step 2: Add dbc_path backward compat test**

```python
    def test_dbc_path_property(self):
        """dbc_path returns joined string of all paths."""
        from crc_checker.dbc.models import DBCProtectionMap

        map1 = DBCProtectionMap(dbc_paths=["a.dbc", "b.dbc"])
        assert map1.dbc_path == "a.dbc, b.dbc"

        map2 = DBCProtectionMap(dbc_paths=[])
        assert map2.dbc_path == ""
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_dbc_resolver.py -v
```

Expected: 2 new tests PASS.

---

### Task 11: Tests — DataID JSON round-trip and multi-sheet

**Files:**
- Create: `tests/test_dataid.py`

- [ ] **Step 1: Create test file with all tests**

```python
"""Tests for DataID parsing, JSON serialization, and multi-sheet merge."""
import json
import os
import tempfile
import pytest
from crc_checker.dataid.parser import (
    DataIDMap, ColumnMapping, parse_dataid_xlsx_multi
)


class TestDataIDMapSerialization:
    """Test JSON round-trip serialization."""

    def test_to_json_and_from_json_roundtrip(self):
        dm = DataIDMap(sheet_name="TestSheet")
        dm.add(0x143, "Checksum_ACC1", 0x0054)
        dm.add(0x143, "Checksum_ACC2", 0x0055)
        dm.add(0x299, "Checksum_IFC1", 0x00AB)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            dm.to_json(tmp_path, source="test.xlsx", mapping="greatwall_j6m",
                       sheets=["TestSheet"])

            # Verify file content
            with open(tmp_path, "r") as f:
                raw = json.load(f)
            assert raw["format"] == "dataid_map_v1"
            assert raw["source"] == "test.xlsx"
            assert len(raw["entries"]) == 3

            # Round-trip
            loaded = DataIDMap.from_json(tmp_path)
            assert len(loaded) == 3
            assert loaded.get(0x143, "Checksum_ACC1") == 0x0054
            assert loaded.get(0x143, "Checksum_ACC2") == 0x0055
            assert loaded.get(0x299, "Checksum_IFC1") == 0x00AB
            assert loaded.get(0x999, "nonexistent") is None
        finally:
            os.unlink(tmp_path)

    def test_from_json_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"format": "dataid_map_v1", "entries": []}, f)
            tmp_path = f.name
        try:
            dm = DataIDMap.from_json(tmp_path)
            assert len(dm) == 0
        finally:
            os.unlink(tmp_path)

    def test_from_json_bad_format(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"format": "unknown_v2", "entries": []}, f)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported.*format"):
                DataIDMap.from_json(tmp_path)
        finally:
            os.unlink(tmp_path)


class TestDataIDMapUpdate:
    """Test merging of DataIDMap instances."""

    def test_update_adds_new_and_overwrites_duplicates(self):
        dm1 = DataIDMap()
        dm1.add(0x100, "Checksum_X", 0x0010)
        dm1.add(0x200, "Checksum_Y", 0x0020)

        dm2 = DataIDMap()
        dm2.add(0x200, "Checksum_Y", 0x0099)  # duplicate, overwrites
        dm2.add(0x300, "Checksum_Z", 0x0030)  # new

        overwritten = dm1.update(dm2)
        assert overwritten == 1
        assert len(dm1) == 3
        assert dm1.get(0x100, "Checksum_X") == 0x0010  # unchanged
        assert dm1.get(0x200, "Checksum_Y") == 0x0099  # overwritten by dm2
        assert dm1.get(0x300, "Checksum_Z") == 0x0030  # new

    def test_update_empty_other(self):
        dm1 = DataIDMap()
        dm1.add(0x100, "Checksum_X", 0x0010)
        dm2 = DataIDMap()

        overwritten = dm1.update(dm2)
        assert overwritten == 0
        assert len(dm1) == 1
```

- [ ] **Step 2: Run new tests**

```bash
pytest tests/test_dataid.py -v
```

Expected: All 5 tests PASS.

---

### Task 12: Integration — update run_cmd dataid auto-generate flow

**Files:**
- Modify: `cli/main.py`

- [ ] **Step 1: Update verbose logging in run_cmd for DataID auto-generate**

Replace the existing DataID block (already partially done in Task 8) with proper logging:

```python
    # In run_cmd, after cfg loading:
    if verbose and cfg.dataid_json:
        if Path(cfg.dataid_json).exists():
            click.echo(f"DataID JSON: {cfg.dataid_json} (fast path)")
        elif cfg.dataid_xlsx:
            click.echo(f"DataID: generating {cfg.dataid_json} from {cfg.dataid_xlsx}...")
```

Add `from pathlib import Path` to cli/main.py imports.

---

### Task 13: Final integration — full test suite + manual verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests PASS (existing + new).

- [ ] **Step 2: Run with coverage**

```bash
pytest --cov=crc_checker tests/
```

Expected: Coverage not regressed.

- [ ] **Step 3: Manual verification — CLI help**

```bash
crc-check verify --help
crc-check preprocess-dataid --help
crc-check run --help
```

Expected: New options and commands visible.

- [ ] **Step 4: Manual verification — generate config**

```bash
crc-check gen-config test_config.json
```

Expected: Config includes `dbcs`, `dataid.json`, `dataid.sheet` as array.

- [ ] **Step 5: Commit final changes**

```bash
git add -A
git commit -m "feat: multi-DBC support, DataID JSON preprocessing, HTML report fixes

- Multi-DBC: --dbc accepts directory or multiple values, first-match-wins merge
- DataID JSON: DataIDMap.to_json/from_json, auto-generate on first run
- HTML: PASS signals green highlighted, frame name bold, all frames expanded
- New CLI: crc-check preprocess-dataid command"
```
