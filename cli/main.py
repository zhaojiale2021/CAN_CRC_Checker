"""CLI entry point — click-based command group."""

from __future__ import annotations

import json
from pathlib import Path
import click

from crc_checker.config import DEFAULT_MAX_FRAMES
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset, get_validation, list_presets
from crc_checker.dbc.parser import parse_dbc
from crc_checker.trace.reader import TraceReader
from crc_checker.verify.engine import VerifyEngine
from crc_checker.report.html import write_html


# ---------------------------------------------------------------------------
# Shared helpers used by both ``verify`` and ``run`` commands
# ---------------------------------------------------------------------------

_TRACE_EXTENSIONS = {".blf", ".asc", ".mf4", ".trc", ".csv", ".log", ".txt"}


def _parse_crc_params(algo: str | None, custom_crc: str | None) -> CRCParams | None:
    """Resolve CRC parameters from --algo or --custom-crc."""
    if custom_crc:
        data = json.loads(custom_crc)
        return CRCParams(
            width=data["width"],
            polynomial=int(data["poly"], 16) if isinstance(data["poly"], str) else data["poly"],
            initial_value=int(data["init"], 16) if isinstance(data["init"], str) else data["init"],
            final_xor=int(data["xor"], 16) if isinstance(data["xor"], str) else data["xor"],
            reflect_in=data.get("reflect_in", False),
            reflect_out=data.get("reflect_out", False),
            name=data.get("name", "custom"),
        )
    if algo:
        return get_preset(algo)
    return None


def _parse_crc_range(mode: str, start: int | None, end: int | None) -> CRCRange:
    """Build CRCRange from CLI options."""
    return CRCRange(
        mode=mode,
        start_byte=start or 0,
        end_byte=end if end is not None else -1,
    )


def _expand_trace_paths(trace_files: list[str]) -> list[str]:
    """Expand trace file paths, recursing into directories."""
    result: list[str] = []
    for t in trace_files:
        tp = Path(t)
        if tp.is_dir():
            files = sorted(f for f in tp.iterdir()
                          if f.suffix.lower() in _TRACE_EXTENSIONS)
            if not files:
                raise click.BadParameter(f"No trace files found in: {t}")
            result.extend(str(f) for f in files)
        else:
            result.append(str(tp))
    return result


def _build_algorithms(crc_params: CRCParams | None):
    """Build protection algorithm list from CRC params."""
    # pylint: disable=import-outside-toplevel
    from crc_checker.verify.runner import build_algorithms
    return build_algorithms(crc_params)


def _output_report(report, output_fmt: str, output_file: str,
                   only_failures: bool, max_sections: int | None = None):
    """Render verification report as table or HTML(返回提示文本,无则空串)。"""
    if output_fmt == "html":
        path = output_file or "crc_report.html"
        note = write_html(report, path, only_failures, max_sections=max_sections)
        if note:
            click.echo(f"报告已受限: {note}")
        click.echo(f"HTML: {path}")
    else:
        _print_table(report, only_failures)


# pylint: disable=too-many-locals
def _print_table(report, only_failures: bool = False):
    """Print results as a formatted table to terminal."""
    verdicts = report.failed if only_failures else report.verdicts

    if not verdicts:
        click.echo("No verification results.")
        return

    # Column widths
    ts_w, id_w, sig_w, algo_w, exp_w, act_w = 12, 10, 25, 16, 10, 10

    # Header
    header = (
        f"{'Timestamp':<{ts_w}} {'CAN ID':<{id_w}} {'Signal':<{sig_w}} "
        f"{'Algorithm':<{algo_w}} {'Expected':<{exp_w}} {'Actual':<{act_w}} Verdict"
    )
    click.echo(header)
    click.echo("-" * len(header))

    for v in verdicts:
        status = (
            click.style("PASS", fg="green")
            if v.is_pass
            else click.style("FAIL", fg="red", bold=True)
        )
        exp_str = f"0x{v.expected_value:0{(v.expected_value.bit_length() + 7) // 8 * 2}X}"
        act_str = f"0x{v.actual_value:0{(v.actual_value.bit_length() + 7) // 8 * 2}X}"

        line = (
            f"{v.timestamp:>{ts_w}.6f} "
            f"{f'0x{v.frame_id:03X}':<{id_w}} "
            f"{v.signal_name:<{sig_w}} "
            f"{v.algorithm:<{algo_w}} "
            f"{exp_str:<{exp_w}} "
            f"{act_str:<{act_w}} "
            f"{status}"
        )
        click.echo(line)

        if not v.is_pass and v.detail:
            click.echo(f"  {click.style(v.detail, fg='yellow')}")

    # Summary
    summary = report.summary()
    click.echo()
    click.echo("=" * 60)
    click.echo(f"SUMMARY: {summary['total_frames']} frames, "
               f"{summary['pass_count']} passed, "
               f"{summary['fail_count']} failed "
               f"({summary['pass_rate']} pass rate)")


