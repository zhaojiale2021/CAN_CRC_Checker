# CAN CRC Checker

CAN 总线 CRC/Rolling Counter 校验工具，自动识别 DBC 中的 Checksum 和 RollingCounter 信号，与 trace 数据比对验证。

## 快速开始

### Windows
双击 `run.bat`，或用命令行：
```
run.bat gwm_config.json
```

### Linux / Git Bash
```
./run.sh gwm_config.json
```

### 直接调用
```
crc-check.exe run -c gwm_config.json -v
```

## 配置文件

```json
{
  "dbc": "dbc",                    // DBC 文件或目录
  "traces": ["trace"],             // trace 文件或目录 (.blf/.asc/.mf4/.trc)
  "crc": { "preset": "CRC8/SAE-J1850-ZERO" },
  "range": { "mode": "exclude_crc" },
  "dataid": {
    "xlsx": "dbc/dataid.xlsx",     // DataID Excel（可选）
    "mapping": "greatwall_j6m"     // 列映射预设
  },
  "filter": {
    "frame_ids": null,             // CAN ID 过滤，如 ["0x143","0x299"]
    "max_frames": 200              // 最大处理帧数
  },
  "output": {
    "format": "html",              // table | html
    "file": "report.html",
    "only_failures": false
  },
  "rc": { "max_valid": 14 }
}
```

## 常用命令

```bash
# 列出 CRC 预设算法
crc-check.exe presets

# 查看 DBC 中的保护信号
crc-check.exe inspect dbc/xxx.dbc

# 生成示例配置
crc-check.exe gen-config example.json

# 从配置运行
crc-check.exe run -c config.json -v

# 预处理 DataID Excel → JSON（加速后续运行）
crc-check.exe preprocess-dataid --xlsx dataid.xlsx -o dataid.json

# 直接 CLI 运行（不需要配置文件）
crc-check.exe verify --dbc dbc/ --trace trace/ --algo CRC8/AUTOSAR
```

## 支持格式

| 类型 | 格式 |
|------|------|
| DBC | `.dbc` |
| Trace | `.blf` `.asc` `.mf4` `.trc` `.csv` `.log` |
| DataID | `.xlsx` `.json` |
| Report | `.html` |

## 多 DBC

配置 `"dbc": "dbc"` 指向目录即可。工具会自动采样 trace，选择匹配度最高的 DBC，并自动匹配对应的 DataID sheet。
