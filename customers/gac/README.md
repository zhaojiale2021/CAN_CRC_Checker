# GAC（广汽）ADC 校验包

广汽智能驾驶域控制器（ADC）的 CAN 总线 E2E 校验。按 **平台** 组织，不按单个项目 ——
DBC 与 DataID 配置表是按平台发布的，而 CRC 算法、信号命名、DataID 数值在所有项目间一致。

| 目录 | 平台 | 适用项目 | DataID 源表 | 示例 trace |
|------|------|----------|-------------|-----------|
| `eea40/` | EEA4.0 | **t75 / t996d / v20** | `EEA4.0 E2E DataID ConfigurationV1.9.xlsx` | 待放（T75/V20 的 trace） |
| `eea30-hev/` | EEA3.0 混动 | **t09 / t68 / t88** | `EEA3.0混动系列_E2E DataID Configuration_V1.32.xlsx` | 待放 |
| `eea30-bev/` | EEA3.0 纯电 AB | **s52 / s52-e046** | `EEA3.0纯电平台 E2E DataID Configuration_V3.0.xls`（旧版 .xls） | 有（S52 台架 `can_merge.blf`） |
| `radar/` | 雷达私有总线（FR/FLR/FRR/RLR/RRR） | 所有项目（雷达一致） | V20 固件 `NetE2E_Cfg.hpp`（OEM 表无雷达条目） | 待放 |

> 平台归属用 DBC 报文集合核对过（Jaccard / md5 指纹，2026-09）：
> s52 的 CANFD2 与纯电平台 DBC **md5 完全一致**，s52-e046 98.1%；t88 两个 DBC、t996d 两个 DBC
> 分别与混动/EEA4.0 平台 md5 完全一致；t68 的 DBC 文件名即 `EEA3.0混动_CMX_ADC_V10.0`。

> 项目与平台的对应关系如与实车不符，以实车 DBC 版本为准；新增项目通常**不需要新目录**，
> 只要它的 DBC 与某一平台一致，直接复用该平台目录并把 trace 放进 `trace/` 即可。

## 为什么可以通用（2026-09 核对结论）

三路核对（固件源码 / DBC+DataID 实表 / trace 实测）得到：

1. **算法一致**：profile 由 CRC 信号位宽决定 —— 2 字节 → Profile 5（CRC16/CCITT + DataID 追加 lo_hi
   + CRC 字节交换），1 字节 → Profile 1（CRC8/SAE-J1850-ZERO + DataID 前置）。8 个项目零差异。
   固件位置：`components/E2E/src/E2E_P05.c` / `E2E_P01.c`，`Crc.c`。
2. **DataID 数值一致**：按信号名比对 s52 / s52-e046 / t09 / t68 / t75 / t88 / t996d / v20 的
   `NetE2E_Cfg.hpp`，151~178 个信号 **0 处数值差异**；各平台 DataID 表对共有报文的数值也一致
   （97.5%~99.2%）。
3. **三平台 DBC 的 CRC/Counter 布局相同**：CRC 恒在第 0~1 字节、Counter 在第 2 字节
   （Profile 5），报文集合与载荷信号才有差异。

差异只出现在少数几处，都已经写进各平台 `config.json`：

- EEA3.0（混动/纯电）`CCU_SRS_1`（0x1AE）双 E2E 实例的分段：CRC_1 → 0~12 字节、CRC_2 → 13~31 字节；
  **EEA4.0 无分段**，只有单实例、按整帧 56 字节。
- `CCU_TimeSync`（0x400）的 `SYNC_FC_CRC` 不是 E2E，需跳过；EEA4.0 还要跳过 5 个 `*_ICE` 校验。
- `CCU_PADS_1`（0x396）按台架实测的 8 字节段（与固件 32 字节口径不一致，见平台 README）。

## 雷达（`radar/`）

雷达私有总线（FR/FLR/FRR/RLR/RRR）单列一个包，因为**雷达所有项目一致**，与整车平台无关：

- DBC 取 V20 的（V20 多一个 `CANFCR_Signal.dbc` 覆盖 FLR/FRR；其余项目只有 FR/RLR/RRR）。
- 报文是 **Profile 1**（8-bit CRC），保护**前 30 字节**（固件 `RADAR_DATALENGTH = 240` bit），
  CRC 在 Byte0、alive counter 在 bit 12（4-bit，0~14）；**BlockCounter 不校验**（它是块计数）。
- DataID 来自 V20 固件雷达总线常量（OEM E2E 表里没有雷达条目）；FR 部分与
  `G300_T75&V20_Proj_FR_Radar+CR_Radar_CMX_V2.1` 的 `Data ID` 表逐条一致。

## 固件侧已知差异（2026-09 核对，工具口径与固件不一致的地方）

工具已按下面结论配置；列在这里是为了看到报告异常时能快速对上固件侧原因。
详细证据见 `mcu_app_j6` 对应文件行号。