@click.group()
def cli():
    """CAN CRC Checker — DBC-aware CAN bus CRC/Rolling Counter verification tool."""


@cli.command()
@click.option("--dbc", "dbc_paths", multiple=True,
              type=click.Path(exists=True), help="Path to DBC file(s) or directory (repeatable)")
@click.option("--trace", "trace_files", required=True, multiple=True,
              type=click.Path(exists=True), help="Path to trace file(s) (BLF, ASC, MF4, ...)")
@click.option("--algo", default=None, help="CRC preset name (e.g. CRC8/AUTOSAR)")
@click.option("--custom-crc", default=None, help="Custom CRC params as JSON string")
@click.option("--range", "range_mode", default="exclude_crc",
              type=click.Choice(["full_payload", "exclude_crc", "custom_range"]),
              help="CRC data range mode")
@click.option("--range-start", type=int, default=None, help="Custom range start byte (0-indexed)")
@click.option("--range-end", type=int, default=None, help="Custom range end byte")
@click.option("--checksum-pattern", default=None,
              help="Override regex for checksum signal matching")
@click.option("--rc-pattern", default=None,
              help="Override regex for rolling counter signal matching")
@click.option("--patterns-file", default=None, type=click.Path(exists=True),
              help="YAML with signal-name patterns (see crc_checker/data/patterns.yaml)")
@click.option("--dataid-xlsx", default=None, type=click.Path(exists=True),
              help="Excel file with DataID mappings for E2E CRC calculation")
@click.option("--dataid-sheet", default=None,
              help="Sheet name in the DataID Excel (default: auto-detect)")
@click.option("--dataid-mapping", default=None,
              help="Column mapping: name from dataid_mappings.yaml "
                   "(hi_lo_two_cols, single_16bit, generic_abc, simple_8bit, "
                   "description_regex) or a JSON object")
@click.option("--frame-ids", default=None,
              help="Comma-separated CAN IDs to filter (e.g. 0x323,0x299)")
@click.option("--output", "output_fmt", default="table",
              type=click.Choice(["table", "html"]),
              help="Output format")
