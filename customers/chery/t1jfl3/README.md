# Chery T1JFL3 CAN CRC Checker

奇瑞 T1JFL3 CAN 总线 CRC/Rolling Counter 校验工具

## 算法

- **E2E Profile 1A**: CRC8/SAE-J1850-ZERO (poly=0x1D, init=0x00, xor=0x00)
  - DataID 放在数据场前（prepend, lo_hi）
  - CRC: 8 bit, 矩阵定义为大端格式
  - Counter: 4 bit, 最大值 14 (0xE)
  - 64-byte 报文保护范围：Byte2~Byte55

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
