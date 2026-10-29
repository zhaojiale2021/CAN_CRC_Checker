"""Rolling Counter error folding (one verdict per episode) + trend chart series.

* Consecutive failing frames fold into ONE verdict (``×N (until t=...)``) — a
  counter stuck at 14 or constant 15 (max_valid=14) is recorded once, not once
  per frame.
* Every frame's value still lands in the per-signal series (``rc_series``),
  the source for the HTML trend charts.
"""

from __future__ import annotations

import os
import pathlib
import re
import tempfile

from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.protect.rolling_counter import RollingCounterVerifier
from crc_checker.report.html import write_html
from crc_checker.report.trends import (RC_X0, RC_X1, _render_rc_chart,
                                       count_rc_episodes, format_rate)
from crc_checker.trace.models import CanFrame
from crc_checker.verify.engine import VerifyEngine


def _all_pages(file_path: str) -> str:
    """报告主文件 + 所有分片的内容拼接(断言时跨页看)。"""
    stem = os.path.splitext(file_path)[0]
    text = ""
    for path in sorted(pathlib.Path(os.path.dirname(file_path)).glob(
            f"{os.path.basename(stem)}*.html")):
        text += path.read_text(encoding="utf-8")
    return text


def _frame(ts: float, rc_value: int, frame_id: int = 0x123,
           channel: int = 0) -> CanFrame:
    """A frame whose RC signal (start_bit 56, 4-bit, LE) carries rc_value."""
    data = bytearray(8)
    data[7] = rc_value & 0x0F          # start_bit 56 = byte 7, low nibble (LE)
    return CanFrame(timestamp=ts, arbitration_id=frame_id, dlc=8, data=bytes(data),
                    channel=channel)


def _prot(rc_max_valid: int | None = 14) -> MessageProtection:
    """One protection group: 4-bit RC at start_bit 56, max_valid 14."""
    prot = MessageProtection(frame_id=0x123, frame_name="ACC_1", dlc=8)
    prot.rolling_counter_signal = SignalInfo(name="ACC_1_Counter", start_bit=56, length=4)
    prot.rc_max_valid = rc_max_valid
    return prot


class _Reader:  # pylint: disable=too-few-public-methods
    """Minimal TraceReader stand-in: iterates pre-built frames."""

    file_path = "memory.blf"

    def __init__(self, frames):
        self._frames = frames

    def frames(self):
        """Iterate the pre-built frames (TraceReader interface)."""
        return iter(self._frames)


def _run(verifier, values, prot=None):
    """Run the verifier over frames 0..N-1 (1s apart); return emitted verdicts."""
    rc_values = []
    for i, value in enumerate(values):
        result = verifier.verify(_frame(float(i), value), prot or _prot())
        if result is not None:
            rc_values.append(result)
    return rc_values


class TestErrorFolding:
    """Consecutive failing frames fold into ONE verdict per episode."""

    def test_stuck_at_max_14_recorded_once(self):
        """Counter frozen at max_valid=14 → one STALE record for the whole episode."""
        values = list(range(15)) + [14, 14, 14]
        verdicts = _run(RollingCounterVerifier(), values)
        fails = [v for v in verdicts if not v.is_pass]
        assert len(fails) == 1
        assert fails[0].detail.startswith("STALE")
        assert fails[0].repeat_count == 3
        assert "×3" in fails[0].detail
        assert "until" in fails[0].detail
        # until = the last failing frame's timestamp (index 17)
        assert f"{17:.6f}" in fails[0].detail

    def test_invalid_15_recorded_once(self):
        """Constant 15 (max_valid=14): INVALID first, repeats fold into ONE record."""
        verdicts = _run(RollingCounterVerifier(), [0, 1, 15, 15, 15])
        fails = [v for v in verdicts if not v.is_pass]
        assert len(fails) == 1
        assert fails[0].detail.startswith("INVALID")
        assert fails[0].repeat_count == 3
        assert "×3" in fails[0].detail

    def test_recovery_starts_new_episode(self):
        """A PASS closes the episode; a later failure is a separate record."""
        verdicts = _run(RollingCounterVerifier(), [0, 1, 2, 2, 2, 3, 3, 3])
        fails = [v for v in verdicts if not v.is_pass]
        assert len(fails) == 2
        assert all(f.repeat_count == 2 for f in fails)
        # The first record kept the first failure's timestamp
        assert fails[0].timestamp == 3.0
        assert fails[1].timestamp == 6.0

    def test_isolated_skip_not_folded(self):
        """A one-off SKIP has repeat_count 1 and no ×N suffix."""
        verdicts = _run(RollingCounterVerifier(), [0, 1, 3, 4])
        fails = [v for v in verdicts if not v.is_pass]
        assert len(fails) == 1
        assert fails[0].detail.startswith("SKIP")
        assert fails[0].repeat_count == 1
        assert "×" not in fails[0].detail

    def test_normal_wrap_is_pass(self):
        """14 → 0 wrap stays a normal PASS (no folding of passes)."""
        verdicts = _run(RollingCounterVerifier(), [13, 14, 0, 1])
        fails = [v for v in verdicts if not v.is_pass]
        assert fails == []
        assert len(verdicts) == 4


