"""Textual TUI application — setup screen + results browser + export.

Launch without arguments to enter the file-picker setup screen:
    crc-check tui
Or with arguments to skip directly to results:
    crc-check verify --dbc ... --trace ... --tui
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Button, Input, Select, Label,
    DirectoryTree, DataTable,
)
from textual.reactive import reactive
from textual import events, on
from textual.screen import Screen, ModalScreen

from crc_checker.dbc.models import DBCProtectionMap
from crc_checker.crc.models import CRCParams, CRCRange
from crc_checker.crc.presets import get_preset, list_presets
from crc_checker.trace.reader import TraceReader
from crc_checker.verify.engine import VerifyEngine

# ---------------------------------------------------------------------------
# Trace file discovery
# ---------------------------------------------------------------------------

TRACE_EXTENSIONS = {".blf", ".asc", ".trc", ".mf4", ".mdf", ".csv", ".log"}


def _find_trace_files(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    if p.is_file():
        return [str(p)]
    if p.is_dir():
        files = []
        for ext in TRACE_EXTENSIONS:
            files.extend(str(f) for f in p.glob(f"*{ext}"))
            files.extend(str(f) for f in p.glob(f"*{ext.upper()}"))
        return sorted(files)
    return []


# ---------------------------------------------------------------------------
# Export modal screen
# ---------------------------------------------------------------------------

class ExportScreen(ModalScreen):
    """Modal dialog for choosing export format and file path."""

    CSS = """
    ExportScreen {
        align: center middle;
    }

    #export-dialog {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #export-dialog .title {
        text-style: bold;
        color: $accent;
        content-align: center middle;
        margin-bottom: 1;
    }

    #export-dialog Input {
        width: 100%;
        margin-top: 1;
        margin-bottom: 1;
    }

    #export-dialog Select {
        width: 100%;
        margin-top: 1;
        margin-bottom: 1;
    }

    #export-dialog Horizontal {
        margin-top: 1;
        height: auto;
    }

    #export-dialog Button {
        width: 1fr;
        margin: 0 1;
    }
    """

    def __init__(self, default_name: str = "crc_report"):
        super().__init__()
        self._default_name = default_name

    def compose(self) -> ComposeResult:
        with Container(id="export-dialog"):
            yield Static("📤 Export Report", classes="title")

            yield Label("Format:")
            yield Select(
                [
                    ("HTML (self-contained, collapsible)", "html"),
                    ("CSV (flat table)", "csv"),
                    ("JSON (structured)", "json"),
                ],
                id="export-format",
                allow_blank=False,
            )

            yield Label("File path:")
            yield Input(
                placeholder=f"e.g. {self._default_name}.html",
                id="export-path",
                value=f"{self._default_name}.html",
            )

            yield Label("Content:")
            yield Select(
                [
                    ("All verdicts", "all"),
                    ("Failures only", "failures"),
                ],
                id="export-content",
                allow_blank=False,
            )

            with Horizontal():
                yield Button("Cancel", id="export-cancel", variant="default")
                yield Button("Export", id="export-do", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "export-cancel":
            self.dismiss(None)
        elif event.button.id == "export-do":
            fmt = self.query_one("#export-format", Select).value
            path = self.query_one("#export-path", Input).value.strip()
            content = self.query_one("#export-content", Select).value
            if not path:
                self.notify("Please enter a file path.", severity="error")
                return
            self.dismiss({"format": fmt, "path": path, "only_failures": content == "failures"})


# ---------------------------------------------------------------------------
# Results screen
# ---------------------------------------------------------------------------

class ResultsScreen(Screen):
    """Screen that shows verification results in a DataTable with action bar."""

    CSS = """
    #result-summary {
        dock: top;
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
        content-align: center middle;
    }

    #result-table {
        height: 1fr;
    }

    #result-action-bar {
        dock: bottom;
        height: 3;
        background: $surface;
        border-top: solid $primary-background;
        padding: 0 1;
        align: center middle;
    }

    #result-action-bar Horizontal {
        width: 100%;
        align: center middle;
    }

    #result-action-bar Button {
        margin: 0 1;
        min-width: 14;
    }

    #result-status {
        dock: bottom;
        height: 1;
        background: $panel;
        padding: 0 1;
        content-align: left middle;
        text-style: dim;
    }

    .pass { color: $success; }
    .fail { color: $error; }
    """

    def __init__(self, protection_map: DBCProtectionMap,
                 trace_files: list[str],
                 crc_params: CRCParams | None,
                 crc_range: CRCRange,
                 frame_ids: list[int] | None = None,
                 max_frames: int | None = None):
        super().__init__()
        self.protection_map = protection_map
        self.trace_files = trace_files
        self.crc_params = crc_params
        self.crc_range = crc_range
        self.frame_ids = frame_ids
        self.max_frames = max_frames
        self._verdicts: list = []
        self._processing_done = False
        self._filter_failures = False
        self._pass_count = 0
        self._fail_count = 0
        self._frame_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Processing...", id="result-summary")
        yield DataTable(id="result-table")
        with Container(id="result-action-bar"):
            with Horizontal():
                yield Button("Filter: All", id="btn-filter", variant="default")
                yield Button("Export", id="btn-export", variant="primary")
                yield Button("Back to Setup", id="btn-back", variant="default")
                yield Button("Quit", id="btn-quit", variant="error")
        yield Static("", id="result-status")

    def on_mount(self):
        table = self.query_one("#result-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            "Timestamp", "CAN ID", "Signal", "Algorithm",
            "Expected", "Actual", "Verdict"
        )
        self.set_timer(0.2, self._process_trace)

    @on(Button.Pressed, "#btn-filter")
    def on_filter(self, event: Button.Pressed):
        self._toggle_filter()

    @on(Button.Pressed, "#btn-export")
    def on_export(self, event: Button.Pressed):
        if not self._verdicts:
            self.notify("No results to export.", severity="warning")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.app.push_screen(
            ExportScreen(default_name=f"crc_report_{ts}"),
            callback=self._do_export,
        )

    @on(Button.Pressed, "#btn-back")
    def on_back(self, event: Button.Pressed):
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-quit")
    def on_quit(self, event: Button.Pressed):
        self.app.exit()

    def on_key(self, event: events.Key):
        if event.key == "q":
            self.app.exit()
        elif event.key == "f":
            self._toggle_filter()
        elif event.key == "e":
            if self._verdicts:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.app.push_screen(
                    ExportScreen(default_name=f"crc_report_{ts}"),
                    callback=self._do_export,
                )
        elif event.key == "b":
            self.app.pop_screen()

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _process_trace(self):
        table = self.query_one("#result-table", DataTable)
        status = self.query_one("#result-status", Static)
        summary_w = self.query_one("#result-summary", Static)

        from crc_checker.protect.checksum import CRCVerifier
        from crc_checker.protect.rolling_counter import RollingCounterVerifier
        algorithms = []
        if self.crc_params:
            algorithms.append(CRCVerifier(self.crc_params, None))
        algorithms.append(RollingCounterVerifier())
        engine = VerifyEngine(self.protection_map, algorithms)

        for trace_path in self.trace_files:
            try:
                with TraceReader(trace_path) as reader:
                    for verdict in engine.run_stream(
                        reader, frame_ids=self.frame_ids, max_frames=self.max_frames
                    ):
                        self._verdicts.append(verdict)
                        self._frame_count += 1
                        if verdict.is_pass:
                            self._pass_count += 1
                        else:
                            self._fail_count += 1

                        exp_w = max(2, (verdict.expected_value.bit_length() + 7) // 8 * 2)
                        act_w = max(2, (verdict.actual_value.bit_length() + 7) // 8 * 2)
                        table.add_row(
                            f"{verdict.timestamp:.6f}",
                            f"0x{verdict.frame_id:03X}",
                            verdict.signal_name,
                            verdict.algorithm,
                            f"0x{verdict.expected_value:0{exp_w}X}",
                            f"0x{verdict.actual_value:0{act_w}X}",
                            "✅" if verdict.is_pass else "❌",
                            key=str(len(self._verdicts) - 1),
                        )

                        if self._frame_count % 100 == 0:
                            status.update(
                                f"Processing... {self._frame_count} frames | "
                                f"Pass: {self._pass_count} | Fail: {self._fail_count}"
                            )
            except Exception as e:
                self.notify(f"Error reading {trace_path}: {e}", severity="error")

        total = self._pass_count + self._fail_count
        rate = self._pass_count / total * 100 if total > 0 else 100
        self._processing_done = True

        summary_w.update(
            f"Frames: {self._frame_count} | "
            f"[green]Pass: {self._pass_count}[/green] | "
            f"[red]Fail: {self._fail_count}[/red] | "
            f"Rate: {rate:.1f}%"
        )
        status.update(
            f"Done. {total} verifications. "
            f"[F]ilter  [E]xport  [B]ack  [Q]uit"
        )

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _toggle_filter(self):
        table = self.query_one("#result-table", DataTable)
        table.clear()
        self._filter_failures = not self._filter_failures

        for i, v in enumerate(self._verdicts):
            if self._filter_failures and v.is_pass:
                continue
            exp_w = max(2, (v.expected_value.bit_length() + 7) // 8 * 2)
            act_w = max(2, (v.actual_value.bit_length() + 7) // 8 * 2)
            table.add_row(
                f"{v.timestamp:.6f}",
                f"0x{v.frame_id:03X}",
                v.signal_name,
                v.algorithm,
                f"0x{v.expected_value:0{exp_w}X}",
                f"0x{v.actual_value:0{act_w}X}",
                "✅" if v.is_pass else "❌",
                key=str(i),
            )

        btn = self.query_one("#btn-filter", Button)
        status = self.query_one("#result-status", Static)
        if self._filter_failures:
            btn.label = "Filter: Failures Only"
            status.update("FAILURES ONLY | [F]ilter [E]xport [B]ack [Q]uit")
        else:
            btn.label = "Filter: All"
            status.update("ALL | [F]ilter [E]xport [B]ack [Q]uit")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _do_export(self, config: dict | None):
        """Called when ExportScreen is dismissed with export config."""
        if config is None:
            return  # cancelled

        fmt = config["format"]
        path = config["path"]
        only_failures = config["only_failures"]

        from crc_checker.verify.models import VerifyReport
        from crc_checker.report.html import write_html
        from crc_checker.report.csv_writer import write_csv
        from crc_checker.report.json_writer import write_json

        report = VerifyReport(
            verdicts=self._verdicts,
            dbc_path=self.protection_map.dbc_path,
            trace_path=", ".join(self.trace_files),
            total_frames=self._frame_count,
            total_verdicts=len(self._verdicts),
        )

        try:
            if fmt == "html":
                write_html(report, path, only_failures)
            elif fmt == "csv":
                write_csv(report, path, only_failures)
            elif fmt == "json":
                write_json(report, path, only_failures)
            self.notify(f"✅ Exported to {path}", title="Export Complete")
        except Exception as e:
            self.notify(f"Export failed: {e}", severity="error")


# ---------------------------------------------------------------------------
# Setup screen
# ---------------------------------------------------------------------------

class SetupScreen(Screen):
    """Initial screen for selecting DBC, DataID, trace files, and CRC algorithm."""

    CSS = """
    #setup-container {
        padding: 1 2;
        height: 1fr;
    }

    .section-title {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 1;
    }

    #setup-left {
        width: 1fr;
        margin-right: 1;
    }

    #setup-right {
        width: 1fr;
    }

    Input {
        width: 100%;
    }

    Select {
        width: 100%;
    }

    #dir-tree {
        height: 12;
        border: solid $primary-background;
        margin-top: 1;
        margin-bottom: 1;
    }

    #selected-files {
        height: 5;
        border: solid $primary-background;
        padding: 1;
        margin-top: 1;
    }

    #start-btn {
        width: 100%;
        margin-top: 1;
    }

    .hint {
        color: $text-muted;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="setup-container"):
            with Horizontal():
                # Left column — file selection
                with Vertical(id="setup-left"):
                    yield Static("[DBC File]", classes="section-title")
                    yield Input(
                        placeholder="Path to .dbc file (e.g. test_dbc/network.dbc)",
                        id="dbc-path",
                    )

                    yield Static("[DataID Excel] (optional)", classes="section-title")
                    yield Input(
                        placeholder="Path to DataID .xlsx file",
                        id="dataid-path",
                    )
                    yield Input(
                        placeholder="Sheet name (auto-detect if blank)",
                        id="dataid-sheet",
                    )

                    yield Static("[Trace Files / Directory]", classes="section-title")
                    yield Input(
                        placeholder="Path to .blf file or directory with trace files",
                        id="trace-path",
                    )
                    yield Static(
                        "Supported: .blf .asc .trc .mf4 .csv — if a directory is "
                        "given, all matching files will be scanned.",
                        classes="hint",
                    )

                    yield DirectoryTree(os.path.abspath("."), id="dir-tree")
                    yield Static("No trace files selected.", id="selected-files")

                # Right column — algorithm config
                with Vertical(id="setup-right"):
                    yield Static("[CRC Algorithm]", classes="section-title")
                    yield Select(
                        [(name, name) for name in list_presets()],
                        id="algo-select",
                        prompt="Select CRC algorithm...",
                    )

                    yield Static("[CRC Data Range]", classes="section-title")
                    yield Select(
                        [
                            ("Exclude CRC field (recommended)", "exclude_crc"),
                            ("Full payload", "full_payload"),
                            ("Custom byte range", "custom_range"),
                        ],
                        id="range-select",
                        allow_blank=False,
                    )

                    yield Static("[Options]", classes="section-title")
                    yield Input(
                        placeholder="CAN ID filter (e.g. 0x143,0x299)",
                        id="frame-ids",
                    )
                    yield Input(
                        placeholder="Max frames (blank = all)",
                        id="max-frames",
                    )

            yield Button("Start Verification", id="start-btn", variant="primary")
            yield Button("Load Config JSON...", id="load-config-btn", variant="default")
        yield Footer()

    def on_mount(self):
        self._trace_files: list[str] = []
        self._refresh_selected_label()

    @on(DirectoryTree.FileSelected, "#dir-tree")
    def on_file_selected(self, event: DirectoryTree.FileSelected):
        path = str(event.path)
        ext = os.path.splitext(path)[1].lower()

        if ext in TRACE_EXTENSIONS:
            if path not in self._trace_files:
                self._trace_files.append(path)
                self._refresh_selected_label()
                self.notify(f"Added: {os.path.basename(path)}")
            else:
                self._trace_files.remove(path)
                self._refresh_selected_label()
        elif ext == ".dbc":
            self.query_one("#dbc-path", Input).value = path
            self.notify(f"DBC set: {os.path.basename(path)}")
        elif ext in (".xlsx", ".xls"):
            self.query_one("#dataid-path", Input).value = path
            self._auto_detect_sheets(path)
            self.notify(f"DataID set: {os.path.basename(path)}")
        elif ext == ".json":
            self._on_load_config_path(path)
        else:
            self.notify(f"Unsupported format: {ext}", severity="warning")

    @on(Input.Changed, "#trace-path")
    def on_trace_path_changed(self, event: Input.Changed):
        path = event.value.strip()
        if not path or not os.path.exists(path):
            return
        if os.path.isfile(path):
            self._trace_files = [path]
        elif os.path.isdir(path):
            self._trace_files = _find_trace_files(path)
        self._refresh_selected_label()

    @on(Input.Changed, "#dataid-path")
    def on_dataid_path_changed(self, event: Input.Changed):
        path = event.value.strip()
        if path and os.path.exists(path) and path.endswith((".xlsx", ".xls")):
            self._auto_detect_sheets(path)

    def _auto_detect_sheets(self, xlsx_path: str):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, data_only=True)
            sheets = wb.sheetnames
            wb.close()
            if sheets:
                sheet_input = self.query_one("#dataid-sheet", Input)
                if not sheet_input.value:
                    real_sheets = [s for s in sheets if not s.startswith("Sheet")]
                    if len(real_sheets) <= 2:
                        sheet_input.placeholder = f"Detected: {real_sheets[0]}"
        except Exception:
            pass

    def _refresh_selected_label(self):
        label = self.query_one("#selected-files", Static)
        if self._trace_files:
            text = f"Selected {len(self._trace_files)} trace file(s):\n"
            for f in self._trace_files[:10]:
                text += f"  • {os.path.basename(f)}\n"
            if len(self._trace_files) > 10:
                text += f"  ... and {len(self._trace_files) - 10} more"
        else:
            text = "No trace files selected. Click files in the tree above\n"
            text += "or type a directory path to scan."
        label.update(text)

    @on(Button.Pressed, "#start-btn")
    @on(Button.Pressed, "#load-config-btn")
    def on_load_config(self, event: Button.Pressed):
        """Prompt for a config JSON path and populate fields."""
        from crc_checker.config import load_config

        # Ask user for config path via a simple approach: use the DBC input
        # as a temporary config path entry, then restore
        dbc_input = self.query_one("#dbc-path", Input)
        current = dbc_input.value
        dbc_input.value = ""
        dbc_input.placeholder = "Enter path to .json config file, then press Enter..."

        @on(Input.Submitted, "#dbc-path")
        def _load(ev: Input.Submitted):
            # Restore handler after one use
            self._on_load_config_path(ev.value)
            dbc_input.value = current
            dbc_input.placeholder = "Path to .dbc file (e.g. test_dbc/network.dbc)"

    def _on_load_config_path(self, config_path: str):
        """Populate all fields from a config JSON file."""
        from crc_checker.config import load_config
        from crc_checker.crc.presets import list_presets

        if not config_path or not os.path.exists(config_path):
            self.notify("Config file not found.", severity="error")
            return

        try:
            cfg = load_config(config_path)
        except Exception as e:
            self.notify(f"Failed to load config: {e}", severity="error")
            return

        # Populate all fields
        self.query_one("#dbc-path", Input).value = cfg.dbc
        self.query_one("#trace-path", Input).value = cfg.traces[0] if cfg.traces else ""
        if cfg.dataid_xlsx:
            self.query_one("#dataid-path", Input).value = cfg.dataid_xlsx
        if cfg.dataid_sheet:
            self.query_one("#dataid-sheet", Input).value = cfg.dataid_sheet

        # CRC algorithm
        if cfg.crc_preset:
            try:
                self.query_one("#algo-select", Select).value = cfg.crc_preset
            except Exception:
                pass

        # Range
        try:
            self.query_one("#range-select", Select).value = cfg.range_mode
        except Exception:
            pass

        if cfg.frame_ids:
            self.query_one("#frame-ids", Input).value = ",".join(
                f"0x{x:03X}" for x in cfg.frame_ids
            )
        if cfg.max_frames:
            self.query_one("#max-frames", Input).value = str(cfg.max_frames)

        # Update trace files
        if cfg.traces:
            self._trace_files = []
            for t in cfg.traces:
                if os.path.exists(t):
                    self._trace_files.append(t)
            self._refresh_selected_label()

        self.notify(f"Loaded config: {os.path.basename(config_path)}")

    def on_start(self, event: Button.Pressed):
        dbc_path = self.query_one("#dbc-path", Input).value.strip()
        if not dbc_path or not os.path.exists(dbc_path):
            self.notify("Please select a valid DBC file.", severity="error")
            return

        trace_path = self.query_one("#trace-path", Input).value.strip()
        if trace_path and os.path.exists(trace_path):
            if os.path.isdir(trace_path):
                self._trace_files = _find_trace_files(trace_path)
            elif os.path.isfile(trace_path):
                self._trace_files = [trace_path]
        if not self._trace_files:
            self.notify("Please select at least one trace file or directory.", severity="error")
            return

        algo_name = self.query_one("#algo-select", Select).value
        crc_params = None
        if algo_name and algo_name is not Select.NULL:
            crc_params = get_preset(algo_name)

        range_mode = self.query_one("#range-select", Select).value
        if range_mode is Select.NULL or not range_mode:
            range_mode = "exclude_crc"
        crc_range = CRCRange(mode=range_mode)

        frame_ids_str = self.query_one("#frame-ids", Input).value.strip()
        frame_ids = None
        if frame_ids_str:
            try:
                frame_ids = [
                    int(x.strip(), 16) if x.strip().lower().startswith("0x") else int(x.strip())
                    for x in frame_ids_str.split(",")
                ]
            except ValueError:
                self.notify("Invalid frame ID format.", severity="error")
                return

        max_frames_str = self.query_one("#max-frames", Input).value.strip()
        max_frames = None
        if max_frames_str:
            try:
                max_frames = int(max_frames_str)
            except ValueError:
                self.notify("Invalid max frames value.", severity="error")
                return

        from crc_checker.dbc.parser import parse_dbc
        try:
            protection_map = parse_dbc(dbc_path)
        except Exception as e:
            self.notify(f"Failed to parse DBC: {e}", severity="error")
            return

        if crc_params:
            protection_map.apply_crc_params(crc_params)
        protection_map.apply_crc_range(crc_range)

        dataid_path = self.query_one("#dataid-path", Input).value.strip()
        dataid_sheet = self.query_one("#dataid-sheet", Input).value.strip() or None
        if dataid_path and os.path.exists(dataid_path):
            from crc_checker.dataid import parse_dataid_xlsx
            try:
                dataid_map = parse_dataid_xlsx(dataid_path, dataid_sheet)
                n = protection_map.apply_dataid_map(dataid_map)
                self.notify(f"Loaded {len(dataid_map)} DataID entries ({n} applied)")
            except Exception as e:
                self.notify(f"DataID loading failed: {e}", severity="warning")

        self.app.push_screen(
            ResultsScreen(
                protection_map=protection_map,
                trace_files=self._trace_files,
                crc_params=crc_params,
                crc_range=crc_range,
                frame_ids=frame_ids,
                max_frames=max_frames,
            )
        )


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class CRCCheckerApp(App):
    """CAN CRC Checker TUI application."""

    CSS = """
    Screen {
        layers: base;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def on_mount(self):
        self.push_screen(SetupScreen())


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_tui(protection_map=None, trace_files=None, crc_params=None,
            crc_range=None, frame_ids=None, max_frames=None):
    """Launch TUI — with or without pre-configured data."""
    if protection_map is not None and trace_files is not None:
        app = CRCCheckerApp()
        app.push_screen(
            ResultsScreen(
                protection_map=protection_map,
                trace_files=list(trace_files),
                crc_params=crc_params,
                crc_range=crc_range or CRCRange(mode="exclude_crc"),
                frame_ids=frame_ids,
                max_frames=max_frames,
            )
        )
        app.run()
    else:
        CRCCheckerApp().run()
