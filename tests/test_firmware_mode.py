"""固件源码模式(mcu_app_j6 commit 节点)测试。

解析器测试用合成的 net_cfg 生成物文本,不依赖固件仓库,CI 可跑;
API 测试需要本地配置的固件仓库(config/firmware.yaml 的 path),没有则跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webapp.firmware.config import FirmwareRepoCfg, load_firmware_repos
from webapp.firmware.csv_map import (
    enrich_counter_from_csv,
    parse_sysdesc_csv,
    resolve_msg_symbol,
)
from webapp.firmware.e2e import parse_constants, parse_model
from webapp.firmware.catalog import assign_bus_channels, build_protection_map, entry_to_protection
from webapp.firmware.tabled import parse_tabled_model

REPO_ROOT = Path(__file__).resolve().parent.parent


def _configured_repo() -> FirmwareRepoCfg | None:
    repos = load_firmware_repos()
    return repos[0] if repos and repos[0].local_root() else None


# ---------------------------------------------------------------------------
# Parser (synthetic net_cfg artifacts)
# ---------------------------------------------------------------------------

CALLOUT = """
    /* Name: BCS_1_B, ID: 0x167, Len: 64, Period: 10ms, ReceiveTimeout: 80ms, Comments: CANFD2 */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_BCS_1_B_CANFD2_Can_Network_CANFD2_Channel_CAN_Rx(
        PduIdType PduId, P2CONST(PduInfoType) PduInfoPtr)
    {
        if (E2EVerifyFlag == TRUE)
        {
            boolean t = E2E_P05Verify(
                &CheckState_CANFD2_BCS_1_B_BCS_1_B_CRC_st,
                &Config_CANFD2_BCS_1_B_BCS_1_B_CRC_st,
                &SMConfig_CANFD2_BCS_1_B_BCS_1_B_CRC_st,
                PduInfoPtr->SduDataPtr + 0,
                56u,
                &SMCheckState_CANFD2_BCS_1_B_BCS_1_B_CRC_st);
        }
    }

    /* Name: ADC_4, ID: 0x1A3, Len: 64, Comments: CANFD1 */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_ADC_4_CANFD1_Can_Network_CANFD1_Channel_CAN_Rx(
        PduIdType PduId, P2CONST(PduInfoType) PduInfoPtr)
    {
        if (E2EVerifyFlag == TRUE)
        {
            boolean t = E2E_P01Verify(
                &CheckState_CANFD1_ADC_4_ADC_4_CRC_st,
                &Config_CANFD1_ADC_4_ADC_4_CRC_st,
                &SMConfig_CANFD1_ADC_4_ADC_4_CRC_st,
                PduInfoPtr->SduDataPtr + 0,
                &SMCheckState_CANFD1_ADC_4_ADC_4_CRC_st);
        }
    }

    /* Name: BCS_2_A, ID: 0x160, Len: 64, Comments: CANFR */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_BCS_2_A_CANFR_Can_Network_CANFR_Channel_CAN_Rx(
        PduIdType PduId, P2CONST(PduInfoType) PduInfoPtr)
    {
        if (E2EVerifyFlag == TRUE)
        {
            boolean t = E2E_P01Verify(
                &CheckState_CANFR_BCS_2_A_BCS_2_CRC_st,
                &Config_CANFR_BCS_2_A_BCS_2_CRC_st,
                &SMConfig_CANFR_BCS_2_A_BCS_2_CRC_st,
                PduInfoPtr->SduDataPtr + 0,
                &SMCheckState_CANFR_BCS_2_A_BCS_2_CRC_st);
        }
    }

    /* Name: MRRAD1, ID: 0x430, Len: 64, Comments: CANFD3FR */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_MRRAD1_CANFD3FR_Can_Network_CANFD3FR_Channel_CAN_Tx(
        PduIdType PduId, P2CONST(PduInfoType) PduInfoPtr)
    {
        (void)ZX_E2E_P05Protect(
            &Config_CANFD3FR_MRRAD1_Checksum430_st,
            &ProtectState_CANFD3FR_MRRAD1_Checksum430_st,
            (PduInfoPtr->SduDataPtr + 0),
            8u);
    }
"""

CFG = """
const E2E_P05ConfigType Config_CANFD2_BCS_1_B_BCS_1_B_CRC_st =
    {CRCOFFSET, CANFD2_BCS_1_B_DATALENGTH, COM_RX_MSG_CANFD2_BCS_1_B_BCS_1_B_CRC_DATA_ID,
     MAXDELTACOUNTERINIT};

const E2E_P01ConfigType Config_CANFD1_ADC_4_ADC_4_CRC_st =
    {COUNTEROFFSET, CRCOFFSET, 0x0640, DATAIDNIBBLEOFFSET, E2E_P01_DATAID_NIBBLE,
     CANFD1_ADC_4_DATALENGTH, MAXDELTACOUNTERINIT, MAXNONEWORREPEATEDDATA, SYNCCOUNTERINIT};

