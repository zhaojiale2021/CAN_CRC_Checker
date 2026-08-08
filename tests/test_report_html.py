"""Tests for HTML report frame rendering (CRC/RC highlights, DataID tooltip)."""

from crc_checker.report.html import _build_frame_html
from crc_checker.verify.models import VerifyVerdict


def _crc_verdict(**overrides) -> VerifyVerdict:
    """Build a CRC verdict with sensible defaults for rendering tests."""
    defaults = {
        "frame_id": 0x160,
        "timestamp": 1.0,
        "algorithm": "crc",
        "signal_name": "BCS_2_CRC",
        "expected_value": 0x1234,
        "actual_value": 0x1234,
        "is_pass": True,
        "start_bit": 0,
        "length": 16,
        "byte_order": "big_endian",
    }
    defaults.update(overrides)
    return VerifyVerdict(**defaults)


class TestDataIDTooltip:
    """DataID segment label shows value + name + profile on hover."""

    def test_tooltip_includes_name_and_profile(self):
        """Tooltip contains value, matched name and E2E profile."""
        v = _crc_verdict(
            dataid=0x0111,
            dataid_name="CCU_6",
            dataid_profile="Profile Variant 1A",
        )
        html = _build_frame_html([v], bytes(8))
        assert '<span class="did">0x0111' in html
        assert (
            '<span class="tooltip">'
            'DataID 0x0111 · CCU_6 · Profile Variant 1A'
            '</span>'
        ) in html

    def test_tooltip_without_name_or_profile(self):
        """Tooltip falls back to the bare value."""
        v = _crc_verdict(dataid=0x0111)
        html = _build_frame_html([v], bytes(8))
        assert '<span class="tooltip">DataID 0x0111</span>' in html

    def test_no_dataid_no_label(self):
        """Frames without a DataID render no did badge."""
        v = _crc_verdict(dataid=None)
        html = _build_frame_html([v], bytes(8))
        assert 'class="did"' not in html
        assert 'DataID' not in html


class TestCRCHighlight:
    """Motorola 16-bit CRC must highlight both bytes."""

    def test_motorola_16bit_highlights_two_bytes(self):
        """Profile 5 CRC: both payload bytes get the crc-pass class."""
        v = _crc_verdict(is_pass=True)
        html = _build_frame_html([v], bytes(8))
        # byte 0 and byte 1 both carry the crc-pass class
        assert html.count('class="hex-byte crc-pass"') == 2

    def test_intel_16bit_highlights_two_bytes(self):
        """Intel 16-bit CRC: both payload bytes get the crc-pass class."""
        v = _crc_verdict(start_bit=48, byte_order="little_endian")
        html = _build_frame_html([v], bytes(8))
        assert html.count('class="hex-byte crc-pass"') == 2


class TestCRCAlgorithmTag:
    """Frame header shows deduplicated CRC algorithm name."""

    def test_single_algorithm_tag(self):
        """One algorithm -> one tag after the frame name."""
        v = _crc_verdict(crc_algorithm="CRC16/CCITT")
        html = _build_frame_html([v], bytes(8))
        assert '<span class="algo-tag">CRC16/CCITT</span>' in html

    def test_multiple_verdicts_dedup(self):
        """Two verdicts with the same algorithm render a single tag."""
        v1 = _crc_verdict(crc_algorithm="CRC16/CCITT")
        v2 = _crc_verdict(
            timestamp=2.0, signal_name="Other_CRC",
            crc_algorithm="CRC16/CCITT",
        )
        html = _build_frame_html([v1, v2], bytes(8))
        assert html.count('class="algo-tag"') == 1

    def test_no_algorithm_no_tag(self):
        """Verdicts without crc_algorithm (e.g. RC) render no tag."""
        v = _crc_verdict(crc_algorithm="")
        html = _build_frame_html([v], bytes(8))
        assert 'class="algo-tag"' not in html