| 项目 | 现象 | 固件位置 |
|------|------|----------|
| s52-e046 | `CCU_SRS_1` 的 E2E **完全失效**：切片长度 8 ≠ `DataLength` 56，`E2E_P05Verify` 每次返回 `E2E_E_INPUTERR_WRONG`，既不校验也不报 DEM | `net_cfg/s52-e046/src/NetCom_Callout_Can.cpp:3386-3404`、`NetE2E_Cfg.hpp:124-125` |
| s52-e046 | 8-bit 的 `UINM_PADS_1_CRC` / `HOD_1_CRC` 被当成 P05/CRC16 校验 → HOD_1 持续误报 CRC DEM（PADS_1 事件被禁用，仅数据被判无效） | 同上 `:3186-3196`、`:3679-3686` |
| v20 | **702/703 条 DEM 事件宏被映射成 `DEM_EVENT_INVALID_VALUE`**（生成的宏用 `CAN0..CAN5`，Dem 配置用 `CANFD1/CANFD2/CANFR`）→ E2E/TO 全部不上报；且数据驱动型 callout 不看 `update_flag`，E2E 结果不 gate 数据 | `valin_cfg/v20/inc/valin_cfg/valin_cfg_dem_event.hpp:65`、`NetCom_Callout_Can.cpp:64-116` |
| t09 | `CCU_TimeSync/SYNC_FC_CRC` 按 P01 校验且 `CRCOffset=0`，但 DBC 里该 CRC 在 byte 1 → 每帧比错字节（事件当前禁用，属潜在问题） | `net_cfg/t09/src/NetCom_Callout_Can.cpp:3540-3547`、DBC `SYNC_FC_CRC : 15\|8` |
| t75/t996d/v20 | `LBMS_1` 用错 DataID：固件 `0x0424`（`RLBMS_1` 的值），OEM 表 `LBMS_1`(0x319) = `0x0122` | `net_cfg/t75/inc/net_cfg/NetE2E_Cfg.hpp:477-478` 等 |
| t68 | 缺 `EPB_2`(0x26B) 的 E2E 配置（t09 有）；DBC 里有该 CRC | `net_cfg/t68/src/NetE2E_Cfg.cpp` |
| 生成器 | CRC 切片 offset 仍按 8 字节向下取整（`CMainBase.py:513/584`），只有 `CCU_SRS_1` 用模板里的 `gac_override` 手工兜住；TX 按通道选 profile、RX 按位宽选，存在潜在分歧 | `tools/com_code_generator/CMainBase.py:513,584` |
| 全平台 | `*_ICE`（EEA4）与 `SYNC_FC_CRC` 不是 E2E，工具按 `crc.skip` 跳过；固件侧 t75 的 hooks 缺 `*_ICE` 排除规则（当前输出一致，重生成有风险） | `tools/com_code_generator/projects/gac.py:24-41,113-127` |

**已验证一致**：CRC 表与实现逐位对齐（CRC8 0x1D / CRC16 0x1021，SAE-J1850 校验值 0x4B、CCITT-FALSE 0x29B1）；
P05/P01 的 DataID 位置与字节序、counter 位置与 0x00~0x0E 合法范围、SRS_1 的 13/19 分段、
各报文 DataID 数值（除上表 LBMS 外全部一致）、每个 CRC 字段都有对应校验调用。

## 新增 / 更新平台

```bash
# 1) 放入新 DBC 与 DataID 源表
cp ADCPublic_CANFD1.dbc ADCPublic_CANFD2.dbc <平台目录>/dbc/

# 2) 重新生成 DataID JSON（源表更新后必做）
crc-check preprocess-dataid --xlsx "<平台目录>/dbc/<DataID 表>" \
    --sheet "Data ID Config" --mapping gac_eea4 -o <平台目录>/dbc/dataid.json

# 3) 放入 trace 后运行
cd <平台目录> && ./run.sh
```

## 配置要点（新平台复制粘贴时注意）

```jsonc
"crc": {
  "preset": "CRC16/CCITT",          // Profile 5 默认算法
  "byte_swap": true,                // Profile 5: CRC 结果字节交换
  "profile_by_width": true,          // 按 CRC 位宽自动选 Profile 5 / Profile 1
  "profiles": {
    // 可覆盖字段：preset / dataid_position / dataid_byte_order / byte_swap /
    //            counter_max_valid / range{mode,start_byte,end_byte}
    "p01": {
      "preset": "CRC8/SAE-J1850-ZERO",
      "dataid_position": "prepend",
      "byte_swap": false,
      "counter_max_valid": 14,       // 4-bit counter 合法 0~14（15 无效）
      "range": { "mode": "custom_range", "start_byte": 0, "end_byte": -1 }
    }
  },
  "range_overrides": {               // 逐报文校验段（SRS_1 双段）
    "SRS_1_CRC_1": { "mode": "custom_range", "start_byte": 0, "end_byte": 13 },
    "SRS_1_CRC_2": { "mode": "custom_range", "start_byte": 13, "end_byte": 32 }
  },
  "skip": ["SYNC_FC_CRC"]            // 非 E2E 信号
},
"range": { "mode": "custom_range", "start_byte": 0, "end_byte": 56 }
```

- Profile 1（8-bit）必须显式给 `range: custom_range`：若沿用 `exclude_crc`，
  在 CAN FD + DataID 组合下会被自动升级成 segment 模式（`protect/checksum.py`）。
- Profile 1 的 counter 是 4-bit、**合法范围 0~14**（15 为无效值），由 profile 的
  `counter_max_valid: 14` 带出；不要用全局 `rc.max_valid`，那会把 8-bit counter 一起限死。
- 报文级校验段用 `crc.range_overrides`（键为校验信号名）：`SRS_1_CRC_1/2` 双段、
  `UINM_PADS_1_CRC` 按台架实测的 8 字节段（0x396，与固件 32 字节口径不一致，见平台 README）。
- `dataid.json` 是快路径，源表更新后要重新生成，否则读到旧值。
- `filter.max_frames` 示例配置为 2000（跑得快）；正式校验设成 `null` 跑全量
  （S52 台架 trace 全量约 13.8 万条 CRC verdict）。