const E2E_P01ConfigType Config_CANFR_BCS_2_A_BCS_2_CRC_st =
    {COUNTEROFFSET, CRCOFFSET, COM_RX_MSG_CANFR_BCS_2_A_BCS_2_CRC_DATA_ID,
     DATAIDNIBBLEOFFSET, E2E_P01_DATAID_NIBBLE, CANFR_BCS_2_A_DATALENGTH,
     MAXDELTACOUNTERINIT, MAXNONEWORREPEATEDDATA, SYNCCOUNTERINIT};

const E2E_P05ConfigType Config_CANFD3FR_MRRAD1_Checksum430_st =
    {CRCOFFSET, RX_CANFD3FR_MRRAD1_Checksum430_DATALENGTH,
     COM_RX_MSG_CANFD3FR_MRRAD1_Checksum430_DATA_ID, MAXDELTACOUNTERINIT};
"""

HEADER = """
constexpr uint16 COUNTEROFFSET          = 8u;
constexpr uint16 CRCOFFSET              = 0u;
constexpr uint16 DATAIDNIBBLEOFFSET     = 12u;
constexpr uint16 CANFD2_BCS_1_B_DATALENGTH       = 448u;
constexpr uint16 CANFD1_ADC_4_DATALENGTH         = 448u;
constexpr uint16 CANFR_BCS_2_A_DATALENGTH        = 240u;
constexpr uint16 COM_RX_MSG_CANFD2_BCS_1_B_BCS_1_B_CRC_DATA_ID     = 0x0670u;
constexpr uint16 COM_RX_MSG_CANFR_BCS_2_A_BCS_2_CRC_DATA_ID        = 0x0032u;
constexpr uint16 COM_RX_MSG_CANFD3FR_MRRAD1_Checksum430_DATA_ID    = NIBBLE_REVERSE_16(0x430u);
"""


class TestParser:
    """NetE2E_Cfg 三份生成物 → E2E 目录。"""

    @pytest.fixture(name="catalog")
    def catalog_fixture(self):
        """Parse the synthetic artifacts once per test."""
        return parse_model(CALLOUT, CFG, HEADER, config_path="mcu_app_j6@dev:cpj_x/net_cfg/m")

    def test_constants_resolve_macros(self):
        """Literal and macro-wrapped constants both resolve to numbers."""
        constants = parse_constants(HEADER)
        assert constants["CANFD2_BCS_1_B_DATALENGTH"] == 448
        # NIBBLE_REVERSE_16 按宏定义求值,而不是当字面量:0x430 → 0x0340
        assert constants["COM_RX_MSG_CANFD3FR_MRRAD1_Checksum430_DATA_ID"] == 0x0340

    def test_verify_callout_parsed(self, catalog):
        """The RX P05 verify callout yields the full per-message entry."""
        entry = next(e for e in catalog.entries if e.frame_name == "BCS_1_B")
        assert entry.frame_id == 0x167
        assert entry.profile == "P05"
        assert entry.direction == "Rx"
        assert entry.bus == "CANFD2"
        assert entry.crc_offset == 0
        assert entry.crc_len == 56
        assert entry.dataid == 0x0670
        assert entry.data_length == 448
        assert entry.config_symbol == "CANFD2_BCS_1_B_BCS_1_B_CRC"

    def test_tx_protect_callout_parsed(self, catalog):
        """TX 报文的 ZX_E2E_P05Protect 同样可解析(trace 里有 MCU 发出的帧)。"""
        entry = next(e for e in catalog.entries if e.frame_name == "MRRAD1")
        assert entry.frame_id == 0x430
        assert entry.direction == "Tx"
        assert entry.profile == "P05"
        assert entry.crc_len == 8
        # NIBBLE_REVERSE_16 包裹的 DataID 按宏求值
        assert entry.dataid == 0x0340

    def test_p01_fields_positional(self, catalog):
        """P01 初始化器按字段序解析:CounterOffset/CRCOffset/DataID/..."""
        entry = next(e for e in catalog.entries if e.config_symbol
                     == "CANFD1_ADC_4_ADC_4_CRC")
        assert entry.profile == "P01"
        assert entry.counter_offset == 8
        assert entry.crc_offset == 0
        assert entry.dataid == 0x0640
        assert entry.data_length == 448

    def test_no_diagnostics_on_clean_artifacts(self, catalog):
        """A clean set of artifacts parses without warnings."""
        assert catalog.diagnostics == []


# ---------------------------------------------------------------------------
# Catalog: entries → protection map + bus/channel assignment
# ---------------------------------------------------------------------------

class TestCatalogConversion:
    """E2E 条目 → 保护映射;总线按 trace 采样分配通道。"""

    def _catalog(self):
        return parse_model(CALLOUT, CFG, HEADER, config_path="mcu_app_j6@dev:m")

    def test_protection_map_groups_by_frame_id(self):
        """Entries group by frame id; P05/P01 layouts follow crc.profiles."""
        catalog = self._catalog()
        pm = build_protection_map(catalog)
        # 0x167 (P05) / 0x1A3 (P01) / 0x160 (P01) / 0x430 (P05) 都在映射里
        assert set(pm.all_frame_ids()) == {0x167, 0x1A3, 0x160, 0x430}
        for protections in pm.messages.values():
            for prot in protections:
                if prot.e2e_profile == "Profile 5":
                    assert prot.crc_params.name.startswith("CRC16/CCITT")
                    assert prot.crc_range.dataid_position == "append"
                    assert prot.crc_range.crc_byte_swap is True
                else:
                    assert prot.crc_params.name.startswith("CRC8/SAE-J1850")
                    assert prot.crc_range.dataid_position == "prepend"
                    assert prot.crc_range.crc_byte_swap is False
                assert prot.crc_range.mode == "custom_range"

    def test_radar_bus_dropped_when_absent(self):
        """总线不在 trace 通道里(台架没接)时整组丢弃并给诊断,不猜。"""
        catalog = self._catalog()
        # trace 里没有雷达报文:CANFR 命中率 0 → 整组丢弃
        channel_ids = {0: {0x167, 0x1A3}, 1: {0x1AE, 0x430}}
        assignment, _coverage, diagnostics = assign_bus_channels(catalog, channel_ids)
        assert set(assignment) == {"CANFD1", "CANFD2", "CANFD3FR"}
        assert "CANFR" not in assignment
        assert any("CANFR" in d["message"] for d in diagnostics)


# ---------------------------------------------------------------------------
# SysDesc CSV + PduId 表驱动(全适配:GWM/BAIC/Chery/GAC t75 家族)
# ---------------------------------------------------------------------------

# 列名与真实 SysDesc CSV 一致(按表头定位,生成器演进改列序不受影响)
_SYSDESC_HEADER = ("Can Channel,ECU,Msg Name,Msg ID(hex),Msg Length(bytes),"
                   "Signal Name,IsCrcSignal,IsRcSignal,Start Bit Position,"
                   "Signal Length")
SYSDESC_CSV = _SYSDESC_HEADER + """
CANA,ECU1,ABM1,0x351,2,Checksum_ABM1,No,No,,,
CANA,ECU1,ABM1,0x351,2,Checksum_ABM1,Yes,No,0,8
CANA,ECU1,ABM1,0x351,2,RollingCounter_ABM1,No,Yes,56,4
CAN0,ECU1,BLE_0x1F8,0x1F8,8,BleRpa1Chks,Yes,No,0,8
CAN0,ECU1,BLE_0x1F8,0x1F8,8,Rfc0,No,Yes,12,4
CAN0,ECU1,BDC_CAPE_1,0x570,8,Cape1Chks,No,No,,,
CANFD5,ECU1,BCS_2_C,0x160,64,BCS_2_CRC,Yes,No,0,16
CANFD5,ECU1,ACC_FD1,0x14A,8,Checksum_ACC_FD1,Yes,No,0,8
CANA,ECU1,ACC,0x141,8,Checksum_ACC,Yes,No,0,8
CAN0,ECU1,ADC_A_0x136,0x136,32,Adas1Chks,No,No,,,
"""

# GWM de09g 形态(A1):RX seg 7 字段内联,无 bool 标记,Config=E2E_P01ConfigType
GWM_CFG = """
const E2E_P01ConfigType Config_CANA_ABM1_Checksum_ABM1_st = {
    COUNTEROFFSET,
    CRCOFFSET,
    COM_RX_MSG_CANA_ABM1_Checksum_ABM1_DATA_ID,
    0u,
    E2E_P01_DATAID_BOTH,
    DATALENGTH,
    MAXDELTACOUNTERINIT,
    MAXNONEWORREPEATEDDATA,
    SYNCCOUNTERINIT};

