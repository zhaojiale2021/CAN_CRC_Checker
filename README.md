<div align="center">

# CAN CRC Checker

DBC-aware CAN bus CRC / rolling-counter verification for BLF, ASC, MF4 and TRC traces.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/zhaojiale2021/CAN_CRC_Checker/actions/workflows/pylint.yml/badge.svg)](https://github.com/zhaojiale2021/CAN_CRC_Checker/actions/workflows/pylint.yml)

[English](./README.md) | [🌍 中文](./docs/zh-CN/README.md)

</div>

---

Point it at a DBC and a captured trace. It finds the checksum and rolling-counter
signals by name, computes the expected values with the configured algorithm, and
reports every mismatch with a self-contained HTML report. No vehicle-specific
code: signal-name patterns and DataID workbook layouts are configuration files.

The repository ships **only synthetic example data**.

## 🚀 30-second start

```bash
git clone https://github.com/zhaojiale2021/CAN_CRC_Checker.git
cd CAN_CRC_Checker
pip install -r requirements.txt

# Run the bundled example (CLI; no packaging step, no .exe)
python -m cli.main run -c examples/example/config.json -v

# Optional: install the `crc-check` command
pip install -e .
crc-check run -c examples/example/config.json -v
crc-check presets
crc-check inspect examples/example/dbc/network.dbc
```

Expected output: 160 frames, 320 checks, 100 % pass.

```bash
# Deliberately broken example → failures + RC error trends
python -m cli.main run -c examples/example/config_bad.json -v
```

## 🌐 Web version

```bash
./run_web.sh 8000          # Windows: run_web.bat 8000
# http://127.0.0.1:8000
```

Select a project id, upload a trace, and get a summary, failure table and HTML
report. The browser only sends project ids; paths stay server-side. Projects are
scanned from `projects/` (or `examples/` when `projects/` does not exist; override
with `CRC_CHECKER_PROJECTS_DIR`). The Vue frontend is committed as
`frontend/dist`, so a deployment machine needs no Node. See
[docs/web-api.md](docs/web-api.md).

## 🌟 What you get

| When you need… | What it does |
| --- | --- |
| **Find protection signals automatically** | Prefix (`Checksum_*`, `CRC_*`) and suffix (`*_CRC`, `*_Counter`) naming, indexed E2E instances, sensor bus markers, block-counter exclusion — all driven by YAML regexes |
| **Verify E2E profiles** | Profile 5 (CRC16/CCITT, DataID append, byte swap) and Profile 1/1A (CRC8/SAE-J1850-ZERO, DataID prepend, 4-bit counter) |
| **Non-CRC checksums** | SUM8, SUM8/XOR-FF, XOR8/SEED, selected per message from DBC comments |
| **Many trace formats** | BLF, ASC, MF4, TRC, CSV/LOG via python-can |
| **Big traces** | Streaming verification, cached CRC engines, decimated RC trend charts, report size guard |
| **DataID tables** | `.xlsx`, legacy `.xls` and preprocessed JSON; named column layouts from YAML |
| **Reproducible results** | CLI and web share one runner (`crc_checker/verify/runner.py`) |

## 🧮 Supported algorithms

Verified with real data means the algorithm reproduced expected values on
captured CAN traces during development. Everything else is implemented and
unit-tested against known-answer vectors, but **not verified with real data** —
`crc-check presets` prints the same status.

| Preset | Use | Status |
| --- | --- | --- |
| `CRC16/CCITT` | AUTOSAR E2E Profile 5 | ✅ verified with real data |
| `CRC8/SAE-J1850-ZERO` | AUTOSAR E2E Profile 1 / 1A | ✅ verified with real data |
| `CRC8/SAE-J1850` | DBC-comment checksums | ✅ verified with real data |
| `SUM8/XOR-FF` | sum of bytes `& 0xFF`, then `XOR 0xFF` | ✅ verified with real data |
| `XOR8/SEED` | byte-wise XOR with a constant seed | ✅ verified with real data |
| `SUM8` | plain additive sum `& 0xFF` | ✅ verified (wider variants unverified) |
| `CRC8/AUTOSAR`, `CRC8/H2F`, `CRC16/ARC`, `CRC16/MODBUS`, `CRC32/AUTOSAR`, `CRC32/ETHERNET`, `XOR8` | — | ⚠️ not verified with real data |

Details and promotion checklist: [docs/supported-algorithms.md](docs/supported-algorithms.md).

## 🧩 Extending without code changes

**New signal naming** — add a regex to
[`crc_checker/data/patterns.yaml`](crc_checker/data/patterns.yaml):

```yaml
checksum:
  prefix: ['(?i)^(checksum|check_sum|crc|e2e_crc)']
  suffix: ['(?i)(_crc|_checksum|_chks)([0-9_]*)$']
rolling_counter:
  prefix: ['(?i)^(rolling.?counter|rc_|alive.?counter)']
  suffix: ['(?i)(_counter|_cntr|_msgcntr)([0-9_]*)$']
  exclude: ['(?i)block_?counter']
```

Or point `signals.patterns_file` at your own YAML, or use
`signals.checksum_patterns` / `signals.rc_patterns` inline.

**New DataID workbook layout** — add a named mapping to
[`crc_checker/data/dataid_mappings.yaml`](crc_checker/data/dataid_mappings.yaml),
then select it with `dataid.mapping`. Use `dataid.mapping_file` for a separate
file. Built-in names: `hi_lo_two_cols`, `single_16bit`, `generic_abc`,
`simple_8bit`, `description_regex`.

**New project** — put `config.json` (+ DBC / DataID / trace) under `projects/`.

## ⚙️ Configuration

A run is a JSON file (`crc-check gen-config` writes an annotated example). The
main sections:

| Section | Field | Description |
| --- | --- | --- |
| `crc` | `preset` | Preset name, or `custom` for inline parameters |
| | `byte_swap` | Swap computed CRC bytes (Profile 5) |
| | `auto_classify` | Pick the algorithm per message from DBC comments |
| | `profile_by_width` | 2-byte CRC → Profile 5, 1-byte → Profile 1 |
| | `profiles` | Per-profile overrides (algorithm, DataID layout, range, counter max) |
| | `range_overrides` / `skip` | Per-message range / unverified signals |
| `range` | `mode` | `exclude_crc` / `full_payload` / `custom_range` |
| `dataid` | `json` / `xlsx` | Preprocessed JSON (fast) or Excel workbook |
| | `mapping` / `mapping_file` | DataID column layout |
| `signals` | `patterns_file` | Custom signal-name YAML |
| | `checksum_pattern(s)` / `rc_pattern(s)` | Regex overrides |
| `rc` | `max_valid` | Max valid counter value (default `2^bits - 1`) |
| `output` | `max_report_sections` | Frame-section cap (default 30 000, 0 = unlimited) |

Full schema: `crc_checker/config.py` (`CONFIG_SCHEMA_DOC`).

## 📁 Repository layout

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
cli/                    Click CLI (python -m cli.main)
webapp/                 FastAPI backend
frontend/               Vue 3 + Element Plus (dist committed)
examples/               Synthetic example project + generator
tests/                  pytest suite
```

## 🧪 Development

```bash
pytest
pylint crc_checker/ cli/ webapp/ tests/ examples/     # must stay 10.00/10
cd frontend && npm test                               # node --test
cd frontend && npm install && npm run build           # rebuild committed dist
python examples/generate_example.py                   # regenerate the example
```

## 🤝 Contributing

Issues and pull requests are welcome. Please run the lint and test commands above
before opening a PR; the CI runs the same pylint and pytest checks on Python 3.9
and 3.10.

## 📄 License

MIT. See [LICENSE](./LICENSE).

---

<div align="center">

**DBC in, trace in, verdicts out — no customer-specific code paths.**

[⭐ Star us on GitHub](https://github.com/zhaojiale2021/CAN_CRC_Checker) · [🐛 Report Issues](https://github.com/zhaojiale2021/CAN_CRC_Checker/issues)

</div>
