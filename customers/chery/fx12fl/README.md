# Chery FX12FL CAN CRC Checker

奇瑞 FX12 FL CAN 总线 CRC/Rolling Counter 校验工具

## 算法（按报文从 DBC 注释自动分类）

| 分类 | 描述（DBC 注释） | 实现 |
|------|------------------|------|
| CRC-8 | `Checksum(SAE J1850 CRC-8)` / `CRC (SAE J1850 CRC-8)` / 无细节 `CRC` | CRC8/SAE-J1850 (poly=0x1D, init=0xFF, xor=0xFF) |
| SUM8/XOR-FF | `((Byte0+...+Byte6) AND 0xFF) XOR 0xFF` | 排除 CRC 字节后其余字节求和 `& 0xFF` 再 `XOR 0xFF` |
| XOR8/SEED | `0x01 XOR 0x27 XOR Byte0 ... XOR Byte6`（YAS 雷达） | 全部字节异或，seed = 注释中 0xNN 常量异或（如 YAS_1=0x26） |

- 命名：后缀式 `<Msg>_CRC` / `<Msg>_Checksum`、RC `<Msg>_MsgCntr` / `<Msg>_MessageCounter`
- CRC 8 bit，Motorola，位置随报文不同（byte1~7），`exclude_crc` 按信号位自动排除
- Counter 4 bit（`max_valid` 自动 = 15）
- 无 DataID

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