class TestSeries:
    """Every frame's value lands in the per-signal series."""

    def test_series_records_every_frame(self):
        """The series keeps every frame — including folded repeats."""
        rc = RollingCounterVerifier()
        _run(rc, [0, 1, 15, 15, 15])
        series = rc.get_series()[(0x123, 0, "ACC_1_Counter")]
        assert len(series) == 5
        assert [p[1] for p in series] == [0, 1, 15, 15, 15]
        assert [p[2] for p in series] == [True, True, False, False, False]
        assert series[2][3] == "INVALID"   # first 15
        assert series[3][3] == "STALE"     # repeats are STALE per-frame

    def test_series_meta_carries_chart_config(self):
        """Bit length + max valid recorded at first occurrence."""
        rc = RollingCounterVerifier()
        _run(rc, [0, 1])
        assert rc.get_series_meta()[(0x123, 0, "ACC_1_Counter")] == \
            {"length": 4, "max_valid": 14}

    def test_channels_get_separate_series(self):
        """The same frame id on two channels has its own series each."""
        rc = RollingCounterVerifier()
        prot = _prot()
        for i, v in enumerate([0, 1, 2]):
            rc.verify(_frame(float(i), v, channel=0), prot)
            rc.verify(_frame(float(i) + 0.5, v, channel=1), prot)
        series = rc.get_series()
        assert len(series[(0x123, 0, "ACC_1_Counter")]) == 3
        assert len(series[(0x123, 1, "ACC_1_Counter")]) == 3


class TestEngineSeries:
    """VerifyEngine populates report.rc_series; series are per-run."""

    def _engine(self) -> VerifyEngine:
        """Engine with one 4-bit RC group (max_valid 14), no CRC."""
        pm = DBCProtectionMap()
        pm.messages[0x123] = [_prot()]
        return VerifyEngine.create_default(pm, crc_params=None)

    def test_engine_populates_report_series(self):
        """engine.run fills report.rc_series/rc_series_meta; folding cuts fails."""
        report = self._engine().run(
            _Reader([_frame(float(i), v) for i, v in enumerate([0, 1, 2, 2, 2])]))
        key = (0x123, 0, "ACC_1_Counter")
        assert len(report.rc_series[key]) == 5
        assert report.rc_series_meta[key] == {"length": 4, "max_valid": 14}
        assert report.fail_count == 1  # folded episode

    def test_series_is_per_run(self):
        """Re-running the same engine (shared verifier) must not mix series."""
        engine = self._engine()
        frames = [_frame(float(i), v) for i, v in enumerate([0, 1, 2, 2, 2])]
        engine.run(_Reader(frames))
        report2 = engine.run(_Reader(frames))
        key = (0x123, 0, "ACC_1_Counter")
        assert len(report2.rc_series[key]) == 5  # only its own run, not 10


