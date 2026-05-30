# CAN CRC Checker

DBC-aware CAN bus CRC/Rolling Counter verification tool. Parses DBC files to auto-identify checksum and rolling counter signal positions, reads trace files (BLF, ASC, MF4, TRC), computes expected CRC values with configurable algorithms (CRC8/16/32 or fully custom), and compares against actual values — with multiple report formats (terminal table, HTML, CSV, JSON).

## Features

- **DBC-aware**: automatically locates `Checksum_*` / `RollingCounter_*` signal pairs by naming convention
- **CRC8/16/32 + custom**: 8 built-in automotive presets (AUTOSAR, SAE-J1850, H2F, MODBUS, ETHERNET…) plus fully parameterised custom CRC
- **DataID (E2E)**: parse DataID from Excel, prepend to CRC input per AUTOSAR E2E specification
- **Rolling Counter detection**: PASS / STALE / SKIP / RESET classification across consecutive frames
- **Multi-format trace**: BLF, ASC, TRC, MF4, CSV, LOG — via python-can
- **CAN FD**: 64-byte payloads fully supported
- **Reports**: terminal table, self-contained HTML, CSV, JSON
- **CLI + TUI**: scriptable CLI for automation, Textual TUI for interactive browsing

## Installation

```bash
pip install -e .
```

Requires Python ≥ 3.9.

## Quick Start

### Standalone .exe (no Python required)

