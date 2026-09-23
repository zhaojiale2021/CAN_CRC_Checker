# BAIC B81VS CAN CRC Checker

北汽 B81VS CAN 总线 CRC/Rolling Counter 校验工具

## 算法（按报文从 DBC 注释自动分类）

| 分类 | 描述（DBC 注释） | 实现 |
|------|------------------|------|
| SUM8/XOR-FF | `Checksum = (byte0+byte1+…+byteN) and 0xFF`（注释省略了 XOR） | 对注释点名的字节求和 `& 0xFF` 再 `XOR 0xFF`（对齐 mcu 端 `crc_calculatecrcxor`，其实现带 `^0xFF`）。注释里的 byte 编号是**帧内绝对编号**，多段报文逐段给出（`0x393`：byte1..7 / byte9..15 / byte17..23 / …） |
| Profile 1A | `CRC checksum. …（Profile：1A；DataID：0x00EB）` | CRC8/SAE-J1850-ZERO + DataID（从注释解析，prepend lo_hi） |
| skip | `算法另附文件` / nibble 亚字节校验 | 不自动校验，保持默认算法 |

- 命名：CRC `<Msg>_Checksum` / `<Msg>_Chks`，RC `<Msg>_RollingCounter` / `<Msg>Cntr`
- CAN FD 多段报文：每段段首一个 CRC（`*_Chks1/2/3…`），段内 4bit RC，DataID 逐段独立。
  每段 CRC 的覆盖范围是该段 8 字节内 CRC 之后的 7 字节（注释原文
  `DataID and the following 7 bytes are included in CRC checksum calculation`），
  即 `CRC8/SAE-J1850-ZERO(DataID_lo, DataID_hi, byte1…byte7)`——**不是**整帧的其余字节。
  多段报文：`ADC_APA_0x135`（3 段，DataID 0x00E8/9/A）、`ADC_ADAS_0x136`（4 段，0x00EB…EE）、
  `IDC_0x38C`（3 段，0x0042/3/4）
- 常规报文：CRC 在 byte0 或 byte7，`exclude_crc` 按信号位自动排除
- RollingCounter 范围：Profile 1A 的 4bit 计数器是 **0..14**（E2E 规定 14 之后回 0，0xF 为
  invalid，DBC 里写 `[0|14]`）；SUM8/XOR-FF 报文的是普通 4bit 0..15。工具按分类结果分别取
  `max_valid`，不要给 Profile 1A 报文配 15，否则每次回绕都会误报
- 3 通道：ADASBUS / BJEVCR / FR60（`dbc/` 目录多 DBC，按通道自动选择）
- ADASBUS 矩阵为 GBK 编码，注释里的全角标点（`（Profile：1A；DataID：…）`）用于解析
  DataID；解析器会自动识别文件编码（utf-8 → gbk → latin-1），DBC 可原样使用
- 传统 CAN（BJEVCR/FR60）的 `Checksum<ID>` 无算法注释，默认按 SUM8 校验；
  其中 16bit 校验位的精确行为待真实 trace 验证后确认

## 用法

### Windows
双击 `run.bat` 或命令行：
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
├── dbc/             # DBC 数据库文件
└── trace/           # Trace 数据文件（BLF）
```

## 输出

运行后在当前目录生成 `report.html`，浏览器打开即可查看校验结果。
