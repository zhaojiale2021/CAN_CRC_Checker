"""JSON configuration file support — pre-define all parameters in one file.

Example config (all fields optional except dbc and traces):

{
  "dbc": "test_dbc/network.dbc",
  "traces": ["test_data/trace.blf"],
  "crc": {
    "preset": "CRC8/AUTOSAR"
  },
  "range": {
    "mode": "exclude_crc"
  },
  "dataid": {
    "xlsx": "test_dbc/dataid.xlsx",
    "sheet": "DBC_V2.5 ADAS1"
  },
  "filter": {
    "frame_ids": ["0x143", "0x299"],
    "max_frames": 5000
  },
  "output": {
    "format": "html",
    "file": "report.html",
    "only_failures": true
  },
  "tui": false
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset
from crc_checker.dataid.parser import (
    DataIDMap,
    match_sheet_to_dbc,
    parse_dataid_xlsx,
    parse_dataid_xlsx_multi,
)


def _get_xlsx_sheet_names(xlsx_path: str) -> list[str]:
    """Get sheet names from an .xlsx/.xls file (avoids openpyxl bugs)."""
    # pylint: disable=import-outside-toplevel
    from crc_checker.dataid.parser import get_sheet_names
    return get_sheet_names(xlsx_path)


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
# pylint: disable=too-many-instance-attributes
class RunConfig:
    """All parameters for a CRC verification run.

    Can be constructed from a JSON file via `load_config()`.
    """
    dbc: str = ""                               # Path to DBC file or directory (required)
    dbcs: list[str] = field(default_factory=list)  # Explicit list of DBC paths (files or dirs)
    dbc_merge: bool = False                     # Merge all DBCs into one map (vs per-channel)
    traces: list[str] = field(default_factory=list)  # Trace file paths (required)
    crc_preset: str = ""                        # Preset name, e.g. "CRC8/AUTOSAR"
    crc_custom: dict | None = None              # Custom CRC params dict
    crc_byte_swap: bool = False                 # Byte-swap computed CRC (Profile 5 LE→BE)
    crc_auto_classify: bool = False             # fx12fl: per-message algo from DBC comments
    crc_overrides: dict[str, str] = field(default_factory=dict)  # frame id/name → preset
    crc_profiles: dict = field(default_factory=dict)  # profile key → field overrides
    crc_profile_by_width: bool = False          # select profile from CRC signal width
    crc_range_overrides: dict = field(default_factory=dict)  # frame/signal → range dict
    crc_skip: list = field(default_factory=list)  # frame ids/names/signals to skip
    range_mode: str = "exclude_crc"             # full_payload | exclude_crc | custom_range
    range_start: int = 0
    range_end: int = -1
    dataid_position: str = "prepend"    # "prepend" (GWM) | "append" (E2E Profile 5/1)
    dataid_byte_order: str = "lo_hi"    # "lo_hi" | "hi_lo" (high byte first)
    dataid_xlsx: str = ""                       # DataID Excel path
    dataid_sheet: str = ""                      # Sheet name(s), comma-separated ("" = auto)
    dataid_mapping: str = ""                    # Column mapping name/JSON
    dataid_json: str = ""                       # Preprocessed DataID JSON path (fast load)
    dataid_default: int | None = None           # Fallback DataID value (0x0000) when not found
    frame_ids: list[int] | None = None          # CAN ID filter
    max_frames: int | None = None               # Frame limit
    checksum_pattern: str | None = None         # Regex override
    rc_pattern: str | None = None               # Regex override
    output_format: str = "table"                # table | html
    output_file: str = ""                       # Output path
    only_failures: bool = False                 # Show failures only
    rc_max_valid: int | None = None             # Max valid RC value (None = auto from bit length)

    # Derived / resolved fields
    _resolved_paths: dict = field(default_factory=dict, repr=False)

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
        """Get the flat list of DBC file paths (after directory expansion)."""
        # pylint: disable=import-outside-toplevel
        from crc_checker.dbc.parser import DBCParser
        paths = []
        if self.dbc:
            paths.append(self.dbc)
        paths.extend(self.dbcs)
        # pylint: disable=protected-access
        return DBCParser._collect_dbc_files(paths) if paths else []

    _TRACE_EXTENSIONS = {".blf", ".asc", ".mf4", ".trc", ".csv", ".log", ".txt"}

    def get_trace_paths(self) -> list[str]:
        """Get the flat list of trace file paths (after directory expansion)."""
        result: list[str] = []
        for p in self.traces:
            path = Path(p)
            if path.is_dir():
                files = sorted(
                    f for f in path.iterdir()
                    if f.suffix.lower() in self._TRACE_EXTENSIONS
                )
                if not files:
                    raise FileNotFoundError(f"No trace files found in directory: {p}")
                result.extend(str(f) for f in files)
            elif path.is_file():
                result.append(str(path))
            else:
                raise FileNotFoundError(f"Trace path not found: {p}")
        return result

    def load_dataid(self, dbc_name: str = ""):
        """Load DataID map using smart auto-generate logic.

        If dbc_name is provided, auto-match the best sheet to the DBC name.

        Priority:
        1. dataid_json exists → fast load from JSON
        2. dataid_json specified but missing + dataid_xlsx present → parse xlsx, save JSON
        3. dataid_xlsx only → slow path (backward compat)
        4. Neither → None
        """
        log = logging.getLogger("crc_checker")

        # Fast path: JSON exists
        if self.dataid_json and Path(self.dataid_json).exists():
            log.debug("Loading DataID from JSON: %s", self.dataid_json)
            return DataIDMap.from_json(self.dataid_json)

        # Resolve sheets: auto-match to DBC name if no explicit sheet specified
        if self.dataid_sheet:
            sheets = [
                s.strip() for s in self.dataid_sheet.split(",") if s.strip()
            ]
        else:
            sheets = None
        if not sheets and dbc_name and self.dataid_xlsx:
            all_sheets = _get_xlsx_sheet_names(self.dataid_xlsx)
            matched = match_sheet_to_dbc(dbc_name, all_sheets)
            if matched:
                sheets = [matched]
                log.info(
                    "Auto-matched sheet '%s' for DBC '%s'", matched, dbc_name
                )

        mapping = self.dataid_mapping or None

        # Auto-generate: JSON specified but missing, xlsx available
        if self.dataid_json and self.dataid_xlsx:
            log.info("Generating DataID JSON: %s", self.dataid_json)
            dm = parse_dataid_xlsx_multi(self.dataid_xlsx, sheets, mapping=mapping)
            if len(dm) > 0:
                dm.to_json(
                    self.dataid_json,
                    source=self.dataid_xlsx,
                    mapping=self.dataid_mapping,
                    sheets=sheets,
                )
                log.info(
                    "DataID JSON saved: %s (%d entries)",
                    self.dataid_json, len(dm),
                )
            return dm

        # Slow path: xlsx only (backward compat, with auto-match)
        if self.dataid_xlsx:
            if not sheets and dbc_name:
                all_sheets = _get_xlsx_sheet_names(self.dataid_xlsx)
                matched = match_sheet_to_dbc(dbc_name, all_sheets)
                if matched:
                    sheets = [matched]
                    log.info(
                        "Auto-matched sheet '%s' for DBC '%s'", matched, dbc_name
                    )
            if sheets and len(sheets) > 1:
                return parse_dataid_xlsx_multi(
                    self.dataid_xlsx, sheets, mapping=mapping,
                )
            sheet_name = sheets[0] if sheets else None
            return parse_dataid_xlsx(
                self.dataid_xlsx, sheet_name, mapping=mapping,
            )

        return None

    def build_crc_params(self) -> CRCParams | None:
        """Build CRCParams from config."""

        if self.crc_custom:
            d = self.crc_custom
            def _h(v):
                if isinstance(v, str):
                    return int(v, 16)
                return v
            return CRCParams(
                width=d["width"],
                polynomial=_h(d["poly"]),
                initial_value=_h(d.get("init", "0x00")),
                final_xor=_h(d.get("xor", "0x00")),
                reflect_in=d.get("reflect_in", False),
                reflect_out=d.get("reflect_out", False),
                name=d.get("name", "custom"),
                checksum_type=d.get("type", "crc"),  # "crc" | "sum_xor" | "xor_seed"
            )
        if self.crc_preset:
            return get_preset(self.crc_preset)
        return None

    def build_crc_range(self) -> CRCRange:
        """Build CRCRange from config."""
        return CRCRange(
            mode=self.range_mode,
            start_byte=self.range_start,
            end_byte=self.range_end,
            dataid_position=self.dataid_position,
            dataid_byte_order=self.dataid_byte_order,
            crc_byte_swap=self.crc_byte_swap,
        )


def apply_crc_config(cfg: "RunConfig", protection_map) -> dict[str, int]:
    """Apply every CRC-related section of a RunConfig to a protection map.

    Shared by the ``run`` CLI command and by tests/tools so both drive the
    protection map in the same order. Order matters:

    1. global params + range (the baseline for every group),
    2. E2E profiles (per-group algorithm/range/DataID layout),
    3. per-message range overrides (GAC second E2E segment),
    4. skip list (signals that only look protected),
    5. DBC-comment auto-classification, then explicit per-message overrides.

    Returns:
        Counts per step, for verbose logging (keys: profiles, range_overrides,
        skip, auto_classify, overrides).
    """
    # pylint: disable=import-outside-toplevel
    from crc_checker.crc.profiles import load_profiles

    counts = {"profiles": 0, "range_overrides": 0, "skip": 0,
              "auto_classify": 0, "overrides": 0}

    crc_params = cfg.build_crc_params()
    if crc_params:
        protection_map.apply_crc_params(crc_params)
        # Legacy profile handling (Profile 1 → CRC8/SAE-J1850-ZERO) kept for
        # configs that predate crc.profiles
        protection_map.apply_profile_crc_params(crc_params)
    protection_map.apply_crc_range(cfg.build_crc_range())

    if cfg.crc_profiles or cfg.crc_profile_by_width:
        counts["profiles"] = protection_map.apply_profiles(
            load_profiles(cfg.crc_profiles),
            select_by_width=cfg.crc_profile_by_width)

    if cfg.crc_range_overrides:
        counts["range_overrides"] = protection_map.apply_range_overrides(
            cfg.crc_range_overrides)

    if cfg.crc_skip:
        counts["skip"] = protection_map.apply_skip(cfg.crc_skip)

    # fx12fl: per-message algorithm from DBC comments (overrides the defaults above)
    if cfg.crc_auto_classify:
        counts["auto_classify"] = protection_map.apply_comment_classification(crc_params)

    # Explicit per-message overrides win over everything above
    if cfg.crc_overrides:
        counts["overrides"] = protection_map.apply_crc_overrides(cfg.crc_overrides)

    if cfg.rc_max_valid is not None:
        protection_map.apply_rc_config(max_valid=cfg.rc_max_valid)

    return counts


# ---------------------------------------------------------------------------
# JSON schema (for validation / documentation)
# ---------------------------------------------------------------------------

CONFIG_SCHEMA_DOC = """
{
  // === Required ===
  "dbc": "path/to/network.dbc",
  "traces": ["trace1.blf", "trace2.asc"],
  // "dbc_merge": true,                  // merge all DBCs into one map instead of
  //                                     // selecting a DBC per trace channel

  // === CRC Algorithm (optional — RC-only if omitted) ===
  "crc": {
    "preset": "CRC8/AUTOSAR"            // Use a built-in preset
    // "byte_swap": true                // Profile 5: swap computed CRC bytes
    // "auto_classify": true            // fx12fl: per-message algo from DBC comments
    //                                   // (J1850 CRC-8 / SUM8/XOR-FF / XOR8/SEED)
    // "overrides": {                   // per-message algorithm override; keys
    //   "0x287": "SUM8/XOR-FF",        // are frame IDs ("0x287"/647) or frame
    //   "ICM_5": "SUM8/XOR-FF"         // names, applied after auto_classify
    // },
    // "profile_by_width": true,        // GAC: E2E profile from the CRC signal
    //                                   // width (2 bytes -> Profile 5, 1 -> Profile 1)
    // "profiles": {                    // per-profile overrides; unlisted fields keep
    //   "p01": {                       // the built-in value
    //     "preset": "CRC8/SAE-J1850-ZERO",   // CRC preset name
    //     "dataid_position": "prepend",      // append | prepend
    //     "dataid_byte_order": "lo_hi",      // lo_hi | hi_lo
    //     "byte_swap": false,                // swap computed CRC bytes
    //     "counter_max_valid": 14,           // RC valid range 0..14 (15 = invalid)
    //     "range": { "mode": "custom_range", // "" (inherit config range) |
    //                "start_byte": 0, "end_byte": -1 }   // exclude_crc | custom_range
    //   },
    //   "p05": { "preset": "CRC16/CCITT", "byte_swap": true,
    //            "range": { "mode": "custom_range", "start_byte": 0, "end_byte": 56 } }
    // },
    // "range_overrides": {             // per-message/signal CRC range, e.g. the
    //   "SRS_1_CRC_2": {               // second E2E instance of CCU_SRS_1
    //     "mode": "custom_range", "start_byte": 13, "end_byte": 32
    //   }
    // },
    // "skip": ["SYNC_FC_CRC"],         // frame ids/names/signals left unverified
    // OR custom:
    // "custom": {
    //   "width": 8,
    //   "poly": "0x2F",
    //   "init": "0xFF",
    //   "xor": "0xFF",
    //   "reflect_in": false,
    //   "reflect_out": false,
    //   "type": "crc"                   // "crc" | "sum_xor" | "xor_seed"
    // }
  },

  // === CRC Data Range ===
  "range": {
    "mode": "exclude_crc",               // full_payload | exclude_crc | custom_range
    "start_byte": 0,                     // for custom_range
    "end_byte": -1                       // -1 = end of payload
  },

  // === DataID (E2E) ===
  "dataid": {
    "xlsx": "path/to/dataid.xlsx",       // .xlsx or legacy .xls
    "json": "path/to/dataid.json",       // preprocessed (fast path, wins over xlsx)
    "sheet": "DBC_V2.5 ADAS1",           // blank = auto-detect
    "mapping": "greatwall_j6m",          // builtin name or JSON string
    "position": "prepend",               // prepend (GWM/Profile 1) | append (Profile 5)
    "byte_order": "lo_hi",               // lo_hi | hi_lo
    "default": null                      // DataID for unmatched groups (e.g. 0)
  },

  // === Filter ===
  "filter": {
    "frame_ids": ["0x143", "0x299"],     // null = all
    "max_frames": 10000                   // null = all
  },

  // === Signal Detection Overrides ===
  "signals": {
    "checksum_pattern": null,            // null = default regex
    "rc_pattern": null
  },

  // === Output ===
  "output": {
    "format": "html",                    // table | html
    "file": "report.html",
    "only_failures": false
  },

  // === Rolling Counter ===
  "rc": {
    "max_valid": 14                      // Max valid RC value before wrap to 0
                                         // (null = auto: 2^length - 1)
  },

  // === UI ===
  "tui": false                           // true = launch TUI instead of CLI output
}
"""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def load_config(config_path: str) -> RunConfig:
    """Load and validate a JSON configuration file.

    Args:
        config_path: Path to a .json configuration file.

    Returns:
        RunConfig with all parameters resolved.

    Raises:
        FileNotFoundError: config file doesn't exist.
        ValueError: invalid or missing required fields.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfg = RunConfig()
    base_dir = str(path.parent)

    # Required
    cfg.dbc = data.get("dbc", "")
    # NEW: dbcs array
    dbcs_raw = data.get("dbcs", [])
    if isinstance(dbcs_raw, str):
        dbcs_raw = [dbcs_raw]
    cfg.dbcs = dbcs_raw
    # Merge all DBCs into a single map instead of per-channel DBC selection
    # (t1lfl1: B_CAN and C1_CAN are logged on both trace channels)
    cfg.dbc_merge = data.get("dbc_merge", False)

    traces_raw = data.get("traces", [])
    if isinstance(traces_raw, str):
        traces_raw = [traces_raw]
    cfg.traces = traces_raw

    if not cfg.dbc and not cfg.dbcs:
        raise ValueError("Config must specify 'dbc' or 'dbcs' path.")
    if not cfg.traces:
        raise ValueError("Config must specify at least one 'traces' entry.")

    # CRC
    crc = data.get("crc", {})
    if crc:
        cfg.crc_preset = crc.get("preset", "")
        cfg.crc_custom = crc.get("custom")
        cfg.crc_byte_swap = crc.get("byte_swap", False)
        # fx12fl: auto-classify per-message algorithm from DBC comments
        cfg.crc_auto_classify = crc.get("auto_classify", False)
        # Per-message algorithm overrides (frame id/name → preset), applied
        # after auto-classification so they always win.
        cfg.crc_overrides = crc.get("overrides") or {}
        # E2E profile table (GAC: mixes Profile 5 and Profile 1 on one bus).
        # "profile_by_width" selects the profile from the CRC signal width the
        # way the firmware does (2-byte CRC → Profile 5, 1-byte → Profile 1).
        cfg.crc_profiles = crc.get("profiles") or {}
        cfg.crc_profile_by_width = crc.get("profile_by_width", False)
        # Per-message CRC range overrides (frame id/name/signal → range dict).
        cfg.crc_range_overrides = crc.get("range_overrides") or {}
        # Protection groups to leave unverified (frame ids/names/signal names).
        cfg.crc_skip = crc.get("skip") or []

    # Range
    rng = data.get("range", {})
    if rng:
        cfg.range_mode = rng.get("mode", "exclude_crc")
        cfg.range_start = rng.get("start_byte", 0)
        cfg.range_end = rng.get("end_byte", -1)

    # DataID
    did = data.get("dataid", {})
    if did:
        cfg.dataid_xlsx = did.get("xlsx", "")
        sheet_raw = did.get("sheet", "")
        if isinstance(sheet_raw, list):
            cfg.dataid_sheet = ",".join(sheet_raw)
        else:
            cfg.dataid_sheet = sheet_raw
        cfg.dataid_mapping = did.get("mapping", "")
        cfg.dataid_json = did.get("json", "")
        cfg.dataid_position = did.get("position", "prepend")
        cfg.dataid_byte_order = did.get("byte_order", "lo_hi")
        cfg.dataid_default = did.get("default")

    # Filter
    flt = data.get("filter", {})
    if flt:
        raw_ids = flt.get("frame_ids")
        if raw_ids:
            cfg.frame_ids = [
                int(x, 16) if isinstance(x, str) and x.lower().startswith("0x") else int(x)
                for x in raw_ids
            ]
        cfg.max_frames = flt.get("max_frames")

    # Signals
    sig = data.get("signals", {})
    if sig:
        cfg.checksum_pattern = sig.get("checksum_pattern")
        cfg.rc_pattern = sig.get("rc_pattern")

    # Output
    out = data.get("output", {})
    if out:
        cfg.output_format = out.get("format", "table")
        cfg.output_file = out.get("file", "")
        cfg.only_failures = out.get("only_failures", False)

    # RC config
    rc_cfg = data.get("rc", {})
    if rc_cfg:
        cfg.rc_max_valid = rc_cfg.get("max_valid")

    # Resolve relative paths
    cfg.resolve_paths(base_dir)

    return cfg