const RxE2E_Cfg g_rx_e2e_cfg_ast[MAX_RX_PDU_ID + 1u] = {
    { 16, 1, {
        { &Config_CANA_ABM1_Checksum_ABM1_st,
          &CheckState_CANA_ABM1_Checksum_ABM1_st,
          &SMConfig_CANA_ABM1_Checksum_ABM1_st,
          &SMCheckState_CANA_ABM1_Checksum_ABM1_st,
          0, DEM_EVENT_A_CRC, DEM_EVENT_B_RC },
    }, DEM_EVENT_TO, true },
    { 8, 0, { }, DEM_EVENT_C_TO, false },
};

const TxE2E_Cfg g_tx_e2e_cfg_ast[MAX_TX_PDU_ID + 1u] = {
    { 8, 1, {
        { &Config_CANA_ABM1_Checksum_ABM1_st,
          &ProtectState_CANA_ABM1_Checksum_ABM1_st,
          0 },
    } },
};
"""

# GAC t75 形态(A2):RX seg 9 字段带 data_length 与 is_p05,Config 按 P05/P01 区分
GAC_CFG = """
const E2E_P05ConfigType Config_CANFD5_BCS_2_C_BCS_2_CRC_st =
    {CRCOFFSET, CANFD5_BCS_2_C_DATALENGTH, COM_RX_MSG_CANFD5_BCS_2_C_BCS_2_CRC_DATA_ID,
     MAXDELTACOUNTERINIT};

