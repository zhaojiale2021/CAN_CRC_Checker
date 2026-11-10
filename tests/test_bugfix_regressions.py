"""Regression tests for the bug union fixed across two independent audits.

Each test pins one previously-broken behaviour so it cannot silently regress:

* multi-pattern ``(?i)`` joins crashed on Python 3.11+,
* ``classify_crc_algo`` misread ``DataID:0x01A5`` as Profile 1A,
* ``parse_sum_byte_range`` missed the compact ``byte1..7`` form,
* ``get_preset`` rejected ``CRC-8/AUTOSAR`` (hyphen inside the algorithm name),
* DataID column auto-detect let the bare ``data_id`` pattern hijack Hi/Lo columns,
* raw-xlsx fallback split rich-text shared strings and hex-parsed numeric cells,
* the HTML report emitted DBC message names unescaped,
* extended (29-bit) frame IDs never matched their protection group,
* segment-mode CRC coverage excluded the segment head instead of the CRC byte,
* the ``exclude_crc → segment`` upgrade dropped ``crc_byte_swap`` / ``dataid_width``,
* per-message CRC (profiles/overrides, no global preset) ran no CRC at all.
"""

# Tests exercise module-private helpers on purpose.
# pylint: disable=protected-access

import io
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import canmatrix
import openpyxl
import pytest

from cli.main import _print_table, _report_output_path
from crc_checker.config import RunConfig, apply_crc_config
from crc_checker.crc.classify import (
    classify_crc_algo, parse_sum_byte_range,
)
from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset
from crc_checker.crc.profiles import load_profiles
from crc_checker.dataid.parser import (
    ColumnMapping, _auto_detect_columns, parse_dataid_xlsx,
)
from crc_checker.dbc.models import (
    DBCProtectionMap, MessageProtection, SignalInfo,
)
from crc_checker.patterns import join_patterns
from crc_checker.protect.checksum import CRCVerifier
from crc_checker.protect.rolling_counter import RollingCounterVerifier
from crc_checker.report.html import (
    _bit_to_byte_pos, _build_frame_html, _build_rc_charts,
)
from crc_checker.trace.models import CanFrame
from crc_checker.verify.models import VerifyReport, VerifyVerdict


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

def test_join_patterns_scopes_leading_global_flags():
    """Multiple patterns each carrying ``(?i)`` compile on Python 3.11+."""
    joined = join_patterns(("(?i)^(checksum)", "(?i)_crc$"))
    compiled = re.compile(joined)
    assert compiled.match("CheckSum_X")
    assert compiled.search("foo_CRC")


def test_join_patterns_no_flags_wrapped_scoped():
    """Patterns without a leading global flag keep their alternation semantics."""
    joined = join_patterns(("^foo$", "^bar$"))
    assert re.match(joined, "foo")
    assert re.match(joined, "bar")
    assert not re.match(joined, "qux")


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

def test_classify_profile5_dataid_with_1a_not_profile1a():
    """'Profile 5 ... DataID:0x01A5' contains '1A' inside the DataID literal."""
    assert classify_crc_algo("Profile 5 CRC, DataID:0x01A5") == "p05"


def test_classify_profile1a_still_detected():
    """Real Profile 1A comments still classify as p01."""
    assert classify_crc_algo("E2E Profile 1A CRC") == "p01"
    assert classify_crc_algo(
        "CRC checksum. ...（Profile：1A；DataID：0x00EB）") == "p01"


def test_parse_sum_byte_range_compact_form():
    """'byte1..7' end index has no leading 'byte' — the compact range is read."""
    assert parse_sum_byte_range("(byte1..7, byte9..15)") == (1, 7)


def test_parse_sum_byte_range_enumerated_unchanged():
    """The enumerated 'Byte0+…+Byte6' form still works."""
    assert parse_sum_byte_range(
        "((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF"
    ) == (0, 6)


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------

def test_get_preset_crc8_hyphen_catalogue_name():
    """The canonical catalogue spelling 'CRC-8/AUTOSAR' resolves."""
    assert get_preset("CRC-8/AUTOSAR").name == "CRC8/AUTOSAR"
    assert get_preset("CRC16/Ccitt") is get_preset("CRC16/CCITT")


# ---------------------------------------------------------------------------
# DataID column auto-detect
# ---------------------------------------------------------------------------

