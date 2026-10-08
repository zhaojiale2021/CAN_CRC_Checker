"""SysDesc/DBC 的 ``cpj_<oem>_<model>.csv`` → Msg Name ↔ CAN ID 映射。

net 生成代码由该 CSV 对应的 DBC 生成(com_code_gen 头部 ``Dbc Version:`` 指向
同一 ``BswRta/SysDesc/DBC`` 目录),所以报文符号名与 CSV Msg Name 同源——
strip 总线前缀与信号后缀即可 join 出 CAN ID 与 Can Channel。PduId 表驱动的
生成物(GWM/BAIC/Chery 及 GAC t75 系)没有 CAN ID 注释,这里是它们的 ID 来源。

CSV 按「信号一行」组织,报文级列(Can Channel / Msg Name / Msg ID(hex) /
Msg Length(bytes))在每行重复;IsCrcSignal=Yes / IsRcSignal=Yes 的行给出
CRC / 滚动计数器信号名与位置(fx12fl 等原始 CRC 调用家族的计数器来源)。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Dict, List, Optional


def normalize_name(name: str) -> str:
    """大小写/下划线不敏感的名字键(与 DataIDMap.get_normalized 同思路)。"""
    return name.replace("_", "").strip().lower()


@dataclass
class CSVMessage:  # pylint: disable=too-many-instance-attributes
    """One message's identity as recorded by the SysDesc CSV."""

    msg_name: str
    can_id: int
    channel: str
    msg_length: int | None = None    # bytes
    crc_signal_name: str = ""
    crc_start_bit: int | None = None
    crc_bits: int | None = None
    rc_signal_name: str = ""
    rc_start_bit: int | None = None
    rc_bits: int | None = None

    def to_dict(self) -> dict:
        """JSON shape for the source entries view."""
        return {
            "msg_name": self.msg_name,
            "can_id": f"0x{self.can_id:03X}",
            "channel": self.channel,
            "msg_length": self.msg_length,
        }


class SysDescMap:
    """Msg Name(归一化)→ CSV 报文;同名跨总线时合入多条并合并 channel。"""

    def __init__(self) -> None:
        self.by_name: Dict[str, List[CSVMessage]] = {}

    def add(self, message: CSVMessage) -> None:
        """Add one message (same name+id across buses merges the channel)."""
        key = normalize_name(message.msg_name)
        existing = self.by_name.setdefault(key, [])
        for seen in existing:
            if seen.can_id == message.can_id:
                if message.channel and message.channel not in seen.channel:
                    joined = f"{seen.channel}/{message.channel}" if seen.channel \
                        else message.channel
                    seen.channel = joined
                return
        existing.append(message)

    def lookup(self, msg_name: str) -> Optional[CSVMessage]:
        """First message under this (normalized) name, or None."""
        hits = self.by_name.get(normalize_name(msg_name))
        return hits[0] if hits else None


def _column_index(header: List[str], *names: str) -> Optional[int]:
    lowered = [normalize_name(cell) for cell in header]
    for name in names:
        key = normalize_name(name)
        for index, cell in enumerate(lowered):
            if cell == key:
                return index
    return None


def _to_int(text: str) -> Optional[int]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text, 0) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


_CRC_FLAG = {"yes", "y", "true", "1"}


def _pick(row: List[str], column: Optional[int]) -> str:
    if column is None or column >= len(row):
        return ""
    return row[column].strip()


def _is_flag(row: List[str], column: Optional[int]) -> bool:
    return _pick(row, column).lower() in _CRC_FLAG