const E2E_P01ConfigType Config_CANFR_BCS_2_A_BCS_2_CRC_st =
    {COUNTEROFFSET, CRCOFFSET, COM_RX_MSG_CANFR_BCS_2_A_BCS_2_CRC_DATA_ID,
     DATAIDNIBBLEOFFSET, E2E_P01_DATAID_NIBBLE, CANFR_BCS_2_A_DATALENGTH,
     MAXDELTACOUNTERINIT, MAXNONEWORREPEATEDDATA, SYNCCOUNTERINIT};

const RxE2E_Cfg g_rx_e2e_cfg_ast[MAX_RX_PDU_ID + 1u] = {
    {64,
     1,
     {
         {(const void*)&Config_CANFD5_BCS_2_C_BCS_2_CRC_st,
          (void*)&CheckState_CANFD5_BCS_2_C_BCS_2_CRC_st,
          &SMConfig_CANFD5_BCS_2_C_BCS_2_CRC_st,
          &SMCheckState_CANFD5_BCS_2_C_BCS_2_CRC_st,
          0,
          CANFD5_BCS_2_C_DATALENGTH,
          DEM_EVENT_X_CRC,
          DEM_EVENT_Y_RC,
          true},
     }},
    {64, 0, {}},
};

const TxE2E_Cfg g_tx_e2e_cfg_ast[MAX_TX_PDU_ID + 1u] = {
    {64,
     1,
     {
         {(const void*)&Config_CANFD5_BCS_2_C_BCS_2_CRC_st,
          (void*)&ProtectState_CANFD5_BCS_2_C_BCS_2_CRC_st,
          0,
          CANFD5_BCS_2_C_DATALENGTH,
          true},
     }},
};
"""

# BAIC b81vs 形态(B):algo + 类型化 seg 数组引用,Crcxor seg 自带位域
BAIC_CFG = """
const E2E_P01ConfigType Config_CAN0_BLE_0x1F8_BleRpa1Chks_st = {
    COUNTEROFFSET,
    CRCOFFSET,
    COM_RX_MSG_CAN0_BLE_0x1F8_BleRpa1Chks_DATA_ID,
    0u,
    E2E_P01_DATAID_BOTH,
    CAN0_BLE_0x1F8_DATALENGTH,
    MAXDELTACOUNTERINIT,
    MAXNONEWORREPEATEDDATA,
    SYNCCOUNTERINIT};

static const E2E_P01RxSeg g_rx_segs_9[1] = {
    {&Config_CAN0_BLE_0x1F8_BleRpa1Chks_st,
     &CheckState_CAN0_BLE_0x1F8_BleRpa1Chks_st,
     &SMConfig_CAN0_BLE_0x1F8_BleRpa1Chks_st,
     &SMCheckState_CAN0_BLE_0x1F8_BleRpa1Chks_st,
     0u,
     DEM_EVENT_X_CRC,
     DEM_EVENT_Y_RC},
};

static const E2E_CrcxorRxSeg g_rx_segs_7[1] = {
    {0u,
     8u,
     7u,
     6u,
     0u,
     255u,
     &m_uCAN0_BDC_CAPE_1_Rfc0,
     DEM_EVENT_C_CRC,
     DEM_EVENT_D_RC},
};

const RxE2E_Cfg g_rx_e2e_cfg_ast[MAX_RX_PDU_ID + 1u] = {
    {8, 0, 0u, nullptr},
    {8, 1, CRC_ALGO_CRCXOR, &g_rx_segs_7},
    {8, 1, CRC_ALGO_P01, &g_rx_segs_9},
    {32, 2, CRC_ALGO_CRCXOR, &g_rx_segs_70},
};

const TxE2E_Cfg g_tx_e2e_cfg_ast[MAX_TX_PDU_ID + 1u] = {
    {8, 1, CRC_ALGO_CRCXOR, &g_tx_segs_2},
};

static const E2E_CrcxorTxSeg g_tx_segs_2[1] = {
    {0u, 8u, 7u, 6u, 0u, 255u, &m_uCAN0_BDC_CAPE_1_Rfc0},
};