class TestHtmlTrendCharts:
    """The report renders one collapsible SVG chart per RC signal."""

    def _report(self, values):
        pm = DBCProtectionMap()
        pm.messages[0x123] = [_prot()]
        engine = VerifyEngine.create_default(pm, crc_params=None)
        return engine.run(
            _Reader([_frame(float(i), v) for i, v in enumerate(values)]))

    @staticmethod
    def _render(report) -> str:
        """Render the report to HTML; return the file content."""
        path = os.path.join(tempfile.mkdtemp(), "report.html")
        write_html(report, path)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_trends_section_rendered(self):
        """Trends section + chart svg + threshold + folded detail all present."""
        html = self._render(self._report([0, 1, 2, 2, 2]))
        assert "Rolling Counter Trends" in html
        assert "rc-chart-card" in html
        assert "<polyline" in html
        assert "rc-err-dot" in html
        assert 'data-t0="0.000000"' in html
        # max_valid 14 < bit_max 15 → threshold line drawn
        assert "max_valid 14" in html
        # folded detail visible in the verdict table (2 failing frames)
        assert "×2" in html
        assert "until" in html
        # crosshair + readout wiring present
        assert "rcChartHover" in html
        assert 'class="rc-readout"' in html

    def test_signal_name_in_chart_and_tooltips(self):
        """Signal name on the svg (readout) and in error-dot titles."""
        html = self._render(self._report([0, 1, 2, 2, 2]))
        assert 'data-sig="ACC_1_Counter"' in html
        assert "ACC_1_Counter · t=" in html   # error dot <title>

    def test_valid_sample_points_via_markers(self):
        """Pass points ride the polyline as vertex markers (one shared defs)."""
        html = self._render(self._report([0, 1, 2, 3, 4, 5]))
        assert 'marker-mid="url(#rc-pt)"' in html
        assert '<marker id="rc-pt"' in html
        assert 'markerUnits="userSpaceOnUse"' in html

    def test_error_chart_expanded_clean_collapsed(self):
        """Charts with errors start expanded; clean ones stay collapsed."""
        failing = self._render(self._report([0, 1, 2, 2, 2]))
        assert 'rc-chart-card">' in failing          # expanded (has errors)
        clean = self._render(self._report([0, 1, 2, 3, 4]))
        assert 'rc-chart-card collapsed' in clean    # collapsed (no errors)

    def test_decimation_keeps_envelope(self):
        """5000 pass points → polyline vertices capped near RC_MAX_POINTS."""
        html = self._render(self._report([i % 15 for i in range(5000)]))
        match = re.search(r'<polyline class="rc-line" points="([^"]+)"', html)
        assert match
        n = len(match.group(1).split())
        assert 100 <= n <= 1010

    def test_ticks_span_the_actual_time_range(self):
        """x ticks sit inside the plot rect even when t0 ≫ 0 (epoch traces).

        Regression: ticks used to be positioned from t=0 instead of t0,
        pushing every x tick far off the chart for real (epoch) timestamps.
        """
        points = [(1000.0 + i * 0.02, i % 15, True, "") for i in range(120)]
        svg = _render_rc_chart(points, 14, 15)
        # x tick texts sit on the y = RC_Y0 + 14 row
        xs = [float(m) for m in
              re.findall(r'<text class="rc-tick" x="([-\d.]+)" y="224"', svg)]
        assert xs
        assert all(RC_X0 <= x <= RC_X1 for x in xs), xs

    def test_error_points_survive_decimation(self):
        """Sparse errors inside a dense series still get their dot."""
        values = [i % 15 for i in range(5000)]
        values[2500] = 14            # STALE (repeat) at index 2500
        html = self._render(self._report(values))
        assert "rc-err-dot" in html


class TestReportSizeLimit:
    """大 trace 报告体积上限:超限先降级成只留失败帧,再超才截断(都写明)。"""

    def _report(self, values):
        pm = DBCProtectionMap()
        pm.messages[0x123] = [_prot()]
        engine = VerifyEngine.create_default(pm, crc_params=None)
        return engine.run(
            _Reader([_frame(float(i), v) for i, v in enumerate(values)]))

    @staticmethod
    def _write(report, **kwargs) -> tuple[str, list]:
        path = os.path.join(tempfile.mkdtemp(), "report.html")
        note = write_html(report, path, **kwargs)
        return note, _all_pages(path)

    def test_full_report_below_limit_is_untouched(self):
        """帧段没超限时照常全量输出,也没有提示。"""
        note, pages = self._write(self._report([0, 1, 2, 3, 4]), max_sections=100)
        assert note == ""
        assert 'class="report-note"' not in pages
        assert pages.count('class="frame-section') == 5

    def test_huge_report_falls_back_to_failures_only(self):
        """逐帧全量超限 → 自动只留失败帧 + 顶部写明(不静默丢数据)。"""
        # 30 帧正常 + 1 段失败(连续两帧 14):32 个帧段、1 段异常
        values = [i % 15 for i in range(30)] + [14, 14]
        note, pages = self._write(self._report(values), max_sections=10)
        assert "已自动改为只保留失败帧" in note
        assert 'class="report-note"' in pages
        assert pages.count('class="frame-section') == 1     # 只剩失败帧

    def test_sections_truncated_when_failures_also_exceed_limit(self):
        """失败帧也超限时才截断,并说明只给了前 N 段。"""
        values = [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6]   # 多段失败
        note, pages = self._write(self._report(values), only_failures=True,
                                  max_sections=2)
        assert "已截断为前 2 段" in note
        assert pages.count('class="frame-section') == 2

    def test_zero_limit_keeps_everything(self):
        """max_sections=0 → 不限(给需要全量逐帧报告的场合留口子)。"""
        note, pages = self._write(self._report([0, 1, 2, 3, 4, 5, 6, 7, 8]),
                                  max_sections=0)
        assert note == ""
        assert pages.count('class="frame-section') == 9


