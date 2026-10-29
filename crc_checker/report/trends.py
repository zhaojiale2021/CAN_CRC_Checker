"""滚动计数器趋势图与报告口径辅助(与报告 HTML 骨架分离)。

* 一张图一个 RC 信号:内联 SVG 折线 + 错误红点 + max_valid 阈值线;
  HTML 报告 `report/html.py` 与网页结果视图共用这里的几何/抽稀逻辑。
* 口径辅助:`count_rc_episodes()`(连续异常段数)与 `rc_sample_stats()`
  (采样口径的通过/总数)、`format_rate()`(有失败时不写成 100%)—— 折叠 verdict
  不能拿去汇总(见 CLAUDE.md「Accounting」)。
"""

from __future__ import annotations

import math
from collections import defaultdict
from html import escape

from crc_checker.verify.models import VerifyReport


RC_X0, RC_X1 = 44, 984
RC_Y0, RC_Y1 = 210, 14
RC_MAX_POINTS = 1000          # drawn pass points (min/max-decimated beyond this)
RC_MAX_ERROR_DOTS = 2000      # drawn error dots (uniformly thinned beyond this)
# 顶点标记只给稀疏点:8px 标记需要 ~8px 间距(940px 绘图区 ≈ 117 点);
# 密集时画干净折线,逐点读数交给 hover 十字线(与标记无关)。
RC_MARKER_LIMIT = 120

# Valid sample points: one shared marker referenced by sparse charts'
# polylines via marker-start/mid/end — no per-point HTML. Dense charts skip
# the markers entirely (an 8px dot every ~1px floods the line); the crosshair
# hover carries the per-point readout.
_RC_MARKER_DEFS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
    '<marker id="rc-pt" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="8" '
    'markerHeight="8" markerUnits="userSpaceOnUse">'
    '<circle cx="4" cy="4" r="2.8" fill="#3987e5" stroke="#16213e" stroke-width="1.2"/>'
    '</marker></defs></svg>'
)


def _nice_step(span: float, target: int) -> float:
    """Clean tick step (1/2/5 × 10^k) covering ~target ticks over span."""
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _tick_decimals(step: float) -> int:
    """Decimal places for tick labels of the given step."""
    if step >= 1:
        return 0
    if step >= 0.1:
        return 1
    if step >= 0.01:
        return 2
    return 3


def _minmax_decimate(points: list, max_points: int) -> list:
    """Min/max decimation — keeps the sawtooth envelope when thinning."""
    if len(points) <= max_points:
        return list(points)
    n_buckets = max_points // 2
    out: list = []
    step = len(points) / n_buckets
    for i in range(n_buckets):
        lo = int(i * step)
        hi = max(lo + 1, int((i + 1) * step))
        bucket = points[lo:hi]
        if not bucket:
            continue
        vmin = min(bucket, key=lambda p: p[1])
        vmax = max(bucket, key=lambda p: p[1])
        if vmin[0] == vmax[0]:
            out.append(vmin)
        elif vmin[0] < vmax[0]:
            out.extend((vmin, vmax))
        else:
            out.extend((vmax, vmin))
    return out


def _split_trend_points(points: list) -> tuple[list, list]:
    """Pass/fail split of RC series points + thinning of enormous error sets.

    Pass points are min/max-decimated by the caller (keeps the sawtooth
    envelope); error points are always drawn, uniformly thinned only when
    enormous. Shared by the HTML SVG chart and the results-view serialiser.
    """
    pass_pts = [(t, v) for t, v, ok, _ in points if ok]
    fail_pts = [(t, v, cat) for t, v, ok, cat in points if not ok]
    if len(fail_pts) > RC_MAX_ERROR_DOTS:
        thin = len(fail_pts) / RC_MAX_ERROR_DOTS
        fail_pts = [fail_pts[int(i * thin)] for i in range(RC_MAX_ERROR_DOTS)]
    return pass_pts, fail_pts


def rc_sample_stats(report) -> tuple[int, int]:
    """RC 的采样口径 ``(通过, 总数)``。

    连续失败帧被折叠成 1 条 verdict(报告不逐帧刷屏),所以逐帧的通过率只能
    从 ``rc_series`` 数 —— 否则 1800 个失败帧在汇总里缩成「1 个校验项」,
    卡片就会出现 242788/242789 = 99.9996% 这种和趋势图对不上的数字
    series 缺失时(例如 run_stream)退回 verdict 计数。
    """
    if not report.rc_series:
        total = sum(1 for v in report.verdicts if v.algorithm != "crc")
        passed = sum(1 for v in report.verdicts
                     if v.algorithm != "crc" and v.is_pass)
        return passed, total
    total = sum(len(points) for points in report.rc_series.values())
    passed = sum(1 for points in report.rc_series.values()
                 for point in points if point[2])
    return passed, total


