# CAN CRC Checker

DBC-aware CAN bus CRC / rolling-counter verification. It parses a DBC, finds the
checksum and rolling-counter signals, computes the expected values with the
configured algorithm, and compares them with the frames in a trace file
(BLF / ASC / MF4 / TRC / CSV).

The repository ships **only synthetic example data**. Signal-name patterns and
DataID workbook layouts are configuration files, so a new OEM naming convention
or Excel layout does not require code changes.

## Supported algorithms and validation status

"Verified with real data" means the algorithm reproduced the expected values on
captured CAN traces during development of this tool. Algorithms marked
**not verified** are implemented and unit-tested against known vectors, but have
not been checked against real vehicle data in this repository.

| Preset | Use | Status |
|--------|-----|--------|
| `CRC16/CCITT` | AUTOSAR E2E Profile 5 | ✅ verified with real data |
| `CRC8/SAE-J1850-ZERO` | AUTOSAR E2E Profile 1 / 1A | ✅ verified with real data |
| `CRC8/SAE-J1850` | DBC-comment checksums (SAE J1850) | ✅ verified with real data |
| `SUM8/XOR-FF` | sum of bytes `& 0xFF`, then `XOR 0xFF` | ✅ verified with real data |
| `XOR8/SEED` | byte-wise XOR with a constant seed | ✅ verified with real data |
| `SUM8` | plain additive sum `& 0xFF` | ✅ verified (wider field variants not verified) |
| `CRC8/AUTOSAR` | — | ⚠️ not verified with real data |
| `CRC8/H2F` | — | ⚠️ not verified with real data |
| `CRC16/ARC` | — | ⚠️ not verified with real data |
| `CRC16/MODBUS` | — | ⚠️ not verified with real data |
| `CRC32/AUTOSAR` | — | ⚠️ not verified with real data |
| `CRC32/ETHERNET` | — | ⚠️ not verified with real data |
| `XOR8` | plain byte-wise XOR | ⚠️ not verified with real data |

`crc-check presets` prints the same status next to every preset; the tables in
[docs/supported-algorithms.md](docs/supported-algorithms.md) list the evidence.

## Install

```bash
pip install -r requirements.txt
pip install -e .
```

Requires Python 3.9+.

## Quick start

```bash
# Run the synthetic example (all checks pass)
crc-check run -c examples/example/config.json -v

# Inspect which protection signals a DBC contains
crc-check inspect examples/example/dbc/network.dbc

# List presets and their validation status
crc-check presets

# Regenerate the example project (DBC + trace + DataID)
python examples/generate_example.py
```

Or directly:

```bash
crc-check verify \
  --dbc examples/example/dbc/network.dbc \
  --trace examples/example/trace/example.blf \
  --algo CRC8/SAE-J1850-ZERO \
  --output html --output-file report.html
```

## Configuration

A run is described by a JSON file (`crc-check gen-config` writes an annotated
example). The main sections:

| Section | Field | Description |
|---------|-------|-------------|
| `crc` | `preset` | Preset name, or `custom` for inline parameters |
| | `byte_swap` | Swap the computed CRC bytes before comparison (Profile 5) |
| | `auto_classify` | Pick the algorithm per message from DBC comments |
| | `profile_by_width` | Pick Profile 5 for 2-byte CRCs, Profile 1 for 1-byte CRCs |
| | `profiles` | Per-profile overrides (`preset`, DataID layout, range, `counter_max_valid`) |
| | `range_overrides` | Per-message/signal CRC byte range |
| | `skip` | Frame ids/names/signal names left unverified |
| `range` | `mode` | `exclude_crc` / `full_payload` / `custom_range` |
| `dataid` | `json` / `xlsx` | Preprocessed JSON (fast path) or Excel workbook |
| | `mapping` / `mapping_file` | DataID column layout |
| | `position` | `prepend` (Profile 1) / `append` (Profile 5) |
| `signals` | `checksum_patterns` / `rc_patterns` | Extra signal-name regexes |
| | `patterns_file` | Custom YAML with signal-name patterns |
| | `checksum_pattern` / `rc_pattern` | Single regex; replaces the matching above |
| `rc` | `max_valid` | Max valid counter value (default: `2^bits - 1`) |
| `output` | `max_report_sections` | Frame-section cap (default 30000, 0 = unlimited) |

### Extending CRC / RC signal matching

Signal-name rules live in
[`crc_checker/data/patterns.yaml`](crc_checker/data/patterns.yaml). Add a regex
to the relevant list and the resolver picks it up:

```yaml
checksum:
  prefix: ['(?i)^(checksum|check_sum|crc|e2e_crc)']
  suffix: ['(?i)(_crc|_checksum|_chks)([0-9_]*)$']
rolling_counter:
  prefix: ['(?i)^(rolling.?counter|rc_|alive.?counter)']
  suffix: ['(?i)(_counter|_cntr|_msgcntr)([0-9_]*)$']
  exclude: ['(?i)block_?counter']
```

Point `signals.patterns_file` at your own copy to keep local rules separate, or
use `signals.checksum_patterns` / `signals.rc_patterns` in `config.json`.

### Extending DataID workbook layouts

Column layouts live in
[`crc_checker/data/dataid_mappings.yaml`](crc_checker/data/dataid_mappings.yaml).
Each entry is a named `ColumnMapping`: signal-name column, message-id column,
DataID column(s), format, header row and filters. Select it with
`dataid.mapping`, or provide your own file with `dataid.mapping_file`.

## Web version

```bash
./run_web.sh 8000          # Windows: run_web.bat 8000
# http://127.0.0.1:8000
```

The browser selects a project id, uploads a trace, and gets a summary plus a
downloadable self-contained HTML report. Projects are scanned from `projects/`
(or `examples/` when `projects/` does not exist; override with
`CRC_CHECKER_PROJECTS_DIR`). See [docs/web-api.md](docs/web-api.md).

The Vue frontend is committed as `frontend/dist`, so a deployment machine does
not need Node. Rebuild after frontend changes:

```bash
cd frontend && npm install && npm run build
```

## Repository layout

```
crc_checker/            Core package
  crc/                  CRC engine, presets, E2E profiles, comment classifier
  dbc/                  DBC parser + signal resolver
  dataid/               DataID Excel/JSON parser
  trace/                Trace reader (BLF/ASC/MF4/TRC/CSV)
  protect/              CRC and rolling-counter verifiers
  verify/               Verification orchestration (shared by CLI and web)
  report/               Self-contained HTML report + RC trend charts
  data/                 Shipped pattern and DataID-mapping defaults
cli/                    Click CLI
webapp/                 FastAPI backend
frontend/               Vue 3 + Element Plus (dist committed)
examples/               Synthetic example project + generator
tests/                  pytest suite
```

## Testing

```bash
pytest
pylint crc_checker/ cli/ webapp/
cd frontend && npm test
```

## License

MIT — see [LICENSE](LICENSE).