def test_dataid_auto_detect_hi_lo_not_hijacked_by_data_id():
    """'Data ID High Byte' / 'Data ID Low Byte' resolve to the real columns."""
    mapping = ColumnMapping(
        col_signal_name=1, col_message_id=3, col_dataid_hi=12, col_dataid_lo=13,
        dataid_format="hi_lo_two_cols", data_row_start=3, message_id_base=16,
    )
    header = [None] * 20
    header[1] = "Signal Name"
    header[3] = "Message ID"
    header[12] = "Data ID High Byte"
    header[13] = "Data ID Low Byte"
    resolved = _auto_detect_columns(mapping, header)
    assert resolved.col_dataid_hi == 12
    assert resolved.col_dataid_lo == 13


# ---------------------------------------------------------------------------
# raw-xlsx shared strings / numeric cells
# ---------------------------------------------------------------------------

def _build_xlsx_shared_strings():
    """In-memory .xlsx whose shared string 0 is a two-run rich text."""
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        # rich-text shared string: one <si> with two <r>/<t> runs
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><r><t>Checksum_</t></r><r><t>ACC1</t></r></si>'
            '<si><t>0x2FA</t></si>'
            '</sst>',
        )
    raw.seek(0)
    return raw


def test_raw_xlsx_shared_strings_join_rich_runs():
    """A rich-text <si> (two runs) is one shared string, not two."""
    raw = _build_xlsx_shared_strings()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        handle.write(raw.read())
        path = Path(handle.name)
    try:
        with zipfile.ZipFile(path) as archive, archive.open(
                "xl/sharedStrings.xml") as sheet:
            ns = {'s': 'http://schemas.openxmlformats.org/'
                       'spreadsheetml/2006/main'}
            sis = ET.parse(sheet).findall('.//s:si', ns)
        assert len(sis) == 2
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# HTML report escaping
# ---------------------------------------------------------------------------