def count_rc_episodes(points: list) -> int:
    """RC series → 连续异常段数(每段是一串挨着的失败帧,如计数器卡死)。

    报告和结果视图都按「段」和「帧」两个口径展示:一个卡死计数器会连续失败
    上千帧,只显示帧数会让人以为有一千次独立错误。
    """
    episodes = 0
    prev_failed = False
    for _, _, ok, _ in points:
        if not ok and not prev_failed:
            episodes += 1
        prev_failed = not ok
    return episodes


def format_rate(passed: int, total: int) -> str:
    """通过率文案:有失败项时绝不四舍五入成 100%(卡片绿 100% 却又列着失败)。"""
    if total <= 0 or passed >= total:
        return "100.0%"
    rate = passed / total * 100
    for digits in (1, 2, 3, 4, 5):
        text = f"{rate:.{digits}f}"
        if float(text) < 100:
            return f"{text}%"
    return f"{rate:.6f}%"


def _rc_error_stats(errors: int, episodes: int) -> str:
    """RC 趋势图标题里的异常口径(HTML):帧数 + 段数,数字保持红/绿着色。

    一个卡死计数器会连续失败上千帧,只显示帧数会读成上千次独立错误 —— 帧数
    与段数并列。
    """
    if not errors:
        return '<span class="ok">errors: 0</span>'
    unit = "episode" if episodes == 1 else "episodes"
    return (f'errors: <span class="err">{errors}</span> frames · '
            f'<span class="err">{episodes}</span> {unit}')


# pylint: disable=too-many-locals
def _render_rc_chart(points: list, max_valid: int | None, bit_max: int,
                     signal_name: str = "") -> str:
    """One RC signal's SVG line chart: value over precise time, errors highlighted."""
    if not points:
        return ""

    t0 = points[0][0]
    span = max(points[-1][0] - t0, 1e-9)
    v_seen = max(p[1] for p in points)
    y_top = max(bit_max, v_seen, max_valid or 0)

    def x_of(t: float) -> float:
        return RC_X0 + (t - t0) / span * (RC_X1 - RC_X0)

    def y_of(v: float) -> float:
        return RC_Y0 - (v / y_top) * (RC_Y0 - RC_Y1)

    # Pass points are min/max-decimated (keeps the sawtooth envelope); error
    # points are always drawn, uniformly thinned only when enormous.
    pass_pts, fail_pts = _split_trend_points(points)
    drawn = sorted(_minmax_decimate(pass_pts, RC_MAX_POINTS)
                   + [(t, v) for t, v, _ in fail_pts], key=lambda p: p[0])

    # Axes: gridlines + tick labels (x = precise time relative to t0,
    # positions span [t0, t0+span]; y = value)
    x_ticks = []
    x_step = _nice_step(span, 6)
    x_dec = _tick_decimals(x_step)
    i, n = 0, int(span / x_step)
    while i <= n:
        t_rel = i * x_step
        tick_x = x_of(t0 + t_rel)
        anchor = "start" if i == 0 else ("end" if i == n else "middle")
        x_ticks.append(
            f'<line class="rc-grid" x1="{tick_x:.1f}" y1="{RC_Y1}" '
            f'x2="{tick_x:.1f}" y2="{RC_Y0}"/>'
            f'<text class="rc-tick" x="{tick_x:.1f}" y="{RC_Y0 + 14}" '
            f'text-anchor="{anchor}">{t_rel:.{x_dec}f}</text>')
        i += 1

    y_ticks = []
    y_step = _nice_step(y_top, 5)
    y_dec = _tick_decimals(y_step)
    v = 0.0
    while v <= y_top + 1e-9:
        yv = int(v) if float(v).is_integer() else v
        y_ticks.append(
            f'<line class="rc-grid" x1="{RC_X0}" y1="{y_of(v):.1f}" '
            f'x2="{RC_X1}" y2="{y_of(v):.1f}"/>'
            f'<text class="rc-tick" x="{RC_X0 - 6}" y="{y_of(v) + 3:.1f}" '
            f'text-anchor="end">{yv:.{y_dec}f}</text>')
        v += y_step

    # max-valid reference line (values above it are invalid)
    threshold = ""
    if max_valid and 0 < max_valid < y_top:
        ty = y_of(max_valid)
        threshold = (
            f'<line class="rc-threshold" x1="{RC_X0}" y1="{ty:.1f}" '
            f'x2="{RC_X1}" y2="{ty:.1f}"/>'
            f'<text class="rc-thr-label" x="{RC_X1}" y="{ty - 3:.1f}" '
            f'text-anchor="end">max_valid {max_valid}</text>')

    pts_attr = " ".join(f"{x_of(t):.2f},{y_of(v):.2f}" for t, v in drawn)
    # Valid sample points ride the polyline as vertex markers only when the
    # drawn count fits (one shared <defs> marker, see _RC_MARKER_DEFS);
    # dense charts draw a clean line and rely on the crosshair hover.
    markers = ""
    if 1 < len(drawn) <= RC_MARKER_LIMIT:
        markers = (' marker-start="url(#rc-pt)" marker-mid="url(#rc-pt)"'
                   ' marker-end="url(#rc-pt)"')
    line = f'<polyline class="rc-line" points="{pts_attr}"{markers}/>' if len(drawn) > 1 else ""
    if len(drawn) == 1:
        t, v = drawn[0]
        line = f'<circle cx="{x_of(t):.1f}" cy="{y_of(v):.1f}" r="4" fill="#3987e5" ' \
               f'stroke="#16213e" stroke-width="2"/>'

    sig = escape(signal_name) if signal_name else ""
    sig_attr = f' data-sig="{sig}"' if sig else ""
    dots = "".join(
        f'<circle class="rc-err-dot" cx="{x_of(t):.1f}" cy="{y_of(v):.1f}" r="4" '
        f'data-cat="{escape(cat) if cat else "ERROR"}">'
        f'<title>{sig} · t={t:.6f}s · value={v} · '
        f'{escape(cat) if cat else "ERROR"}</title>'
        f'</circle>'
        for t, v, cat in fail_pts
    )

    # Hover handlers are bound by the page script after load — inline
    # attributes would fire during the (long) parse of a big report, before
    # the script defines them, spamming the console with ReferenceErrors.
    return (f'<svg class="rc-svg" viewBox="0 0 1000 250" '
            f'data-t0="{t0:.6f}" data-tspan="{span:.6f}" data-vmax="{y_top}"'
            f'{sig_attr}>'
            f'<text class="rc-tick" x="{RC_X0 - 6}" y="{RC_Y1 - 4}" '
            f'text-anchor="end">value</text>'
            f'<text class="rc-tick" x="{RC_X1}" y="{RC_Y0 + 26}" '
            f'text-anchor="end">t/s</text>'
            f'{"".join(y_ticks)}{"".join(x_ticks)}'
            f'{threshold}'
            f'<line class="rc-axis" x1="{RC_X0}" y1="{RC_Y0}" x2="{RC_X1}" y2="{RC_Y0}"/>'
            f'{line}{dots}'
            f'<line class="rc-crosshair" x1="0" y1="{RC_Y1}" x2="0" y2="{RC_Y0}"/>'
            f'</svg>')


