# GAC EEA3.0 混动平台 CAN CRC Checker

广汽 EEA3.0 混动平台（ADC / 智能驾驶域控制器）CAN 总线 CRC / Rolling Counter 校验工具。
适用项目：**t09 / t68 / t88**（t88 的 DBC 与本平台 md5 完全一致；各项目 DBC 修订版可能更新，
CRC 算法与 DataID 数值一致，详见 `../README.md`）。

## 算法

profile 由 **CRC 信号位宽**自动选择（与固件 `31bd82bcf` 一致：2 字节 → Profile 5，1 字节 → Profile 1）：

| Profile | 算法 | DataID | 校验段 |
|---------|------|--------|--------|
| Profile 5（16-bit CRC） | CRC16/CCITT（0x1021 / init 0xFFFF / 无异或） | **追加**在数据末尾，lo_hi | offset 0，长度 `min(帧长, 56)` → 64 字节报文保护 Byte2~Byte55 |
| Profile 1（8-bit CRC） | CRC8/SAE-J1850-ZERO（0x1D / init 0x00 / 无异或） | **前置**，lo_hi | 整帧去掉 CRC 字节 |

> Profile 1 的固件实现见 `Crc.c:89`（初值 `0xFF ^ 0xFF = 0x00`）与 `E2E_P01.c:375`（再异或 0xFF），
> 净值等价于 init 0x00 / 无末异或。

### 本平台的两处例外（已写进 config.json）

- `CCU_SRS_1`（0x1AE）双 E2E 实例：`SRS_1_CRC_1`（DataID 0x0404）只保护 **Byte0~12**，
  `SRS_1_CRC_2`（DataID 0x0414）保护 **Byte13~31**（`crc.range_overrides`）。
  固件侧对应 s52/t68/t09 的 `+0/13u` 与 `+13/19u` 分段表。
- `CCU_TimeSync`（0x400）的 `SYNC_FC_CRC` 是时间同步校验，不是 E2E（DataID 表中无 0x400，
  且不匹配任何 8-bit CRC 组合），列入 `crc.skip` 跳过。

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
crc-check.exe preprocess-dataid --xlsx "dbc/EEA3.0混动系列_E2E DataID Configuration_V1.32.xlsx" \
    --sheet "Data ID Config" --mapping gac_eea4 -o dbc/dataid.json
```

## 输出

运行后在当前目录生成 `report.html`。

## Trace

`trace/` 目录需放入本平台的 `.blf` / `.asc` / `.mf4` / `.trc` 文件后运行。
本目录未附带示例 trace。
