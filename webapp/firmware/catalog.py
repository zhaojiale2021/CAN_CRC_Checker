"""固件 E2E 条目 → 校验用保护映射(无需 DBC)。

固件生成物本身就带每个报文的保护位位置(CRC 首字节、Counter 字节)与
DataID,直接合成 :class:`MessageProtection` 喂给校验引擎 —— 源码模式下
DBC 不是必需品,固件就是算法与位置的共同来源。

同一条 CAN ID 可能挂在多条总线上(雷达 CANFR/RLR/RRR 的 P01 与 CANFD 的
P05 是不同保护),而 trace 的通道号固件里没有:仿照配置模式的按通道选 DBC,
用 trace 采样把「固件总线」分配到「trace 通道」(按 ID 命中率),没有出现在
trace 里的总线(如台架没接雷达)整组丢弃并给诊断,不猜。
"""

from __future__ import annotations

from crc_checker.crc.presets import get_preset
from crc_checker.crc.models import CRCRange
from crc_checker.dbc.models import (
    ChannelProtectionMap,
    DBCProtectionMap,
    MessageProtection,
    SignalInfo,
)
from webapp.firmware.e2e import E2ECatalog, FirmwareE2E, PROFILE_PRESETS

# P05: CRC16 写在 (Offset>>3) 起 LE 两个字节;DBC 定义为 BE 16 位,
# 工具按 byte_swap 比对 —— 与既有 GAC 配置路径完全一致。
# Counter 在 CRC 后第二个字节(E2E_P05.c: DataPtr[ByteOffset + 2u])。
# P01: CRC8 在 CRCOffset>>3,Counter 4 bit 在 CounterOffset>>3(低位半字节)。
_P01_MAX_COUNTER = 14  # components/E2E/inc/E2E_P01.h E2E_P01_MAX_COUNTER_VALUE
DEFAULT_MIN_BUS_COVERAGE = 0.3
# 结果视图/HTML 里的家族标签:P05/P01 沿用既有 Profile 标签,新家族用预设名。
_PROFILE_LABELS = {"P05": "Profile 5", "P01": "Profile 1"}
# 源码模式支持的家族(callout 注释头/PduId 表/原始 CRC 调用三路解析都能出)。
SUPPORTED_PROFILES = ("P05", "P01", "CRC8", "CRCXOR")


def _counter_signal(entry: FirmwareE2E) -> SignalInfo | None:
    if entry.profile == "P05":
        return SignalInfo(f"{entry.frame_name}_Counter", (entry.crc_offset + 2) * 8,
                          8, "little_endian")
    if entry.profile == "P01":
        offset = entry.counter_offset
        if offset is None:
            return None
        return SignalInfo(f"{entry.frame_name}_Counter", offset, 4, "little_endian")
    if entry.profile in ("CRC8", "CRCXOR"):
        # CRC8/CRCXOR:计数器位域在解析期换算成绝对 bit(fx12fl 来自 SysDesc
        # CSV 的 IsRcSignal 行,b81vs 来自 Crcxor seg 的 rc_local_byte/rc_shift)。
        offset = entry.counter_offset
        if offset is None:
            return None
        width = entry.counter_width or 4
        return SignalInfo(f"{entry.frame_name}_Counter", offset, width,
                          "little_endian")
    return None


def _checksum_signal(entry: FirmwareE2E) -> SignalInfo | None:
    if entry.profile == "P05":
        return SignalInfo(f"{entry.frame_name}_CRC", entry.crc_offset * 8, 16,
                          "big_endian")
    if entry.profile == "P01":
        return SignalInfo(f"{entry.frame_name}_CRC", entry.crc_offset * 8, 8,
                          "little_endian")
    if entry.profile in ("CRC8", "CRCXOR"):
        # CRC 字节在区域基址 + crc_index 处(CRCXOR 的 crc_index 即固件
        # crc_calculatecrcxor 的第三实参)。
        return SignalInfo(f"{entry.frame_name}_CRC",
                          (entry.crc_offset + entry.crc_index) * 8, 8,
                          "little_endian")
    return None


