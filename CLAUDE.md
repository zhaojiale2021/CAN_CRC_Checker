# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAN bus CRC/Rolling Counter verification tool. Parses DBC files to auto-identify Checksum and RollingCounter signal positions, computes expected CRC values with configurable algorithms, and compares against actual values from trace files (BLF, ASC, MF4, TRC). Supports E2E Profile 5 (CRC16/CCITT) and Profile 1 (CRC8/SAE-J1850). See [docs/superpowers/specs/2026-05-30-crc-checker-design.md](docs/superpowers/specs/2026-05-30-crc-checker-design.md) for the full design spec.

## Commands

```bash
# Install dev environment
pip install -r requirements.txt
pip install -e .

# Run tests (all)
pytest

# Run a single test
pytest tests/test_crc_engine.py::TestCRCEngine::test_crc8_autosar_known_vector

# Run with coverage
pytest --cov=crc_checker

# Lint (pylint 10.00/10 required by CI)
pylint crc_checker/ cli/

# Run the CLI (after pip install -e .)
crc-check presets                      # List available CRC presets
crc-check inspect path/to/file.dbc     # Inspect DBC for protection signals
crc-check gen-config example.json      # Generate example config
crc-check run -c config.json           # Run from config file
crc-check preprocess-dataid --xlsx d.xlsx -o d.json   # Preprocess DataID

# Build + package
build.bat                  # Build standalone exe
package.bat                # Package all customers → release/*.zip
package.bat gac/t75        # Package GAC T75 only
./package.sh               # Linux: package all
./package.sh chery/t1jfl3  # Linux: package Chery only
```

## Customer Directory Structure

```
customers/
├── gwm/
│   ├── de09g/             # GWM J6B DE09G (CRC8/SAE-J1850-ZERO)
│   │   ├── config.json, run.bat, run.sh
│   │   ├── dbc/           # DBC files + DataID xlsx/json
│   │   └── trace/         # BLF trace files
│   └── b06-5/             # GWM J6M B06-5 (CRC8/SAE-J1850-ZERO)
└── gac/
    └── t75/               # GAC Trumpchi T75 (E2E Profile 5 + Profile 1A)
        ├── config.json, run.bat, run.sh
        ├── dbc/           # DBC files + DataID xlsx/json
        └── trace/
```

To add a new customer: create `customers/<oem>/<model>/` with `config.json`, `run.bat`, `run.sh`, `dbc/` and `trace/` directories.

## Architecture

**Layer dependencies:** `crc/`, `dbc/`, `trace/`, `dataid/`, `bit_utils.py` are independent leaf modules. `protect/` depends on `crc/` + models. `verify/` assembles everything. `report/` consumes `verify/` models only.

### Core modules

- **`crc_checker/crc/`** — Parameterized CRC engine using lookup-table method. `engine.py` computes CRC8/16/32 with both reflected and non-reflected algorithms, plus fx12fl non-CRC checksums (`sum_xor`, `xor_seed`). `presets.py` holds 12 built-in presets: CRC8/AUTOSAR, CRC8/SAE-J1850, CRC8/SAE-J1850-ZERO, CRC8/H2F, CRC16/ARC, CRC16/MODBUS, **CRC16/CCITT (E2E Profile 5)**, CRC32/AUTOSAR, CRC32/ETHERNET, XOR8, **SUM8/XOR-FF**, **XOR8/SEED**. `classify.py` auto-classifies fx12fl per-message algorithms from DBC comments (J1850 CRC-8 / sum-of-bytes XOR 0xFF / byte-wise XOR with seed). `models.py` defines `CRCParams` (immutable/frozen) and `CRCRange` (mode + byte range + DataID config + byte_swap).

- **`crc_checker/dbc/`** — `parser.py` wraps `canmatrix` to load DBC files. `resolver.py` uses regex matching for Checksum/RC signal pairs. Supports both **prefix-based** naming (`Checksum_*`, `CRC_*`) and **suffix-based** naming (`*_CRC`, `*_Counter`) via auto-detection (`detect_naming_convention()`). `models.py` defines `DBCProtectionMap`, `ChannelProtectionMap` (per-channel DBC assignment), `MessageProtection` (with `crc_profile` for algorithm overrides).

- **`crc_checker/trace/`** — `reader.py` wraps `python-can.LogReader` with iterator pattern. `CanFrame` dataclass: timestamp, arbitration_id, dlc, data (bytes), is_fd, is_extended, channel.

- **`crc_checker/dataid/`** — Parses OEM-specific Excel files for DataID mappings. `parser.py` reads Excel with `ColumnMapping` config. Built-in mappings: `greatwall_j6m` (GWM hi_lo_two_cols), `gac_eea4` (GAC single_16bit), `generic_abc`, `simple_8bit`. Falls back to zipfile-based parser when openpyxl fails. DataID JSON fast-path via `dataid.json` for subsequent runs. `DataIDMap` stores optional `crc_profile` per entry for algorithm overrides.

