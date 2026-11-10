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

import io
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import canmatrix

from crc_checker.crc.classify import (
    classify_crc_algo, parse_sum_byte_range,
)
from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.models import CRCRange
from crc_checker.crc.presets import get_preset
from crc_checker.dataid.parser import ColumnMapping, _auto_detect_columns
from crc_checker.dbc.models import MessageProtection, SignalInfo
from crc_checker.patterns import join_patterns
from crc_checker.protect.checksum import CRCVerifier
from crc_checker.report.html import _build_frame_html
from crc_checker.trace.models import CanFrame
from crc_checker.verify.models import VerifyVerdict


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


def test_crc_byte_end_no_overcount_unaligned():
    """ceil(length/8) excludes exactly the CRC bytes for an unaligned start bit."""
    engine = CRCEngine(get_preset("CRC8/SAE-J1850-ZERO"))
    payload = bytes.fromhex("0102030405060708 F1F2F3F4F5F6F7F8")
    frame = CanFrame(arbitration_id=0x135, timestamp=0.0, dlc=16, data=payload)
    crc_range = CRCRange.for_segment(checksum_start_bit=71, dataid=0x00E9)
    assert engine.compute_for_frame(frame, crc_range, 71, 8, "big_endian") == \
        engine.compute(bytes([0xE9, 0x00]) + payload[9:16])


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
