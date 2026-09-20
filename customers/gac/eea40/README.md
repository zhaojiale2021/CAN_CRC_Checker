# GAC EEA4.0 平台 CAN CRC Checker

广汽 EEA4.0 平台（ADC / 智能驾驶域控制器）CAN 总线 CRC / Rolling Counter 校验工具。
适用项目：**t75 / t996d / v20**（DBC 报文集合与平台 100% 一致；各项目 DBC 修订版可能更新，
CRC 算法与 DataID 数值一致，详见 `../README.md`）。

## 算法

profile 由 **CRC 信号位宽**自动选择（与固件 `31bd82bcf` 一致：2 字节 → Profile 5，1 字节 → Profile 1）：

| Profile | 算法 | DataID | 校验段 |
|---------|------|--------|--------|
| Profile 5（16-bit CRC） | CRC16/CCITT（0x1021 / init 0xFFFF / 无异或） | **追加**在数据末尾，lo_hi | offset 0，长度 `min(帧长, 56)` → 64 字节报文保护 Byte2~Byte55 |
| Profile 1（8-bit CRC） | CRC8/SAE-J1850-ZERO（0x1D / init 0x00 / 无异或） | **前置**，lo_hi | 整帧去掉 CRC 字节 |

> Profile 1 的固件实现见 `Crc.c:89`（初值 `0xFF ^ 0xFF = 0x00`）与 `E2E_P01.c:375`（再异或 0xFF），
> 净值等价于 init 0x00 / 无末异或。

### 本平台的例外（已写进 config.json）

- `CCU_SRS_1`（0x1AE）：本平台只有单个 E2E 实例，固件 `CCU_SRS_1 DATALENGTH = 448` bit
  （**56 字节整帧**，slice offset 0）→ 用全局 `range: 0..56`，**不要**套用 EEA3.0 的 13/19 分段
  （t75 / t996d / v20 三个项目一致；分段只存在于 EEA3.0 混动/纯电）。
- `crc.skip` 里的 6 个信号：`SYNC_FC_CRC`（CCU_TimeSync 的时间同步校验，非 E2E，DataID 表中
  无 0x400）以及 5 个 `*_ICE` 校验（`EMS_1/2/3_ICE_CRC`、`TCU_2_ICE_CRC`、`ADC_1_ICE_CRC`）——
  这 5 条 DBC 标了 E2E 但 DataID 表里没有对应行，固件侧也把 `*_ICE` 排除在外。

## 用法

### Windows
```
run.bat
```

### Linux / Git Bash
```
./run.sh
```

### 直接调用
```
crc-check.exe run -c config.json -v
```

## 目录结构

```
├── crc-check.exe    # 主程序
├── config.json      # 校验配置
├── run.bat / run.sh # 启动脚本
├── dbc/             # DBC + DataID 源表 + dataid.json（预处理结果）
└── trace/           # Trace 数据文件（自行放入 .blf/.asc/.mf4/.trc）
```

DataID 源表更新后重新生成 JSON：

```bash
crc-check.exe preprocess-dataid --xlsx "dbc/EEA4.0 E2E DataID ConfigurationV1.9.xlsx" \
    --sheet "Data ID Config" --mapping gac_eea4 -o dbc/dataid.json
```

## 输出

运行后在当前目录生成 `report.html`。

## Trace

`trace/` 目录需放入本平台（T75 / T996D / V20）的 `.blf` / `.asc` / `.mf4` / `.trc` 后运行。
本目录当前不含示例 trace —— 原先的 S52 台架数据已归入 `../eea30-bev/trace/`。
