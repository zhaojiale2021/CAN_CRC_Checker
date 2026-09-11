# Chery T1LFL1 CAN CRC Checker

奇瑞 T1L FL1 CAN 总线 CRC/Rolling Counter 校验工具（对应固件 `cpj_chery/veh_t1lfl1/net_cfg` 的 `NetE2E_P01_Can.cpp`）。

## 算法（按报文从 DBC 注释自动分类）

| 分类 | 描述（DBC 注释） | 实现 |
|------|------------------|------|
| CRC-8 | `CRC (SAE J1850 CRC-8)` / `CRC_(SAE_J1850_CRC-8)` / `(SAE_J1850_CRC-8)` | CRC8/SAE-J1850 (poly=0x1D, init=0xFF, xor=0xFF) |
| SUM8/XOR-FF | `((Byte0+...+Byte6)_AND_0xFF)_XOR_0xFF` | 排除 CRC 字节后其余字节求和 `& 0xFF` 再 `XOR 0xFF` |
| XOR8/SEED | `0x01_XOR_0x27_XOR_Byte0 ...`（YAS 雷达） | 全部字节异或，seed = 注释中 0xNN 常量异或（YAS_1=0x26, YAS_2=0x29） |

- 命名：校验信号 `<Msg>_CRC` / `<Msg>_Checksum` / `<Msg>_CRCCheck`；计数器 `<Msg>_MessageCounter` / `<Msg>_Message_Counter` / `ALIVE_*`
- CRC 8 bit，Motorola，位置随报文不同（byte0~7），`exclude_crc` 按信号位自动排除
- Counter 4 bit（`max_valid` 自动 = 15）；YAS_1/2 为 8 bit（自动 = 255）
- **无 DataID**；固件按整段 payload（跳过校验字节）计算

### 报文清单（23 条，来自固件 E2E 配置）

| 算法 | 报文（DBC 名 / ID） |
|------|---------------------|
| J1850 CRC-8 | ADCC_10/0x2F9, APA_1/0x22A, APA_2/0x24A, EPS_2/0x394, EPS_3/0x1D3, EPS_4/0x1E3, HCU_1/0x160, IHU_MFS_2/0x360, SAS_1_G/0xC4 |
| SUM8/XOR-FF | ABS_ESP_1/0x2E9, ABS_ESP_3/0x313, ABS_ESP_4/0x316, ABS_ESP_7/0x260, ABS_ESP_8/0x281, ABS_ESP_G/0x502, CEM_BCM_1/0x391, HCU_EMS_1/0xFA, **ICM_5/0x287**, TCU_1/0x1AE, TCU_2/0x300, TRM_1/0x5CF |
| XOR8/SEED | YAS_1/0x127 (seed 0x26), YAS_2/0x128 (seed 0x29) |

> **ICM_5 (0x287)** 的 DBC 注释为空，固件实际使用 SUM8/XOR-FF（`com_checksum`），
> 因此在 `config.json` 的 `crc.overrides` 中显式指定：
> `"overrides": { "0x287": "SUM8/XOR-FF" }`。

### 多 DBC 合并

B_CAN 与 C1_CAN 两个 DBC 的报文在实际 trace 中同时出现在两个通道上，
按通道自动选 DBC 会丢掉 B_CAN（ICM_5、CEM_BCM_1）。
配置里已启用 `"dbc_merge": true`（两 DBC 的 frame_id 互不重叠，合并安全）。

### 已知限制

- **IHU_MFS_2 (0x360)**：DBC 定义 DLC=6、校验字节在 byte0，而固件固定按 8 字节计算
  （`CAN_MSG_CRC_LEN=8`）。若总线补位字节非 0 会不一致，需有该报文数据时复核。
- ICM_1 (0x430) 只有计数器（无 CRC 信号），固件未做保护，报告中会输出其 RC 校验结果。

## 用法

### Windows
```
run.bat config.json
```

### Linux / Git Bash
```
./run.sh config.json
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
├── README.md        # 本文件
├── dbc/             # T1L_FL1_Message_List_{B_CAN,C1_CAN}_V4.0.dbc
└── trace/           # Trace 数据文件（BLF）
```

## 输出

运行后在当前目录生成 `report.html`，浏览器打开即可查看校验结果。