- **`crc_checker/bit_utils.py`** — Extracts/zeros signal bits from CAN payload. Handles Intel (LE) and Motorola (BE) via `_extract_motorola()` / `_extract_intel()`. Motorola extraction handles multi-byte signals (>8 bits) with correct cross-byte boundary logic.

- **`crc_checker/protect/`** — Plugin architecture via `ProtectionAlgorithm` ABC in `base.py`. `checksum.py` (CRCVerifier, stateless, supports byte_swap for Profile 5 LE→BE conversion). `rolling_counter.py` (stateful, tracks per-(frame_id, signal)). RC detects: PASS, STALE (repeat), SKIP (gap>1), RESET (wrap), INVALID (>max_valid).

- **`crc_checker/verify/`** — `engine.py` orchestrates verification: iterates trace frames, matches against protection map, runs algorithms, collects `VerifyVerdict`s into `VerifyReport`. `models.py` defines `VerifyVerdict` and `VerifyReport`.

- **`crc_checker/report/`** — `html.py` generates self-contained HTML with dark theme, CRC/RC byte highlighting (green/red borders), hover tooltips with expected/actual values, per-segment hex dump with DataID display, channel/DBC source tags, collapsible sections, and filter buttons.

### CLI

Entry point: `cli/main.py` — Click command group: `verify`, `run`, `gen-config`, `presets`, `inspect`, `preprocess-dataid`. The `run` command uses JSON config via `crc_checker/config.py`.

### JSON Config Reference

Key config sections (see `config.py` `CONFIG_SCHEMA_DOC` for full reference):

| Section | Field | Description |
|---------|-------|-------------|
| `crc` | `preset` | CRC preset name (e.g. `CRC16/CCITT`, `CRC8/SAE-J1850-ZERO`) |
| | `byte_swap` | Swap computed CRC bytes before compare (Profile 5: `true`) |
| `range` | `mode` | `exclude_crc` / `full_payload` / `custom_range` |
| | `start_byte`, `end_byte` | For `custom_range` (Profile 5 64B: `0, 56`) |
| `dataid` | `xlsx` / `json` | Excel path / Preprocessed JSON (fast load) |
| | `mapping` | `greatwall_j6m` / `gac_eea4` / custom JSON |
| | `position` | `prepend` (GWM, Profile 1) / `append` (Profile 5) |
| | `byte_order` | `lo_hi` (default) / `hi_lo` |
| `signals` | `checksum_pattern` | Custom regex override (null = auto-detect) |
| | `rc_pattern` | Custom regex override |
| `rc` | `max_valid` | Max RC value before wrap (null = auto from bit length) |

### E2E Profile Support

| Profile | CRC Algorithm | DataID Position | CRC Width | Byte Swap | Example Config |
|---------|--------------|-----------------|-----------|-----------|----------------|
| **Profile 5** | CRC16/CCITT | append lo_hi | 16-bit | yes | `customers/gac/t75/` |
| **Profile 1** | CRC8/SAE-J1850-ZERO | prepend lo_hi | 8-bit | no | `customers/gwm/` |

### Key data flow

1. DBC parsed → `DBCProtectionMap` (dict of frame_id → list of `MessageProtection`)
2. DataID loaded (JSON fast-path or Excel) → applied to protection map via multi-strategy matching
3. CRC params + range + profile overrides applied
4. `TraceReader` yields `CanFrame` objects
5. `VerifyEngine.run()` iterates frames, dispatches to `ProtectionAlgorithm.verify()` per group
6. CRCVerifier extracts signal bits, computes expected value (with optional byte_swap), compares
7. Results in `VerifyReport` → rendered as HTML

### Auto-detect behavior

- **Signal naming**: Auto-detects prefix-based (GWM: `Checksum_*`) vs suffix-based (GAC: `*_CRC`) conventions via `detect_naming_convention()`. Requires ≥3 suffix-only matches and zero prefix matches to enable suffix mode.
- **CRC range**: Default `exclude_crc`. For CAN FD + DataID, auto-switches to segment mode. Profile 5 uses `custom_range` with end_byte=56 for 64B messages.
- **RC max_valid**: Default `(1 << signal_length) - 1`. Profile 1 uses `max_valid=14` for 4-bit RC.

### Testing

44 tests in `tests/` — CRC engine known vectors (incl. SUM8/XOR-FF + XOR8/SEED), fx12fl comment auto-classification, DataID serialization, DBC resolver signal matching, suffix extraction, custom patterns, and protection map merge logic.