@click.option("--output-file", default=None, type=click.Path(), help="Output file path")
@click.option("--only-failures", is_flag=True, help="Only show/write failed verdicts")
@click.option("--max-frames", type=int, default=DEFAULT_MAX_FRAMES,
              help="Maximum frames to process (0 = unlimited, default 6000)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
# pylint: disable=too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# pylint: disable=import-outside-toplevel
def verify(dbc_paths, trace_files, algo, custom_crc,
           range_mode, range_start, range_end,
           checksum_pattern, rc_pattern, patterns_file,
           dataid_xlsx, dataid_sheet, dataid_mapping,
           frame_ids, output_fmt, output_file,
           only_failures, max_frames, verbose):
    """Verify CRC and Rolling Counter in CAN trace files."""

    if not dbc_paths:
        raise click.UsageError("At least one --dbc path is required.")

    # Parse CRC params
    if not algo and not custom_crc:
        click.echo("Warning: No CRC algorithm specified. Use --algo or --custom-crc.", err=True)
        click.echo("Only Rolling Counter verification will be performed.", err=True)

    crc_params = _parse_crc_params(algo, custom_crc)
    crc_range = _parse_crc_range(range_mode, range_start, range_end)

    if verbose and crc_params:
        click.echo(f"CRC Algorithm: {crc_params.name}")
        click.echo(f"  poly=0x{crc_params.polynomial:X} init=0x{crc_params.initial_value:X} "
                   f"xor=0x{crc_params.final_xor:X} width={crc_params.width}")

    # Parse frame ID filter
    id_filter = None
    if frame_ids:
        id_filter = [int(x.strip(), 16) if x.strip().startswith("0x") else int(x.strip())
                     for x in frame_ids.split(",")]

    # Build signal patterns
    patterns = None
    if checksum_pattern or rc_pattern:
        patterns = {}
        if checksum_pattern:
            patterns["checksum"] = checksum_pattern
        if rc_pattern:
            patterns["rolling_counter"] = rc_pattern

    # Signal-name patterns (YAML default, optional custom file, regex overrides)
    from crc_checker.patterns import load_naming_patterns
    naming = load_naming_patterns(patterns_file) if patterns_file else None
    if patterns and naming:
        naming = naming.with_overrides(checksum_pattern, rc_pattern)

    # Parse DBC: if multiple, auto-select best match from trace sample
    from crc_checker.dbc.parser import parse_all_dbc, select_best_dbc, sample_trace_ids
    all_dbc = list(dbc_paths)
    if len(all_dbc) == 1 and Path(all_dbc[0]).is_file() and all_dbc[0].endswith('.dbc'):
        # Single DBC file — direct parse
        protection_map = parse_dbc(all_dbc[0], patterns, naming=naming)
        if verbose:
            click.echo(f"Parsing DBC: {all_dbc[0]}")
    else:
        # Multiple or directory — parse all, select by trace match
        dbc_maps = parse_all_dbc(all_dbc, patterns, naming=naming)
        if len(dbc_maps) == 1:
            protection_map = dbc_maps[0]
        else:
            sample_ids = sample_trace_ids(trace_files[0], max_frames=500)
            best_map, best_matched, best_total = select_best_dbc(dbc_maps, sample_ids)
            if best_map is None:
                raise click.UsageError("No DBC matches any frame IDs in trace.")
            protection_map = best_map
            if verbose:
                click.echo(f"Auto-selected: {Path(best_map.dbc_paths[0]).name} "
                           f"({best_matched}/{best_total} IDs matched)")

    if crc_params:
        protection_map.apply_crc_params(crc_params)
    # Only apply explicit range; if user didn't specify --range, let auto-detect work
    if range_mode != "exclude_crc" or range_start != 0 or range_end != -1:
        protection_map.apply_crc_range(crc_range)

    # Parse DataID Excel if provided
    if dataid_xlsx:
        from crc_checker.dataid import parse_dataid_xlsx
        if verbose:
            click.echo(f"Parsing DataID Excel: {dataid_xlsx}" +
                       (f" (sheet: {dataid_sheet})" if dataid_sheet else ""))
        dataid_map = parse_dataid_xlsx(dataid_xlsx, dataid_sheet, mapping=dataid_mapping)
        n = protection_map.apply_dataid_map(dataid_map)
        if verbose:
            click.echo(f"Loaded {len(dataid_map)} DataID entries, {n} applied")

    if verbose:
        click.echo(f"Found protection signals in {len(protection_map.all_frame_ids())} CAN IDs")

    algorithms = _build_algorithms(crc_params)

    for trace_path in _expand_trace_paths(list(trace_files)):
        if verbose:
            click.echo(f"Processing trace: {trace_path}")
        engine = VerifyEngine(protection_map, algorithms)
        with TraceReader(trace_path) as reader:
            report = engine.run(reader, frame_ids=id_filter, max_frames=max_frames)
        report.dbc_paths = protection_map.dbc_paths
        _output_report(report, output_fmt, output_file, only_failures)


@cli.command("presets")
def list_presets_cmd():
    """List all available CRC algorithm presets."""
    click.echo("Available CRC presets:")
    click.echo()
    for name in list_presets():
        p = get_preset(name)
        status, note = get_validation(name)
        label = ("verified with real data" if status == "validated"
                 else "NOT verified with real data")
        click.echo(
            f"  {name:20s} width={p.width} poly=0x{p.polynomial:0{(p.width+3)//4}X} "
            f"init=0x{p.initial_value:0{(p.width+3)//4}X} "
            f"xor=0x{p.final_xor:0{(p.width+3)//4}X} "
            f"ref_in={int(p.reflect_in)} ref_out={int(p.reflect_out)}  "
            f"[{label}]"
        )
        if status != "validated" and note:
            click.echo(f"  {'':20s} {note}")


@cli.command("run")
@click.option("--config", "-c", "config_path", required=True,
              type=click.Path(exists=True), help="Path to JSON config file")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def run_cmd(config_path, verbose):  # pylint: disable=too-many-branches
    """Run verification from a JSON config file.

    Generate an example config:  crc-check gen-config example.json
    Then edit and run:           crc-check run -c example.json
    """
    # pylint: disable=import-outside-toplevel
    from crc_checker.config import load_config
    from crc_checker.verify.runner import RunnerError, run_config

    cfg = load_config(config_path)

    if verbose:
        click.echo(f"Config: {config_path}")
        click.echo(f"DBC:    {cfg.dbc}")
        if cfg.dbcs:
            click.echo(f"DBCs:   {', '.join(cfg.dbcs)}")
        click.echo(f"Traces: {len(cfg.traces)} file(s)")
        if cfg.crc_preset:
            click.echo(f"CRC:    {cfg.crc_preset}")
        elif cfg.crc_custom:
            click.echo("CRC:    custom")
        if cfg.dataid_json and Path(cfg.dataid_json).exists():
            click.echo(f"DataID JSON: {cfg.dataid_json} (fast path)")
        elif cfg.dataid_xlsx:
            click.echo(f"DataID xlsx: {cfg.dataid_xlsx}")

    if not cfg.crc_preset and not cfg.crc_custom and not cfg.crc_auto_classify:
        click.echo("Warning: No CRC algorithm configured. RC-only verification.", err=True)
    if cfg.crc_preset:
        status, _note = get_validation(cfg.crc_preset)
        if status != "validated":
            click.echo(f"Warning: preset {cfg.crc_preset} is not verified with "
                       "real data.", err=True)

    trace_paths = cfg.get_trace_paths()

    # Everything below (DBC selection → DataID → CRC config → verify) lives in
    # crc_checker.verify.runner so the web API cannot drift from the CLI.
    try:
        setup, reports = run_config(cfg, trace_paths)
    except RunnerError as exc:
        raise click.UsageError(str(exc)) from exc

    if verbose:
        for note in setup.notes:
            click.echo(note)
        click.echo(f"Trace files: {len(trace_paths)} file(s)")
        for p in trace_paths:
            click.echo(f"  {p}")

    for report in reports:
        _output_report(report, cfg.output_format, cfg.output_file,
                       cfg.only_failures, cfg.max_report_sections)


@cli.command("preprocess-dataid")
@click.option("--xlsx", required=True, type=click.Path(exists=True),
              help="Path to DataID Excel file")
@click.option("--sheet", "sheets", multiple=True, default=None,
              help="Sheet name(s) to parse (repeatable; default: all sheets)")
@click.option("--mapping", default="hi_lo_two_cols",
              help="Column mapping: name from dataid_mappings.yaml "
                   "(hi_lo_two_cols, single_16bit, generic_abc, simple_8bit, "
                   "description_regex) or a JSON object")
@click.option("--output", "-o", required=True, type=click.Path(),
              help="Output JSON file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
# pylint: disable=import-outside-toplevel
def preprocess_dataid(xlsx, sheets, mapping, output, verbose):
    """Preprocess DataID Excel into standardized JSON for fast reload.

    Parse one or more sheets from a DataID Excel file and export a
    unified JSON that subsequent 'crc-check run' can load directly,
    skipping the slow openpyxl step.

    \b
    Example:
      crc-check preprocess-dataid --xlsx dataid.xlsx \
          --sheet "Sheet1" --sheet "Sheet2" -o dataid.json
    """
    from crc_checker.dataid import parse_dataid_xlsx_multi

    sheet_list = list(sheets) if sheets else None

    if verbose:
        click.echo(f"Parsing: {xlsx}")
        click.echo(f"Mapping: {mapping}")
        if sheet_list:
            click.echo(f"Sheets: {', '.join(sheet_list)}")
        else:
            click.echo("Sheets: all")

    dm = parse_dataid_xlsx_multi(xlsx, sheet_list, mapping=mapping)

    if len(dm) == 0:
        click.echo("Warning: No DataID entries found.", err=True)

    parsed_sheets = sheet_list or ["<auto>"]
    dm.to_json(output, source=xlsx, mapping=mapping, sheets=parsed_sheets)
    click.echo(f"DataID JSON written to {output} ({len(dm)} entries)")


@cli.command("gen-config")
@click.argument("output_path", type=click.Path(), default="crc_config.json")
# pylint: disable=import-outside-toplevel
def gen_config_cmd(output_path):
    """Generate an example JSON config file."""
    from crc_checker.config import generate_example_config
    generate_example_config(output_path)
    click.echo(f"Example config written to {output_path}")
    click.echo(f"Edit it, then: crc-check run -c {output_path}")


@cli.command()
@click.argument("dbc_path", type=click.Path(exists=True))
def inspect(dbc_path):
    """Inspect a DBC file and list all detected protection signals."""
    protection_map = parse_dbc(dbc_path)

    if not protection_map.all_frame_ids():
        click.echo("No protection signals (Checksum/RollingCounter) found in DBC.")
        return

    click.echo(f"DBC: {dbc_path}")
    click.echo(f"Found protection signals in {len(protection_map.all_frame_ids())} CAN IDs:\n")

    for frame_id in sorted(protection_map.all_frame_ids()):
        for prot in protection_map.get_protections(frame_id):
            click.echo(f"  ID=0x{frame_id:03X} ({prot.frame_name}) [{prot.pair_suffix}]")
            if prot.checksum_signal:
                cs = prot.checksum_signal
                click.echo(f"    Checksum:  {cs.name}  start_bit={cs.start_bit} length={cs.length}")
            if prot.rolling_counter_signal:
                rc = prot.rolling_counter_signal
                click.echo(f"    RC:        {rc.name}  start_bit={rc.start_bit} length={rc.length}")
            click.echo()


if __name__ == "__main__":
    cli()
