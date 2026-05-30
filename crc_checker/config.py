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
import os
from dataclasses import dataclass, field
from pathlib import Path

from crc_checker.crc.models import CRCParams, CRCRange


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    """All parameters for a CRC verification run.

    Can be constructed from a JSON file via `load_config()`.
    """
    dbc: str = ""                               # Path to DBC file (required)
    traces: list[str] = field(default_factory=list)  # Trace file paths (required)
    crc_preset: str = ""                        # Preset name, e.g. "CRC8/AUTOSAR"
    crc_custom: dict | None = None              # Custom CRC params dict
    range_mode: str = "exclude_crc"             # full_payload | exclude_crc | custom_range
    range_start: int = 0
    range_end: int = -1
    dataid_xlsx: str = ""                       # DataID Excel path
    dataid_sheet: str = ""                      # Sheet name ("" = auto)
    dataid_mapping: str = ""                    # Column mapping name/JSON
    frame_ids: list[int] | None = None          # CAN ID filter
    max_frames: int | None = None               # Frame limit
    checksum_pattern: str | None = None         # Regex override
    rc_pattern: str | None = None               # Regex override
    output_format: str = "table"                # table | html | csv | json
    output_file: str = ""                       # Output path
    only_failures: bool = False                 # Show failures only
    tui: bool = False                           # Launch TUI
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
        self.traces = [_resolve(t) for t in self.traces]
        if self.dataid_xlsx:
            self.dataid_xlsx = _resolve(self.dataid_xlsx)

    def build_crc_params(self) -> CRCParams | None:
        """Build CRCParams from config."""
        from crc_checker.crc.presets import get_preset

        if self.crc_custom:
            d = self.crc_custom
            def _h(v, field):
                if isinstance(v, str):
                    return int(v, 16)
                return v
            return CRCParams(
                width=d["width"],
                polynomial=_h(d["poly"], "poly"),
                initial_value=_h(d.get("init", "0x00"), "init"),
                final_xor=_h(d.get("xor", "0x00"), "xor"),
                reflect_in=d.get("reflect_in", False),
                reflect_out=d.get("reflect_out", False),
                name=d.get("name", "custom"),
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
        )


# ---------------------------------------------------------------------------
# JSON schema (for validation / documentation)
# ---------------------------------------------------------------------------

CONFIG_SCHEMA_DOC = """
{
  // === Required ===
  "dbc": "path/to/network.dbc",
  "traces": ["trace1.blf", "trace2.asc"],

  // === CRC Algorithm (optional — RC-only if omitted) ===
  "crc": {
    "preset": "CRC8/AUTOSAR"            // Use a built-in preset
    // OR custom:
    // "custom": {
    //   "width": 8,
    //   "poly": "0x2F",
    //   "init": "0xFF",
    //   "xor": "0xFF",
    //   "reflect_in": false,
    //   "reflect_out": false
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
    "xlsx": "path/to/dataid.xlsx",
    "sheet": "DBC_V2.5 ADAS1",           // blank = auto-detect
    "mapping": "greatwall_j6m"           // builtin name or JSON string
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
    "format": "html",                    // table | html | csv | json
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
    traces_raw = data.get("traces", [])
    if isinstance(traces_raw, str):
        traces_raw = [traces_raw]
    cfg.traces = traces_raw

    if not cfg.dbc:
        raise ValueError("Config must specify 'dbc' path.")
    if not cfg.traces:
        raise ValueError("Config must specify at least one 'traces' entry.")

    # CRC
    crc = data.get("crc", {})
    if crc:
        cfg.crc_preset = crc.get("preset", "")
        cfg.crc_custom = crc.get("custom")

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
        cfg.dataid_sheet = did.get("sheet", "")
        cfg.dataid_mapping = did.get("mapping", "")

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

    # UI
    cfg.tui = data.get("tui", False)

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
        "dbc": "test_dbc/network.dbc",
        "traces": ["test_data/trace.blf"],
        "crc": {
            "_comment": "Use 'preset' for built-in, or 'custom' for custom algorithm.",
            "preset": "CRC8/AUTOSAR"
        },
        "range": {
            "_comment": "mode: full_payload | exclude_crc | custom_range",
            "mode": "exclude_crc",
            "start_byte": 0,
            "end_byte": -1
        },
        "dataid": {
            "_comment": "Optional E2E DataID Excel. Remove entire section if not needed.",
            "xlsx": "test_dbc/dataid.xlsx",
            "sheet": "DBC_V2.5 ADAS1",
            "mapping": "greatwall_j6m"
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
        },
        "tui": False
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(example, f, indent=2, ensure_ascii=False)
