# CAN CRC Checker — Design Spec

**Date**: 2026-05-30
**Status**: Approved
**Project**: `crc_check`

## Overview

A CAN bus CRC/checksum verification tool that:

1. Parses DBC files to auto-identify Checksum and Rolling Counter signal positions
2. Reads trace files (BLF, ASC, MF4, TRC, etc.)
3. Computes expected CRC/checksum values using a parameterized CRC engine (CRC8/16/32 + custom params)
4. Compares expected vs actual, detects Rolling Counter anomalies
5. Generates reports (terminal table, HTML, CSV, JSON)
6. Provides CLI for scripting/CI, and TUI (Textual) for interactive use
7. Plugin architecture for future E2E/SecOC protection profile support

## Architecture

```
crc_checker/                    # Core library
├── crc/                        # CRC engine
│   ├── engine.py               # Parameterized CRC computer (lookup-table)
│   ├── presets.py              # Built-in presets (CRC8/AUTOSAR, J1850, CRC16/ARC, etc.)
│   └── models.py               # CRCParams, CRCRange
├── dbc/                        # DBC parsing & signal extraction
│   ├── parser.py               # canmatrix wrapper, extracts protection signals
│   ├── resolver.py             # Name-pattern matching for Checksum/RC signal pairs
│   └── models.py               # SignalInfo, MessageProtection
├── trace/                      # Trace file reading
│   ├── reader.py               # Unified reader (python-can LogReader)
│   └── models.py               # CanFrame
├── protect/                    # Protection algorithm plugins
│   ├── base.py                 # ProtectionAlgorithm ABC
│   ├── checksum.py             # CRC/Checksum verifier
│   ├── rolling_counter.py      # Rolling Counter verifier
│   └── e2e.py                  # (reserved) E2E Profile verification
├── verify/                     # Verification orchestration
│   ├── engine.py               # Frame-by-frame verification, collects results
│   └── models.py               # VerifyVerdict, VerifyReport
└── report/                     # Report generation
    ├── html.py
    ├── csv_writer.py
    └── json_writer.py

cli/
└── main.py                     # click command group

tui/
└── app.py                      # Textual App
```

**Layer dependencies**: `crc/`, `dbc/`, `trace/` are independent leaf modules. `protect/` depends on `crc/` + models. `verify/` assembles everything. `report/` consumes `verify/` models only.

## Key Data Models

### CRCParams
- `width: int` — 8, 16, 32
- `polynomial: int` — e.g. 0x2F for CRC8/AUTOSAR
- `initial_value: int` — e.g. 0xFF
- `final_xor: int` — e.g. 0xFF
- `reflect_in: bool` — byte-level reflection before computation
- `reflect_out: bool` — result reflection before XOR
- `name: str` — optional label

### CRCRange
- `mode: str` — "full_payload" | "exclude_crc" | "custom_range"
- `start_byte: int` — offset within payload (custom mode)
- `end_byte: int` — end offset (custom mode, -1 = end)
- `exclude_signals: list[str]` — signal names to zero-out

### CanFrame
- `timestamp: float`, `arbitration_id: int`, `dlc: int`, `data: bytes`
- `is_fd: bool`, `is_extended: bool`, `channel: int`

### MessageProtection
- `frame_id: int`, `frame_name: str`, `dlc: int`
- `checksum_signal: SignalInfo | None`
- `rolling_counter_signal: SignalInfo | None`
- `pair_suffix: str` — e.g. "ACC1" from "Checksum_ACC1"

### VerifyVerdict
- `frame_id, timestamp, algorithm, signal_name`
- `expected_value: int`, `actual_value: int`
- `is_pass: bool`, `detail: str`

## CRC Engine

- Lookup-table method for performance
- Shared engine across CRC8/16/32 differentiated by `width`
- XOR8 (byte sum) handled as poly=0 special case
- Built-in presets from CRC Catalogue: AUTOSAR, SAE-J1850, H2F, ARC, ETHERNET, etc.

## DBC Signal Recognition

- Default regex patterns:
  - Checksum: `(?i)^(checksum|check_sum|crc|e2e_crc|mac_check)`
  - RollingCounter: `(?i)^(rolling.?counter|rolling_?cntr|rc_|live.?counter|alive.?counter)`
- Patterns overridable via CLI `--checksum-pattern` / `--rc-pattern`
- Signals paired by common suffix within same frame (e.g., `_ACC1` matches both `Checksum_ACC1` and `RollingCounter_ACC1`)

## Trace Reading

- `python-can` LogReader for BLF, ASC, TRC, MF4
- Iterator pattern — memory-safe for large files
- Error frames and remote frames auto-skipped

## Verification Engine

### CRC Verification (stateless, per-frame)
1. Extract actual CRC value from payload bit region
2. Zero-fill CRC field in computation buffer
3. Compute CRC via CRCEngine
4. Compare expected vs actual

### Rolling Counter Verification (stateful, cross-frame)
1. Track `(frame_id, signal_name) -> prev_rc_value`
2. For each frame: `expected = (prev + 1) % (2^length)`
3. Classification: PASS, STALE (repeat), SKIP (gap>1), RESET (wrap to 0)
4. State reset on first frame seen

### Plugin Interface
```python
class ProtectionAlgorithm(ABC):
    algorithm_type: str
    def verify(self, frame: CanFrame, protection: MessageProtection) -> VerifyVerdict
```

## CLI

Command: `crc-check verify`

Required: `--dbc PATH`, `--trace PATH`

Key options:
- `--algo NAME` — preset name
- `--custom-crc JSON` — custom CRC params as JSON string
- `--range MODE` — full_payload | exclude_crc | custom
- `--range-start N`, `--range-end N`
- `--checksum-pattern REGEX`, `--rc-pattern REGEX`
- `--frame-ids ID1,ID2,...`
- `--output FORMAT` — table | html | csv | json
- `--output-file PATH`
- `--only-failures`
- `--max-frames N`
- `--tui` — launch Textual TUI
- `--verbose`

## TUI (Textual)

Tabular display with columns: Timestamp, CAN ID, Signal, Expected, Actual, Verdict.
Color coding: green=PASS, red=FAIL, yellow=RC anomaly.
Keyboard navigation: arrow keys, Enter for detail, F=filter, E=export.

## Report Formats

- **table**: Terminal output (default), grouped by frame_id
- **HTML**: Self-contained, summary cards + collapsible grouped tables
- **CSV**: Flat row-per-verdict
- **JSON**: Full structured output

## Non-Goals (v1)

- Full E2E Profile 5/11 verification (MAC + Freshness validation) — plugin interface reserved
- CAN FD-specific CRC algorithms
- Real-time CAN bus monitoring
- CANoe/CANalyzer integration