# 多段 CRC:同一 PDU 两个 seg,各自带 Config 与 rc_state(不同下标)
static const E2E_CrcxorRxSeg g_rx_segs_70[2] = {
    {0u, 8u, 7u, 6u, 0u, 255u, &m_uCAN0_ADC_A_0x136_Rfc0},
    {8u, 8u, 15u, 14u, 0u, 255u, &m_uCAN0_ADC_A_0x136_Rfc1},
};
"""

# 各形态的常量表:GWM/GAC 用 uint16(BAIC DataId.h 用 uint16_t,一并覆盖)
TABLED_HEADER = """
constexpr uint16 COUNTEROFFSET          = 8u;
constexpr uint16 CRCOFFSET              = 0u;
constexpr uint16 DATAIDNIBBLEOFFSET     = 12u;
constexpr uint16 DATALENGTH             = 64u;
constexpr uint16 CANFD5_BCS_2_C_DATALENGTH       = 448u;
constexpr uint16 CANFR_BCS_2_A_DATALENGTH        = 240u;
constexpr uint16 CAN0_BLE_0x1F8_DATALENGTH       = 64u;
constexpr uint16_t COM_RX_MSG_CANA_ABM1_Checksum_ABM1_DATA_ID      = 0x0012u;
constexpr uint16 COM_RX_MSG_CANFD5_BCS_2_C_BCS_2_CRC_DATA_ID       = 0x0670u;
constexpr uint16 COM_RX_MSG_CANFR_BCS_2_A_BCS_2_CRC_DATA_ID        = 0x0032u;
constexpr uint16_t COM_RX_MSG_CAN0_BLE_0x1F8_BleRpa1Chks_DATA_ID   = 0x0009u;
"""


class TestSysDescCsv:
    """SysDesc CSV → Msg Name ↔ CAN ID;fx12fl 计数器从 IsRcSignal 行补。"""

    def _mapping(self):
        return parse_sysdesc_csv(SYSDESC_CSV)

    def test_msg_map_resolves_ids(self):
        """逐信号行收敛成报文级映射,ID/通道/长度齐全。"""
        mapping = self._mapping()
        abm1 = mapping.lookup("ABM1")
        assert abm1 is not None
        assert abm1.can_id == 0x351
        assert abm1.channel == "CANA"
        assert abm1.msg_length == 2

    def test_multi_channel_same_id_merge(self):
        """同名同 ID 在多条总线时保留多条并合并 channel。"""
        text = SYSDESC_CSV + "CANFD11,ECU1,BCS_2_C,0x160,64,BCS_2_CRC,Yes,No,0,16\n"
        mapping = parse_sysdesc_csv(text)
        bcs = mapping.lookup("BCS_2_C")
        assert bcs.can_id == 0x160
        assert "CANFD5" in bcs.channel and "CANFD11" in bcs.channel

    def test_crc_rc_signal_flags(self):
        """IsCrcSignal/IsRcSignal=Yes 行给出信号名与位域。"""
        mapping = self._mapping()
        abm1 = mapping.lookup("ABM1")
        assert abm1.crc_signal_name == "Checksum_ABM1"
        assert abm1.crc_start_bit == 0
        assert abm1.rc_signal_name == "RollingCounter_ABM1"
        assert abm1.rc_start_bit == 56
        assert abm1.rc_bits == 4

    def test_enrich_counter_from_csv(self):
        """fx12fl 原始 CRC 调用家族:计数器位域由 CSV 的 IsRcSignal 行补。"""
        mapping = self._mapping()
        entry = parse_model(RAW_CALL_CALLOUT, "", "", "fx12fl@test").entries[0]
        entry.profile = "CRC8"
        assert enrich_counter_from_csv([entry], mapping) == 1
        assert entry.counter_offset == 56
        assert entry.counter_width == 4


class TestSymbolResolution:
    """报文符号名 → CSV 报文(连续 token 最长匹配)。"""

    def _mapping(self):
        return parse_sysdesc_csv(SYSDESC_CSV)

    def test_prefix_style_strips_checksum_signal(self):
        """GWM 前缀风格:Config_<BUS>_<MSG>_<Checksum 信号>_st → MSG。"""
        message, candidate = resolve_msg_symbol("CANA_ABM1_Checksum_ABM1", self._mapping())
        assert candidate == "ABM1"
        assert message.can_id == 0x351

    def test_crcxor_rc_state_symbol(self):
        """CRCXOR 的 rc_state 符号(m_u 前缀)→ 剥掉 m_u 与 _RfcN。"""
        message, candidate = resolve_msg_symbol("CAN0_BDC_CAPE_1", self._mapping())
        assert candidate == "BDC_CAPE_1"
        assert message.can_id == 0x570

    def test_embedded_id_in_msg_name(self):
        """报文名内嵌 ID 的(b81vs BLE_0x1F8)整名匹配。"""
        message, candidate = resolve_msg_symbol("CAN0_BLE_0x1F8_BleRpa1Chks",
                                                self._mapping())
        assert candidate == "BLE_0x1F8"
        assert message.can_id == 0x1F8

    def test_longest_match_wins(self):
        """ACC_FD1 优先于 ACC(最长连续 token 匹配)。"""
        _message, candidate = resolve_msg_symbol("CANA_ACC_FD1_Checksum_ACC_FD1",
                                                 self._mapping())
        assert candidate == "ACC_FD1"

    def test_unresolved_returns_none(self):
        """符号名在 CSV 里没有对应报文名 → None,不猜。"""
        message, candidate = resolve_msg_symbol("CANA_NO_SUCH_MSG_Foo_st",
                                                self._mapping())
        assert message is None and candidate == ""


class TestTabledParser:
    """PduId 表驱动的 net_cfg(三种形态)→ E2E 目录。"""

    def _catalog(self, cfg_text, csv_text=SYSDESC_CSV):
        mapping = parse_sysdesc_csv(csv_text) if csv_text else None
        return parse_tabled_model(cfg_text, TABLED_HEADER, mapping,
                                  config_path="mcu_app_j6@dev:m")

    def test_gwm_p01_inline_segs(self):
        """GWM A1:内联 seg 无 bool 标记,P01 按 Config 类型定。"""
        catalog = self._catalog(GWM_CFG)
        entry = next(e for e in catalog.entries if e.frame_name == "ABM1")
        assert entry.profile == "P01"
        assert entry.preset == "CRC8/SAE-J1850-ZERO"
        assert entry.direction == "Rx/Tx"  # RX Verify + TX Protect 同一份 Config
        assert entry.counter_offset == 8
        assert entry.counter_width == 4
        assert entry.dataid == 0x0012
        assert entry.bus == "CANA"

    def test_gac_p05_is_p05_flag(self):
        """GAC A2:is_p05=true 的 seg 按 P05 解析,DataID 从常量表。"""
        catalog = self._catalog(GAC_CFG)
        entry = next(e for e in catalog.entries if e.frame_name == "BCS_2_C")
        assert entry.profile == "P05"
        assert entry.preset == "CRC16/CCITT"
        assert entry.direction == "Rx/Tx"
        assert entry.crc_len == 56  # 448 bits → 56 字节受保护
        assert entry.dataid == 0x0670
        assert entry.frame_id == 0x160
        assert entry.bus == "CANFD5"

    def test_baic_typed_segs_and_crcxor(self):
        """BAIC B:algo + 类型化 seg 数组;Crcxor 位域换算成绝对 bit。"""
        catalog = self._catalog(BAIC_CFG)
        crcxor = next(e for e in catalog.entries if e.frame_name == "BDC_CAPE_1")
        assert crcxor.profile == "CRCXOR"
        assert crcxor.preset == "SUM8/XOR-FF"
        assert crcxor.crc_len == 8
        assert crcxor.dataid is None  # SUM8 不用 DataID
        # seg {offset=0, rc_local_byte=6, rc_shift=0, mask=0xFF} → bit 48 宽 8
        assert crcxor.counter_offset == 48
        assert crcxor.counter_width == 8
        p01 = next(e for e in catalog.entries if e.frame_name == "BLE_0x1F8")
        assert p01.profile == "P01"
        assert p01.dataid == 0x0009
        assert p01.direction == "Rx"

    def test_multi_seg_instances_stay_separate(self):
        """同一 PDU 的多个 seg(多段 CRC)各自成组:不同 offset 不合并。"""
        catalog = self._catalog(BAIC_CFG)
        segs = [e for e in catalog.entries if e.frame_id == 0x136]
        assert len(segs) == 2
        offsets = sorted(e.crc_offset for e in segs)
        assert offsets == [0, 8]
        # 各 seg 的计数器位域独立换算(seg2 的 rc 在段内 byte 14,段基址 8 → 绝对 byte 22)
        widths = {e.counter_offset // 8 for e in segs}
        assert widths == {6, 22}

    def test_unresolved_ids_skipped_with_diagnostics(self):
        """符号名在 CSV 里无对应报文名 → 跳过并给诊断,不猜 ID。"""
        catalog = self._catalog(GWM_CFG, csv_text="Can Channel,ECU,Msg Name,Msg ID(hex)\n")
        assert catalog.entries == []
        assert any("CAN ID 无法解析" in d["message"] for d in catalog.diagnostics)

    def test_missing_csv_all_skipped(self):
        """CSV 缺失(csv_mapping=None)→ 全部跳过 + 诊断,不猜。"""
        catalog = self._catalog(GWM_CFG, csv_text=None)
        assert catalog.entries == []
        assert any("CAN ID 无法解析" in d["message"] for d in catalog.diagnostics)


# fx12fl(Chery)原始 CRC 调用家族:callout 注释自带 ID,调用体是
# crc_calculatecrc8h1d / crc_calculatecrcxor,不走 E2E 库
RAW_CALL_CALLOUT = """
    /* Name: ABM1, ID: 0x351, Len: 2, Period: 20ms, ReceiveTimeout: 200ms, Comments: CAN0 */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_ABM1_CAN0_Can_Network_CAN0_Channel_CAN_Rx(
        PduIdType PduId,
        P2CONST(PduInfoType, AUTOMATIC, COM_APPL_DATA) PduInfoPtr)
    {
        boolean uReturn = TRUE;
        if ((PduInfoPtr->SduLength) >= COM_RX_MSG_CAN0_ABM1_MESSAGE_LENGTH)
        {
            uint8   uCalCrc0 = crc_calculatecrcxor((PduInfoPtr->SduDataPtr), 2, 1);
            uint8   uSigCrc0 = *((uint8*)(PduInfoPtr->SduDataPtr + 1));
            boolean bCrcOk0  = (uCalCrc0 == uSigCrc0);
        }
        return uReturn;
    }

    /* Name: FCM_2, ID: 0x307, Len: 8, Comments: CAN0 */
    FUNC(boolean, COM_APPL_CODE)
    ComIPduCallout_FCM_2_CAN0_Can_Network_CAN0_Channel_CAN_Tx(
        PduIdType PduId,
        P2VAR(PduInfoType, AUTOMATIC, COM_APPL_DATA) PduInfoPtr)
    {
        uint8 uCrc = 0x00;
        uCrc                                    = crc_calculatecrc8h1d((PduInfoPtr->SduDataPtr), 8, 7);
        *((uint8*)(PduInfoPtr->SduDataPtr + 7)) = uCrc;
        return TRUE;
    }