def parse_sysdesc_csv(text: str) -> SysDescMap:
    """逐信号行 → 报文级 SysDescMap(同名报文跨总线各留一条)。

    列按表头名定位(生成器演进改列序不受影响);IsCrcSignal/IsRcSignal=Yes
    的行把该信号记为报文的 CRC / RC 信号(带 Start Bit Position 与位长)。
    个别车型(t88/t996d/v20)的 CSV 带超大单元格(全矩阵贴在一张表里),
    放开 csv 模块默认的 128KB 字段上限。
    """
    csv.field_size_limit(max(csv.field_size_limit(), 16 * 1024 * 1024))
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return SysDescMap()
    header = rows[0]
    columns = {
        "channel": _column_index(header, "Can Channel"),
        "name": _column_index(header, "Msg Name"),
        "id": _column_index(header, "Msg ID(hex)"),
        "len": _column_index(header, "Msg Length(bytes)"),
        "signal": _column_index(header, "Signal Name"),
        "is_crc": _column_index(header, "IsCrcSignal"),
        "is_rc": _column_index(header, "IsRcSignal"),
        "start": _column_index(header, "Start Bit Position"),
        "bits": _column_index(header, "Signal Length"),
    }
    if columns["name"] is None or columns["id"] is None:
        return SysDescMap()
    mapping = SysDescMap()
    for row in rows[1:]:
        _absorb_row(mapping, row, columns)
    return mapping


def _absorb_row(mapping: SysDescMap, row: List[str],
                columns: dict) -> None:
    """One signal row → upsert the message record (CRC/RC signal fields)."""
    name = _pick(row, columns["name"])
    can_id = _to_int(_pick(row, columns["id"]))
    if not name or can_id is None:
        return
    message = _upsert_message(mapping, name, can_id, row, columns)
    if _is_flag(row, columns["is_crc"]):
        message.crc_signal_name = _pick(row, columns["signal"])
        message.crc_start_bit = _to_int(_pick(row, columns["start"]))
        message.crc_bits = _to_int(_pick(row, columns["bits"]))
    if _is_flag(row, columns["is_rc"]):
        message.rc_signal_name = _pick(row, columns["signal"])
        message.rc_start_bit = _to_int(_pick(row, columns["start"]))
        message.rc_bits = _to_int(_pick(row, columns["bits"]))


def _upsert_message(mapping: SysDescMap, name: str, can_id: int,
                    row: List[str], columns: dict) -> CSVMessage:
    """Find or create the message record for (name, can_id)."""
    hits = mapping.by_name.setdefault(normalize_name(name), [])
    for seen in hits:
        if seen.can_id == can_id:
            channel = _pick(row, columns["channel"])
            if channel and channel not in seen.channel:
                seen.channel = f"{seen.channel}/{channel}" if seen.channel else channel
            return seen
    message = CSVMessage(
        msg_name=name, can_id=can_id, channel=_pick(row, columns["channel"]),
        msg_length=_to_int(_pick(row, columns["len"])))
    hits.append(message)
    return message


def resolve_msg_symbol(stem: str, mapping: SysDescMap) -> tuple[Optional[CSVMessage], str]:
    """报文符号名 → CSV 报文(连续 token 最长匹配,先长后短、同长取最左)。

    生成符号 = ``Config_<BUS>_<MSG>_<信号>_st`` / ``m_u<BUS>_<MSG>_Rfc<N>``:
    报文名是符号里一段连续的 token。取全部连续子序列做归一化查找,最长匹配
    者胜(ACC_FD1 优先于 ACC);没有任何候选命中返回 None。

    Returns:
        (报文, 命中的候选名);未命中时 (None, "")。
    """
    tokens = [token for token in stem.split("_") if token]
    if not tokens:
        return None, ""
    for length in range(len(tokens), 0, -1):
        for start in range(0, len(tokens) - length + 1):
            candidate = "_".join(tokens[start:start + length])
            message = mapping.lookup(candidate)
            if message is not None:
                return message, candidate
    return None, ""


def enrich_counter_from_csv(entries, mapping: SysDescMap) -> int:
    """fx12fl 等原始 CRC 调用家族:计数器位域从 SysDesc CSV 的 IsRcSignal 行补。

    callout 的 crc_calculatecrc8h1d/crcxor 实参只带 CRC 位置,不带计数器;
    CSV 的 IsRcSignal=Yes 行(Start Bit Position + 位长)是计数器来源。
    返回充实成功的条目数。
    """
    filled = 0
    for entry in entries:
        if entry.profile not in ("CRC8", "CRCXOR") or entry.counter_offset is not None:
            continue
        message = mapping.lookup(entry.frame_name)
        if message is None or message.rc_start_bit is None:
            continue
        entry.counter_offset = message.rc_start_bit
        entry.counter_width = message.rc_bits
        filled += 1
    return filled
