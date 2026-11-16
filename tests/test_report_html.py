"""Tests for HTML report frame rendering (CRC/RC highlights, DataID tooltip)."""

from crc_checker.report.html import _build_frame_html, write_html
from crc_checker.verify.models import VerifyReport, VerifyVerdict


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


class TestReportSummary:
    """Summary cards and banner use the same sample-based checks as web/CLI."""

    def test_zero_checks_is_not_all_passed(self, tmp_path):
        """An RC-only/empty run must not claim success."""
        report = VerifyReport(trace_path="t.blf")
        path = tmp_path / "report.html"
        write_html(report, str(path))
        text = path.read_text(encoding="utf-8")
        assert "未执行校验" in text
        assert "全部校验通过" not in text
        assert '<div class="value">-</div>' in text

    def test_failure_banner_counts_failures_not_passes(self, tmp_path):
        """The red banner must count failures — showing 2/3 passed under
        "检测到失败" reads as "66.7% failed" when only one check failed."""
        report = VerifyReport(trace_path="t.blf", total_frames=3)
        report.verdicts.extend([
            _crc_verdict(timestamp=1.0),
            _crc_verdict(timestamp=2.0),
            _crc_verdict(timestamp=3.0, is_pass=False),
        ])
        path = tmp_path / "report.html"
        write_html(report, str(path))
        text = path.read_text(encoding="utf-8")
        assert "1 项失败 / 共 3 项" in text
        assert "通过率 66.7%" in text
        assert "2/3 项 · 66.7%" not in text

    def test_failures_show_red_banner(self, tmp_path):
        """Any failed check flips the banner and the overall card."""
        report = VerifyReport(trace_path="t.blf", total_frames=1)
        report.verdicts.append(_crc_verdict(is_pass=False))
        path = tmp_path / "report.html"
        write_html(report, str(path))
        text = path.read_text(encoding="utf-8")
        assert "检测到失败" in text
        assert 'class="card fail"' in text

    def test_frame_cap_is_written_into_the_report(self, tmp_path):
        """The report must say the trace was cut short."""
        report = VerifyReport(trace_path="t.blf", total_frames=10,
                              frames_truncated=True, frame_limit=10)
        path = tmp_path / "report.html"
        write_html(report, str(path))
        text = path.read_text(encoding="utf-8")
        assert "只校验了前 10 帧" in text


class TestOnlyFailuresKeepsFrameContext:
    """Only-fail reports filter frames, never the verdicts of a kept frame.

    A failing CRC next to a healthy counter must stay distinguishable from a
    frame whose RC data never made it into the report.
    """

    @staticmethod
    def _report() -> VerifyReport:
        report = VerifyReport(trace_path="t.blf", total_frames=2)
        report.add_frame_data(1.0, 0x160, bytes(8))
        report.add_frame_data(2.0, 0x160, bytes(8))
        report.verdicts.extend([
            _crc_verdict(timestamp=1.0, is_pass=False),
            _crc_verdict(timestamp=1.0, algorithm="rolling_counter",
                         signal_name="BCS_2_Counter", expected_value=3,
                         actual_value=3, start_bit=16, length=8),
            _crc_verdict(timestamp=2.0),
        ])
        return report

    def test_passing_rc_verdict_stays_visible(self, tmp_path):
        """The failing frame keeps its passing RC row and highlight."""
        path = tmp_path / "report.html"
        write_html(self._report(), str(path), only_failures=True)
        text = path.read_text(encoding="utf-8")
        assert text.count('class="frame-section') == 1
        assert "BCS_2_Counter" in text
        assert '<td>通过</td>' in text
        assert 'class="hex-byte crc-fail"' in text
        assert 'class="hex-byte rc-pass"' in text
        assert "@2.000000s" not in text        # the clean frame is still dropped

    def test_size_downgrade_keeps_frame_context(self, tmp_path):
        """The auto failures-only downgrade keeps the frame's other verdicts too."""
        path = tmp_path / "report.html"
        write_html(self._report(), str(path), max_sections=1)
        text = path.read_text(encoding="utf-8")
        assert "已自动改为只保留失败帧" in text
        assert text.count('class="frame-section') == 1
        assert "BCS_2_Counter" in text