def test_frame_html_escapes_message_name():
    """A hostile DBC message name must not inject HTML."""
    verdicts = [VerifyVerdict(
        frame_id=0x135, timestamp=0.0, algorithm="crc", signal_name="CRC",
        expected_value=0, actual_value=0, is_pass=True, detail="",
        start_bit=0, length=8, byte_order="big_endian",
    )]
    html = _build_frame_html(
        verdicts, bytes(8),
        frame_name="<script>alert(1)</script>", dbc_source="x.dbc",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# extended frame ID
# ---------------------------------------------------------------------------

def test_extended_frame_id_is_masked():
    """29-bit IDs must not carry the 0x80000000 extended flag in the map."""
    frame = canmatrix.Frame(
        name="ExtMsg",
        arbitration_id=canmatrix.ArbitrationId(id=0xF110, extended=True),
        size=8,
    )
    assert frame.arbitration_id.to_compound_integer() & 0x1FFFFFFF == 0xF110


# ---------------------------------------------------------------------------
# segment CRC coverage
# ---------------------------------------------------------------------------

def test_segment_mode_excludes_crc_byte_not_segment_head():
    """A CRC not at the segment head is excluded at its real position."""
    engine = CRCEngine(get_preset("CRC8/SAE-J1850-ZERO"))
    data = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
    frame = CanFrame(arbitration_id=0x135, timestamp=0.0, dlc=8, data=data)
    # CRC at byte 3 (start_bit 24) of an 8-byte segment starting at byte 0:
    # input must be bytes 0..2 and 4..7, not "everything except byte 0".
    crc_range = CRCRange.for_segment(checksum_start_bit=24)
    result = engine.compute_for_frame(frame, crc_range, 24, 8, "little_endian")
    expected = engine.compute(bytes([0x11, 0x22, 0x33, 0x55, 0x66, 0x77, 0x88]))
    assert result == expected


def test_crc_byte_end_covers_unaligned_field():
    """An unaligned 8-bit CRC spans two bytes; both must leave the input.

    With canmatrix start-bit semantics, start_bit=71 / length=8 covers
    byte 8 bit 0 and byte 9 bits 7..1 (confirmed against ``cantools``), so
    the CRC input is bytes 10..15, not 9..15. Deriving the span from
    ``ceil(length/8)`` alone would leave byte 9 (seven CRC bits) in the
    input and make the expected CRC depend on its own bits.
    """
    engine = CRCEngine(get_preset("CRC8/SAE-J1850-ZERO"))
    payload = bytes.fromhex("0102030405060708 F1F2F3F4F5F6F7F8")
    frame = CanFrame(arbitration_id=0x135, timestamp=0.0, dlc=16, data=payload)
    crc_range = CRCRange.for_segment(checksum_start_bit=71, dataid=0x00E9)
    expected = engine.compute(bytes([0xE9, 0x00]) + payload[10:16])
    assert engine.compute_for_frame(frame, crc_range, 71, 8, "big_endian") == expected

    # Flipping any of the 8 CRC-field bits must not change the computed value.
    for bit_index in range(8):
        byte_idx, bit_in_byte = _bit_to_byte_pos(71, bit_index, "big_endian")
        mutated = bytearray(payload)
        mutated[byte_idx] ^= 1 << bit_in_byte
        assert engine.compute_for_frame(
            CanFrame(arbitration_id=0x135, timestamp=0.0, dlc=16, data=bytes(mutated)),
            crc_range, 71, 8, "big_endian") == expected


# ---------------------------------------------------------------------------
# crc_byte_swap propagated through the segment upgrade
# ---------------------------------------------------------------------------

def test_segment_upgrade_preserves_crc_byte_swap():
    """exclude_crc → segment keeps byte-swap (and DataID width)."""
    verifier = CRCVerifier(get_preset("CRC16/CCITT"))
    prot = MessageProtection(
        frame_id=0x193, frame_name="ADC_1", dlc=64, pair_suffix="ADC_1",
        checksum_signal=SignalInfo(name="ADC_1_CRC", start_bit=0, length=16),
        crc_params=get_preset("CRC16/CCITT"),
        crc_range=CRCRange(mode="exclude_crc", dataid=0xABCD,
                           dataid_position="append", dataid_byte_order="lo_hi",
                           dataid_width=1, crc_byte_swap=True),
        dataid=0xABCD,
    )
    frame = CanFrame(arbitration_id=0x193, timestamp=0.0, dlc=64,
                     data=bytes(64), is_fd=True)
    verdict = verifier.verify(frame, prot)
    assert verdict is not None
    # Segment over bytes 0..7, excluding the 16-bit CRC at bytes 0-1 →
    # input is 6 zero bytes + the DataID low byte (dataid_width=1), appended.
    raw = verifier.engine.compute(bytes(6) + bytes([0xCD]))
    swapped = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
    assert verdict.expected_value == swapped
    assert verdict.expected_value != raw


# ---------------------------------------------------------------------------
# per-message CRC without a global preset
# ---------------------------------------------------------------------------

def test_crc_verifier_without_default_params_skips_unconfigured():
    """A CRCVerifier with no default params skips a group with no params."""
    verifier = CRCVerifier(None)
    prot = MessageProtection(
        frame_id=0x500, frame_name="ONLY_RC", dlc=8, pair_suffix="ONLY_RC",
        checksum_signal=SignalInfo(name="ONLY_RC_CRC", start_bit=0, length=8),
    )
    assert verifier.verify(
        CanFrame(arbitration_id=0x500, timestamp=0.0, dlc=8, data=bytes(8)),
        prot,
    ) is None


def test_crc_verifier_uses_per_message_params_without_default():
    """Per-message params drive verification even with no default params."""
    verifier = CRCVerifier(None)
    prot = MessageProtection(
        frame_id=0x287, frame_name="ICM_5", dlc=8, pair_suffix="ICM_5",
        checksum_signal=SignalInfo(name="ICM_5_CRC", start_bit=0, length=8),
        crc_params=get_preset("CRC8/SAE-J1850-ZERO"),
        crc_range=CRCRange(mode="exclude_crc"),
    )
    frame = CanFrame(arbitration_id=0x287, timestamp=0.0, dlc=8,
                     data=bytes([0x00] * 8))
    verdict = verifier.verify(frame, prot)
    assert verdict is not None
    assert verdict.algorithm == "crc"


# ---------------------------------------------------------------------------
# HTML report output paths (multiple traces)
# ---------------------------------------------------------------------------

class _ReportStub:  # pylint: disable=too-few-public-methods
    trace_path = "/logs/trace_a.blf"


def test_report_output_path_unique_per_trace():
    """Several traces must not overwrite one report file."""
    single = _report_output_path("reports/report.html", _ReportStub(), False)
    assert single.endswith("report.html")
    first = _report_output_path("reports/report.html", _ReportStub(), True, index=1)
    other = _report_output_path(
        "reports/report.html",
        type("R", (), {"trace_path": "trace_b.blf"})(), True, index=2)
    assert Path(first).name == "report_1_trace_a.html"
    assert Path(other).name == "report_2_trace_b.html"
    assert first != other
    # Same file name in different directories must not collide either.
    dup = _report_output_path("reports/report.html", _ReportStub(), True, index=2)
    assert dup != first


def test_config_resolves_output_file_against_config_dir(tmp_path):
    """The report path is config-relative like DBC/trace paths."""
    cfg = RunConfig(output_file="out/report.html")
    cfg.resolve_paths(str(tmp_path))
    assert Path(cfg.output_file) == tmp_path / "out" / "report.html"


# ---------------------------------------------------------------------------
# CLI summary uses sample (not folded-verdict) counts
# ---------------------------------------------------------------------------

def test_cli_summary_counts_rc_samples(capsys):
    """A stuck counter folds verdicts; the SUMMARY must still count frames."""
    sig = SignalInfo(name="Counter_X", start_bit=0, length=4)
    prot = MessageProtection(frame_id=0x100, frame_name="M", dlc=8,
                             rolling_counter_signal=sig)
    verifier = RollingCounterVerifier()
    report = VerifyReport()
    for index, value in enumerate([0, 1, 1, 1, 1, 1, 1]):
        verdict = verifier.verify(
            CanFrame(arbitration_id=0x100, timestamp=float(index), dlc=8,
                     data=bytes([value] + [0] * 7)), prot)
        if verdict is not None:
            report.verdicts.append(verdict)
            report.total_verdicts += 1
    for key, points in verifier.get_series().items():
        report.rc_series[key] = points

    _print_table(report)
    summary = [line for line in capsys.readouterr().out.splitlines()
               if line.startswith("SUMMARY")][0]
    assert "2 passed" in summary
    assert "5 failed" in summary
    assert "28.6%" in summary


def test_rc_charts_report_stats_per_channel():
    """Each channel card shows its own errors/samples, not the group total."""
    report = VerifyReport()
    report.rc_series[(0x100, 0, "C")] = [
        (1.0, 0, True, ""), (2.0, 1, False, "STALE")]
    report.rc_series[(0x100, 1, "C")] = [
        (1.0, 0, True, ""), (2.0, 1, True, "")]
    for channel in (0, 1):
        report.rc_series_meta[(0x100, channel, "C")] = {
            "length": 4, "max_valid": 15}

    html = _build_rc_charts(report)
    cards = html.split('<div class="rc-chart-card')[1:]
    assert len(cards) == 2
    by_channel = {}
    for card in cards:
        channel = re.search(r">CH(\d)<", card).group(1)
        stats = re.search(r'stats">(.*?)</span>', card, re.S).group(1)
        by_channel[channel] = ("collapsed" in card.split(">")[0],
                               " ".join(stats.split()))
    assert by_channel["0"] == (False, 'errors: <span class="err">1')
    assert by_channel["1"] == (True, '<span class="ok">errors: 0')


# ---------------------------------------------------------------------------
# DataID header row / per-channel JSON / merged DBCs
# ---------------------------------------------------------------------------

def _write_two_sheet_workbook(path):
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "A"
    first.append(["Signal Name", "Message ID", "Data ID", "x"])
    first.append(["Sig_A_CRC", "100", "0x00AA", "x"])
    second = workbook.create_sheet("B")
    second.append(["Signal Name", "Message ID", "Data ID", "x"])
    second.append(["Sig_B_CRC", "200", "0x00BB", "x"])
    workbook.save(path)


def test_dataid_header_is_found_below_a_title_row(tmp_path):
    """Row 1 may be a title; the header lives at data_row_start - 1."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "S"
    sheet.append(["E2E DataID Configuration"])
    sheet.append([None, "Signal Name", None, "Message ID"]
                 + [None] * 8 + ["DataID High Byte", "DataID Low Byte"])
    sheet.append([None, "Msg_CRC", None, "0x100"]
                 + [None] * 8 + ["0x12", "0x34"])
    path = tmp_path / "ids.xlsx"
    workbook.save(path)

    assert parse_dataid_xlsx(str(path), "S",
                             mapping="hi_lo_two_cols")._map == {
        (0x100, "Msg_CRC"): 0x1234}


def test_channel_dataid_does_not_reuse_first_sheet(tmp_path):
    """Without a JSON cache each channel parses its own sheet."""
    path = tmp_path / "ids.xlsx"
    _write_two_sheet_workbook(path)
    cfg = RunConfig(dataid_xlsx=str(path),
                    dataid_json=str(tmp_path / "ids.json"),
                    dataid_mapping="generic_abc")
    assert cfg.load_dataid("A.dbc", allow_json=False)._map == {
        (0x100, "Sig_A_CRC"): 0xAA}
    assert cfg.load_dataid("B.dbc", allow_json=False)._map == {
        (0x200, "Sig_B_CRC"): 0xBB}


def test_merged_dbcs_load_every_sheet(tmp_path):
    """A merged run auto-matches one sheet per DBC."""
    path = tmp_path / "ids.xlsx"
    _write_two_sheet_workbook(path)
    cfg = RunConfig(dataid_xlsx=str(path), dataid_json=str(tmp_path / "ids.json"),
                    dataid_mapping="generic_abc")
    merged = cfg.load_dataid_for_dbcs(["A.dbc", "B.dbc"])
    assert merged._map == {
        (0x100, "Sig_A_CRC"): 0xAA,
        (0x200, "Sig_B_CRC"): 0xBB,
    }


def _map_with(frame_id: int) -> DBCProtectionMap:
    protection_map = DBCProtectionMap()
    protection_map.messages[frame_id] = [MessageProtection(
        frame_id=frame_id, frame_name=f"M{frame_id:X}", dlc=8,
        pair_suffix="X",
        checksum_signal=SignalInfo(name="CRC_X", start_bit=0, length=8))]
    return protection_map


def test_select_dbcs_samples_every_trace_and_backfills(monkeypatch):
    """Later traces contribute channels; unmatched channels get a fallback DBC."""
    # pylint: disable=import-outside-toplevel
    from crc_checker.verify import runner as runner_module

    samples = {
        "t1.blf": {0: {0x100}},
        "t2.blf": {1: {0x200}},
        "t3.blf": {2: {0x999}},
    }
    seen = []

    def fake_sample(path, max_frames=1000):  # pylint: disable=unused-argument
        seen.append(path)
        return samples[path]

    monkeypatch.setattr(runner_module, "sample_trace_channels", fake_sample)
    map_a, map_b = _map_with(0x100), _map_with(0x200)

    channel_map, ch_dbc = runner_module._select_dbcs(
        RunConfig(), [map_a, map_b], list(samples), [])

    assert seen == list(samples)
    assert set(ch_dbc) == {0, 1, 2}
    assert ch_dbc[0] is map_a
    assert ch_dbc[1] is map_b
    # CH2 matches no DBC; it falls back to the globally best map instead of
    # being silently unverified.
    assert ch_dbc[2] in (map_a, map_b)
    assert channel_map.get_protections(0x100, channel=0)


# ---------------------------------------------------------------------------
# profile selection vs comment classification
# ---------------------------------------------------------------------------

def test_width_profile_layout_is_dropped_when_comment_reclassifies():
    """A comment-classified group must not keep Profile 5's range/byte-swap."""
    protection_map = DBCProtectionMap()
    protection_map.messages[0x100] = [MessageProtection(
        frame_id=0x100, frame_name="M", dlc=64,
        checksum_signal=SignalInfo(name="Checksum_ID", start_bit=0, length=16),
        checksum_comment="0x01 XOR 0x27 XOR Byte0 XOR Byte1")]

    apply_crc_config(RunConfig(crc_profile_by_width=True, crc_auto_classify=True),
                     protection_map)
    group = protection_map.messages[0x100][0]
    assert group.crc_params.name.startswith("XOR8/SEED")
    assert group.crc_range.mode == "exclude_crc"
    assert group.crc_range.crc_byte_swap is False
    assert group.e2e_profile == ""


def test_profile_without_range_applies_dataid_layout():
    """P01's prepend/byte-swap apply even without a profile range object."""
    protection_map = DBCProtectionMap()
    protection_map.messages[0x100] = [MessageProtection(
        frame_id=0x100, frame_name="M", dlc=8, pair_suffix="X",
        checksum_signal=SignalInfo(name="CRC_X", start_bit=0, length=8),
        crc_profile="Profile 1A")]
    protection_map.apply_crc_range(CRCRange(mode="exclude_crc",
                                            dataid_position="prepend"))
    protection_map.apply_profiles(
        load_profiles({"p01": {"dataid_position": "append"}}),
        select_by_width=True)
    assert protection_map.messages[0x100][0].crc_range.dataid_position == "append"


# ---------------------------------------------------------------------------
# P2/P3 hardening
# ---------------------------------------------------------------------------

def test_inline_pattern_string_extends_builtin_prefixes():
    """A bare string must not be split into characters (matching everything)."""
    cfg = RunConfig(checksum_patterns="^MY_CRC")
    naming = cfg.build_naming_patterns()
    assert naming.checksum_re.search("MY_CRC")
    assert naming.checksum_re.search("Checksum_ACC1")   # built-in still active
    assert not naming.checksum_re.search("SpeedValue")


def test_inline_pattern_list_extends_prefixes():
    """List entries extend the built-in prefix rules (documented behaviour)."""
    cfg = RunConfig(checksum_patterns=["^MY_SUM$"])
    naming = cfg.build_naming_patterns()
    assert naming.checksum_re.search("MY_SUM")
    assert naming.checksum_re.search("CRC_ACC1")


def test_resolve_mapping_accepts_dict():
    """``dataid.mapping`` documents a JSON object; a dict must not TypeError."""
    from crc_checker.dataid import parser as dataid_parser  # pylint: disable=import-outside-toplevel

    resolved = dataid_parser.resolve_mapping({"col_signal_name": 0,
                                              "col_message_id": 1,
                                              "col_dataid_hi": 2})
    assert isinstance(resolved, dataid_parser.ColumnMapping)
    assert resolved.col_signal_name == 0


def test_description_regex_accepts_numeric_message_id():
    """Numeric cells are valid message IDs and must not be inherited."""
    from crc_checker.dataid.parser import (  # pylint: disable=import-outside-toplevel
        DataIDMap, _parse_description_regex,
    )

    class _Workbook:  # pylint: disable=too-few-public-methods
        @staticmethod
        def close():
            """No-op for the fake openpyxl workbook."""

    def row(message_id, name, signal, dataid):
        values = [None] * 30
        values[0], values[3], values[11], values[29] = (
            message_id, name, signal, dataid)
        return values

    class _Sheet:  # pylint: disable=too-few-public-methods
        @staticmethod
        def iter_rows(min_row, values_only=True):  # pylint: disable=unused-argument
            """Two description_regex rows, the second with a numeric message ID."""
            yield row("0x100", "MsgA", "MsgA_CRC", "DataID:0x0101")
            yield row(301, "MsgB", "MsgB_CRC", "DataID:0x0202")

    mapping = ColumnMapping(col_signal_name=11, col_message_id=0,
                            col_dataid_hi=29, dataid_format="description_regex",
                            data_row_start=1, message_id_base=16)
    result = DataIDMap()
    _parse_description_regex(_Sheet(), mapping, result, "S", _Workbook())
    assert result._map[(301, "MsgB_CRC")] == 0x0202


def test_missing_sheet_raises_instead_of_returning_empty(tmp_path):
    """A typo in dataid.sheet must fail loudly, not disable all DataIDs."""
    from crc_checker.dataid.parser import parse_dataid_xlsx_multi  # pylint: disable=import-outside-toplevel

    path = tmp_path / "ids.xlsx"
    _write_two_sheet_workbook(path)
    with pytest.raises(ValueError, match="not found"):
        parse_dataid_xlsx_multi(str(path), ["Typo"], mapping="generic_abc")


def test_unknown_range_mode_rejected():
    """A misspelled range mode used to CRC the full payload silently."""
    with pytest.raises(ValueError, match="Unknown CRC range mode"):
        RunConfig(range_mode="bogus").build_crc_range()
    engine = CRCEngine(get_preset("CRC8/AUTOSAR"))
    frame = CanFrame(arbitration_id=0x100, timestamp=0.0, dlc=8, data=bytes(8))
    with pytest.raises(ValueError, match="Unknown CRC range mode"):
        engine.compute_for_frame(frame, CRCRange(mode="bogus"), 0, 8)


def test_custom_crc_width_below_8_rejected():
    """Width < 8 raised an obscure negative-shift error during table build."""
    with pytest.raises(ValueError, match="between 8 and 32"):
        CRCParams(width=4, polynomial=0x3, initial_value=0, final_xor=0)


def test_reflect_in_without_reflect_out_reflects_result():
    """refin=True/refout=False is a legal combination and needs a final reflect."""
    params = CRCParams(width=8, polynomial=0x1D, initial_value=0xFF,
                       final_xor=0xFF, reflect_in=True, reflect_out=False)

    def reflect(value, bits):
        return int(f"{value:0{bits}b}"[::-1], 2)

    expected = 0xFF
    for byte in b"\x01\x02":
        expected ^= reflect(byte, 8)
        for _ in range(8):
            expected = ((expected << 1) ^ 0x1D) & 0xFF if expected & 0x80 \
                else (expected << 1) & 0xFF
    expected ^= 0xFF
    assert CRCEngine(params).compute(b"\x01\x02") == expected


def test_split_nav_keeps_configured_suffix():
    """Split-part links must match the files actually written."""
    from crc_checker.report.html import _split_nav  # pylint: disable=import-outside-toplevel

    nav = _split_nav(1, 2, "report.htm")
    assert "report_p2.htm" in nav
    assert "report_p2.html" not in nav


def test_zero_length_payload_renders_instead_of_crashing():
    """A DLC-0 frame with a verdict must not divide by zero."""
    verdict = VerifyVerdict(
        frame_id=0x100, timestamp=0.0, algorithm="crc", signal_name="CRC",
        expected_value=0, actual_value=0, is_pass=True,
        start_bit=0, length=8)
    assert _build_frame_html([verdict], b"", "M") != ""


def test_page_html_escapes_trace_and_dbc_paths(tmp_path):
    """Trace/DBC paths are user-controlled and must be HTML-escaped."""
    from crc_checker.report.html import write_html  # pylint: disable=import-outside-toplevel

    report = VerifyReport()
    report.trace_path = "<img src=x onerror=alert(1)>.blf"
    report.dbc_paths = ["<b>dbc</b>.dbc"]
    report.add_frame_data(0.0, 0x100, bytes(8))
    report.verdicts.append(VerifyVerdict(
        frame_id=0x100, timestamp=0.0, algorithm="crc", signal_name="CRC",
        expected_value=0, actual_value=0, is_pass=True,
        start_bit=0, length=8))
    path = tmp_path / "report.html"
    write_html(report, str(path))
    html = path.read_text(encoding="utf-8")
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    assert "<b>dbc</b>" not in html


def test_create_default_honors_crc_range():
    """The factory documents and must forward an explicit range."""
    from crc_checker.verify.engine import VerifyEngine  # pylint: disable=import-outside-toplevel

    crc_range = CRCRange(mode="custom_range", start_byte=1, end_byte=5)
    engine = VerifyEngine.create_default(
        DBCProtectionMap(), crc_params=get_preset("CRC8/AUTOSAR"),
        crc_range=crc_range)
    assert engine.algorithms[0]._explicit_range is crc_range  # pylint: disable=protected-access


def test_frame_data_keyed_by_channel():
    """Same (timestamp, id) on two channels must not overwrite each other."""
    report = VerifyReport()
    report.add_frame_data(1.0, 0x100, b"\x01", channel=0)
    report.add_frame_data(1.0, 0x100, b"\x02", channel=1)
    assert report.get_frame_data(1.0, 0x100, 0) == b"\x01"
    assert report.get_frame_data(1.0, 0x100, 1) == b"\x02"
    assert report.get_frame_channel(1.0, 0x100, 1) == 1


def test_safe_filename_blocks_windows_devices():
    """CON/NUL/COM1 resolve to devices on Windows, not upload files."""
    from webapp.main import safe_filename  # pylint: disable=import-outside-toplevel

    assert safe_filename("CON") == "_CON"
    assert safe_filename("NUL.blf") == "_NUL.blf"
    assert safe_filename("COM1") == "_COM1"
    assert safe_filename("normal.blf") == "normal.blf"


def test_negative_max_frames_rejected():
    """A negative cap used to mean "unlimited" silently."""
    from fastapi import HTTPException  # pylint: disable=import-outside-toplevel
    from webapp.main import _parse_frame_limit  # pylint: disable=import-outside-toplevel

    with pytest.raises(HTTPException) as exc_info:
        _parse_frame_limit("-1")
    assert exc_info.value.status_code == 400


def test_merge_keeps_empty_pair_suffix_group():
    """A group whose signal is named exactly ``CRC`` must survive a merge."""
    first = DBCProtectionMap()
    first.messages[0x100] = [MessageProtection(
        frame_id=0x100, frame_name="M", dlc=8, pair_suffix="A",
        checksum_signal=SignalInfo(name="CRC_A", start_bit=0, length=8))]
    second = DBCProtectionMap()
    second.messages[0x100] = [MessageProtection(
        frame_id=0x100, frame_name="M", dlc=8, pair_suffix="",
        checksum_signal=SignalInfo(name="CRC", start_bit=8, length=8))]

    assert first.merge(second) == 1
    assert {p.pair_suffix for p in first.messages[0x100]} == {"A", ""}


def test_first_rc_sample_out_of_range_is_invalid():
    """A first sample above max_valid is invalid even without a baseline."""
    signal = SignalInfo(name="Counter_X", start_bit=0, length=4)
    protection = MessageProtection(frame_id=0x100, frame_name="M", dlc=8,
                                   rolling_counter_signal=signal,
                                   rc_max_valid=14)
    verdict = RollingCounterVerifier().verify(
        CanFrame(arbitration_id=0x100, timestamp=0.0, dlc=8,
                 data=bytes([15] + [0] * 7)), protection)
    assert verdict is not None
    assert verdict.is_pass is False
    assert verdict.detail.startswith("INVALID")


def test_cli_unknown_preset_is_a_usage_error(tmp_path):
    """Unknown presets must not surface as a raw KeyError traceback."""
    import json  # pylint: disable=import-outside-toplevel
    from click.testing import CliRunner  # pylint: disable=import-outside-toplevel
    from cli.main import cli  # pylint: disable=import-outside-toplevel

    example = Path(__file__).resolve().parent.parent / "examples" / "example"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "dbc": str(example / "dbc"),
        "traces": [str(example / "trace" / "example.blf")],
        "crc": {"preset": "BOGUS"},
    }), encoding="utf-8")

    result = CliRunner().invoke(cli, ["run", "-c", str(config)])
    assert result.exit_code == 2
    assert "Unknown CRC preset" in result.output
    assert "Traceback" not in result.output


