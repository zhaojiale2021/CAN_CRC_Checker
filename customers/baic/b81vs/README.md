# BAIC B81VS CAN CRC Checker

北汽 B81VS CAN 总线 CRC/Rolling Counter 校验工具

## 算法（按报文从 DBC 注释自动分类）

| 分类 | 描述（DBC 注释） | 实现 |
|------|------------------|------|
| SUM8 | `Checksum = (byte0+byte1+…+byteN) and 0xFF` | 排除 CRC 字节后其余字节求和 `& 0xFF`（**无** XOR 0xFF） |
| Profile 1A | `CRC checksum. …（Profile：1A；DataID：0x00EB）` | CRC8/SAE-J1850-ZERO + DataID（从注释解析，prepend lo_hi） |
| skip | `算法另附文件` / 亚字节校验 | 不自动校验，保持默认算法 |

- 命名：CRC `<Msg>_Checksum` / `<Msg>_Chks`，RC `<Msg>_RollingCounter` / `<Msg>Cntr`
- CAN FD 多段报文：每段段首一个 CRC（`*_Chks1/2/3…`），段内 4bit RC，DataID 逐段独立
- 常规报文：CRC 在 byte0 或 byte7，`exclude_crc` 按信号位自动排除
- 3 通道：ADASBUS / BJEVCR / FR60（`dbc/` 目录多 DBC，按通道自动选择）
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
