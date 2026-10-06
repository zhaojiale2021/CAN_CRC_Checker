"""固件源码模式(mcu_app_j6 commit 节点)测试。

解析器测试用合成的 net_cfg 生成物文本,不依赖固件仓库,CI 可跑;
API 测试需要本地配置的固件仓库(config/firmware.yaml 的 path),没有则跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webapp.firmware.config import FirmwareRepoCfg, load_firmware_repos
from webapp.firmware.e2e import parse_constants, parse_model
from webapp.firmware.catalog import assign_bus_channels, build_protection_map

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
# Repo config
# ---------------------------------------------------------------------------

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
        repos = load_firmware_repos(cfg, env={
            "CRC_FIRMWARE_REPO_MCU_APP_J6_PATH": "D:/work/feature/mcu_app_j6"})
        assert repos[0].path == "D:/work/feature/mcu_app_j6"
        assert repos[0].local_root() is not None

    def test_to_dict_never_leaks_paths(self):
        """The API shape carries names, never local paths."""
        repo = FirmwareRepoCfg(id="x", name="X", url="ssh://x/y.git", path="D:/secret")
        assert "secret" not in json.dumps(repo.to_dict())


# ---------------------------------------------------------------------------
# API (needs the configured local firmware repo; skipped on CI)
# ---------------------------------------------------------------------------

pytestmark_repo = pytest.mark.skipif(_configured_repo() is None,
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
        ids = {m["id"] for m in body["models"]}
        assert "cpj_gac/s52" in ids
        model = next(m for m in body["models"] if m["id"] == "cpj_gac/s52")
        assert {"supported", "reason", "path", "last_commit"} <= set(model)
        if model["last_commit"]:
            assert len(model["last_commit"]["commit"]) == 40
            assert model["last_commit"]["subject"]

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
        """A table-driven model is refused with 400, never a 500."""
        trace = next((REPO_ROOT / "customers/gac/eea30-bev/trace").glob("*.blf"))
        with open(trace, "rb") as handle:
            response = client.post("/api/firmware/verify", data={
                "repository_id": "mcu_app_j6", "commit": "develop",
                "model_id": "cpj_gwm/de09g",
            }, files={"file": (trace.name, handle)})
        # de09g 是表驱动生成物:要么 400(不支持),要么 400(车型不存在),绝不 500
        assert response.status_code == 400


class TestFirmwareApiNoRepo:  # pylint: disable=too-few-public-methods
    """环境变量覆盖为空 = 回退 yaml 的 path;配置本身不因置空而失效。"""

    def test_env_override_cleared_falls_back_to_yaml(self):
        """Empty env value counts as unset; the yaml path stays."""
        repos = load_firmware_repos(
            env={"CRC_FIRMWARE_REPO_MCU_APP_J6_PATH": ""})
        assert [repo.id for repo in repos] == ["mcu_app_j6"]