Download `crc-check.exe` from [GitHub Releases](https://github.com/zhaojiale2021/CAN_CRC_Checker/releases), then:

```powershell
# Generate example config
.\crc-check.exe gen-config my_config.json

# Edit my_config.json with your DBC/trace paths, then run
.\crc-check.exe run -c my_config.json

# Or launch TUI
.\crc-check.exe tui
```

### From source (Python)

```bash
pip install -e .
```

### 0. Easiest: run from a JSON config file

```bash
# Generate an example config
crc-check gen-config my_config.json

# Edit DBC/trace paths and CRC algorithm in my_config.json, then:
crc-check run -c my_config.json

# With TUI:
#   Set "tui": true in the JSON, or
crc-check run -c my_config.json --tui   # (if --tui flag added)
```

### 1. Inspect a DBC — what protection signals does it have?

```bash
crc-check inspect path/to/network.dbc
```

Output:

```
DBC: path/to/network.dbc
Found protection signals in 42 CAN IDs:

  ID=0x143 (ACC_FD1) [ACC1]
    Checksum:  Checksum_ACC1  start_bit=64 length=8
    RC:        RollingCounter_ACC1  start_bit=124 length=4
  ...
```

### 2. List available CRC presets

```bash
crc-check presets
```

### 3. Run verification (CRC only, no DataID)

```bash
crc-check verify \
    --dbc network.dbc \
    --trace trace.blf \
    --algo CRC8/AUTOSAR
```

### 4. With DataID Excel

```bash
crc-check verify \
    --dbc network.dbc \
    --trace trace.blf \
    --algo CRC8/AUTOSAR \
    --dataid-xlsx dataid_table.xlsx \
    --dataid-sheet "DBC_V2.5 ADAS1"
```

### 5. Export HTML report (failures only)

```bash
crc-check verify \
    --dbc network.dbc \
    --trace trace.blf \
    --algo CRC8/AUTOSAR \
    --dataid-xlsx dataid_table.xlsx \
    --output html --output-file report.html \
    --only-failures
```

### 6. Interactive TUI mode

```bash
crc-check verify --dbc network.dbc --trace trace.blf --tui
```

## JSON Configuration

The simplest way to run repeated checks — define everything in a `.json` file:

```bash
crc-check gen-config my_config.json   # create template
crc-check run -c my_config.json       # run
crc-check run -c my_config.json -v    # run with verbose output
```

### Full config schema

```json
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
    "sheet": "DBC_V2.5 ADAS1",
    "mapping": "greatwall_j6m"
  },

  "filter": {
    "frame_ids": ["0x143", "0x299"],
    "max_frames": 10000
  },

  "output": {
    "format": "html",
    "file": "report.html",
    "only_failures": false
  },

  "tui": false
}
```

| Section | Field | Type | Description |
|---------|-------|------|-------------|
| *(top)* | `dbc` | path | **Required.** DBC file path |
| | `traces` | path[] | **Required.** Trace file paths |
| | `tui` | bool | Launch TUI instead of CLI output |
| `crc` | `preset` | str | Built-in preset name (e.g. `CRC8/AUTOSAR`) |
| | `custom` | object | Custom CRC: `{"width":8,"poly":"0x2F",...}` |
| `range` | `mode` | str | `full_payload` / `exclude_crc` / `custom_range` |
| | `start_byte` | int | Custom range start (0-indexed) |
| | `end_byte` | int | Custom range end (-1 = end) |
| `dataid` | `xlsx` | path | DataID Excel (optional) |
| | `sheet` | str | Sheet name (blank = auto) |
| | `mapping` | str | Builtin name or JSON column mapping |
| `filter` | `frame_ids` | str[] | CAN ID filter (null = all) |
| | `max_frames` | int | Max frames (null = all) |
| `output` | `format` | str | `table` / `html` / `csv` / `json` |
| | `file` | path | Output file path |
| | `only_failures` | bool | Show failures only |

All sections except `dbc` and `traces` are optional — omit any section to use defaults. The `crc` section can contain either `preset` (built-in) or `custom` (fully custom parameters), not both.

## CLI Reference

```
crc-check verify [OPTIONS]

Required:
  --dbc PATH               DBC file
  --trace PATH             Trace file(s), repeatable: --trace a.blf --trace b.asc

CRC Algorithm:
  --algo NAME              Preset: CRC8/AUTOSAR, CRC8/SAE-J1850, CRC8/H2F,
                           CRC16/ARC, CRC16/MODBUS, CRC32/AUTOSAR,
                           CRC32/ETHERNET, XOR8
  --custom-crc JSON        Fully custom: '{"width":8,"poly":"0x2F","init":"0xFF",
                           "xor":"0xFF","reflect_in":false,"reflect_out":false}'

CRC Range:
  --range MODE             full_payload | exclude_crc (default) | custom_range
  --range-start N          Start byte offset (custom_range mode)
  --range-end N            End byte offset (custom_range mode)

DataID (E2E):
  --dataid-xlsx PATH       Excel file with DataID table
  --dataid-sheet NAME      Sheet name (default: first sheet)
  --dataid-mapping SPEC    Builtin name or JSON column mapping (see below)

Signal Detection Overrides:
  --checksum-pattern RE    Regex for checksum signal names
  --rc-pattern RE          Regex for rolling counter signal names

Filtering / Output:
  --frame-ids 0x143,0x299  Only process these CAN IDs
  --max-frames N           Stop after N frames
  --only-failures          Hide PASS verdicts
  --output FORMAT          table (default) | csv | json | html
  --output-file PATH       Write report to file
  --tui                    Launch interactive Textual TUI
  --verbose, -v            Verbose progress
```

### Other commands

```bash
crc-check inspect network.dbc     # List protection signals in a DBC
crc-check presets                  # List all built-in CRC algorithm presets
```

## Custom CRC Algorithm

Pass a JSON object describing any CRC:

```bash
crc-check verify \
    --dbc net.dbc --trace trace.blf \
    --custom-crc '{
        "width": 8,
        "poly": "0x2F",
        "init": "0xFF",
        "xor": "0xFF",
        "reflect_in": false,
        "reflect_out": false,
        "name": "my-custom-crc8"
    }'
```

| Field | Type | Description |
|-------|------|-------------|
| `width` | int | 8, 16, or 32 |
| `poly` | hex str | Polynomial (e.g. `"0x2F"`) |
| `init` | hex str | Initial value (e.g. `"0xFF"`) |
| `xor` | hex str | Final XOR mask (e.g. `"0xFF"`) |
| `reflect_in` | bool | Reflect each input byte |
| `reflect_out` | bool | Reflect final result |
| `name` | str | Optional label |

## DataID Excel Support

### Default format (Great Wall Motors J6M)

The default column layout expects:

| Col B (1) | Col C (2) | Col D (3) | … | Col M (12) | Col N (13) |
|-----------|-----------|-----------|---|------------|------------|
| Signal name | Message name | Message ID | … | DataID Hi | DataID Lo |

Data rows start at row 3. Message IDs are hex (`0x143`). DataID is two 8-bit columns (Hi << 8 | Lo).

### Custom column mapping

If your Excel uses a different layout, specify a column mapping:

```bash
# Use a different builtin mapping
crc-check verify ... --dataid-mapping generic_abc

# Custom mapping as JSON
crc-check verify ... --dataid-mapping '{
    "col_signal_name": 0,
    "col_message_id": 1,
    "col_dataid_hi": 2,
    "col_dataid_lo": -1,
    "dataid_format": "single_16bit",
    "data_row_start": 2,
    "message_id_base": 16,
    "signal_name_filter": ["Checksum", "CRC"]
}'
```

#### ColumnMapping fields

| Field | Default | Description |
|-------|---------|-------------|
| `col_signal_name` | 1 | 0-based column index for signal name |
| `col_message_id` | 3 | 0-based column index for CAN ID |
| `col_dataid_hi` | 12 | 0-based column index for DataID (hi byte or full value) |
| `col_dataid_lo` | 13 | 0-based column index for DataID lo byte (-1 if unused) |
| `dataid_format` | `"hi_lo_two_cols"` | `hi_lo_two_cols` / `two_cols_lsb_first` / `single_16bit` / `single_8bit` |
| `data_row_start` | 3 | 1-based row number where data begins |
| `message_id_base` | 16 | Radix for CAN ID: 16 (hex) or 10 (decimal) |
| `signal_name_filter` | `["checksum","crc","check_sum","e2e_crc"]` | Prefixes to identify checksum rows; `null` to accept all |

#### Builtin mappings

| Name | Description |
|------|-------------|
| `greatwall_j6m` | Great Wall J6M format (default) |
| `generic_abc` | Col A=Signal, B=ID(hex), C=DataID(16-bit hex) |
| `simple_8bit` | Col A=ID(decimal), B=Signal, C=DataID(8-bit) |

To add your own format permanently, register it in `BUILTIN_MAPPINGS` in [crc_checker/dataid/parser.py](crc_checker/dataid/parser.py).

## Architecture

```
crc_checker/
├── crc/          CRC engine (8 presets + custom, lookup-table)
├── dbc/          DBC parsing & signal identification
├── trace/        Unified trace reader (BLF/ASC/MF4/TRC)
├── dataid/       DataID Excel parser (extensible column mapping)
├── protect/      Protection algorithm plugins (CRC, RollingCounter, E2E…)
├── verify/       Verification orchestration engine
├── report/       Report generators (HTML, CSV, JSON, terminal table)
└── bit_utils.py  CAN signal bit extraction
cli/main.py       Click CLI
tui/app.py        Textual TUI
```

## Build

### From source

```bash
pip install -r requirements.txt
pip install -e .
```

### Standalone .exe

```bash
# Windows
build.bat           # Full build with TUI (~107 MB)
build.bat cli       # CLI-only (~32 MB)

# Manual build
pip install pyinstaller
pyinstaller --onefile --name crc-check \
    --hidden-import canmatrix --hidden-import canmatrix.formats \
    --hidden-import canmatrix.formats.dbc \
    --hidden-import openpyxl --hidden-import textual \
    --collect-all canmatrix \
    cli/main.py
```

Output: `dist/crc-check.exe`

## Dependencies

```
python-can>=4.5       # Trace file reading (BLF/ASC/MF4/TRC)
canmatrix>=1.1        # DBC parsing
click>=8.1            # CLI framework
bitstruct>=8.19       # Bit-level signal extraction
openpyxl>=3.0         # DataID Excel parsing
textual>=0.70         # TUI (optional, omit for CLI-only)
pyinstaller>=6.0      # .exe packaging (dev only)
```

## License

MIT