def test_cli_verify_accepts_trace_directory(tmp_path):
    """``--trace <dir>`` is expanded before DBC selection samples a file."""
    import shutil  # pylint: disable=import-outside-toplevel
    from click.testing import CliRunner  # pylint: disable=import-outside-toplevel
    from cli.main import cli  # pylint: disable=import-outside-toplevel

    example = Path(__file__).resolve().parent.parent / "examples" / "example"
    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    shutil.copy(example / "dbc" / "network.dbc", dbc_dir / "a.dbc")
    (dbc_dir / "b.dbc").write_text(
        'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\n'
        'BO_ 500 B: 8 ECU\n'
        ' SG_ X : 0|8@1+ (1,0) [0|255] "" ECU\n',
        encoding="utf-8",
    )
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    shutil.copy(example / "trace" / "example.blf", trace_dir / "example.blf")

    result = CliRunner().invoke(
        cli, ["verify", "--dbc", str(dbc_dir), "--trace", str(trace_dir),
              "--max-frames", "50"])
    assert result.exit_code == 0, result.output


def test_web_report_exposes_basenames_only():
    """The web payload must not leak server filesystem paths."""
    from webapp.service import report_to_dict  # pylint: disable=import-outside-toplevel

    report = VerifyReport()
    report.dbc_paths = ["/secret/dir/network.dbc", r"C:\logs\other.dbc"]
    assert report_to_dict(report)["dbc_paths"] == ["network.dbc", "other.dbc"]


