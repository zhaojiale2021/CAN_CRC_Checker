"""固件 E2E 配置解析 — 从 mcu_app_j6 的生成物推导每个报文的实际保护。

支持 com_code_gen 产出的 GAC net_cfg 家族:每报文一个 callout 函数,注释行
自带 Name/ID/Len/Comments,函数体内按 profile 调 E2E_P05Verify/E2E_P01Verify,
配置在 NetE2E_Cfg.cpp 的 Config_*_st 初始化器、常量表在 NetE2E_Cfg.hpp::

    /* Name: BCS_1_B, ID: 0x167, Len: 64, Period: 10ms, ..., Comments: CANFD2*/
    ... E2E_P05Verify(&CheckState_..., &Config_..., &SMConfig_...,
                      PduInfoPtr->SduDataPtr + 0, 56u, ...) ...
    const E2E_P05ConfigType Config_..._st = {CRCOFFSET, <MSG>_DATALENGTH,
                                             COM_RX_MSG_..._DATA_ID, MAXDELTACOUNTERINIT};

PduId 表驱动的新一代生成物(GWM/BAIC/Chery 及 GAC t75 系)没有 CAN ID 注释,
需要联 Com/CanIf 生成物才能解析 —— 明确跳过并给出诊断,不猜测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# callout 注释行:/* Name: BCS_1_B, ID: 0x167, Len: 64, Period: 10ms, ..., Comments: CANFD2*/
_CALLOUT_HEADER = re.compile(
    r"/\*\s*Name:\s*(?P<name>[^,]+?),\s*ID:\s*(?P<fid>0x[0-9A-Fa-f]+),\s*"
    r"Len:\s*(?P<len>\d+),(?P<rest>[^*]*)\*/")
# callout 函数名结尾标出方向:...Channel_CAN_Rx / _Tx
_DIRECTION = re.compile(r"Channel_CAN_(?P<dir>Rx|Tx)\s*\(")
# 校验(RX)与保护(TX)调用:同一块结构,同一份 Config;TX 报文同样出现在 trace 里
_VERIFY_CALL = re.compile(r"(?:ZX_)?E2E_(?P<profile>P05|P01)(?:Verify|Protect)\s*\(")
_CONFIG_REF = re.compile(r"&Config_(?P<sym>\w+?)_st")
# `(PduInfoPtr->SduDataPtr + 0),\n 56u` 与不带括号的形式都要吃
_CRC_ARGS = re.compile(
    r"SduDataPtr\s*\+\s*(?P<offset>\d+)u?\s*\)?\s*,\s*(?P<length>\d+)u")
# fx12fl(Chery)原始 CRC 调用(不走 E2E 库):
#   crc_calculatecrc8h1d((PduInfoPtr->SduDataPtr), 8, 7)   — J1850 CRC-8
#   crc_calculatecrcxor((PduInfoPtr->SduDataPtr), 4, 2)    — SUM8/XOR-FF
# 实参 (SduDataPtr[, +offset], len, crc_index),crc_index 是 CRC 字节下标
_RAW_CALL = re.compile(
    r"crc_calculate(?P<kind>crc8h1d|crcxor)\s*\(\s*\(?\s*(?:PduInfoPtr->)?"
    r"SduDataPtr\s*(?:\+\s*(?P<offset>\d+)u?)?\s*\)?\s*,\s*(?P<length>\d+)u?\s*,"
    r"\s*(?P<index>\d+)u?")

# Config_*_st 初始化器(NetE2E_Cfg.cpp,多行)
_P05_CONFIG = re.compile(
    r"const\s+E2E_P05ConfigType\s+Config_(?P<sym>\w+?)_st\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL)
_P01_CONFIG = re.compile(
    r"const\s+E2E_P01ConfigType\s+Config_(?P<sym>\w+?)_st\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL)

# 常量表(NetE2E_Cfg.hpp):constexpr uintN NAME = 0x...u; 或 = NIBBLE_REVERSE_16(0x...u);
# 类型可能是 uint16 或 uint16_t(BAIC DataId.h 带 _t 后缀)
_CONST = re.compile(
    r"constexpr\s+uint\d+(?:_t)?\s+(?P<name>\w+)\s*=\s*"
    r"(?P<value>0x[0-9A-Fa-f]+|\d+|[A-Za-z0-9_]+\((?P<arg>0x[0-9A-Fa-f]+|\d+)u?\))u?\s*;")

# E2E_P01ConfigType 初始化器的字段序(components/E2E/inc/E2E_P01.h)
_P01_FIELDS = ("counter_offset", "crc_offset", "dataid", "dataid_nibble_offset",
               "dataid_mode", "data_length", "max_delta", "max_no_new", "sync_counter")
# E2E_P05ConfigType 初始化器的字段序(E2E_P05.h)
_P05_FIELDS = ("offset", "data_length", "dataid", "max_delta")


@dataclass
class FirmwareE2E:  # pylint: disable=too-many-instance-attributes
    """One message's E2E protection as implemented by the firmware."""

    frame_id: int
    frame_name: str
    bus: str = ""
    direction: str = ""                 # Rx | Tx
    profile: str = ""                   # "P05" | "P01" | "CRC8" | "CRCXOR"
    preset: str = ""                    # 实际预设名(CRC16/CCITT 等);空 = 按 profile 推
    crc_offset: int = 0                 # CRC 区域首字节(字节序)
    crc_len: int | None = None          # 受保护字节数(来自校验调用)
    crc_index: int = 0                  # CRC 字节在区域内的下标(P05/P01 为 0)
    dlc: int = 0                        # 报文长度字节(callout Len / CSV Msg Length)
    dataid: int | None = None
    data_length: int | None = None      # bits(来自 Config/常量表)
    counter_offset: int | None = None   # bits(P01)或字节(P05 固定布局)
    counter_width: int | None = None    # bits(P01 固定 4,CRCXOR 按 mask)
    config_symbol: str = ""
    source_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON shape for the results view."""
        return {
            "frame_id": self.frame_id,
            "frame_id_hex": f"0x{self.frame_id:03X}",
            "frame_name": self.frame_name,
            "bus": self.bus,
            "direction": self.direction,
            "profile": self.profile,
            "preset": self.preset,
            "crc_offset": self.crc_offset,
            "crc_len": self.crc_len,
            "dataid": None if self.dataid is None else f"0x{self.dataid:04X}",
            "data_length": self.data_length,
            "config_symbol": self.config_symbol,
        }


@dataclass
class E2ECatalog:
    """Parsed E2E catalog for one firmware model at one commit."""

    entries: List[FirmwareE2E] = field(default_factory=list)
    diagnostics: List[dict] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)


# 各家族 profile → 实际预设(preset)。callout 家族(fx12fl 原始 CRC 调用)
# 与 PduId 表驱动家族共用;P05/P01 与 profile 表(crc/profiles.py)语义一致。
PROFILE_PRESETS = {
    "P05": "CRC16/CCITT",
    "P01": "CRC8/SAE-J1850-ZERO",
    "CRC8": "CRC8/SAE-J1850",
    "CRCXOR": "SUM8/XOR-FF",
}


def _split_args(body: str) -> list[str]:
    """Split a C initializer body on top-level commas (bodies carry no braces)."""
    parts, depth, current = [], 0, []
    for char in body:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _resolve(token: str, symbols: Dict[str, int]) -> Optional[int]:
    """Resolve one initializer token to a number (literal hex/dec or symbol).

    生成物带 C 的 ``u`` 后缀(0x0640u / 448u),先剥掉再解析。
    """
    token = token.strip().rstrip("uU")
    if not token:
        return None
    if token.lower().startswith("0x"):
        return int(token, 16)
    if token.isdigit():
        return int(token)
    return symbols.get(token)


def _nibble_reverse_16(value: int) -> int:
    """NIBBLE_REVERSE_16(生成器模板里的宏): 半字节反转 0x430 → 0x0340。"""
    return (((value >> 12) & 0x000F) | ((value >> 4) & 0x00F0)
            | ((value << 4) & 0x0F00) | ((value << 12) & 0xF000)) & 0xFFFF


def parse_constants(header_text: str) -> Dict[str, int]:
    """constexpr 常量表(NetE2E_Cfg.hpp):DATALENGTH / DATA_ID / 全局偏移。

    NIBBLE_REVERSE_16(0x430) 这类宏包裹的值按宏定义求值,而不是当字面量。
    """
    constants: Dict[str, int] = {}
    for match in _CONST.finditer(header_text):
        raw = match.group("value")
        arg = match.group("arg")
        if arg is not None:
            value = int(arg.rstrip("uU").rstrip(")"), 0)
            if raw.startswith("NIBBLE_REVERSE_16"):
                value = _nibble_reverse_16(value)
        else:
            value = int(raw.rstrip("uU"), 0)
        constants[match.group("name")] = value
    return constants


def _parse_p05_config(match, symbols: Dict[str, int]) -> dict:
    values = [_resolve(token, symbols) for token in _split_args(match.group("body"))]
    fields_map = dict(zip(_P05_FIELDS, values))
    return {"offset": fields_map.get("offset") or 0,
            "data_length": fields_map.get("data_length"),
            "dataid": fields_map.get("dataid")}


def _parse_p01_config(match, symbols: Dict[str, int]) -> dict:
    values = [_resolve(token, symbols) for token in _split_args(match.group("body"))]
    fields_map = dict(zip(_P01_FIELDS, values))
    return {"counter_offset": fields_map.get("counter_offset"),
            "crc_offset": fields_map.get("crc_offset") or 0,
            "dataid": fields_map.get("dataid"),
            "data_length": fields_map.get("data_length")}


def parse_configs(cfg_text: str, symbols: Dict[str, int]) -> Dict[str, dict]:
    """Config_*_st 初始化器 → {symbol: {profile, dataid, data_length, ...}}。"""
    configs: Dict[str, dict] = {}
    for match in _P05_CONFIG.finditer(cfg_text):
        parsed = _parse_p05_config(match, symbols)
        parsed["profile"] = "P05"
        configs[match.group("sym")] = parsed
    for match in _P01_CONFIG.finditer(cfg_text):
        parsed = _parse_p01_config(match, symbols)
        parsed["profile"] = "P01"
        configs[match.group("sym")] = parsed
    return configs


def parse_callouts(cpp_text: str) -> List[dict]:
    """解析 callout 注释行 + 函数体内的校验调用 → 每报文一条。

    E2E 库家族(P05/P01 Verify/Protect 调用)之外,还认 fx12fl 的原始 CRC
    调用家族(crc_calculatecrc8h1d = CRC8/SAE-J1850、crc_calculatecrcxor =
    SUM8/XOR-FF;计数器位域不在调用里,由 SysDesc CSV 补)。
    """
    headers = list(_CALLOUT_HEADER.finditer(cpp_text))
    entries: List[dict] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(cpp_text)
        block = cpp_text[header.end():end]
        direction_match = _DIRECTION.search(block)
        bus_match = re.search(r"Comments:\s*(\S+)", header.group("rest") or "")
        entry = {
            "frame_name": header.group("name").strip(),
            "frame_id": int(header.group("fid"), 16),
            "dlc": int(header.group("len")),
            "bus": bus_match.group(1).strip() if bus_match else "",
            "direction": direction_match.group("dir") if direction_match else "",
        }
        verify = _VERIFY_CALL.search(block)
        if verify is not None:
            config = _CONFIG_REF.search(block)
            crc_args = _CRC_ARGS.search(block)
            entry.update({
                "profile": verify.group("profile"),
                "config_symbol": config.group("sym") if config else "",
                "crc_offset": int(crc_args.group("offset")) if crc_args else 0,
                "crc_len": int(crc_args.group("length")) if crc_args else None,
            })
        else:
            raw = _RAW_CALL.search(block)
            if raw is None:
                continue
            entry.update({
                "profile": "CRC8" if raw.group("kind") == "crc8h1d" else "CRCXOR",
                "config_symbol": "",
                "crc_offset": int(raw.group("offset") or 0),
                "crc_len": int(raw.group("length")),
                "crc_index": int(raw.group("index")),
            })
        entries.append(entry)
    return entries


def _dedupe(entries: List[FirmwareE2E]) -> List[FirmwareE2E]:
    """CANFD1_/CANFD2_ 是同一报文在两条总线上的重复配置,数值一致时合并。

    同一报文在 RX(Verify)与 TX(Protect)两路重复时同样合并,方向拼成
    ``Rx/Tx``;总线标记不同时拼成 ``CANFD1/CANFD2``。
    """
    unique: List[FirmwareE2E] = []
    seen: Dict[tuple, FirmwareE2E] = {}
    for entry in entries:
        key = (entry.frame_id, entry.profile, entry.crc_offset, entry.crc_len,
               entry.dataid, entry.data_length)
        existing = seen.get(key)
        if existing is None:
            seen[key] = entry
            unique.append(entry)
            continue
        if entry.bus and entry.bus not in existing.bus:
            existing.bus = f"{existing.bus}/{entry.bus}" if existing.bus else entry.bus
        if entry.direction and entry.direction not in existing.direction:
            existing.direction = (f"{existing.direction}/{entry.direction}"
                                  if existing.direction else entry.direction)
    return unique


def parse_model(callout_text: str, cfg_text: str, header_text: str,
                config_path: str) -> E2ECatalog:
    """一个车型 net_cfg 的三份生成物 → 该车型的 E2E 目录。

    Args:
        callout_text: ``src/NetCom_Callout_Can.cpp`` 的内容(带 Name/ID 注释)。
        cfg_text: ``src/NetE2E_Cfg.cpp``(Config_*_st 初始化器),可为空。
        header_text: ``inc/net_cfg/NetE2E_Cfg.hpp``(常量表),可为空。
        config_path: 生成物路径(记进每条目录,便于追溯)。
    """
    diagnostics: list[dict] = []
    symbols = parse_constants(header_text)
    configs = parse_configs(cfg_text, symbols)
    catalog = E2ECatalog(source_files=[config_path])

    entries: list[FirmwareE2E] = []
    unresolved: set[str] = set()
    for callout in parse_callouts(callout_text):
        config = configs.get(callout["config_symbol"], {})
        dataid = config.get("dataid")
        if dataid is None:
            raw = symbols.get(f"COM_RX_MSG_{callout['config_symbol']}_DATA_ID")
            dataid = raw if raw is not None else symbols.get(
                f"COM_TX_MSG_{callout['config_symbol']}_DATA_ID")
        if callout["config_symbol"] and dataid is None:
            unresolved.add(callout["config_symbol"])
        entries.append(FirmwareE2E(
            frame_id=callout["frame_id"],
            frame_name=callout["frame_name"],
            bus=callout["bus"],
            direction=callout["direction"],
            profile=callout["profile"],
            preset=PROFILE_PRESETS.get(callout["profile"], ""),
            crc_offset=callout["crc_offset"],
            crc_len=callout["crc_len"],
            crc_index=callout.get("crc_index", 0),
            dlc=callout.get("dlc", 0),
            dataid=dataid,
            data_length=config.get("data_length"),
            counter_offset=config.get("counter_offset"),
            config_symbol=callout["config_symbol"],
            source_files=[config_path],
        ))

    if unresolved:
        diagnostics.append({
            "level": "warning",
            "message": f"{len(unresolved)} 个报文的 DataID 无法从常量表解析,"
                       f"已置空: {', '.join(sorted(unresolved)[:5])}...",
        })
    catalog.entries = _dedupe(entries)
    return catalog
