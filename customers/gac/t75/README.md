# GAC T75 CAN CRC Checker

广汽传祺 T75 CAN 总线 CRC/Rolling Counter 校验工具

## 算法

- **E2E Profile 5**: CRC16/CCITT，DataID 追加在数据末尾（lo_hi），CRC 结果字节交换（LE→BE）
  - 64-byte 报文保护范围：Byte2~Byte55
  - 短报文保护范围：CRC 外全部数据场
- **E2E Profile 1A**: CRC8/SAE-J1850-ZERO，DataID 放在数据场前

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
├── dbc/             # DBC 数据库文件 + DataID JSON
└── trace/           # Trace 数据文件
```

## 输出

运行后在当前目录生成 `report.html`，浏览器打开即可查看校验结果。

## 常用命令

```bash
crc-check.exe presets                    # 列出 CRC 预设
crc-check.exe inspect dbc/xxx.dbc       # 查看 DBC 保护信号
crc-check.exe preprocess-dataid --xlsx dbc/dataid.xlsx -o dbc/dataid.json
```
