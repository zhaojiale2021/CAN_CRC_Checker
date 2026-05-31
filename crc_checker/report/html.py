"""HTML report generator — segment hex view with inline CRC/RC highlighting."""

from crc_checker.verify.models import VerifyReport, VerifyVerdict

CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 20px; background: #1a1a2e; color: #e0e0e0; }
  .container { max-width: 1600px; margin: 0 auto; }
  h1 { color: #e0e0e0; margin-bottom: 16px; font-size: 22px; }
  .info-bar { background: #16213e; border-radius: 8px; padding: 10px 20px;
              margin-bottom: 16px; font-size: 12px; color: #8899aa; }
  .summary-cards { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .card { background: #16213e; border-radius: 8px; padding: 12px 20px;
          min-width: 130px; text-align: center; }
  .card .label { font-size: 11px; color: #8899aa; text-transform: uppercase;
                 letter-spacing: 0.5px; }
  .card .value { font-size: 26px; font-weight: bold; margin-top: 2px; }
  .card.fail .value { color: #e74c3c; }
  .card.pass .value { color: #2ecc71; }

  .frame-section { background: #16213e; border-radius: 8px; margin-bottom: 12px;
                   overflow: hidden; }
  .frame-header { display: flex; align-items: center; padding: 10px 16px;
                  background: #0f3460; cursor: pointer; user-select: none;
                  gap: 16px; }
  .frame-header .id { font-weight: bold; font-size: 15px; font-family: 'SF Mono',
                      'Consolas', monospace; min-width: 80px; }
  .frame-header .name { font-weight: bold; font-size: 15px; color: #e0e0e0;
                     font-family: 'SF Mono', 'Consolas', monospace; margin-left: 2px; }
  .frame-header .ts { color: #8899aa; font-size: 12px; font-family: 'SF Mono',
                      'Consolas', monospace; }
  .frame-header .stats { margin-left: auto; font-size: 12px; display: flex; gap: 8px; }
  .frame-header .stats .ok { color: #2ecc71; }
  .frame-header .stats .err { color: #e74c3c; }
  .frame-header .arrow { transition: transform .2s; font-size: 12px; color: #8899aa; }
  .frame-section.collapsed .frame-body { display: none; }
  .frame-section.collapsed .arrow { transform: rotate(-90deg); }
  .frame-body { padding: 12px 16px; }

  .channel-tag { display: inline-block; padding: 1px 8px; border-radius: 3px;
                 font-size: 11px; font-weight: bold; font-family: 'SF Mono', 'Consolas', monospace; }
  .channel-0 { background: #1a3a5c; color: #4a8ac9; }
  .channel-1 { background: #1a4a3a; color: #4ac98a; }
  .channel-2 { background: #4a3a1a; color: #c99a4a; }
  .channel-3 { background: #3a1a4a; color: #9a4ac9; }
  .dbc-tag { display: inline-block; padding: 1px 6px; border-radius: 3px;
             font-size: 10px; color: #667788; background: #1a1a2e;
             font-family: 'SF Mono', 'Consolas', monospace;
             max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .hex-grid { display: flex; flex-direction: column; gap: 2px;
              font-family: 'SF Mono', 'Consolas', 'Courier New', monospace; }
  .hex-row { display: flex; align-items: center; gap: 4px; font-size: 13px; }
  .hex-offset { color: #556677; min-width: 45px; text-align: right;
                font-size: 11px; }
  .hex-bytes { display: flex; gap: 2px; }
  .hex-byte { display: inline-block; width: 28px; text-align: center;
              padding: 2px 4px; border-radius: 3px; border: 1px solid transparent;
              position: relative; cursor: default; }
  .hex-byte.crc-pass { border-color: #2ecc71; background: rgba(46,204,113,0.12); }
  .hex-byte.crc-fail { border-color: #e74c3c; background: rgba(231,76,60,0.18);
                       color: #e74c3c; font-weight: bold; }
  .hex-byte.rc-pass { border-bottom: 2px solid #2ecc71; }
  .hex-byte.rc-fail { border-bottom: 2px solid #e74c3c; background: rgba(231,76,60,0.12); }
  .hex-byte.has-crc.rc-pass { border: 1px solid #2ecc71; background: rgba(46,204,113,0.15); }
  .hex-byte.has-crc.rc-fail { border: 1px solid #e74c3c; background: rgba(231,76,60,0.2); }
  .hex-byte .tooltip { visibility: hidden; position: absolute; bottom: 110%;
                       left: 50%; transform: translateX(-50%); background: #333;
                       color: #fff; font-size: 11px; padding: 3px 8px;
                       border-radius: 4px; white-space: nowrap; z-index: 10; }
  .hex-byte:hover .tooltip { visibility: visible; }

  .segment-label { color: #556677; font-size: 10px; min-width: 85px;
                   text-align: right; margin-right: 4px; }
  .segment-label .did { color: #3a6b8c; }

  .verdict-table { margin-top: 12px; border-top: 1px solid #1a1a2e; padding-top: 8px; }
  .verdict-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .verdict-table th { color: #8899aa; text-align: left; padding: 4px 8px;
                      font-weight: normal; border-bottom: 1px solid #1a1a2e; }
  .verdict-table td { padding: 3px 8px; font-family: 'SF Mono', 'Consolas', monospace; }
  .verdict-table .pass td { color: #2ecc71; }
  .verdict-table .fail td { color: #e74c3c; }

  .filter-bar { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .filter-bar button { padding: 6px 14px; border: 1px solid #0f3460;
                       background: #16213e; color: #e0e0e0; border-radius: 4px;
                       cursor: pointer; font-size: 12px; }
  .filter-bar button.active { background: #0f3460; border-color: #e94560; }
  .filter-bar button:hover { background: #0f3460; }
  .filter-bar .sep { color: #334455; margin: 0 4px; font-size: 12px; }
"""


def _bit_to_byte_pos(start_bit: int, bit_index: int, byte_order: str) -> tuple[int, int]:
    """Convert signal start_bit + bit_index to (byte_offset, bit_in_byte)."""
    from crc_checker.bit_utils import _canmatrix_to_physical_msb
    if byte_order == "big_endian":
        physical_msb = _canmatrix_to_physical_msb(start_bit)
        phys_bit = physical_msb - bit_index
    else:
        phys_bit = start_bit + bit_index
    return phys_bit // 8, phys_bit % 8


def _build_frame_html(verdicts: list[VerifyVerdict], frame_data: bytes,
                      frame_name: str = "", channel: int = 0,
                      dbc_source: str = "") -> str:
    """Build HTML for one frame: hex dump with highlights + verdict table."""
    if not verdicts:
        return ""

    frame_id = verdicts[0].frame_id
    ts = verdicts[0].timestamp
    dlc = len(frame_data)

    # Collect signal positions for highlighting
    byte_styles: dict[int, dict] = {}
    signals_info: list[dict] = []

    for v in verdicts:
        if not v.start_bit or not v.length:
            continue
        for bit_i in range(v.length):
            byte_idx, bit_in_byte = _bit_to_byte_pos(v.start_bit, bit_i, v.byte_order)
            if 0 <= byte_idx < dlc:
                if byte_idx not in byte_styles:
                    byte_styles[byte_idx] = {}
                key = "crc" if v.algorithm == "crc" else "rc"
                status = "pass" if v.is_pass else "fail"
                existing = byte_styles[byte_idx].get(key)
                if existing is None or (existing == "pass" and status == "fail"):
                    byte_styles[byte_idx][key] = status

        signals_info.append({
            "name": v.signal_name,
            "algorithm": v.algorithm,
            "expected": v.expected_value,
            "actual": v.actual_value,
            "pass": v.is_pass,
            "detail": v.detail,
        })

    seg_size = 8 if dlc > 8 else dlc
    num_segments = (dlc + seg_size - 1) // seg_size

    seg_dataid: dict[int, int] = {}
    for v in verdicts:
        if v.dataid is not None and v.start_bit:
            seg_idx = v.start_bit // (seg_size * 8)
            seg_dataid[seg_idx] = v.dataid

    crc_ok = sum(1 for v in verdicts if v.algorithm == "crc" and v.is_pass)
    crc_err = sum(1 for v in verdicts if v.algorithm == "crc" and not v.is_pass)
    rc_ok = sum(1 for v in verdicts if v.algorithm != "crc" and v.is_pass)
    rc_err = sum(1 for v in verdicts if v.algorithm != "crc" and not v.is_pass)

    hex_rows = []
    for seg_idx in range(num_segments):
        seg_start = seg_idx * seg_size
        seg_end = min(seg_start + seg_size, dlc)
        seg_bytes = frame_data[seg_start:seg_end]

        bytes_html = ""
        for i, b in enumerate(seg_bytes):
            byte_idx = seg_start + i
            styles = byte_styles.get(byte_idx, {})
            css_class = ""

            crc_status = styles.get("crc")
            rc_status = styles.get("rc")
            if crc_status and rc_status:
                css_class = f"has-crc rc-{rc_status}" if crc_status == "pass" else f"has-crc crc-fail"
            elif crc_status:
                css_class = f"crc-{crc_status}"
            elif rc_status:
                css_class = f"rc-{rc_status}"

            tooltip = ""
            if crc_status or rc_status:
                parts = []
                for v in verdicts:
                    sig_start_byte, _ = _bit_to_byte_pos(v.start_bit, 0, v.byte_order)
                    sig_end_byte, _ = _bit_to_byte_pos(v.start_bit, v.length - 1, v.byte_order)
                    if min(sig_start_byte, sig_end_byte) <= byte_idx <= max(sig_start_byte, sig_end_byte):
                        status = "OK" if v.is_pass else "ERR"
                        parts.append(f"{v.signal_name}: exp=0x{v.expected_value:X} act=0x{v.actual_value:X} [{status}]")
                tooltip = " | ".join(parts)

            tooltip_html = f'<span class="tooltip">{tooltip}</span>' if tooltip else ""
            bytes_html += f'<span class="hex-byte {css_class}">{b:02X}{tooltip_html}</span>'

        offset = f"0x{seg_start:04X}"
        did = seg_dataid.get(seg_idx)
        label = f'Seg{seg_idx} <span class="did">0x{did:04X}</span>' if did is not None else f"Seg{seg_idx}"
        hex_rows.append(
            f'<div class="hex-row">'
            f'<span class="segment-label">{label}</span>'
            f'<span class="hex-offset">{offset}</span>'
            f'<span class="hex-bytes">{bytes_html}</span>'
            f'</div>'
        )

    verdict_rows = ""
    for s in signals_info:
        row_class = "pass" if s["pass"] else "fail"
        exp_w = max(2, (s["expected"].bit_length() + 7) // 8 * 2)
        act_w = max(2, (s["actual"].bit_length() + 7) // 8 * 2)
        verdict_rows += (
            f'<tr class="{row_class}">'
            f'<td>{s["name"]}</td>'
            f'<td>{s["algorithm"]}</td>'
            f'<td>0x{s["expected"]:0{exp_w}X}</td>'
            f'<td>0x{s["actual"]:0{act_w}X}</td>'
            f'<td>{"PASS" if s["pass"] else "FAIL"}</td>'
            f'</tr>'
        )

    stats_html = ""
    if crc_ok + crc_err > 0:
        stats_html += f'<span class="ok">CRC:{crc_ok}</span>' if crc_ok > 0 else ""
        stats_html += f'<span class="err">CRC:{crc_err}</span>' if crc_err > 0 else ""
    if rc_ok + rc_err > 0:
        stats_html += f'<span class="ok">RC:{rc_ok}</span>' if rc_ok > 0 else ""
        stats_html += f'<span class="err">RC:{rc_err}</span>' if rc_err > 0 else ""

    # Channel tag (always show, channel 0 is valid)
    ch_tag = f'<span class="channel-tag channel-{channel % 4}">CH{channel}</span>'

    # DBC source tag
    dbc_tag = f'<span class="dbc-tag" title="{dbc_source}">{dbc_source}</span>' if dbc_source else ""

    collapsed = ""
    name_html = f'<span class="name">({frame_name})</span>' if frame_name else ""

    return f"""
    <div class="frame-section{collapsed}" data-channel="{channel}">
      <div class="frame-header" onclick="this.parentElement.classList.toggle('collapsed')">
        <span class="arrow">&#9660;</span>
        {ch_tag}
        <span class="id">0x{frame_id:03X}</span>
        {name_html}
        {dbc_tag}
        <span class="ts">@{ts:.6f}s</span>
        <span class="stats">{stats_html}</span>
      </div>
      <div class="frame-body">
        <div class="hex-grid">{''.join(hex_rows)}</div>
        <div class="verdict-table">
          <table>
            <tr><th>Signal</th><th>Type</th><th>Expected</th><th>Actual</th><th>Verdict</th></tr>
            {verdict_rows}
          </table>
        </div>
      </div>
    </div>"""


def write_html(report: VerifyReport, file_path: str, only_failures: bool = False) -> None:
    """Write verification results to a self-contained HTML file with hex-dump view.

    Features:
    - Channel display and per-channel filtering
    - DBC source tag for each frame
    - Full payload hex dump with CRC/RC highlighting
    - Hover tooltips, collapsible sections, filter buttons
    """
    from datetime import datetime

    verdicts = report.failed if only_failures else report.verdicts

    from collections import defaultdict
    grouped: dict[tuple[float, int], list[VerifyVerdict]] = defaultdict(list)
    for v in verdicts:
        grouped[(v.timestamp, v.frame_id)].append(v)

    # Collect unique channels and DBC sources
    channels: set[int] = set()
    dbc_sources: dict[int, str] = {}  # frame_id -> dbc_source from first protection

    # Build frame HTML sections
    frame_sections = []
    for (ts, fid), f_verdicts in sorted(grouped.items(), key=lambda x: (x[0][1], x[0][0])):
        fdata = report.get_frame_data(ts, fid)
        if fdata is None:
            continue
        ch = report.get_frame_channel(ts, fid)
        channels.add(ch)

        fname = report.get_frame_name(fid)
        dbc_src = report.get_frame_dbc_source(fid)
        frame_sections.append(_build_frame_html(f_verdicts, fdata, fname, channel=ch, dbc_source=dbc_src))

    # Compute separate CRC and RC stats
    crc_total = sum(1 for v in report.verdicts if v.algorithm == "crc")
    crc_pass = sum(1 for v in report.verdicts if v.algorithm == "crc" and v.is_pass)
    rc_total = sum(1 for v in report.verdicts if v.algorithm != "crc")
    rc_pass = sum(1 for v in report.verdicts if v.algorithm != "crc" and v.is_pass)
    crc_rate = crc_pass / crc_total if crc_total > 0 else 1.0
    rc_rate = rc_pass / rc_total if rc_total > 0 else 1.0

    dbc_display = ", ".join(report.dbc_paths) if report.dbc_paths else report.dbc_path

    # Build channel filter buttons
    ch_buttons = ""
    if len(channels) > 1:
        ch_buttons = '<span class="sep">|</span>'
        for ch in sorted(channels):
            ch_buttons += f'<button onclick="showChannel({ch})">CH{ch}</button>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CAN CRC Check Report</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="container">
<h1>CAN CRC Check Report</h1>
<div class="info-bar">
  DBC: {dbc_display}<br>
  Trace: {report.trace_path}<br>
  Channels: {len(channels)}<br>
  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>
<div class="summary-cards">
  <div class="card"><div class="label">Frames</div><div class="value">{report.total_frames}</div></div>
  <div class="card"><div class="label">Total Verdicts</div><div class="value">{report.total_verdicts}</div></div>
  <div class="card pass"><div class="label">CRC Pass</div><div class="value">{crc_pass}/{crc_total}</div></div>
  <div class="card"><div class="label">CRC Rate</div><div class="value">{crc_rate:.1%}</div></div>
  <div class="card pass"><div class="label">RC Pass</div><div class="value">{rc_pass}/{rc_total}</div></div>
  <div class="card"><div class="label">RC Rate</div><div class="value">{rc_rate:.1%}</div></div>
</div>

<div class="filter-bar">
  <button class="active" onclick="showAll()">All frames</button>
  <button onclick="showErrors()">Errors only</button>
  {ch_buttons}
  <span class="sep">|</span>
  <button onclick="expandAll()">Expand all</button>
  <button onclick="collapseAll()">Collapse all</button>
</div>

{''.join(frame_sections)}

</div>
<script>
function showAll() {{
  document.querySelectorAll('.frame-section').forEach(el => el.style.display = '');
  updateBtns('all');
}}
function showErrors() {{
  document.querySelectorAll('.frame-section').forEach(el => {{
    el.style.display = el.querySelector('.fail') ? '' : 'none';
  }});
  updateBtns('errors');
}}
function showChannel(ch) {{
  document.querySelectorAll('.frame-section').forEach(el => {{
    el.style.display = el.dataset.channel == ch ? '' : 'none';
  }});
  updateBtns('ch'+ch);
}}
function expandAll() {{
  document.querySelectorAll('.frame-section').forEach(el => el.classList.remove('collapsed'));
}}
function collapseAll() {{
  document.querySelectorAll('.frame-section').forEach(el => el.classList.add('collapsed'));
}}
function updateBtns(activeId) {{
  document.querySelectorAll('.filter-bar button').forEach(b => b.classList.remove('active'));
}}
</script>
</body>
</html>"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