"""


class TestRawCalloutFamily:
    """fx12fl 原始 CRC 调用(crc_calculatecrc8h1d / crcxor)的 callout 解析。"""

    def _entries(self):
        return parse_model(RAW_CALL_CALLOUT, "", "", "fx12fl@test").entries

    def test_crcxor_call_parsed(self):
        """crc_calculatecrcxor → CRCXOR,crc_index 是 CRC 字节下标。"""
        entry = self._entries()[0]
        assert entry.frame_id == 0x351
        assert entry.frame_name == "ABM1"
        assert entry.profile == "CRCXOR"
        assert entry.preset == "SUM8/XOR-FF"
        assert entry.direction == "Rx"
        assert entry.crc_len == 2
        assert entry.crc_index == 1
        assert entry.bus == "CAN0"

    def test_crc8_call_parsed(self):
        """crc_calculatecrc8h1d → CRC8/SAE-J1850(客户配置同款)。"""
        entry = next(e for e in self._entries() if e.frame_name == "FCM_2")
        assert entry.profile == "CRC8"
        assert entry.preset == "CRC8/SAE-J1850"
        assert entry.direction == "Tx"
        assert entry.crc_len == 8
        assert entry.crc_index == 7

    def test_protection_from_raw_call_entries(self):
        """原始调用条目 → 保护映射:J1850 CRC-8 + SUM8/XOR-FF 各自成组。"""
        mapping = parse_sysdesc_csv(SYSDESC_CSV)
        entries = self._entries()
        enrich_counter_from_csv(entries, mapping)
        protections = [entry_to_protection(e) for e in entries]
        assert all(p is not None for p in protections)
        crcxor = next(p for p in protections if p.frame_id == 0x351)
        assert crcxor.crc_params.name.startswith("SUM8/XOR-FF")
        assert crcxor.rolling_counter_signal is not None
        assert crcxor.rolling_counter_signal.length == 4


class TestRepoConfig:
    """config/firmware.yaml + 环境变量覆盖。"""

    def test_missing_file_is_empty(self, tmp_path):
        """A missing yaml means no repos configured."""
        assert not load_firmware_repos(tmp_path / "none.yaml")

    def test_env_overrides_path(self, tmp_path):
        """CRC_FIRMWARE_REPO_<ID>_PATH overrides the yaml path."""
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text(json.dumps({
            "firmware_repositories": [
                {"id": "mcu_app_j6", "name": "mcu", "path": "D:/old/path",
                 "url": "ssh://x/y.git"},
            ],
        }), encoding="utf-8")
        # local_root() requires a .git inside, so build a throwaway checkout.
        checkout = tmp_path / "mcu_app_j6"
        (checkout / ".git").mkdir(parents=True)
        repos = load_firmware_repos(cfg, env={
            "CRC_FIRMWARE_REPO_MCU_APP_J6_PATH": str(checkout)})
        assert repos[0].path == str(checkout)
        assert repos[0].local_root() == checkout

    def test_to_dict_never_leaks_paths(self):
        """The API shape carries names, never local paths."""
        repo = FirmwareRepoCfg(id="x", name="X", url="ssh://x/y.git", path="D:/secret")
        assert "secret" not in json.dumps(repo.to_dict())


# ---------------------------------------------------------------------------
# API (needs the configured local firmware repo; skipped on CI)
# ---------------------------------------------------------------------------

# pytest.mark.skipif only applies when bound to the name `pytestmark`; binding
# it to any other name silently does nothing and the tests run everywhere.
_FIRMWARE_REPO_AVAILABLE = _configured_repo() is not None


@pytest.mark.skipif(not _FIRMWARE_REPO_AVAILABLE,
                    reason="config/firmware.yaml 无可用的本地固件仓库")
class TestFirmwareApi:
    """固件源码模式的接口(需要本地固件仓库)。"""

    @pytest.fixture(name="client")
    def client_fixture(self, tmp_path):
        """API client backed by a throwaway run store."""
        # pylint: disable=import-outside-toplevel
        from fastapi.testclient import TestClient
        from webapp.main import create_app
        from webapp.service import RunStore
        return TestClient(create_app(store=RunStore(tmp_path / "runs", max_runs=3)))

    def test_repositories_endpoint(self, client):
        """GET /api/firmware/repositories returns the configured repos."""
        body = client.get("/api/firmware/repositories").json()
        assert body["count"] == len(body["repositories"])
        assert {"id", "name", "source"} <= set(body["repositories"][0])

    def test_scan_returns_models_and_nodes(self, client):
        """The scan lists models with support flags and per-model nodes."""
        body = client.post("/api/firmware/scan",
                           json={"repository_id": "mcu_app_j6", "commit": "develop"}).json()
        assert len(body["resolved_commit"]) == 40
        models = {m["id"]: m for m in body["models"]}
        assert "cpj_gac/s52" in models
        model = models["cpj_gac/s52"]
        assert {"supported", "reason", "path", "last_commit"} <= set(model)
        if model["last_commit"]:
            assert len(model["last_commit"]["commit"]) == 40
            assert model["last_commit"]["subject"]
        # 全适配后,PduId 表驱动的家族(GWM/BAIC/Chery/GAC t75 系)都支持,
        # 且带 SysDesc CSV 的定位结果
        for model_id in ("cpj_gwm/de09g", "cpj_baic/b81vs", "cpj_gac/t75"):
            assert models[model_id]["supported"], model_id
            assert models[model_id]["sysdesc_csv"].endswith(".csv"), model_id

    def test_verify_against_firmware_commit(self, client):
        """s52 车型 + 台架 trace:走 固件 E2E → 通道分配 → 校验 全链路。"""
        trace = next((REPO_ROOT / "customers/gac/eea30-bev/trace").glob("*.blf"))
        with open(trace, "rb") as handle:
            response = client.post("/api/firmware/verify", data={
                "repository_id": "mcu_app_j6", "commit": "develop",
                "model_id": "cpj_gac/s52", "max_frames": "1500",
            }, files={"file": (trace.name, handle)})
        assert response.status_code == 200, response.text
        body = response.json()
        source = body["source"]
        assert source["mode"] == "firmware"
        assert len(source["commit"]) == 40
        assert source["model_id"] == "cpj_gac/s52"
        assert source["entries"]["total"] > 0
        report = body["reports"][0]
        assert report["total_frames"] > 0
        assert body["report_url"].endswith("/report.html")

    def test_verify_rejects_unknown_commit(self, client):
        """An unresolvable ref is a 400, never a 500."""
        trace = next((REPO_ROOT / "customers/gac/eea30-bev/trace").glob("*.blf"))
        with open(trace, "rb") as handle:
            response = client.post("/api/firmware/verify", data={
                "repository_id": "mcu_app_j6", "commit": "no-such-ref-xyz",
                "model_id": "cpj_gac/s52",
            }, files={"file": (trace.name, handle)})
        assert response.status_code == 400

    def test_verify_rejects_unsupported_model(self, client):
        """A model with neither callout headers nor PduId tables is 400, never 500."""
        trace = next((REPO_ROOT / "customers/gac/eea30-bev/trace").glob("*.blf"))
        with open(trace, "rb") as handle:
            response = client.post("/api/firmware/verify", data={
                "repository_id": "mcu_app_j6", "commit": "develop",
                "model_id": "cpj_smartxtruck/sxt",
            }, files={"file": (trace.name, handle)})
        # sxt 两路解析都不支持:要么 400(不支持),要么 400(车型不存在),绝不 500
        assert response.status_code == 400

    def test_verify_tabled_model_with_csv_join(self, client):
        """全适配:表驱动车型(GWM de09g)联 SysDesc CSV 解析出条目。"""
        scan = client.post("/api/firmware/scan",
                           json={"repository_id": "mcu_app_j6", "commit": "develop"}).json()
        model = next(m for m in scan["models"] if m["id"] == "cpj_gwm/de09g")
        assert model["supported"] and model["sysdesc_csv"]
        # 不上传 trace 也能验证 catalog 解析:借 verify 接口全链路走一遍
        trace = next((REPO_ROOT / "customers/gwm/b06-5/trace").glob("*.blf"))
        with open(trace, "rb") as handle:
            response = client.post("/api/firmware/verify", data={
                "repository_id": "mcu_app_j6", "commit": "develop",
                "model_id": "cpj_gwm/de09g", "max_frames": "500",
            }, files={"file": (trace.name, handle)})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"]["model_id"] == "cpj_gwm/de09g"
        assert body["source"]["entries"]["total"] > 0
        # 条目带实际预设(SUM8/XOR-FF 或 SAE-J1850-ZERO 家族)
        assert body["source"]["supported"] is True


class TestFirmwareApiNoRepo:  # pylint: disable=too-few-public-methods
    """环境变量覆盖为空 = 回退 yaml 的 path;配置本身不因置空而失效。"""

    def test_env_override_cleared_falls_back_to_yaml(self):
        """Empty env value counts as unset; the yaml path stays."""
        repos = load_firmware_repos(
            env={"CRC_FIRMWARE_REPO_MCU_APP_J6_PATH": ""})
        assert [repo.id for repo in repos] == ["mcu_app_j6"]
