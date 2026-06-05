# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAN bus CRC/Rolling Counter verification tool. Parses DBC files to auto-identify Checksum and RollingCounter signal positions, computes expected CRC values with configurable algorithms, and compares against actual values from trace files (BLF, ASC, MF4, TRC). See [docs/superpowers/specs/2026-05-30-crc-checker-design.md](docs/superpowers/specs/2026-05-30-crc-checker-design.md) for the full design spec.

## Commands

```bash
# Install dev environment
pip install -r requirements.txt
pip install -e .

# Run tests (all)
pytest

# Run a single test file
pytest tests/test_crc_engine.py

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
crc-check verify --dbc x.dbc --trace t.blf --algo CRC8/AUTOSAR  # Direct CLI

# Build standalone .exe (Windows only)
build.bat
```

## Architecture

**Layer dependencies:** `crc/`, `dbc/`, `trace/`, `dataid/`, `bit_utils.py` are independent leaf modules. `protect/` depends on `crc/` + models. `verify/` assembles everything. `report/` consumes `verify/` models only.

Each package's `__init__.py` re-exports its public API (key classes and functions). When importing across modules, prefer the package-level imports (e.g., `from crc_checker.crc import CRCParams, CRCConfig, CRCEngine`).

### Core modules

- **`crc_checker/crc/`** — Parameterized CRC engine using lookup-table method. [`engine.py`](crc_checker/crc/engine.py) computes CRC8/16/32 with both reflected (right-shifting) and non-reflected (left-shifting) algorithms. [`presets.py`](crc_checker/crc/presets.py) holds 9 built-in automotive presets (AUTOSAR, SAE-J1850, H2F, MODBUS, ETHERNET, etc.). [`models.py`](crc_checker/crc/models.py) defines `CRCParams` (immutable/frozen) and `CRCRange` (mode + byte range + DataID for E2E).

- **`crc_checker/dbc/`** — [`parser.py`](crc_checker/dbc/parser.py) wraps `canmatrix` to load DBC files. [`resolver.py`](crc_checker/dbc/resolver.py) uses regex pattern matching to identify Checksum/RC signal pairs by naming convention and pairs them by common suffix (e.g., `Checksum_ACC1` + `RollingCounter_ACC1` → pair_suffix="ACC1"). Default patterns match `Checksum_*`, `CRC_*`, `E2E_CRC_*` and `RollingCounter_*`, `RC_*`, `LiveCounter_*`. Custom patterns can override via `--checksum-pattern` / `--rc-pattern`.

- **`crc_checker/trace/`** — [`reader.py`](crc_checker/trace/reader.py) wraps `python-can.LogReader` with iterator pattern for memory-safe reading of large files. Skips error frames and remote frames. `CanFrame` dataclass: timestamp, arbitration_id, dlc, data (bytes), is_fd, is_extended, channel.

- **`crc_checker/dataid/`** — Parses OEM-specific Excel files for DataID mappings (AUTOSAR E2E). [`parser.py`](crc_checker/dataid/parser.py) reads Excel with `ColumnMapping` config. [`presets.py`](crc_checker/dataid/presets.py) has built-in column mappings: `greatwall_j6m`, `generic_abc`, `simple_8bit`. [`models.py`](crc_checker/dataid/models.py) defines `ColumnMapping` and `DataIDEntry`. Custom mappings can be provided via JSON. DataID is prepended (low byte first) to payload before CRC computation.

- **`crc_checker/bit_utils.py`** — Extracts/zeros signal bits from CAN payload. Handles both Intel (little-endian, start_bit = LSB) and Motorola (big-endian, start_bit = MSB with canmatrix's inverted bit numbering). Critical: `_canmatrix_to_physical_msb()` converts canmatrix's internal bit numbering to physical positions for Motorola signals.

- **`crc_checker/protect/`** — Plugin architecture via `ProtectionAlgorithm` ABC (algorithm_type + verify() + reset()). Two implementations: [`checksum.py`](crc_checker/protect/checksum.py) (CRCVerifier, stateless) and [`rolling_counter.py`](crc_checker/protect/rolling_counter.py) (stateful, tracks per-(frame_id, signal) across frames). RC detects: PASS, STALE (repeat), SKIP (gap>1), RESET (unexpected wrap to 0), INVALID (exceeds max_valid). [`models.py`](crc_checker/protect/models.py) defines the `ProtectionAlgorithm` ABC and `ProtectionGroup` dataclass.

- **`crc_checker/verify/`** — [`engine.py`](crc_checker/verify/engine.py) orchestrates verification: iterates trace frames, matches against `DBCProtectionMap`, runs each algorithm on each protection group, collects `VerifyVerdict`s into `VerifyReport`. Also provides `run_stream()` for streaming results. [`models.py`](crc_checker/verify/models.py) defines `VerifyVerdict` (per-frame verdict: PASS/FAIL/ERROR with metadata), `SegmentReport` (per-protection-group aggregated stats), and `VerifyReport` (top-level report with all segments).

- **`crc_checker/report/`** — [`html.py`](crc_checker/report/html.py) generates self-contained HTML with dark theme, summary cards, collapsible frame sections, per-segment hex-dump with inline CRC/RC byte highlighting, hover tooltips, and filter buttons (All/Errors/Expand/Collapse).

### CLI

Entry point: [`cli/main.py`](cli/main.py) — Click command group with `verify`, `run`, `gen-config`, `presets`, `inspect` subcommands. The `run` command uses JSON config via [`crc_checker/config.py`](crc_checker/config.py) (`RunConfig` dataclass + `load_config()` with path resolution relative to config file location). `RunConfig` fields: `dbc_path`, `trace_path`, `output_path`, `crc_algorithm`, `crc_range` (mode + start/end), `dataid_config`, `checksum_pattern`, `rc_pattern`, `rc_max_valid`.

### Key data flow

1. DBC parsed → `DBCProtectionMap` (dict of frame_id → list of `MessageProtection`)
2. CRC params + range + DataID applied to protection map
3. `TraceReader` yields `CanFrame` objects
4. `VerifyEngine.run()` iterates frames, dispatches to `ProtectionAlgorithm.verify()` per protection group
5. Each verifier extracts signal bits via `bit_utils.extract_signal_bits()`, computes expected value, compares
6. Results collected in `VerifyReport` → rendered as table (terminal) or HTML

### Auto-detect behavior

- **CRC range**: When no explicit range is set, defaults to `exclude_crc` (full payload minus CRC bytes). For CAN FD frames (DLC > 8) with DataID, auto-switches to 8-byte segment mode.
- **RC max_valid**: When not set, defaults to `(1 << signal_length) - 1`. When set (e.g., 14 for 4-bit RC), values > max_valid are flagged as INVALID.

### Testing

Tests use pytest with known CRC test vectors (CRC Catalogue "123456789" check string). `test_crc_engine.py` validates all presets against known values. `test_dbc_resolver.py` tests signal name matching, suffix extraction, pairing logic, and custom pattern overrides.
