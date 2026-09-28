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
pylint crc_checker/ cli/ webapp/

# Web version (网页版): FastAPI + Vue; frontend/dist is committed
./run_web.sh 8000          # Windows: run_web.bat 8000  → http://127.0.0.1:8000
cd frontend && npm run build   # rebuild dist after frontend changes
cd frontend && npm test        # frontend unit tests (node --test)

# Run the CLI (after pip install -e .)
crc-check presets                      # List available CRC presets
crc-check inspect path/to/file.dbc     # Inspect DBC for protection signals
crc-check gen-config example.json      # Generate example config
crc-check run -c config.json           # Run from config file
crc-check preprocess-dataid --xlsx d.xlsx -o d.json   # Preprocess DataID

# Build + package
build.bat                  # Build standalone exe
package.bat                # Package all customers → release/*.zip
package.bat gac/eea40      # Package GAC EEA4.0 only
package.bat gac/radar      # Package GAC radar buses only
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
├── gac/                   # 按平台组织（DBC/DataID 表按平台发布，算法与 DataID 数值全项目一致）
│   ├── eea40/             # GAC EEA4.0 平台 (t75/t996d/v20) — Profile 5 + Profile 1
│   ├── eea30-hev/         # GAC EEA3.0 混动平台 (t09/t68/t88)
│   ├── eea30-bev/         # GAC EEA3.0 纯电AB 平台 (s52/s52-e046，DataID 表是 .xls)
│   ├── radar/             # GAC 雷达私有总线 (FR/FLR/FRR/RLR/RRR，P01 30 字节段)
│   └── README.md          # 平台↔项目对照、通用性结论、新平台接入步骤
├── chery/
│   ├── t1jfl3/            # Chery T1J FL3 (E2E Profile 1A + DataID)
│   ├── fx12fl/            # Chery FX12 FL (J1850 CRC-8 / SUM8/XOR-FF / XOR8/SEED)
└── baic/
    └── b81vs/             # BAIC B81VS (Profile 1A + DataID / SUM8/XOR-FF)