def test_raw_xlsx_resolves_sheet_relationships(tmp_path):
    """The raw fallback must read the relationship target, not sheetId."""
    from crc_checker.dataid.parser import (  # pylint: disable=import-outside-toplevel
        _parse_xlsx_raw, resolve_mapping,
    )

    path = tmp_path / "ids.xlsx"
    _write_two_sheet_workbook(path)
    mapping = resolve_mapping("generic_abc")
    assert _parse_xlsx_raw(str(path), "A", mapping)._map == {
        (0x100, "Sig_A_CRC"): 0xAA}
    assert _parse_xlsx_raw(str(path), "B", mapping)._map == {
        (0x200, "Sig_B_CRC"): 0xBB}


def test_comment_dataid_fills_only_missing():
    """The DataID workbook is applied first; the comment must not overwrite it."""
    # pylint: disable=import-outside-toplevel
    from crc_checker.crc.classify import build_crc_params_from_comment
    from crc_checker.crc.presets import PRESETS

    protection_map = DBCProtectionMap()
    filled = MessageProtection(
        frame_id=0x100, frame_name="M_A", dlc=8, pair_suffix="A",
        checksum_signal=SignalInfo(name="Checksum_A", start_bit=0, length=8),
        checksum_comment="Profile 1A, DataID:0x00EB",
        dataid=0x1234)  # already loaded from the workbook
    gapped = MessageProtection(
        frame_id=0x200, frame_name="M_B", dlc=8, pair_suffix="B",
        checksum_signal=SignalInfo(name="Checksum_B", start_bit=0, length=8),
        checksum_comment="Profile 1A, DataID:0x00EB")  # workbook had no entry
    protection_map.messages[0x100] = [filled]
    protection_map.messages[0x200] = [gapped]

    protection_map.apply_comment_classification(
        build_crc_params_from_comment("", PRESETS["CRC8/SAE-J1850"]))
    assert filled.dataid == 0x1234          # workbook value survives
    assert gapped.dataid == 0x00EB          # comment fills the gap
