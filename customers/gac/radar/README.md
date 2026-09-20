# GAC 雷达总线 CAN CRC Checker (FR / FLR / FRR / RLR / RRR)

广汽雷达私有 CAN 总线的 E2E 校验（前雷达 + 角雷达 + 后雷达），DBC 取 **V20** 的
（V20 多了 `CANFCR_Signal.dbc`，同时覆盖前角雷达 FLR / FRR；其余项目只有 FR/RLR/RRR）。
雷达所有项目一致，所以本目录不按项目区分。

## 总线 ↔ DBC

| DBC | 总线（V20 固件） | 报文 |
|-----|------------------|------|
| `FR_signal.dbc` | CAN2 | FR 前雷达：`FR_SensorState` + `FR_Obj_01..32` + `FR_RadarInfo` + 底盘 `*_A` 报文 |
| `CANFCR_Signal.dbc` | CAN5 | FLR / FRR 前角雷达（各 32 个 Obj + SensorState + RadarInfo） |
| `RLR_Signal.dbc` | CAN3 | RLR 后左雷达 |
| `RRR_Signal.dbc` | CAN4 | RRR 后右雷达 |

## 算法

雷达报文是 **AUTOSAR E2E Profile 1**（8-bit CRC）：

| 信号 | 位置 | 说明 |
|------|------|------|
| `<雷达>_Msg_CheckSum[_CanNN]` | Byte0（bit 0，8-bit） | CRC |
| `<雷达>_Msg_AliveCounter[_CanNN]` | bit 12，4-bit | 滚动计数（0~14 合法） |
| `<雷达>_BlockCounter[_CanNN]` | bit 8，4-bit | **块计数，不是滚动计数** —— 工具不会校验它 |

- 算法：CRC8/SAE-J1850-ZERO（0x1D / init 0x00 / 无异或），**DataID 前置** lo→hi；
- 保护段：**前 30 字节**（固件 `RADAR_DATALENGTH = 240` bit，注释 "0-29 byte"）；
  16 字节的 `EPS_1` 等短帧按整帧处理；
- DataID：`dbc/dataid.json`，取自 V20 固件 `NetE2E_Cfg.hpp`（雷达总线的常量，0x0800~0x0826）。
  OEM 的 E2E DataID 表里**没有雷达条目**，所以这里以固件为准；FR 部分与
  `G300_T75&V20_Proj_FR_Radar+CR_Radar_CMX_V2.1` 的 `Data ID` 表逐条一致。

## 用法

```
run.bat                 # Windows
./run.sh                # Linux / Git Bash
```

`trace/` 放本总线的 `.blf` / `.asc` / `.mf4` / `.trc`（多总线合并的 trace 也支持，
工具按通道自动选 DBC）。

## 已知情况

- `ADC_SOC_TimeSync`（0x300，8-bit `SYNC_FC_CRC`）在雷达总线上**固件不做 E2E 校验**，
  已列入 `crc.skip`；OEM 雷达表里它标了 DataID 0x00FF，如需按发送方口径校验可自行去掉 skip。
- `dataid.json` 由固件常量生成；固件更新雷达 DataID 后需要重新生成（见 `../README.md`）。

## 目录结构

```
├── crc-check.exe    # 主程序
├── config.json      # 校验配置
├── run.bat / run.sh
├── dbc/             # 4 个雷达 DBC + dataid.json
└── trace/           # 自行放入 trace
```