def _crc_range(entry: FirmwareE2E) -> CRCRange:
    """受保护字节范围 + DataID 布局,语义与 crc.profiles 的 p01/p05 一致。"""
    if entry.profile == "P05":
        length = entry.crc_len or ((entry.data_length or 0) // 8) or None
        return CRCRange(
            mode="custom_range", start_byte=entry.crc_offset,
            end_byte=length if length else -1,
            dataid=entry.dataid, dataid_position="append",
            dataid_byte_order="lo_hi", crc_byte_swap=True)
    if entry.profile == "CRCXOR":
        # CRCXOR:求和区间是 seg 的 [offset, offset+crc_len),CRC 字节位
        # (offset+crc_index)由引擎排除 —— 与 crc_calculatecrcxor 的
        # skip-index 语义一致。
        return CRCRange(
            mode="custom_range", start_byte=entry.crc_offset,
            end_byte=(entry.crc_offset + entry.crc_len) if entry.crc_len else -1,
            dataid=entry.dataid, dataid_position="append",
            dataid_byte_order="lo_hi", crc_byte_swap=False)
    # P01/CRC8:受保护范围是 [crc_offset, crc_offset + DataLength/8) —— 固件
    # E2E_P01Verify 以 DataPtr = SduDataPtr + seg.offset 起算 Config 的
    # DataLength,多段报文每段只覆盖自己的块(雷达 240bit → 30 字节)。
    # CRC8(fx12fl)无 DataID,exclude_crc 同客户路径。
    length = (entry.data_length or 0) // 8
    if entry.profile == "CRC8":
        return CRCRange(mode="exclude_crc")
    return CRCRange(
        mode="custom_range", start_byte=entry.crc_offset,
        end_byte=(entry.crc_offset + length) if length else -1,
        dataid=entry.dataid, dataid_position="prepend",
        dataid_byte_order="lo_hi", crc_byte_swap=False)


def entry_to_protection(entry: FirmwareE2E) -> MessageProtection | None:
    """One firmware entry → one protection group (None for non-E2E entries)."""
    # preset 字段(解析期按 profile/固件调用定死)优先。四种家族:P05(GAC
    # CRC16)、P01(SAE-J1850-ZERO)、CRC8(fx12fl J1850)、CRCXOR(SUM8/XOR-FF)。
    preset = entry.preset or PROFILE_PRESETS.get(entry.profile, "")
    if not preset or entry.profile not in ("P05", "P01", "CRC8", "CRCXOR"):
        return None
    label = _PROFILE_LABELS.get(entry.profile, preset)
    return MessageProtection(
        frame_id=entry.frame_id,
        frame_name=entry.frame_name,
        dlc=entry.dlc or ((entry.data_length or 0) // 8 if entry.data_length else 0),
        pair_suffix="CRC" if entry.profile == "P05" else entry.frame_name,
        checksum_signal=_checksum_signal(entry),
        rolling_counter_signal=_counter_signal(entry),
        crc_params=get_preset(preset),
        crc_range=_crc_range(entry),
        dataid=entry.dataid,
        dataid_name=entry.frame_name,
        crc_profile=label,
        e2e_profile=label,
        rc_max_valid=(_P01_MAX_COUNTER if entry.profile == "P01" else None),
        dbc_source=entry.config_symbol,
    )


def _disambiguate_counter_names(protections: list[MessageProtection]) -> None:
    """同一 frame_id 的多组保护计数器同名时,RC 跟踪按信号名串线(STALE 误报)。

    多段帧(如 GWM 0x2AB 五个 Checksum_*)每组各有自己的 counter,按 CRC 字节
    偏移给信号名加后缀区分;单段帧不动(保持既有展示)。
    """
    names = [p.rolling_counter_signal.name for p in protections
             if p.rolling_counter_signal is not None]
    duplicated = {name for name in names if names.count(name) > 1}
    if not duplicated:
        return
    for protection in protections:
        signal = protection.rolling_counter_signal
        if signal is not None and signal.name in duplicated:
            signal.name = f"{signal.name}@{protection.crc_range.start_byte:02X}"


def _bus_maps(catalog: E2ECatalog) -> dict[str, DBCProtectionMap]:
    """Group entries by firmware bus → one protection map per bus."""
    maps: dict[str, DBCProtectionMap] = {}
    for entry in catalog.entries:
        protection = entry_to_protection(entry)
        if protection is None:
            continue
        bus_map = maps.setdefault(entry.bus or "", DBCProtectionMap())
        bus_map.messages.setdefault(entry.frame_id, []).append(protection)
    for bus_map in maps.values():
        for protections in bus_map.messages.values():
            _disambiguate_counter_names(protections)
    return maps


def assign_bus_channels(  # pylint: disable=too-many-locals
    catalog: E2ECatalog, channel_ids: dict[int, set[int]],
    min_coverage: float = DEFAULT_MIN_BUS_COVERAGE,
) -> tuple[dict[str, int], dict[str, float], list[dict]]:
    """把固件总线分配到 trace 通道(按各通道上该总线 ID 的命中率)。

    Returns:
        (bus→channel, bus→命中率, diagnostics)。命中率不足 ``min_coverage``
        的总线(典型:台架没接的雷达总线)不参与校验,并记一条诊断。
    """
    bus_ids: dict[str, set[int]] = {}
    for entry in catalog.entries:
        if entry.profile in SUPPORTED_PROFILES:
            bus_ids.setdefault(entry.bus or "", set()).add(entry.frame_id)

    assignment: dict[str, int] = {}
    coverage: dict[str, float] = {}
    diagnostics: list[dict] = []
    for bus, ids in sorted(bus_ids.items()):
        best_channel, best_hits = None, 0.0
        for channel, seen in sorted(channel_ids.items()):
            if not ids:
                continue
            hits = len(ids & seen) / len(ids)
            if hits > best_hits:
                best_channel, best_hits = channel, hits
        coverage[bus] = round(best_hits, 3)
        if best_channel is None or best_hits < min_coverage:
            diagnostics.append({
                "level": "warning",
                "message": f"总线 {bus or '(无标记)'} 的报文在该 trace 中"
                           f"命中率 {best_hits:.0%},低于 {min_coverage:.0%},"
                           f"未参与校验(典型:台架未接这条总线)",
            })
            continue
        # 同一通道已被更合适的总线占用时仍共用:CANFD1/CANFD2 常混在同一通道。
        assignment[bus] = best_channel
    return assignment, coverage, diagnostics


def build_channel_map(  # pylint: disable=too-many-locals
    catalog: E2ECatalog, channel_ids: dict[int, set[int]],
    min_coverage: float = DEFAULT_MIN_BUS_COVERAGE,
) -> tuple[ChannelProtectionMap, dict[str, int], list[dict]]:
    """Firmware entries → channel-aware protection map (buses matched to channels)."""
    assignment, coverage, diagnostics = assign_bus_channels(
        catalog, channel_ids, min_coverage)
    channel_map = ChannelProtectionMap()
    bus_by_channel: dict[int, list[str]] = {}
    for bus, channel in assignment.items():
        bus_by_channel.setdefault(channel, []).append(bus)
    for channel, buses in sorted(bus_by_channel.items()):
        merged = DBCProtectionMap()
        for bus in buses:
            merged.merge(_bus_maps(catalog)[bus])
        channel_map.set_channel(channel, merged)
        diagnostics.append({
            "level": "info",
            "message": f"CH{channel} ← {' + '.join(buses)}"
                       f"(命中率 {min(coverage[b] for b in buses):.0%})",
        })
    for entry in catalog.entries:
        if entry.bus not in assignment and entry.bus not in coverage:
            diagnostics.append({
                "level": "warning",
                "message": f"报文 {entry.frame_name} 无总线标记,未参与校验",
            })
    return channel_map, assignment, diagnostics


def build_protection_map(catalog: E2ECatalog) -> DBCProtectionMap:
    """Bus-agnostic map over all entries (used when the caller needs every group)."""
    merged = DBCProtectionMap()
    for bus_map in _bus_maps(catalog).values():
        for frame_id, protections in bus_map.messages.items():
            merged.messages.setdefault(frame_id, []).extend(protections)
    return merged