```

To add a new customer: create `customers/<oem>/<model>/` with `config.json`, `run.bat`, `run.sh`, `dbc/` and `trace/` directories.

## Architecture

**Layer dependencies:** `crc/`, `dbc/`, `trace/`, `dataid/`, `bit_utils.py` are independent leaf modules. `protect/` depends on `crc/` + models. `verify/` assembles everything. `report/` consumes `verify/` models only.

### Core modules

- **`crc_checker/crc/`** — Parameterized CRC engine using lookup-table method. `engine.py` computes CRC8/16/32 with both reflected and non-reflected algorithms, plus fx12fl non-CRC checksums (`sum_xor`, `xor_seed`). `presets.py` holds 13 built-in presets: CRC8/AUTOSAR, CRC8/SAE-J1850, CRC8/SAE-J1850-ZERO, CRC8/H2F, CRC16/ARC, CRC16/MODBUS, **CRC16/CCITT (E2E Profile 5)**, CRC32/AUTOSAR, CRC32/ETHERNET, XOR8, **SUM8**, **SUM8/XOR-FF**, **XOR8/SEED**. `classify.py` auto-classifies per-message algorithms from DBC comments (fx12fl: J1850 CRC-8 / sum-XOR 0xFF / byte-wise XOR with seed; b81vs: Profile 1A + DataID / plain SUM8 / skip, plus the covered byte range of sum checksums so multi-segment CAN FD frames sum only their own 8-byte block; GAC `E2E Profile 5` → `p05`, handled by the profile table instead of a preset). `profiles.py` defines the E2E profile table (see below). `models.py` defines `CRCParams` (immutable/frozen) and `CRCRange` (mode + byte range + DataID config + byte_swap).

- **`crc_checker/crc/profiles.py`** — `E2EProfile` table: per-profile algorithm, DataID position/byte order, byte swap and CRC range. Built-ins: `p01` (CRC8/SAE-J1850-ZERO, DataID prepend, range inherited) and `p05` (CRC16/CCITT, append, byte swap, `custom_range 0..56`). `load_profiles()` merges `crc.profiles` from config.json; `profile_key_from_width()` implements the firmware rule (2 B → P5, 1 B → P1). Applied per protection group by `DBCProtectionMap.apply_profiles()`, so one bus can mix P5 and P1 with different DataID layouts.

- **`crc_checker/dbc/`** — `parser.py` wraps `canmatrix` to load DBC files (encoding auto-detected: utf-8 → gbk → latin-1, so GBK matrices like BAIC's keep their Chinese comments). `resolver.py` uses regex matching for Checksum/RC signal pairs. Supports both **prefix-based** naming (`Checksum_*`, `CRC_*`) and **suffix-based** naming (`*_CRC`, `*_Counter`) via auto-detection (`detect_naming_convention()`); indexed instances (`SRS_1_CRC_1` / `SRS_1_CRC_2`, `_Counter_<n>`) stay separate groups (GAC CCU_SRS_1 carries two E2E instances). Radar sensor frames are matched too: a trailing bus marker is stripped (`SGU1_Msg_CheckSum_Can03` → `SGU1_Msg_CheckSum`) and `*_BlockCounter` is explicitly not a rolling counter (only `*_Msg_AliveCounter` counts frames). `models.py` defines `DBCProtectionMap`, `ChannelProtectionMap` (per-channel DBC assignment), `MessageProtection` (with `crc_profile` hint + resolved `e2e_profile`), plus `apply_profiles()` / `apply_range_overrides()` / `apply_skip()`.

- **`crc_checker/trace/`** — `reader.py` wraps `python-can.LogReader` with iterator pattern. `CanFrame` dataclass: timestamp, arbitration_id, dlc, data (bytes), is_fd, is_extended, channel.

- **`crc_checker/dataid/`** — Parses OEM-specific Excel files for DataID mappings. `parser.py` reads Excel with `ColumnMapping` config. Built-in mappings: `greatwall_j6m` (GWM hi_lo_two_cols), `gac_eea4` (GAC single_16bit), `generic_abc`, `simple_8bit`. Falls back to zipfile-based parser when openpyxl fails, and reads legacy `.xls` (BIFF) workbooks via `xlrd` (GAC EEA3.0纯电平台). DataID rows are registered under the message name **and** under the CRC signal name found in the Remark column (`SRS_1_CRC2`), so messages with several E2E instances keep one DataID each; `DataIDMap.get_normalized()` matches names ignoring underscores/case. DataID JSON fast-path via `dataid.json` for subsequent runs. `DataIDMap` stores optional `crc_profile` per entry for algorithm overrides.

- **`crc_checker/bit_utils.py`** — Extracts/zeros signal bits from CAN payload. Handles Intel (LE) and Motorola (BE) via `_extract_motorola()` / `_extract_intel()`. Motorola extraction handles multi-byte signals (>8 bits) with correct cross-byte boundary logic.

- **`crc_checker/protect/`** — Plugin architecture via `ProtectionAlgorithm` ABC in `base.py`. `checksum.py` (CRCVerifier, stateless, supports byte_swap for Profile 5 LE→BE conversion). `rolling_counter.py` (stateful, tracks per-(frame_id, signal)). RC detects: PASS, STALE (repeat), SKIP (gap>1), RESET (wrap), INVALID (>max_valid).

- **`crc_checker/verify/`** — `engine.py` orchestrates verification: iterates trace frames, matches against protection map, runs algorithms, collects `VerifyVerdict`s into `VerifyReport`. `models.py` defines `VerifyVerdict` and `VerifyReport`.

- **`crc_checker/report/`** — `html.py` generates self-contained HTML with dark theme, CRC/RC byte highlighting (green/red borders), hover tooltips with expected/actual values, per-segment hex dump with DataID display, channel/DBC source tags, collapsible sections, and filter buttons.

### Web version (网页版)

`webapp/` (FastAPI) + `frontend/` (Vue 3 + Element Plus; `frontend/dist` is committed so
the deploy machine needs no Node). Start with `./run_web.sh 8000`.

- `webapp/catalog.py` — scans `customers/<oem>/<model>/config.json`. The browser only ever
  sends a project **id**, never a path; the server resolves everything else.
- `webapp/service.py` — bridges the shared runner to the web: temp upload → run → JSON +
  self-contained HTML report. Finished runs are cached LRU (20) under `data/web/`
  (gitignored); the uploaded trace is deleted right after the run.
- `webapp/main.py` — `/api/projects`, `/api/verify` (multipart), `/api/runs/{id}/report.html`,
  `/api/version`; `frontend/dist` is mounted last so every `/api` route wins.
- `webapp/version.py` — the **commit 节点** view: `running` (commit/branch/subject/dirty) is
  pinned at import time, `checkout` is re-read on every `/api/version` call so a `git pull`
  without restart shows "部署目录与服务启动时的版本状态不同"; `dirty` is scoped to runtime
  paths; git unavailable → all-None "版本未知" (never an error). Mirrors the reference
  `evm-fault-analyzer` deployment-version design.

`crc_checker/verify/runner.py` is the single implementation of "DBC selection → DataID →
CRC config → verify" — `crc-check run` and `POST /api/verify` both call it, so the CLI and
the web cannot drift apart. Details: [docs/web-api.md](docs/web-api.md).

### CLI

Entry point: `cli/main.py` — Click command group: `verify`, `run`, `gen-config`, `presets`, `inspect`, `preprocess-dataid`. The `run` command uses JSON config via `crc_checker/config.py`.

### JSON Config Reference

Key config sections (see `config.py` `CONFIG_SCHEMA_DOC` for full reference):

| Section | Field | Description |
|---------|-------|-------------|
| `crc` | `preset` | CRC preset name (e.g. `CRC16/CCITT`, `CRC8/SAE-J1850-ZERO`) |
| | `byte_swap` | Swap computed CRC bytes before compare (Profile 5: `true`) |
| | `profiles` | Per-profile overrides: `preset`, `dataid_position`, `byte_swap`, `range` (GAC: `p01` gets `custom_range 0..-1`) |
| | `profile_by_width` | Pick profile from the CRC signal width (2 B → P5, 1 B → P1) |
| | `range_overrides` | Per-message/signal range: `{"SRS_1_CRC_2": {"mode": "custom_range", "start_byte": 13, "end_byte": 32}}` |
| | `skip` | Frame ids/names/signal names left unverified (`["SYNC_FC_CRC"]`) |
| `range` | `mode` | `exclude_crc` / `full_payload` / `custom_range` |
| | `start_byte`, `end_byte` | For `custom_range` (Profile 5 64B: `0, 56`) |
| `dataid` | `xlsx` / `json` | Excel path (`.xlsx` or legacy `.xls`) / Preprocessed JSON (fast load) |
| | `mapping` | `greatwall_j6m` / `gac_eea4` / custom JSON |
| | `position` | `prepend` (GWM, Profile 1) / `append` (Profile 5) |
| | `byte_order` | `lo_hi` (default) / `hi_lo` |
| `signals` | `checksum_pattern` | Custom regex override (null = auto-detect) |
| | `rc_pattern` | Custom regex override |
| `rc` | `max_valid` | Max RC value before wrap (null = auto from bit length) |

### E2E Profile Support

| Profile | CRC Algorithm | DataID Position | CRC Width | Byte Swap | Example Config |
|---------|--------------|-----------------|-----------|-----------|----------------|
| **Profile 5** | CRC16/CCITT | append lo_hi | 16-bit | yes | `customers/gac/eea40/` |
| **Profile 1** | CRC8/SAE-J1850-ZERO | prepend lo_hi | 8-bit | no | `customers/gwm/`, GAC 8-bit messages (counter 0..14) |

Profile selection (GAC): `crc.profile_by_width: true` picks the profile from the CRC
signal width — the firmware rule (2 B → P5, 1 B → P1, see mcu_app_j6 `31bd82bcf`).
Per-group `crc_range` then carries the DataID layout, so P5 (append) and P1 (prepend)
coexist on one bus. GAC extras: `crc.range_overrides` (CCU_SRS_1 second segment
13..32) and `crc.skip` (CCU_TimeSync `SYNC_FC_CRC` is not E2E).

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

161 tests in `tests/` — CRC engine known vectors (incl. SUM8/XOR-FF + XOR8/SEED), fx12fl + b81vs comment auto-classification (Profile 1A DataID / SUM8 / skip), GBK DBC decoding (BAIC comments keep their full-width punctuation, so the Profile 1A DataID parses), comment-derived sum-checksum byte ranges + Profile 1 counter max (b81vs matrix), DBC resolver signal matching, suffix extraction, custom patterns, protection map merge logic, GAC E2E (`tests/test_gac_e2e.py`: profile selection by CRC width, multi-CRC messages, per-message ranges, skip list, legacy `.xls` DataID workbooks, radar `_Msg_CheckSum_CanNN` / block-counter naming), and the web layer (`tests/test_webapp.py`: project scan, deployment-version semantics, shared runner, upload → verify → report via the real committed traces). Frontend pure-logic tests run with `cd frontend && npm test` (`node --test`).