def _build_rc_charts(report: VerifyReport) -> str:
    """Rolling Counter trends section: one collapsible SVG chart per RC signal."""
    if not report.rc_series:
        return ""

    grouped: dict[tuple[int, str], list] = defaultdict(list)
    for (fid, ch, sig), points in report.rc_series.items():
        grouped[(fid, sig)].append((ch, points))

    entries = []
    for (fid, sig), ch_lists in grouped.items():
        errors = sum(1 for _, pts in ch_lists for p in pts if not p[2])
        samples = sum(len(pts) for _, pts in ch_lists)
        episodes = sum(count_rc_episodes(pts) for _, pts in ch_lists)
        entries.append((fid, sig, ch_lists, errors, episodes, samples))
    # Signals with errors first, then by frame id / signal name
    entries.sort(key=lambda e: (-e[3], e[0], e[1]))

    cards = []
    for fid, sig, ch_lists, errors, episodes, samples in entries:
        fname = report.get_frame_name(fid)
        name_html = f'<span class="frame-name">({escape(fname)})</span>' if fname else ""
        for ch, points in sorted(ch_lists):
            meta = report.rc_series_meta.get((fid, ch, sig), {})
            length = meta.get("length", 4)
            max_valid = meta.get("max_valid")
            bit_max = (1 << length) - 1
            span = max(points[-1][0] - points[0][0], 0.0)
            svg = _render_rc_chart(points, max_valid, bit_max, signal_name=sig)
            if not svg:
                continue
            # Charts with errors start expanded; clean ones stay collapsed
            collapsed = "" if errors else " collapsed"
            cards.append(f"""
    <div class="rc-chart-card{collapsed}">
      <div class="rc-chart-header" onclick="this.parentElement.classList.toggle('collapsed')">
        <span class="arrow">&#9660;</span>
        <span class="id">0x{fid:03X}</span>
        <span class="name">{escape(sig)}</span>
        {name_html}
        <span class="channel-tag channel-{ch % 4}">CH{ch}</span>
        <span class="stats">{_rc_error_stats(errors, episodes)}
          · samples: {samples}</span>
      </div>
      <div class="rc-chart-body">
        {svg}
        <div class="rc-readout"></div>
        <div class="rc-chart-note">t0 = {points[0][0]:.6f}s · span {span:.6f}s</div>
      </div>
    </div>""")

    if not cards:
        return ""
    return (f'<div class="rc-charts">{_RC_MARKER_DEFS}'
            f'<h2>Rolling Counter Trends</h2>{"".join(cards)}</div>')
