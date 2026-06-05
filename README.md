# CAN CRC Checker

DBC-aware CAN bus CRC/Rolling Counter verification tool. Supports E2E Profile 5 (CRC16/CCITT) and Profile 1/1A (CRC8/SAE-J1850).

## Supported Customers

| OEM | Model | Algorithm | DataID | Status |
|-----|-------|-----------|--------|--------|
| **GAC** | T75 (Trumpchi) | Profile 5 + Profile 1A | append, lo_hi, byte-swap | 98.77% |
| **GWM** | DE09G (J6B) | CRC8/SAE-J1850-ZERO | prepend, lo_hi | 96.70% |
| **GWM** | B06-5 (J6M) | CRC8/SAE-J1850-ZERO | prepend, lo_hi | 71.91% |
| **Chery** | T1JFL3 | CRC8/SAE-J1850-ZERO | prepend, lo_hi | Pending trace |

## Quick Start

### From source

```bash
pip install -r requirements.txt
pip install -e .
```

### Standalone .exe

```bash
# Build
build.bat                    # Output: dist\crc-check.exe

# Copy to customer directory and run
cp dist\crc-check.exe customers/gac/t75/
cd customers/gac/t75
./run.bat
```

## Usage

```bash
# JSON config (recommended)
crc-check run -c config.json -v

# CLI direct
crc-check verify --dbc network.dbc --trace trace.blf --algo CRC8/SAE-J1850-ZERO

# List presets
crc-check presets

# Inspect DBC
crc-check inspect path/to/file.dbc

# Preprocess DataID (Chery format)
crc-check preprocess-dataid \
  --xlsx matrix.xlsx --sheet CANFD1 --sheet CANFD2 \
  --mapping chery_t1jfl3 -o dataid.json
```

## Project Structure

```
crc_checker/          # Core Python package
  crc/                # CRC engine (10 presets + custom)
  dbc/                # DBC parser + signal resolver
  dataid/             # DataID Excel parser (5 builtin mappings)
  trace/              # Trace reader (BLF/ASC/MF4/TRC)
  protect/            # CRC + Rolling Counter verifiers
  verify/             # Verification orchestration
  report/             # HTML report generator
cli/                  # Click CLI
customers/            # Per-customer configs
  gac/t75/            # GAC Trumpchi T75
  gwm/de09g/          # GWM J6B DE09G
  gwm/b06-5/          # GWM J6M B06-5
  chery/t1jfl3/       # Chery T1JFL3
tests/                # pytest test suite
```

## JSON Config Reference

| Section | Field | Description |
|---------|-------|-------------|
| `crc` | `preset` | `CRC8/SAE-J1850-ZERO` / `CRC16/CCITT` / custom |
| | `byte_swap` | Swap CRC bytes (Profile 5: `true`) |
| `range` | `mode` | `exclude_crc` / `custom_range` |
| | `start_byte`, `end_byte` | Range bounds (Profile 5: `0, 56`) |
| `dataid` | `json` | Preprocessed JSON (fast load) |
| | `mapping` | `greatwall_j6m` / `gac_eea4` / `chery_t1jfl3` |
| | `position` | `prepend` / `append` |
| | `byte_order` | `lo_hi` / `hi_lo` |
| `signals` | `checksum_pattern` | Custom regex (null = auto) |
| | `rc_pattern` | Custom regex |
| `rc` | `max_valid` | Max RC value (14 for 4-bit) |

## Testing

```bash
pytest                          # 27 tests
pytest --cov=crc_checker        # With coverage
pylint crc_checker/ cli/        # Must score 10.00/10
```

## License

MIT
