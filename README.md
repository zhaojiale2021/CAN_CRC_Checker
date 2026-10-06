# CAN CRC Checker

DBC-aware CAN bus CRC/Rolling Counter verification tool. Supports E2E Profile 5 (CRC16/CCITT) and Profile 1/1A (CRC8/SAE-J1850).

## Supported Customers

| OEM | Model | Algorithm | DataID | Status |
|-----|-------|-----------|--------|--------|
| **GAC** | EEA4.0 platform (T75/V20/T996D) | Profile 5 + Profile 1 (by CRC width) | append / prepend, lo_hi, byte-swap | see `customers/gac/README.md` |
| **GAC** | EEA3.0 混动 platform (s52/t68/t09) | Profile 5 + Profile 1 (by CRC width) | append / prepend, lo_hi, byte-swap | 待提供 trace |
| **GAC** | EEA3.0 纯电 AB platform | Profile 5 + Profile 1 (by CRC width) | append / prepend, lo_hi, byte-swap | 待提供 trace |
| **GAC** | Radar buses (FR/FLR/FRR/RLR/RRR) | Profile 1 (CRC8/SAE-J1850-ZERO) | prepend, lo_hi, 30-byte segment | 待提供 trace |
| **GWM** | DE09G (J6B) | CRC8/SAE-J1850-ZERO | prepend, lo_hi | 96.70% |
| **GWM** | B06-5 (J6M) | CRC8/SAE-J1850-ZERO | prepend, lo_hi | 71.91% |
| **Chery** | T1JFL3 | CRC8/SAE-J1850-ZERO | prepend, lo_hi | Pending trace |

## Quick Start

### Web version (内网网页工具)

```bash
pip install -r requirements.txt
./run_web.sh 8000          # Windows: run_web.bat 8000
# 浏览器访问 http://<服务器IP>:8000
```

选客户项目 → 上传 trace → 校验 → 看汇总/失败明细并下载 HTML 报告。
导航栏「版本」入口显示服务运行的 commit(commit 节点):运行 commit 在服务加载时
固定,部署目录 commit 每次单独读取,`git pull` 后未重启会提示两者不一致。

前端是 Vue 3 + Element Plus,产物 `frontend/dist` 已提交进 git(部署机无需 Node);
改前端见 [docs/web-api.md](docs/web-api.md)。

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
cp dist\crc-check.exe customers/gac/eea40/
cd customers/gac/eea40
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
  verify/             # Verification orchestration (+ runner.py: shared by CLI & web)
  report/             # HTML report generator
cli/                  # Click CLI
webapp/               # FastAPI backend (网页版)
frontend/             # Vue 3 + Element Plus; dist/ is committed
customers/            # Per-customer configs
  gac/eea40/          # GAC EEA4.0 platform (T75/V20/T996D)
  gac/eea30-hev/      # GAC EEA3.0 hybrid platform (s52/t68/t09)
  gac/eea30-bev/      # GAC EEA3.0 BEV AB platform
  gac/radar/          # GAC radar buses (FR/FLR/FRR/RLR/RRR)
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
| | `profile_by_width` | Pick E2E profile from CRC signal width (GAC: 2 B → P5, 1 B → P1) |
| | `profiles` | Per-profile overrides (`preset`, DataID position, `range`) |
| | `range_overrides` | Per-message/signal CRC range (GAC `SRS_1_CRC_2`: `13..32`) |
| | `skip` | Frame ids/names/signals left unverified (GAC `SYNC_FC_CRC`) |
| `range` | `mode` | `exclude_crc` / `custom_range` |
| | `start_byte`, `end_byte` | Range bounds (Profile 5: `0, 56`) |
| `dataid` | `json` | Preprocessed JSON (fast load) |
| | `mapping` | `greatwall_j6m` / `gac_eea4` / `chery_t1jfl3` |
| | `xlsx` | DataID workbook (.xlsx or legacy .xls) |
| | `position` | `prepend` / `append` |
| | `byte_order` | `lo_hi` / `hi_lo` |
| `signals` | `checksum_pattern` | Custom regex (null = auto) |
| | `rc_pattern` | Custom regex |
| `rc` | `max_valid` | Max RC value (14 for 4-bit) |

## Testing

```bash
pytest                          # 177 tests
pytest --cov=crc_checker        # With coverage
pylint crc_checker/ cli/ webapp/   # Must score 10.00/10
cd frontend && npm test         # frontend unit tests (node --test)
```

## License

MIT
