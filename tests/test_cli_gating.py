"""CLI gating, summaries, and frame-cap visibility."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "example"


def _config(tmp_path: Path, trace_name: str, **overrides) -> str:
    """Example config with absolute paths and table output (nothing written)."""
    data = json.loads((EXAMPLE / "config.json").read_text(encoding="utf-8"))
    data["dbc"] = str(EXAMPLE / "dbc")
    data["traces"] = [str(EXAMPLE / "trace" / trace_name)]
    data["dataid"]["json"] = str(EXAMPLE / "dbc" / "dataid.json")
    data["output"] = {"format": "table"}
    data.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _run(*args: str):
    return CliRunner().invoke(cli, ["run", *args])


class TestExitCodes:
    """A verification tool must be usable as a CI gate."""

    def test_fail_on_failure_passes_clean_trace(self, tmp_path):
        """A clean run exits 0 under the gate."""
        config = _config(tmp_path, "example.blf")
        result = _run("-c", config, "--fail-on-failure")
        assert result.exit_code == 0, result.output
        assert "SUMMARY:" in result.output

    def test_fail_on_failure_fails_broken_trace(self, tmp_path):
        """A failing run exits 1 under the gate."""
        config = _config(tmp_path, "example_bad.blf")
        result = _run("-c", config, "--fail-on-failure")
        assert result.exit_code == 1
        assert "SUMMARY:" in result.output

    def test_min_pass_rate_gate(self, tmp_path):
        """The percentage gate fails a broken trace and passes a clean one."""
        good = _config(tmp_path, "example.blf")
        assert _run("-c", good, "--min-pass-rate", "100").exit_code == 0
        bad = _config(tmp_path, "example_bad.blf")
        assert _run("-c", bad, "--min-pass-rate", "100").exit_code == 1

    def test_no_flag_keeps_historical_exit_zero(self, tmp_path):
        """Existing scripts must not start failing without opting in."""
        config = _config(tmp_path, "example_bad.blf")
        assert _run("-c", config).exit_code == 0


class TestSummaries:
    """The summary is always printed, including in HTML/only-failures mode."""

    def test_html_mode_prints_summary(self, tmp_path):
        """HTML mode still reports the verdict on stdout."""
        report = tmp_path / "report.html"
        config = _config(tmp_path, "example.blf",
                         output={"format": "html", "file": str(report)})
        result = _run("-c", config)
        assert result.exit_code == 0, result.output
        assert f"HTML: {report}" in result.output
        assert "SUMMARY:" in result.output
        assert "320 passed" in result.output

    def test_only_failures_on_clean_trace_still_summarises(self, tmp_path):
        """No failures is not the same as no results."""
        config = _config(tmp_path, "example.blf",
                         output={"format": "table", "only_failures": True})
        result = _run("-c", config)
        assert result.exit_code == 0, result.output
        assert "No failed verdicts." in result.output
        assert "SUMMARY:" in result.output
        assert "No verification results." not in result.output

    def test_frame_cap_is_loud(self, tmp_path):
        """Hitting the cap is called out in the summary, not silent."""
        config = _config(tmp_path, "example.blf",
                         filter={"max_frames": 10})
        result = _run("-c", config)
        assert result.exit_code == 0, result.output
        assert "WARNING: stopped at the frame cap (10 frames)" in result.output

    def test_unknown_config_key_is_not_silent(self, tmp_path):
        """A typo'd key is reported even without -v."""
        config = _config(tmp_path, "example.blf", filtre={})
        result = _run("-c", config)
        assert result.exit_code == 0, result.output
        # click <8.2 merges stderr into output; newer versions expose stderr
        # (and raise ValueError if it was not captured separately).
        try:
            combined = result.output + (result.stderr or "")
        except ValueError:
            combined = result.output
        assert "filtre" in combined


class TestVerifyErrors:
    """Bad user input is a usage error, not a traceback."""

    def test_invalid_regex_is_a_usage_error(self):
        """A bad regex is a click usage error (exit 2), not a traceback."""
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
            "--checksum-pattern", "(",
        ])
        assert result.exit_code == 2
        assert "Traceback" not in result.output

    def test_corrupt_dataid_workbook_is_a_usage_error(self, tmp_path):
        """A non-zip .xlsx must not leak openpyxl/zipfile tracebacks."""
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not a zip file")
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
            "--algo", "CRC8/SAE-J1850", "--max-frames", "5",
            "--dataid-xlsx", str(bad),
        ])
        assert result.exit_code == 2
        assert "Traceback" not in result.output

    def test_version_flag(self):
        """The CLI exposes the package version."""
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output
