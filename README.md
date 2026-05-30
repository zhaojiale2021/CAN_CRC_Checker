# CAN CRC Checker

DBC-aware CAN bus CRC/Rolling Counter verification tool. Reads DBC files to auto-identify Checksum/RollingCounter signal positions, computes expected CRC values with configurable algorithms (CRC8/16/32 or fully custom), and compares against actual values from trace files (BLF, ASC, MF4, TRC).

## Features

- **DBC-aware**: auto-locates `Checksum_*` / `RollingCounter_*` signal pairs by naming convention
- **CRC8/16/32 + custom**: 9 built-in automotive presets (AUTOSAR, SAE-J1850, H2F, MODBUS, ETHERNET…) plus fully parameterised custom CRC
- **DataID (E2E)**: parse DataID from Excel, prepend to CRC input per AUTOSAR E2E spec, extensible column mapping for different OEM formats
- **Rolling Counter detection**: PASS / STALE / SKIP / RESET / INVALID across consecutive frames, configurable wrap range
- **Segment-based CRC**: auto-detect 8-byte segments in multiplexed CAN FD frames
- **Multi-format trace**: BLF, ASC, TRC, MF4, CSV, LOG via python-can
- **HTML report**: hex-dump view per segment with inline CRC/RC highlighting, DataID display, collapsible sections

## Quick Start

### Standalone .exe (no Python required)

Download from [Releases](https://github.com/zhaojiale2021/CAN_CRC_Checker/releases):

```powershell
# Generate example config
.\crc-check.exe gen-config my_config.json

# Edit paths and CRC algorithm, then:
.\crc-check.exe run -c my_config.json
```

### From source

```bash
pip install -r requirements.txt
pip install -e .
```

## Usage

### 1. JSON config (recommended)

```bash
# Generate template
crc-check gen-config my_config.json

# Edit, then run
crc-check run -c my_config.json
```

Example config:

```json
{
  "dbc": "network.dbc",
  "traces": ["trace.blf"],
  "crc": {"preset": "CRC8/SAE-J1850-ZERO"},
  "dataid": {
    "xlsx": "dataid.xlsx",
    "sheet": "DBC_V2.5 ADAS1"
  },
  "output": {"format": "html", "file": "report.html"}
}
```

### 2. CLI direct

```bash
crc-check verify --dbc network.dbc --trace trace.blf --algo CRC8/SAE-J1850-ZERO
crc-check verify ... --dataid-xlsx dataid.xlsx --dataid-sheet "Sheet1" --output html
crc-check inspect network.dbc
crc-check presets
```

## JSON Config Reference

| Section | Field | Description |
|---------|-------|-------------|
| *(top)* | `dbc` | **Required.** DBC file path |
| | `traces` | **Required.** Trace file paths |
| `crc` | `preset` | Built-in preset name, or use `custom` for custom params |
| | `custom` | `{"width":8,"poly":"0x2F","init":"0xFF","xor":"0xFF","reflect_in":false,"reflect_out":false}` |
| `range` | `mode` | `exclude_crc` / `full_payload` / `custom_range` (default: auto-detect) |
| `dataid` | `xlsx` | DataID Excel file path |
| | `sheet` | Sheet name (blank = auto) |
| | `mapping` | `greatwall_j6m` / `generic_abc` / `simple_8bit` / JSON custom |
| `filter` | `frame_ids` | CAN ID filter: `["0x143","0x299"]` or null |
| | `max_frames` | Max frames to process or null |
| `rc` | `max_valid` | Max RC value before wrap to 0 (null = auto from bit length) |
| `output` | `format` | `table` / `html` |
| | `file` | Output file path |
| | `only_failures` | `true` / `false` |

## CRC Presets

| Name | Poly | Init | XOR | Notes |
|------|------|------|-----|-------|
| `CRC8/AUTOSAR` | 0x2F | 0xFF | 0xFF | Standard AUTOSAR |
| `CRC8/SAE-J1850` | 0x1D | 0xFF | 0xFF | Standard SAE-J1850 |
| `CRC8/SAE-J1850-ZERO` | 0x1D | 0x00 | 0x00 | Zero-init variant |
| `CRC8/H2F` | 0x2F | 0xFF | 0xFF | Reflected |
| `CRC16/ARC` | 0x8005 | 0x0000 | 0x0000 | Reflected |
| `CRC16/MODBUS` | 0x8005 | 0xFFFF | 0x0000 | Reflected |
| `CRC32/AUTOSAR` | 0xF4ACFB13 | 0xFFFFFFFF | 0xFFFFFFFF | Reflected |
| `CRC32/ETHERNET` | 0x04C11DB7 | 0xFFFFFFFF | 0xFFFFFFFF | Reflected |
| `XOR8` | 0x00 | 0x00 | 0x00 | Simple XOR checksum |

## Build

```bash
# Windows
build.bat           # Full build (~40 MB)

# Manual
pip install pyinstaller
pyinstaller --onefile --name crc-check \
    --collect-all canmatrix --hidden-import openpyxl \
    cli/main.py
```

## Architecture

```
crc_checker/
├── crc/          CRC engine (9 presets + custom, lookup-table)
├── dbc/          DBC parsing & signal identification
├── trace/        Unified trace reader (BLF/ASC/MF4/TRC)
├── dataid/       DataID Excel parser (extensible column mapping)
├── protect/      Protection algorithm plugins (CRC, RollingCounter)
├── verify/       Verification orchestration engine
├── report/       HTML report generator (hex-dump + inline highlight)
└── bit_utils.py  CAN signal bit extraction
cli/main.py       Click CLI
```

## License

MIT