class TestRcErrorAccounting:
    """报告/结果视图的异常口径:帧数与连续异常段数并列,通过率不虚报 100%。"""

    def _report(self, values):
        pm = DBCProtectionMap()
        pm.messages[0x123] = [_prot()]
        engine = VerifyEngine.create_default(pm, crc_params=None)
        return engine.run(
            _Reader([_frame(float(i), v) for i, v in enumerate(values)]))

    @staticmethod
    def _render(report) -> str:
        """Render through the trend-chart helper (same temp-file flow)."""
        return TestHtmlTrendCharts._render(report)  # pylint: disable=protected-access

    def test_count_rc_episodes(self):
        """连续失败算一段;恢复后再失败是新的一段。"""
        def pts(flags):
            return [(float(i), 0, ok, "" if ok else "STALE")
                    for i, ok in enumerate(flags)]

        assert count_rc_episodes(pts([True, True, True])) == 0
        assert count_rc_episodes(pts([True, False, False, False])) == 1
        assert count_rc_episodes(pts([False, False, True, False])) == 2
        assert count_rc_episodes(pts([False, True, False])) == 2
        assert count_rc_episodes([]) == 0

    def test_chart_header_shows_frames_and_episodes(self):
        """卡死计数器:标题给「N 帧 · 1 段」,不再是让人读成 N 次错误的裸帧数。"""
        html = self._render(self._report([0, 1, 2, 2, 2, 2, 2, 2, 2, 2]))
        assert ('errors: <span class="err">7</span> frames · '
                '<span class="err">1</span> episode') in html
        assert "samples: 10" in html

    def test_clean_chart_header_shows_zero(self):
        """全过的图只显示绿色 0,不带段数。"""
        html = self._render(self._report([0, 1, 2, 3, 4]))
        assert '<span class="ok">errors: 0</span>' in html
        assert "episodes" not in html

    def test_isolated_failures_count_as_separate_episodes(self):
        """偶发失败(不连续)按段数累计。"""
        html = self._render(self._report([0, 1, 1, 2, 3, 3, 4]))
        assert '<span class="err">2</span> episodes' in html

    def test_format_rate_never_rounds_away_a_failure(self):
        """1 个失败 / 40 万帧也必须显示成非 100%(原来 .1% 会写成 100.0%)。"""
        assert format_rate(3, 3) == "100.0%"
        assert format_rate(0, 0) == "100.0%"
        assert format_rate(4217, 4218) == "99.98%"
        assert format_rate(187556, 187890) == "99.8%"
        assert format_rate(244587, 244588) == "99.9996%"

    def test_summary_card_not_green_when_failures_exist(self):
        """RC 有失败时卡片不再是绿色 pass(避免绿 100% 旁边列着失败项)。"""
        html = self._render(self._report([0, 1, 2, 2, 2]))
        assert '<div class="card"><div class="label">RC Pass</div>' in html
        assert '<div class="card pass"><div class="label">RC Pass</div>' not in html

    def test_rc_card_counts_samples_not_folded_verdicts(self):
        """RC 卡片按采样计:折叠的失败帧不能被缩成 1 个校验项。"""
        report = self._report([0, 1, 2, 2, 2])
        assert report.fail_count == 1          # 折叠成一条 episode
        html = self._render(report)
        assert "<div class=\"value\">3/5</div>" in html   # 5 采样 / 3 通过

    def test_summary_cards_stay_green_when_clean(self):
        """全过时卡片仍是绿色 pass。"""
        html = self._render(self._report([0, 1, 2, 3, 4]))
        assert '<div class="card pass"><div class="label">RC Pass</div>' in html