def generate_example_config(output_path: str):
    """Write an annotated example config file."""
    example = {
        "_comment": "CAN CRC Checker configuration file. Remove _comment fields before use.",
        "dbc": "dbc/",
        "dbcs": [],
        "dbc_merge": False,
        "traces": ["test_data/trace.blf"],
        "crc": {
            "_comment": "Use 'preset' for built-in, or 'custom' for custom algorithm.",
            "preset": "CRC8/AUTOSAR",
            "byte_swap": False,
            "profile_by_width": False,
            "_profiles_comment": (
                "Optional per-profile overrides; unlisted fields keep the built-in value. "
                "Profile keys: p01 (Profile 1: CRC8/SAE-J1850-ZERO, DataID prepend, "
                "counter 0..14), p05 (Profile 5: CRC16/CCITT, DataID append, byte_swap, "
                "range 0..56). Example: "
                "{\"p01\": {\"preset\": \"CRC8/SAE-J1850-ZERO\", "
                "\"dataid_position\": \"prepend\", \"byte_swap\": false, "
                "\"counter_max_valid\": 14, "
                "\"range\": {\"mode\": \"custom_range\", \"start_byte\": 0, \"end_byte\": -1}}}"
            ),
            "profiles": {},
            "_range_overrides_comment": (
                "Per-message/signal CRC range, keyed by frame id/name or checksum signal "
                "name. Example: {\"SRS_1_CRC_2\": {\"mode\": \"custom_range\", "
                "\"start_byte\": 13, \"end_byte\": 32}}"
            ),
            "range_overrides": {},
            "skip": [],
            "overrides": {}
        },
        "range": {
            "_comment": "mode: full_payload | exclude_crc | custom_range",
            "mode": "exclude_crc",
            "start_byte": 0,
            "end_byte": -1
        },
        "dataid": {
            "_comment": "Optional E2E DataID. Use 'json' for fast preprocessed format.",
            "xlsx": "test_dbc/dataid.xlsx",
            "sheet": ["DBC_V2.5 ADAS1", "DBC_V2.5 ADAS2"],
            "mapping": "greatwall_j6m",
            "json": "test_dbc/dataid.json"
        },
        "filter": {
            "_comment": "Optional. Omit or set to null for no limit.",
            "frame_ids": None,
            "max_frames": None
        },
        "output": {
            "format": "html",
            "file": "report.html",
            "only_failures": False
        },
        "rc": {
            "_comment": "Optional RC range config. Remove to auto-detect from bit length.",
            "max_valid": None
        }
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(example, f, indent=2, ensure_ascii=False)
