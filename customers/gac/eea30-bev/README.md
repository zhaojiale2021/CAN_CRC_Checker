# GAC EEA3.0 纯电平台 CAN CRC Checker

广汽 EEA3.0 纯电 AB 平台（ADC / 智能驾驶域控制器）CAN 总线 CRC / Rolling Counter 校验工具。
适用项目：**s52 / s52-e046**（s52 的 CANFD2 DBC 与本平台 md5 完全一致；各项目 DBC 修订版可能更新，
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
  本平台 DataID 表还包含第三个实例 `SRS_1_CRC3`（0x0412），当前 DBC 无该信号，配置里无需处理。
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
crc-check.exe preprocess-dataid --xlsx "dbc/EEA3.0纯电平台 E2E DataID Configuration_V3.0.xls" \
    --sheet "Data ID Config" --mapping gac_eea4 -o dbc/dataid.json
```

## 输出

运行后在当前目录生成 `report.html`。

## Trace（S52 台架示例）

`trace/can_merge.blf` 是 S52 台架的多总线合并数据，直接 `run.bat` 即可复现：

- CRC verdict **137,604 条**，仅 2 条报文不通过（见下）。
- `0x396 CCU_PADS_1`：按台架实测口径「**前 8 字节**」校验（CRC8/SAE-J1850-ZERO +
  DataID 0x0133 前置，934/934 命中），配置里对应
  `"UINM_PADS_1_CRC": {"mode": "custom_range", "start_byte": 0, "end_byte": 8}`。
  注意固件 `CANFD1_CCU_PADS_1_DATALENGTH = 256` bit（32 字节整帧），与发送方口径不一致，
  s52/t09/t68/t88 四个项目都一样 —— 属于待 OEM 确认的问题（按固件口径这条会判 E2E 错）。
- `0x3BD HOD_1`：621 帧内容全零（HOD 未接），CRC/Counter 必然不过，属台架数据现象。
- `0x156 CCU_ZCUR_8` / `0x2B8 CCU_ZCUR_SBM_5`：曾因 DataID 表单元格尾随空格丢失 DataID
  （已修，现全过）。
- `0x2C0 IPS_1`（200 ms）/ `0x309 ZCUR_4`（100 ms）：Counter 每次发送固定 **+10 / +5**
  （其余同周期报文都是 +1，如 `0x317 ZCUF_2`、`0x3C7 DMS_1`），两通道各自递增。
  即发送方每 20 ms 递增一次 counter，而报文 100/200 ms 才发一次 —— 接收方按 +1 判定，
  因此工具报 SKIP。CRC 正常，属发送方/固件待确认项。

> 本平台的 E2E DataID 配置表是旧版 `.xls`（BIFF）格式，工具经 `xlrd` 直接读取，
> 无需手工转 `.xlsx`。
