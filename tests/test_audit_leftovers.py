"""Third batch of audit-fix regression tests.

Pins the smaller leftovers fixed after the PR #6/#7 merge: DataID default
conversion and text-cell base, description_regex failing loudly outside
openpyxl, XOR8 custom params, resolver warnings, profile-override fallback,
and the webapp run store's LRU eviction.
"""

from crc_checker.config import load_config
from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import PRESETS
from crc_checker.crc.profiles import _CRC_SIGNAL_NAME
from crc_checker.dataid.parser import (
    ColumnMapping, DataIDMap, _add_dataid_row, _auto_detect_columns,
    _parse_xls,
)
from crc_checker.dbc.models import (
    DBCProtectionMap, MessageProtection, SignalInfo)
from crc_checker.dbc.resolver import SignalResolver
from crc_checker.trace.models import CanFrame
from webapp.service import RunOutcome, RunStore


def test_dataid_default_string_converted_at_load(tmp_path):
    """A string dataid.default is converted at load, not mid-run."""
    base = '{"dbc": "x.dbc", "traces": ["t.blf"], "dataid": {"default": %s}}'
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(base % '"0x00EB"', encoding="utf-8")
    assert load_config(str(cfg_file)).dataid_default == 0x00EB

    cfg_file.write_text(base % "233", encoding="utf-8")
    assert load_config(str(cfg_file)).dataid_default == 233


def test_dataid_text_cells_respect_dataid_base():
    """Decimal-text DataID cells parse as decimal when the base says so."""
    mapping = ColumnMapping(
        col_signal_name=0, col_message_id=1, col_dataid_hi=2,
        col_dataid_lo=-1, dataid_format="single_8bit",
        dataid_base=10, data_row_start=2, message_id_base=16,
        signal_name_filter=[],
    )
    dm = DataIDMap()
    assert _add_dataid_row(["SIG", "0100", "84"], mapping, dm)
    assert dm.get(0x0100, "SIG") == 84  # not 0x84

    # 0x-prefixed text stays hex regardless of the base.
    dm2 = DataIDMap()
    assert _add_dataid_row(["SIG", "0100", "0x84"], mapping, dm2)
    assert dm2.get(0x0100, "SIG") == 0x84


def test_dataid_dec_header_autodetects_decimal_base():
    """A 'DataID (dec)' header switches text DataID cells to decimal."""
    mapping = ColumnMapping(
        col_signal_name=0, col_message_id=1, col_dataid_hi=2,
        col_dataid_lo=-1, dataid_format="single_8bit",
        data_row_start=2, message_id_base=16,
    )
    header = ["Signal", "Message ID", "Data ID (dec)"]
    resolved = _auto_detect_columns(mapping, header)
    assert resolved.dataid_base == 10


def test_parse_xls_rejects_description_regex():
    """description_regex on a legacy .xls fails loudly, not silently empty."""
    mapping = ColumnMapping(dataid_format="description_regex")
    try:
        _parse_xls("whatever.xls", "Sheet1", mapping)
    except ValueError as exc:
        assert "description_regex" in str(exc)
    else:
        raise AssertionError("description_regex .xls parse should raise")


def test_xor8_custom_params_apply_final_xor():
    """poly=0 checksums seed with initial_value and apply final_xor."""
    params = CRCParams(width=8, polynomial=0, initial_value=0x00,
                       final_xor=0xFF, name="XOR8/FF")
    engine = CRCEngine(params)
    frame = CanFrame(arbitration_id=0x100, timestamp=0.0, dlc=4,
                     data=bytes([0x01, 0x02, 0x03, 0x04]))
    # full_payload still excludes the CRC field byte itself (byte 0).
    assert engine.compute_for_frame(
        frame, CRCRange(mode="full_payload"), 0, 8, "little_endian"
    ) == 0xFF ^ 0x02 ^ 0x03 ^ 0x04


def test_resolver_warns_on_same_suffix_checksum(caplog):
    """Two checksums collapsing onto one suffix must log a warning."""
    frame = {
        "frame_id": 0x310, "frame_name": "DUP", "dlc": 8,
        "signals": [
            {"name": "DUP_CheckSum_Can01", "start_bit": 0, "length": 8,
             "byte_order": "little_endian", "comment": ""},
            {"name": "DUP_CheckSum_Can02", "start_bit": 8, "length": 8,
             "byte_order": "little_endian", "comment": ""},
        ],
    }
    with caplog.at_level("WARNING", logger="crc_checker"):
        prot_map = SignalResolver().build_protection_map([frame])
    groups = prot_map.messages[0x310]
    assert len(groups) == 1
    assert "overwrites" in caplog.text


def test_strategy4_skips_empty_frame_name():
    """An empty frame_name must not substring-match an arbitrary signal."""
    dm = DataIDMap(sheet_name="S")
    dm.add(0x100, "SomeChecksum", 0x1234)
    prot = MessageProtection(
        frame_id=0x100, frame_name="", dlc=8, pair_suffix="X",
        checksum_signal=SignalInfo(name="X_CRC", start_bit=0, length=8),
    )
    prot_map = DBCProtectionMap()
    prot_map.messages[0x100] = [prot]
    prot_map.apply_dataid_map(dm)
    assert prot.dataid is None


def test_crc_signal_name_regex_accepts_bare_crc():
    """A remark naming the signal plainly 'CRC' / 'CRC2' still matches."""
    assert _CRC_SIGNAL_NAME.match("CRC")
    assert _CRC_SIGNAL_NAME.match("CRC2")
    assert _CRC_SIGNAL_NAME.match("CCU_1_CRC2")
    assert not _CRC_SIGNAL_NAME.match("NotACrcSignal")


def test_apply_profile_overrides_partial_dict():
    """A partial profile-overrides dict falls back instead of KeyError."""
    prot = MessageProtection(
        frame_id=0x100, frame_name="M", dlc=8, pair_suffix="M",
        checksum_signal=SignalInfo(name="M_CRC", start_bit=0, length=8),
        crc_profile="Profile 1A",
    )
    prot_map = DBCProtectionMap()
    prot_map.messages[0x100] = [prot]
    prot_map.apply_profile_crc_params(
        default_params=PRESETS["CRC16/CCITT"], profile_overrides={})
    assert prot.crc_params is PRESETS["CRC16/CCITT"]


def test_run_store_evicts_least_recently_used(tmp_path):
    """A frequently downloaded report is not evicted just for being old."""
    store = RunStore(runs_dir=tmp_path, max_runs=3)
    runs = [
        RunOutcome(run_id=f"r{i}", created_at=float(i), project_id="p",
                   trace_name=f"t{i}.blf", payload={})
        for i in range(3)
    ]
    for outcome in runs:
        store.add(outcome)
    # Touch r0 (oldest) so it becomes most recently used.
    store.get("r0")
    store.add(RunOutcome(run_id="r3", created_at=3.0, project_id="p",
                         trace_name="t3.blf", payload={}))
    assert store.get("r0") is not None      # survived: recently used
    assert store.get("r1") is None          # evicted: least recently used
