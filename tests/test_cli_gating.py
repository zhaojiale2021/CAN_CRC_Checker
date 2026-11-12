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


def _separated_runner() -> CliRunner:
    """CliRunner that keeps stderr out of stdout.

    click <8.2 merges the streams unless ``mix_stderr`` is disabled; click
    8.2+ removed the flag because separation is the only behaviour. Set it
    only where the attribute exists so both versions stay quiet.
    """
    runner = CliRunner()
    if hasattr(runner, "mix_stderr"):
        runner.mix_stderr = False
    return runner


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

    def test_fail_on_failure_fails_when_trace_is_truncated(self, tmp_path):
        """A clean prefix cannot pass when a frame cap omitted the rest."""
        config = _config(tmp_path, "example.blf", filter={"max_frames": 10})
        result = _run("-c", config, "--fail-on-failure")
        assert result.exit_code == 1
        assert "WARNING: stopped at the frame cap" in result.output

    def test_allow_truncated_is_explicit_gate_exception(self, tmp_path):
        """The truncation exception opts a capped trace back into the gate."""
        config = _config(tmp_path, "example.blf", filter={"max_frames": 10})
        result = _run("-c", config, "--fail-on-failure", "--allow-truncated")
        assert result.exit_code == 0, result.output

    def test_min_pass_rate_gate(self, tmp_path):
        """The percentage gate fails a broken trace and passes a clean one."""
        good = _config(tmp_path, "example.blf")
        assert _run("-c", good, "--min-pass-rate", "100").exit_code == 0
        bad = _config(tmp_path, "example_bad.blf")
        assert _run("-c", bad, "--min-pass-rate", "100").exit_code == 1

    def test_gate_fails_when_no_checks_were_performed(self, tmp_path):
        """An enabled gate fails closed for a report with no protection checks."""
        dbc = tmp_path / "empty.dbc"
        dbc.write_text('VERSION ""\nNS_ :\nBS_ :\nBU_: ECU\n', encoding="utf-8")
        trace = EXAMPLE / "trace" / "example.blf"
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(dbc), "--trace", str(trace),
            "--fail-on-failure",
        ])
        assert result.exit_code == 1, result.output

    def test_allow_empty_is_explicit_gate_exception(self, tmp_path):
        """The empty-result exception preserves an explicitly requested run."""
        dbc = tmp_path / "empty.dbc"
        dbc.write_text('VERSION ""\nNS_ :\nBS_ :\nBU_: ECU\n', encoding="utf-8")
        trace = EXAMPLE / "trace" / "example.blf"
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(dbc), "--trace", str(trace),
            "--fail-on-failure", "--allow-empty",
        ])
        assert result.exit_code == 0, result.output

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


class TestVerifyOutput:
    """The direct CLI supports clean machine-readable JSON output."""

    def test_json_stdout_is_one_document(self):
        """Verbose JSON output on stdout remains one parseable document."""
        result = _separated_runner().invoke(cli, [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
            "--algo", "CRC8/SAE-J1850", "--max-frames", "10",
            "--output", "json", "-v",
        ])
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["schema_version"] == 1
        assert document["summary"]["checks"] > 0
        assert "CRC Algorithm:" in result.stderr

    def test_json_only_failures_filters_details_but_keeps_counts(self, tmp_path):
        """JSON failure-only output omits passes without altering sample totals."""
        config = _config(
            tmp_path, "example.blf",
            output={"format": "json", "only_failures": True},
        )
        result = _run("-c", config)
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)["reports"][0]
        assert report["verdicts"] == []
        assert report["summary"]["checks"] > 0
        assert report["summary"]["passed"] == report["summary"]["checks"]

    def test_json_file_receives_document(self, tmp_path):
        """The JSON-file option writes one document and leaves stdout empty."""
        output = tmp_path / "result.json"
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
            "--algo", "CRC8/SAE-J1850", "--max-frames", "10",
            "--output", "json", "--json-file", str(output),
        ])
        assert result.exit_code == 0, result.output
        assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1
        assert result.output == ""

    def test_json_file_rejects_non_json_output(self):
        """The JSON file option requires JSON output mode."""
        result = CliRunner().invoke(cli, [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
            "--json-file", "out.json",
        ])
        assert result.exit_code == 2
        assert "requires --output json" in result.output

    def test_range_bounds_require_nonnegative_start_and_exclusive_end(self):
        """Reject invalid byte bounds and empty/reversed custom intervals."""
        base = [
            "verify", "--dbc", str(EXAMPLE / "dbc"),
            "--trace", str(EXAMPLE / "trace" / "example.blf"),
        ]
        for extra in (("--range", "custom_range", "--range-start", "-1"),
                      ("--range", "custom_range", "--range-end", "-2"),
                      ("--range", "custom_range", "--range-start", "5",
                       "--range-end", "3"),
                      ("--range", "custom_range", "--range-start", "3",
                       "--range-end", "3")):
            result = CliRunner().invoke(cli, [*base, *extra])
            assert result.exit_code == 2
            assert "must be" in result.output


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

    def test_preprocess_corrupt_workbook_is_a_usage_error(self, tmp_path):
        """Invalid Excel archives fail cleanly rather than leaking tracebacks."""
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not a zip file")
        result = CliRunner().invoke(cli, [
            "preprocess-dataid", "--xlsx", str(bad), "-o", str(tmp_path / "out.json")
        ])
        assert result.exit_code == 2
        assert "Traceback" not in result.output

    def test_version_flag(self):
        """The CLI exposes the package version."""
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output


class TestInspect:
    """inspect accepts what verify's --dbc accepts (file or directory)."""

    def test_inspect_single_file(self):
        """A single DBC prints its protection signals."""
        result = CliRunner().invoke(
            cli, ["inspect", str(EXAMPLE / "dbc" / "network.dbc")])
        assert result.exit_code == 0, result.output
        assert "Checksum:" in result.output

    def test_inspect_directory(self):
        """A directory is expanded to its *.dbc files (same rule as verify)."""
        result = CliRunner().invoke(cli, ["inspect", str(EXAMPLE / "dbc")])
        assert result.exit_code == 0, result.output
        assert "network.dbc" in result.output
        assert "Checksum:" in result.output
