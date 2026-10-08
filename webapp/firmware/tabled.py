"""PduId 表驱动的 net_cfg 解析(GWM/BAIC/Chery 及 GAC t75 系新一代生成物)。

新一代 com_code_gen 的生成物没有 per-message callout 注释,报文配置在
NetE2E_Cfg.cpp 的 PduId 索引表 ``g_rx/g_tx_e2e_cfg_ast`` 里;CAN ID 不在
表里(在 CanIf/Com 层),但表条目链到命名符号(``Config_<BUS>_<MSG>_<信号>_st``
/ ``m_u<BUS>_<MSG>_Rfc``),而符号名与 SysDesc/DBC 的 CSV 报文名同源(net
代码由该 DBC 生成)——联 CSV 得 CAN ID 与 Can Channel。已见三种表形态:

  A1 GWM(de09g/b06-5):条目 ``{len, count, {segs}, to_event, has_to}``,
     RX seg 7 字段 ``{config, check_state, sm_config, sm_check_state,
     offset, crc_event, rc_event}``,TX seg 3 字段;Config=E2E_P01ConfigType
  A2 GAC(t75 系):RX seg 9 字段带 data_length 与 is_p05(区分 P05/P01),
     TX seg 5 字段 ``{config, protect_state, offset, data_length, is_p05}``
  B  BAIC(b81vs):条目 ``{len, count, algo, &segs}``,algo=CRC_ALGO_P01/
     CRC_ALGO_CRCXOR,seg 是类型化 ``E2E_P01RxSeg`` / ``E2E_CrcxorRxSeg``
     数组(Crcxor seg 自带 offset/crc_len/crc_index/rc 位域)

CAN ID 解析失败(符号名在 CSV 里没有对应报文名)的报文整组跳过并给诊断,
不猜测 ID。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from webapp.firmware.csv_map import SysDescMap, resolve_msg_symbol
from webapp.firmware.e2e import (
    E2ECatalog,
    FirmwareE2E,
    PROFILE_PRESETS,
    _dedupe,
    _resolve,
    _split_args,
    parse_configs,
    parse_constants,
)

# PduId 索引表(RX/TX 两个方向各一张)
_TABLE = re.compile(
    r"const\s+(?:Rx|Tx)E2E_Cfg\s+g_(?P<dir>rx|tx)_e2e_cfg_ast\s*\[[^\]]*\]\s*=\s*\{")
# 类型化 seg 数组(BAIC 形态):static const E2E_P01RxSeg g_rx_segs_9[1] = {...};
_SEG_ARRAY = re.compile(
    r"static\s+const\s+E2E_(?P<kind>P01|Crcxor)(?P<dir>Rx|Tx)Seg\s+"
    r"(?P<name>\w+)\s*\[\s*\d*\s*\]\s*=\s*\{")
# 表条目链到的命名符号
_CONFIG_REF = re.compile(r"&Config_(?P<sym>\w+?)_st\b")
_RC_SYMBOL = re.compile(r"&m_u(?P<sym>\w+?)_Rfc\d*\b")


def _matching_brace(text: str, open_index: int) -> int:
    """``{`` 的配对 ``}`` 下标(嵌套计数);未闭合返回 -1。"""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _entry_groups(body: str) -> List[str]:
    """数组体按深度 1 的 ``{...}`` 组拆条目(空占位/间隔忽略)。"""
    groups, index = [], 0
    while index < len(body):
        if body[index] == "{":
            close = _matching_brace(body, index)
            if close < 0:
                break
            groups.append(body[index + 1:close])
            index = close + 1
        else:
            index += 1
    return groups


@dataclass
class SegInstance:  # pylint: disable=too-many-instance-attributes
    """One seg (per-message per-CRC-segment E2E instance) from a table walk."""

    stem: str             # Config_/rc_state 符号里的报文段(含总线前缀)
    kind: str             # "P01" | "P05" | "CRCXOR"
    direction: str = ""   # "Rx" | "Tx"
    offset: int = 0       # seg 基字节偏移(SduDataPtr + offset)
    data_length: int | None = None   # bits(t75 P05 的 <MSG>_DATALENGTH)
    crc_len: int | None = None       # 受保护字节数(Crcxor seg)
    crc_index: int | None = None     # CRC 字节在段内的下标(Crcxor seg)
    counter_offset: int | None = None  # bits(P01 Config / Crcxor 位域换算)
    counter_width: int | None = None   # bits(P01 固定 4,Crcxor 按 mask)


@dataclass
class TableEntry:
    """One PduId table entry: {msg_length, seg_count, segs[, ...]}."""

    direction: str                      # "Rx" | "Tx"
    msg_length: int | None = None
    seg_count: int = 0
    inline_segs: List[List[str]] = field(default_factory=list)  # seg 字段列表(Variant A)
    seg_ref: str = ""                   # &g_rx_segs_N(Variant B)
    algo: str = ""                      # CRC_ALGO_*(Variant B)


def _resolve_value(token: str, symbols: Dict[str, int]) -> Optional[int]:
    token = token.strip()
    if token.startswith("&"):
        return symbols.get(token[1:].rstrip("uU"))
    return _resolve(token, symbols)


def _parse_seg_fields(direction: str, fields: List[str],
                      symbols: Dict[str, int]) -> SegInstance | None:
    """内联 seg(字段列表)→ SegInstance,按方向与字段数区分形态。"""
    config_ref = _CONFIG_REF.search(" ".join(fields))
    if config_ref is None:
        return None
    stem = config_ref.group("sym")
    is_p05 = next((token.strip().lower() == "true" for token in fields
                   if token.strip().lower() in ("true", "false")), None)
    instance = SegInstance(stem=stem, kind="P05" if is_p05 else "P01",
                           direction=direction)
    if direction == "Rx":
        instance.offset = _resolve_value(fields[4], symbols) or 0
        if is_p05 and len(fields) >= 6:
            instance.data_length = _resolve_value(fields[5], symbols)
    else:
        instance.offset = _resolve_value(fields[2], symbols) or 0
        if is_p05 and len(fields) >= 4:
            instance.data_length = _resolve_value(fields[3], symbols)
    return instance


def _seg_instance_from_array(kind: str, direction: str, fields: List[str],
                             symbols: Dict[str, int]) -> SegInstance | None:
    """类型化 seg 数组条目(BAIC 形态)→ SegInstance。

    字段序按方向不同:P01 RX ``{config, check_state, sm_config,
    sm_check_state, offset, crc_event, rc_event}``(7 字段)/ TX ``{config,
    protect_state, offset}``(3 字段);Crcxor RX 9 字段 / TX 7 字段
    (0..6 同 RX,无事件字段)。
    """
    if kind == "P01":
        config_index, offset_index = (0, 4) if direction == "Rx" else (0, 2)
        if len(fields) <= offset_index:
            return None
        config_ref = _CONFIG_REF.search(fields[config_index])
        if config_ref is None:
            return None
        return SegInstance(stem=config_ref.group("sym"), kind="P01",
                           direction=direction,
                           offset=_resolve_value(fields[offset_index], symbols) or 0)
    # Crcxor: {offset, crc_len, crc_index, rc_local_byte, rc_shift,
    #          rc_val_mask, rc_state[, crc_event[, rc_event]]}
    if len(fields) < 7:
        return None
    rc_ref = _RC_SYMBOL.search(fields[6])
    if rc_ref is None:
        return None
    offset = _resolve_value(fields[0], symbols) or 0
    mask = _resolve_value(fields[5], symbols) or 0
    local_byte = _resolve_value(fields[3], symbols) or 0
    shift = _resolve_value(fields[4], symbols) or 0
    return SegInstance(
        stem=rc_ref.group("sym"), kind="CRCXOR", direction=direction,
        offset=offset,
        crc_len=_resolve_value(fields[1], symbols),
        crc_index=_resolve_value(fields[2], symbols),
        counter_offset=offset * 8 + local_byte * 8 + shift,
        counter_width=bin(mask).count("1") if mask else None,
    )


def parse_seg_arrays(cpp_text: str) -> Dict[str, list]:
    """类型化 seg 数组(BAIC 形态)→ {数组名: [字段列表, ...]}。"""
    arrays: Dict[str, list] = {}
    for match in _SEG_ARRAY.finditer(cpp_text):
        open_index = match.end() - 1
        close = _matching_brace(cpp_text, open_index)
        if close < 0:
            continue
        body = cpp_text[open_index + 1:close]
        entries = [_split_args(group) for group in _entry_groups(body)]
        arrays[match.group("name")] = entries
    return arrays


def parse_pdu_tables(cpp_text: str, symbols: Dict[str, int]) -> Dict[str, List[TableEntry]]:  # pylint: disable=too-many-locals
    """PduId 索引表(RX/TX)→ {方向: [TableEntry]}。

    条目第一/二个字段是 msg_length 与 seg_count;BAIC 形态带 algo 与
    ``&g_*_segs_N`` 引用,GWM/GAC 形态是内联 ``{...}`` segs。
    """
    tables: Dict[str, List[TableEntry]] = {}
    for match in _TABLE.finditer(cpp_text):
        open_index = match.end() - 1
        close = _matching_brace(cpp_text, open_index)
        if close < 0:
            continue
        body = cpp_text[open_index + 1:close]
        direction = match.group("dir").capitalize()
        entries = [_entry_from_fields(g, direction, symbols)
                   for g in _entry_groups(body)]
        tables[direction] = entries
    return tables


def _entry_from_fields(group: str, direction: str,  # pylint: disable=too-many-branches
                       symbols: Dict[str, int]) -> TableEntry | None:
    """One table entry body → TableEntry(读 msg_length/seg_count + segs)。"""
    fields = _split_args(group)
    if len(fields) < 2:
        return None
    entry = TableEntry(direction=direction)
    entry.msg_length = _resolve_value(fields[0], symbols)
    entry.seg_count = _resolve_value(fields[1], symbols) or 0
    for field_value in fields[2:]:
        token = field_value.strip()
        seg_ref = re.fullmatch(r"&(\w+segs\w*)", token)
        if seg_ref:
            entry.seg_ref = seg_ref.group(1)
        elif token.startswith("CRC_ALGO_"):
            entry.algo = token
        elif token.startswith("{"):
            inner = token[1:token.rfind("}")] if token.endswith("}") else token[1:]
            for seg_group in _entry_groups(inner):
                seg_fields = _split_args(seg_group)
                if seg_fields:
                    entry.inline_segs.append(seg_fields)
    return entry


def _collect_instances(tables: Dict[str, List[TableEntry]],
                       seg_arrays: Dict[str, list],
                       symbols: Dict[str, int]) -> List[SegInstance]:
    """两张表 → 每 seg 一个 SegInstance(BAIC 引用展开成 seg 数组条目)。"""
    instances: List[SegInstance] = []
    for direction, entries in sorted(tables.items()):
        for entry in entries:
            if entry.seg_count <= 0:
                continue
            if entry.inline_segs:
                for seg_fields in entry.inline_segs:
                    instance = _parse_seg_fields(direction, seg_fields, symbols)
                    if instance is not None:
                        instances.append(instance)
            elif entry.seg_ref:
                for seg_fields in seg_arrays.get(entry.seg_ref, []):
                    kind = entry.algo.removeprefix("CRC_ALGO_") if entry.algo else ""
                    if kind not in ("P01", "CRCXOR"):
                        kind = "P01" if "P01" in str(seg_fields) else "CRCXOR"
                    instance = _seg_instance_from_array(kind, direction,
                                                        seg_fields, symbols)
                    if instance is not None:
                        instances.append(instance)
    return instances


def _dataid_for(stem: str, configs: Dict[str, dict],
                symbols: Dict[str, int]) -> Optional[int]:
    config = configs.get(stem, {})
    dataid = config.get("dataid")
    if dataid is None:
        raw = symbols.get(f"COM_RX_MSG_{stem}_DATA_ID")
        dataid = raw if raw is not None else symbols.get(f"COM_TX_MSG_{stem}_DATA_ID")
    return dataid


def parse_tabled_model(cfg_text: str, header_text: str, csv_mapping: SysDescMap,  # pylint: disable=too-many-locals
                       config_path: str) -> E2ECatalog:
    """PduId 表驱动的 net_cfg(+SysDesc CSV)→ 该车型的 E2E 目录。

    Args:
        cfg_text: ``src/NetE2E_Cfg.cpp``(Config_*_st + PduId 表 + seg 数组)。
        header_text: ``inc/net_cfg/NetE2E_Cfg.hpp``(常量表),可为空。
        csv_mapping: SysDesc CSV 的报文映射(CAN ID 来源),可为空(则全部
            跳过并给诊断)。
        config_path: 生成物路径(记进每条目录,便于追溯)。
    """
    diagnostics: list[dict] = []
    symbols = parse_constants(header_text)
    configs = parse_configs(cfg_text, symbols)
    seg_arrays = parse_seg_arrays(cfg_text)
    tables = parse_pdu_tables(cfg_text, symbols)
    catalog = E2ECatalog(source_files=[config_path])

    if not tables:
        diagnostics.append({
            "level": "warning",
            "message": "net_cfg 里没有 PduId 索引表(g_rx/g_tx_e2e_cfg_ast)",
        })
        return catalog

    instances = _collect_instances(tables, seg_arrays, symbols)
    entries: list[FirmwareE2E] = []
    unresolved: list[str] = []
    for instance in instances:
        if csv_mapping is None:
            message, _candidate = None, ""
        else:
            message, _candidate = resolve_msg_symbol(instance.stem, csv_mapping)
        frame_id = message.can_id if message is not None else None
        if frame_id is None:
            unresolved.append(instance.stem)
            continue
        config = configs.get(instance.stem, {})
        profile = (config.get("profile") if instance.kind != "CRCXOR"
                   else "CRCXOR") or ("P05" if instance.kind == "P05" else "P01")
        dataid = _dataid_for(instance.stem, configs, symbols)
        data_length = instance.data_length or config.get("data_length")
        counter_offset = instance.counter_offset
        if profile == "P01" and counter_offset is None:
            raw = config.get("counter_offset")
            counter_offset = (instance.offset * 8 + raw) if raw is not None else None
        entries.append(FirmwareE2E(
            frame_id=frame_id,
            frame_name=message.msg_name if message is not None else instance.stem,
            bus=message.channel if message is not None else "",
            direction=instance.direction,
            profile=profile,
            preset=PROFILE_PRESETS.get(profile, ""),
            crc_offset=instance.offset,
            crc_len=instance.crc_len or (data_length // 8 if data_length else None),
            crc_index=instance.crc_index or 0,
            dlc=message.msg_length if message is not None else 0,
            dataid=dataid,
            data_length=data_length,
            counter_offset=counter_offset,
            counter_width=instance.counter_width or (4 if profile == "P01" else None),
            config_symbol=instance.stem,
            source_files=[config_path],
        ))

    if unresolved:
        preview = ", ".join(sorted(unresolved)[:5])
        diagnostics.append({
            "level": "warning",
            "message": f"{len(unresolved)} 个报文的 CAN ID 无法解析"
                       f"(符号名在 SysDesc CSV 里没有对应报文名),"
                       f"已跳过: {preview}...",
        })
    catalog.entries = _dedupe(entries)
    catalog.diagnostics = diagnostics
    return catalog
