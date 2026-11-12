"""Tests for the web version: project catalog, runner sharing, API endpoints.

The API tests use the synthetic project under ``examples/example`` so the whole
path (upload → run → serialise → report) is exercised end to end.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import crc_checker.report.html as html_mod
from crc_checker.config import DEFAULT_MAX_FRAMES, load_config
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.protect.rolling_counter import RollingCounterVerifier
from crc_checker.trace.models import CanFrame
from crc_checker.verify.engine import VerifyEngine
from crc_checker.verify.models import VerifyReport, VerifyVerdict
from crc_checker.verify.runner import RunnerError, build_protection_map, run_config
from webapp.catalog import get_project, scan_projects
from webapp.main import (UPLOADS_DIR, MAX_DBC_UPLOADS, create_app,
                         max_upload_bytes, safe_filename)
from webapp.service import (RunStore, RunOutcome, report_to_dict,
                            resolve_max_frames)
from webapp.version import DeploymentVersion, read_revision

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "examples" / "example"
EXAMPLE_TRACE = EXAMPLE_DIR / "trace" / "example.blf"
BAD_TRACE = EXAMPLE_DIR / "trace" / "example_bad.blf"
EXAMPLE_PROJECT = "examples/example"


@pytest.fixture(autouse=True)
def isolate_projects_root(monkeypatch):
    """Scan examples/ so a local projects/ directory cannot change the results.

    projects/ holds customer data and is not part of the repository; without
    this override, adding one locally makes the catalog tests (and every test
    that looks up ``examples/example``) depend on the developer's machine.
    """
    monkeypatch.setenv("CRC_CHECKER_PROJECTS_DIR", str(REPO_ROOT / "examples"))


@pytest.fixture(name="client")
def client_fixture(tmp_path):
    """API client backed by a throwaway run store (no writes into data/)."""
    return TestClient(create_app(store=RunStore(tmp_path / "runs", max_runs=3)))


# ---------------------------------------------------------------------------
# Project catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    """Project directory scanning."""

    def test_finds_shipped_projects(self):
        """The shipped example project is listed."""
        projects = scan_projects()
        ids = {p.id for p in projects}
        assert EXAMPLE_PROJECT in ids
        assert len(ids) >= 1

    def test_skips_directories_without_config(self, tmp_path):
        """Directories without a config are not runnable projects."""
        (tmp_path / "oem" / "empty").mkdir(parents=True)
        (tmp_path / "oem" / "real").mkdir(parents=True)
        (tmp_path / "oem" / "real" / "config.json").write_text(
            json.dumps({"dbc": "dbc", "traces": ["trace"]}), encoding="utf-8")
        assert [p.id for p in scan_projects(tmp_path)] == ["oem/real"]

    def test_summary_does_not_leak_paths(self):
        """The picker payload carries names only, never paths."""
        project = get_project(EXAMPLE_PROJECT)
        assert project is not None
        summary = project.to_dict()["summary"]
        assert summary["crc"] == "CRC8/SAE-J1850 (from DBC comments)"
        # The DataID label names the file actually loaded (the JSON fast path).
        assert summary["dataid"] == "dataid.json / hi_lo_two_cols / prepend"
        # Only file names leave the server, never filesystem paths.
        blob = json.dumps(project.to_dict(), ensure_ascii=False)
        assert str(REPO_ROOT) not in blob

    def test_get_project_unknown(self):
        """Unknown ids resolve to None (API turns that into 404)."""
        assert get_project("nope/nothing") is None

    def test_dbc_files_and_traces_listed(self):
        """DBC and sample trace names come from the project dir."""
        project = get_project(EXAMPLE_PROJECT)
        assert project is not None
        assert project.dbc_files == ["network.dbc"]
        assert "example.blf" in project.sample_traces


# ---------------------------------------------------------------------------
# Deployment version (commit node)
# ---------------------------------------------------------------------------

class TestVersion:
    """Running commit vs. deploy-directory commit."""

    def test_read_revision_without_git(self, tmp_path):
        """No .git means all fields unknown, not an exception."""
        assert read_revision(tmp_path) == {
            "commit": None, "branch": None, "subject": None,
            "committed_at": None, "dirty": None,
        }

    def test_read_revision_of_this_repo(self):
        """The repository itself yields a full SHA and branch."""
        revision = read_revision(REPO_ROOT)
        assert revision["commit"] and len(revision["commit"]) == 40
        assert revision["branch"]
        assert isinstance(revision["dirty"], bool)

    def test_read_revision_survives_non_ascii_subject(self, tmp_path, monkeypatch):
        """A Chinese commit subject must not break decoding (locale is GBK here)."""
        if not shutil.which("git"):
            pytest.skip("git not available")
        # Under the pre-push hook GIT_DIR / GIT_WORK_TREE are inherited and
        # would redirect both the subprocesses and read_revision() at the
        # outer repository instead of the temporary one.
        for key in [k for k in os.environ if k.startswith("GIT_")]:
            monkeypatch.delenv(key)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "修复:CRC 校验中文标题"],
                       cwd=tmp_path, check=True, env=env)
        revision = read_revision(tmp_path)
        assert revision["commit"] and len(revision["commit"]) == 40
        assert "修复" in revision["subject"]

    def test_info_shape(self):
        """The /api/version payload keeps its contract (no server paths)."""
        info = DeploymentVersion(REPO_ROOT).info()
        assert set(info) == {"running", "checkout", "checkout_changed",
                             "started_at"}
        assert "path" not in info
        assert set(info["running"]) == {"commit", "branch", "subject",
                                        "committed_at", "dirty"}
        assert info["started_at"].endswith("+00:00")

    def test_unknown_checkout_is_none_not_false(self, tmp_path):
        """No .git -> "version unknown": checkout_changed must be JSON null, not false."""
        info = DeploymentVersion(tmp_path).info()
        assert info["running"]["commit"] is None
        assert info["checkout_changed"] is None


# ---------------------------------------------------------------------------
# Shared runner (the code path the CLI also uses)
# ---------------------------------------------------------------------------

class TestRunner:
    """build_protection_map / run_config on shipped customer configs."""

    def test_run_config_produces_report(self):
        """A shipped project config verifies a shipped trace."""
        cfg = load_config(str(EXAMPLE_DIR / "config.json"))
        cfg.max_frames = 200
        setup, reports = run_config(cfg, [str(EXAMPLE_TRACE)])
        assert len(reports) == 1
        assert reports[0].total_verdicts > 0
        assert reports[0].dbc_paths
        assert any(note.startswith("Using DBC") for note in setup.notes)

    def test_missing_dbc_raises_runner_error(self, tmp_path):
        """A missing DBC path surfaces as RunnerError, not FileNotFoundError."""
        cfg = load_config(str(EXAMPLE_DIR / "config.json"))
        cfg.dbc = str(tmp_path / "gone")
        cfg.dbcs = []
        with pytest.raises(RunnerError):
            build_protection_map(cfg)

    def test_auto_classify_fallback_algorithm(self):
        """A config with auto_classify but no preset gets a fallback algorithm."""
        cfg = load_config(str(EXAMPLE_DIR / "config.json"))
        cfg.crc_preset = ""
        setup, _ = run_config(cfg, [str(EXAMPLE_TRACE)])
        assert cfg.crc_preset == "CRC8/SAE-J1850"
        assert setup.counts["auto_classify"] >= 0

    def test_max_frames_is_exact(self):
        """max_frames caps the run exactly, even when frames carry no protection."""
        cfg = load_config(str(EXAMPLE_DIR / "config.json"))
        cfg.max_frames = 50
        _, reports = run_config(cfg, [str(EXAMPLE_TRACE)])
        assert reports[0].total_frames == 50


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

class TestServiceHelpers:
    """Small pure helpers used by the API layer."""

    def test_safe_filename_strips_paths(self):
        """Upload names are reduced to a safe basename."""
        assert safe_filename("../../etc/passwd") == "passwd"
        assert safe_filename("C:\\logs\\trace.blf") == "trace.blf"
        assert safe_filename("") == "trace.blf"
        assert safe_filename("T1L-FL1 状态检查.blf") == "T1L-FL1 状态检查.blf"

    def test_resolve_max_frames(self):
        """None = config default (fallback 6000), 0 = unlimited, >0 = explicit cap."""
        assert resolve_max_frames(None, 2000) == 2000     # config default
        assert resolve_max_frames(500, 2000) == 500       # explicit override
        assert resolve_max_frames(0, 2000) is None        # unlimited
        assert resolve_max_frames(None, None) == DEFAULT_MAX_FRAMES  # default frame cap

    def test_run_store_evicts_oldest(self, tmp_path):
        """Only the newest runs stay downloadable."""
        store = RunStore(tmp_path, max_runs=2)
        for index in range(3):
            store.add(RunOutcome(run_id=f"r{index}", created_at=float(index),
                                 project_id="p", trace_name="t", payload={}))
        assert store.get("r0") is None
        assert store.get("r2") is not None

    def test_run_store_removes_split_parts_on_evict(self, tmp_path):
        """Evicting a run also removes its split parts (deleting only the
        main file would leave the parts on disk forever).
        """
        store = RunStore(tmp_path, max_runs=1)
        for part in ("r0.html", "r0_p2.html", "r0_p3.html"):
            (tmp_path / part).write_text("x", encoding="utf-8")
        store.add(RunOutcome(run_id="r0", created_at=0.0, project_id="p",
                             trace_name="t", payload={}, html_path=tmp_path / "r0.html"))
        store.add(RunOutcome(run_id="r1", created_at=1.0, project_id="p",
                             trace_name="t", payload={}))
        assert not list(tmp_path.glob("*.html"))

    def test_new_store_purges_stale_reports(self, tmp_path):
        """After a restart the run index is gone, but stale report files
        must still be purged (otherwise they pile up forever).
        """
        (tmp_path / "old.html").write_text("x", encoding="utf-8")
        (tmp_path / "old_p2.html").write_text("x", encoding="utf-8")
        RunStore(tmp_path)
        assert not list(tmp_path.glob("*.html"))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class TestApi:
    """Endpoints served to the Vue frontend."""

    def test_projects_endpoint(self, client):
        """GET /api/projects returns the scanned projects."""
        body = client.get("/api/projects").json()
        assert body["count"] == len(body["projects"])
        assert {"id", "oem", "model", "dbc_files", "summary"} <= set(body["projects"][0])

    def test_version_endpoint_is_not_cached(self, client):
        """GET /api/version is always re-read by the browser."""
        response = client.get("/api/version")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "running" in response.json()

    def test_verify_all_pass(self, client):
        """A trace with no mismatches reports 100% and a report link."""
        with open(EXAMPLE_TRACE, "rb") as handle:
            response = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "1500",
            }, files={"file": (EXAMPLE_TRACE.name, handle)})
        assert response.status_code == 200, response.text
        body = response.json()
        report = body["reports"][0]
        assert report["total_frames"] > 0
        assert report["fail_count"] == 0
        assert report["pass_rate"] == 1.0
        assert body["report_url"].endswith("/report.html")

    def test_verify_reports_failures(self, client):
        """The deliberately corrupted trace exercises failure serialisation."""
        with open(BAD_TRACE, "rb") as handle:
            response = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "500",
            }, files={"file": (BAD_TRACE.name, handle)})
        assert response.status_code == 200, response.text
        report = response.json()["reports"][0]
        assert report["fail_count"] > 0
        first = report["failures"][0]
        assert {"frame_id_hex", "signal", "expected_hex", "actual_hex", "detail"} <= set(first)
        assert report["frames"][0]["fail"] >= report["frames"][-1]["fail"]

    def test_verify_includes_rc_trends(self, client):
        """rc_trends carries bounded per-signal series for the results-view charts."""
        with open(BAD_TRACE, "rb") as handle:
            response = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "500",
            }, files={"file": (BAD_TRACE.name, handle)})
        assert response.status_code == 200, response.text
        trends = response.json()["reports"][0]["rc_trends"]
        assert trends, "expected RC trend data for the example trace"
        first = trends[0]
        assert {"signal", "frame_id_hex", "channel", "bit_max", "max_valid",
                "samples", "errors", "episodes", "t0", "tspan", "points"} <= set(first)
        # Same accounting as frame counts: episodes <= frames, and every
        # error point belongs to at least one episode.
        assert all(t["episodes"] <= t["errors"] for t in trends)
        assert all(t["errors"] == 0 or t["episodes"] >= 1 for t in trends)
        # signals with errors first: once a clean signal appears, none follows with errors
        error_flags = [t["errors"] > 0 for t in trends]
        assert not any(error_flags[i] and not error_flags[i - 1]
                       for i in range(1, len(error_flags)))
        points = first["points"]
        assert points == sorted(points, key=lambda p: p[0])
        assert all(p[2] in (0, 1) and (p[2] == 0 or p[3]) for p in points)

    def test_report_download_and_cache(self, client, tmp_path):
        """The HTML report is downloadable; unknown runs 404."""
        with open(EXAMPLE_TRACE, "rb") as handle:
            body = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "300",
            }, files={"file": (EXAMPLE_TRACE.name, handle)}).json()
        report = client.get(body["report_url"])
        assert report.status_code == 200
        assert "CAN CRC Check Report" in report.text
        assert client.get("/api/runs/does-not-exist/report.html").status_code == 404
        # One sub-directory per run: the main file goes to runs/<run_id>/<run_id>.html
        run_id = body["run_id"]
        main = tmp_path / "runs" / run_id / f"{run_id}.html"
        assert main.is_file()
        assert not (tmp_path / "runs" / f"{run_id}.html").exists()

    def test_report_split_parts_served(self, client, monkeypatch):
        """Over-limit reports are split: the main file carries a nav bar,
        part URLs are downloadable, unknown parts 404.
        """
        monkeypatch.setattr(html_mod, "SPLIT_MAX_SECTIONS", 100)
        with open(EXAMPLE_TRACE, "rb") as handle:
            body = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "300",
            }, files={"file": (EXAMPLE_TRACE.name, handle)}).json()
        run_id = body["run_id"]
        main = client.get(body["report_url"])
        assert main.status_code == 200
        assert "page-nav" in main.text  # split notice + prev/next page links
        assert f'href="{run_id}_p2.html"' in main.text
        # The nav's relative link resolves to the part route and works.
        part = client.get(f"/api/runs/{run_id}/{run_id}_p2.html")
        assert part.status_code == 200
        assert "page-nav" in part.text
        # Unknown part names (traversal / made-up) are rejected.
        assert client.get(f"/api/runs/{run_id}/{run_id}_p9.html").status_code == 404
        assert client.get(f"/api/runs/{run_id}/..%2F..%2Fetc.html").status_code == 404
        # Parts of another run must not be reachable via this run's URL (directory isolation)
        assert client.get(f"/api/runs/{run_id}/otherrun_p2.html").status_code == 404

    def test_verify_unknown_project(self, client):
        """An unknown project id is rejected with 404."""
        response = client.post("/api/verify", data={"project_id": "nope/none"},
                               files={"file": ("t.blf", b"x")})
        assert response.status_code == 404

    def test_verify_rejects_empty_file(self, client):
        """An empty upload is rejected before any parsing."""
        response = client.post("/api/verify", data={"project_id": EXAMPLE_PROJECT},
                               files={"file": ("t.blf", b"")})
        assert response.status_code == 400
        assert "空" in response.json()["detail"]

    def test_verify_rejects_bad_frame_limit(self, client):
        """A non-numeric frame limit is a 400, not a 500."""
        response = client.post("/api/verify",
                               data={"project_id": EXAMPLE_PROJECT, "max_frames": "abc"},
                               files={"file": ("t.blf", b"x")})
        assert response.status_code == 400

    def test_verify_rejects_oversized_upload(self, client, monkeypatch):
        """The upload cap is enforced while streaming."""
        monkeypatch.setenv("CRC_WEB_MAX_UPLOAD_MB", "1")
        payload = b"\0" * (2 * 1024 * 1024)
        response = client.post("/api/verify", data={"project_id": EXAMPLE_PROJECT},
                               files={"file": ("big.blf", payload)})
        assert response.status_code == 413

    def test_upload_is_deleted_after_run(self, client):
        """The temp trace must not survive the request."""
        with open(EXAMPLE_TRACE, "rb") as handle:
            client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "200",
            }, files={"file": (EXAMPLE_TRACE.name, handle)})
        uploads = REPO_ROOT / "data" / "web" / "uploads"
        assert not uploads.exists() or not any(uploads.iterdir())


class TestFrameAccounting:
    """Message summaries are counted per frame, not per folded verdict."""

    @staticmethod
    def _report(values: list[int]) -> object:
        """One 4-bit RC group (max_valid 14); failing frames fold into one verdict."""
        protection = MessageProtection(
            frame_id=0x421, frame_name="MsgX", dlc=8,
            checksum_signal=None,
            rolling_counter_signal=SignalInfo("MsgX_Counter", 56, 4,
                                              "little_endian"),
            rc_max_valid=14)
        pm = DBCProtectionMap()
        pm.messages[0x421] = [protection]
        engine = VerifyEngine(pm, [RollingCounterVerifier()])

        class Reader:  # pylint: disable=too-few-public-methods
            """Minimal TraceReader stand-in over in-memory frames."""
            file_path = "mem"

            def frames(self):
                """Yield the scripted frames, one per value."""
                for index, value in enumerate(values):
                    data = bytes(7) + bytes([value & 0x0F])
                    yield CanFrame(timestamp=float(index), arbitration_id=0x421,
                                   dlc=8, data=data, channel=0)

        return engine.run(Reader())

    def test_folded_frames_still_count_as_frames(self):
        """0,1,2,2,2 -> 5 frames / 3 pass / 2 fail (only one verdict, x2)."""
        report = self._report([0, 1, 2, 2, 2])
        assert report.fail_count == 1            # folded into one episode
        payload = report_to_dict(report)
        row = payload["frames"][0]
        assert (row["total"], row["pass"], row["fail"]) == (5, 3, 2)
        signal = row["signals"][0]
        assert (signal["total"], signal["pass"], signal["fail"]) == (5, 3, 2)
        assert signal["last_detail"].startswith("STALE")

    def test_check_totals_are_sample_based(self):
        """Card accounting: checks/failures count per frame sample, not per folded verdict."""
        payload = report_to_dict(self._report([0, 1, 2, 2, 2]))
        assert payload["check_total"] == 5
        assert payload["check_pass"] == 3
        assert payload["check_fail"] == 2
        assert payload["rc_pass"] == 3 and payload["rc_total"] == 5

    def test_same_id_on_two_channels_stays_separate(self):
        """A gateway trace carries the same CAN ID on two buses."""
        report = VerifyReport()
        for channel in (0, 1):
            report.verdicts.append(VerifyVerdict(
                frame_id=0x100, timestamp=1.0, algorithm="crc",
                signal_name="M_CRC", expected_value=0, actual_value=0,
                is_pass=True, channel=channel))
        payload = report_to_dict(report)
        assert len(payload["frames"]) == 2
        assert {frame["channel"] for frame in payload["frames"]} == {0, 1}

    def test_trace_truncation_is_serialised(self):
        """The web result can warn that the frame cap cut the trace."""
        report = VerifyReport(frames_truncated=True, frame_limit=10)
        payload = report_to_dict(report)
        assert payload["trace_truncated"] is True
        assert payload["trace_frame_limit"] == 10


class TestSampleTraceApi:
    """The project's own trace verifies directly — no download-then-upload round trip."""

    def test_sample_trace_runs_without_upload(self, client):
        """The catalog's sample trace name is enough."""
        response = client.post("/api/verify-sample", data={
            "project_id": EXAMPLE_PROJECT,
            "trace_name": "example.blf",
            "max_frames": "100",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["trace_name"] == "example.blf"
        assert body["reports"][0]["total_frames"] == 100
        assert body["report_url"].endswith("/report.html")

    def test_sample_trace_rejects_unknown_name(self, client):
        """Only names listed by the catalog are accepted — no path injection."""
        response = client.post("/api/verify-sample", data={
            "project_id": EXAMPLE_PROJECT,
            "trace_name": "../config.json",
        })
        assert response.status_code == 404


class TestStartupLogging:
    """uvicorn startup banner filter: 0.0.0.0 is not a reachable address, so not printed."""

    @staticmethod
    def _banner(host):
        """Build a uvicorn "Uvicorn running on ..." log record."""
        return logging.LogRecord(
            "uvicorn.error", logging.INFO, __file__, 1,
            "Uvicorn running on %s (Press CTRL+C to quit)",
            (f"http://{host}:8000",), None)

    def test_bind_any_banner_is_dropped(self):
        """When listening on 0.0.0.0, the misleading banner line is filtered out."""
        logger = logging.getLogger("uvicorn.error")
        assert logger.filter(self._banner("0.0.0.0")) is False

    def test_other_banners_and_logs_pass(self):
        """Banners with a concrete address and normal log records are unaffected."""
        logger = logging.getLogger("uvicorn.error")
        # Logger.filter() returns the LogRecord on Python 3.12+ and True on
        # older versions; only "not filtered" is part of the contract.
        assert logger.filter(self._banner("127.0.0.1"))
        record = logging.LogRecord(
            "uvicorn.error", logging.INFO, __file__, 2,
            "Application startup complete.", None, None)
        assert logger.filter(record)


class TestManualApi:
    """Manual upload mode: DBC + trace + a page-filled config."""
    @staticmethod
    def _post(client, config, trace=EXAMPLE_TRACE, dataid=None):
        dbc_path = EXAMPLE_DIR / "dbc" / "network.dbc"
        files = [("dbcs", (dbc_path.name, dbc_path.read_bytes())),
                 ("trace", (trace.name, trace.read_bytes()))]
        if dataid is not None:
            files.append(("dataid", (dataid.name, dataid.read_bytes())))
        return client.post("/api/verify-manual",
                           data={"config": json.dumps(config)},
                           files=files)

    def test_presets_endpoint(self, client):
        """GET /api/presets lists built-in algorithms with validation status."""
        body = client.get("/api/presets").json()
        names = {item["name"] for item in body["presets"]}
        assert "CRC8/SAE-J1850-ZERO" in names
        item = next(p for p in body["presets"] if p["name"] == "CRC8/SAE-J1850-ZERO")
        assert item["width"] == 8
        assert item["validated"] is True

    def test_manual_verify_with_preset_and_dataid(self, client):
        """Uploaded DBC + trace + DataID run through the shared runner."""
        config = {
            "crc": {"preset": "CRC8/SAE-J1850", "auto_classify": True,
                    "profile_by_width": True},
            "range": {"mode": "exclude_crc"},
            "dataid": {"position": "prepend", "byte_order": "lo_hi",
                       "mapping": "hi_lo_two_cols"},
            "filter": {"max_frames": 1500},
        }
        response = self._post(client, config, dataid=EXAMPLE_DIR / "dbc" / "dataid.json")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["project_id"] == "manual"
        assert body["project"]["name"] == "手动配置"
        assert body["setup"]["dbc_names"] == ["network.dbc"]
        assert body["setup"]["dataid_entries"] > 0
        assert body["reports"][0]["total_frames"] > 0

    def test_manual_rejects_browser_paths(self, client):
        """Path fields only come from uploads; hand-written config traces are rejected."""
        response = self._post(client, {"traces": ["C:/secret.blf"]})
        assert response.status_code == 400
        assert "traces" in response.json()["detail"]

    def test_manual_rejects_wrong_upload_type(self, client):
        """DBC upload slots must be .dbc files."""
        response = client.post("/api/verify-manual", data={"config": "{}"},
                               files=[("dbcs", ("network.txt", b"x")),
                                      ("trace", (EXAMPLE_TRACE.name,
                                                 EXAMPLE_TRACE.read_bytes()))])
        assert response.status_code == 400
        assert "network.txt" in response.json()["detail"]

    def test_manual_rejects_too_many_dbcs(self, client):
        """The server enforces the same 10-DBC cap as the page."""
        dbc_bytes = (EXAMPLE_DIR / "dbc" / "network.dbc").read_bytes()
        files = [("dbcs", (f"n{i}.dbc", dbc_bytes)) for i in range(11)]
        files.append(("trace", (EXAMPLE_TRACE.name, EXAMPLE_TRACE.read_bytes())))
        response = client.post("/api/verify-manual", data={"config": "{}"},
                               files=files)
        assert response.status_code == 400
        assert "最多" in response.json()["detail"]

    def test_manual_does_not_leak_uploads(self, client):
        """The run's upload directory is deleted afterwards (the report
        lives in the RunStore's own directory).
        """
        response = self._post(client, {"filter": {"max_frames": 100}})
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        assert not (UPLOADS_DIR / run_id).exists()


# ---------------------------------------------------------------------------
# Server limits + hardening
# ---------------------------------------------------------------------------

class TestLimitsEndpoint:
    """GET /api/limits — the page must follow the server's caps, not hardcode them."""

    def test_limits_exposed(self, client):
        """The payload carries upload cap, DBC limit and the frame default."""
        body = client.get("/api/limits").json()
        assert body["max_upload_mb"] == max_upload_bytes() // (1024 * 1024)
        assert body["max_dbc_files"] == MAX_DBC_UPLOADS
        assert body["manual_default_frames"] == DEFAULT_MAX_FRAMES

    def test_upload_cap_override_is_visible(self, client, monkeypatch):
        """Changing the cap via the env var changes what the API reports."""
        monkeypatch.setenv("CRC_WEB_MAX_UPLOAD_MB", "7")
        assert client.get("/api/limits").json()["max_upload_mb"] == 7

    def test_upload_cap_falls_back_on_garbage(self, client, monkeypatch):
        """A non-numeric env override falls back to the default, not an error."""
        monkeypatch.setenv("CRC_WEB_MAX_UPLOAD_MB", "not-a-number")
        body = client.get("/api/limits").json()
        assert body["max_upload_mb"] == max_upload_bytes() // (1024 * 1024)


class TestCatalogCache:
    """scan_projects caches per stat signature — freshness must survive it."""

    @staticmethod
    def _make_project(root: Path, group: str, name: str) -> None:
        target = root / group / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}", encoding="utf-8")

    def test_new_project_is_seen_after_cached_scan(self, tmp_path):
        """A project created after a cached scan is picked up."""
        self._make_project(tmp_path, "oem", "a")
        assert [p.id for p in scan_projects(tmp_path)] == ["oem/a"]
        self._make_project(tmp_path, "oem", "b")
        assert [p.id for p in scan_projects(tmp_path)] == ["oem/a", "oem/b"]

    def test_removed_project_disappears_after_cached_scan(self, tmp_path):
        """Deleting a project's config drops it from the next scan."""
        self._make_project(tmp_path, "oem", "a")
        assert len(scan_projects(tmp_path)) == 1
        (tmp_path / "oem" / "a" / "config.json").unlink()
        assert scan_projects(tmp_path) == []

    def test_edited_config_changes_the_summary(self, tmp_path):
        """A config edit (in-place, no create/delete) invalidates the summary."""
        self._make_project(tmp_path, "oem", "a")
        config = tmp_path / "oem" / "a" / "config.json"
        assert scan_projects(tmp_path)[0].summary["crc"] == "RC only"
        content = '{"crc": {"preset": "CRC8/AUTOSAR"}}'
        config.write_text(content, encoding="utf-8")
        # Windows can stamp two writes within one timer tick (~15ms) with the
        # same mtime; nudge it so the test exercises the signature logic, not
        # clock granularity.
        stamp = config.stat().st_mtime_ns + 10 ** 9
        os.utime(config, ns=(stamp, stamp))
        assert scan_projects(tmp_path)[0].summary["crc"] == "CRC8/AUTOSAR"


class TestUnhandledErrors:  # pylint: disable=too-few-public-methods
    """The 500 fallback: like the CLI, a traceback never reaches the client."""

    def test_unexpected_error_is_a_json_500(self, tmp_path, monkeypatch):
        """An error outside the expected set is a generic JSON 500, no internals."""

        def explode(*_args, **_kwargs):
            raise RuntimeError("boom in C:\\secret\\path.blf")

        monkeypatch.setattr("webapp.main.run_project", explode)
        client = TestClient(
            create_app(store=RunStore(tmp_path / "runs", max_runs=1)),
            raise_server_exceptions=False)
        response = client.post(
            "/api/verify",
            data={"project_id": EXAMPLE_PROJECT},
            files={"file": ("trace.blf", EXAMPLE_TRACE.read_bytes())},
        )
        assert response.status_code == 500
        message = response.json()["message"]
        assert "服务器内部错误" in message
        # No internals leak: not the exception text, not the filesystem.
        assert "boom" not in message and "secret" not in message


class TestRunStoreConcurrency:
    """add/get/sweep run in the threadpool — the store must stay consistent."""

    def test_concurrent_adds_respect_max_runs(self, tmp_path):
        """Parallel adds never exceed max_runs and stay readable afterwards."""
        store = RunStore(tmp_path / "runs", max_runs=5)
        outcomes = [RunOutcome(run_id=f"r{i}", created_at=float(i),
                               project_id="p", trace_name="t.blf", payload={})
                    for i in range(40)]

        def add_all() -> None:
            for outcome in outcomes:
                store.add(outcome)

        threads = [threading.Thread(target=add_all) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(store) <= 5
        for run_id in list(store._runs):  # pylint: disable=protected-access
            assert store.get(run_id) is not None

    def test_concurrent_gets_and_sweeps_are_safe(self, tmp_path):
        """Readers racing the evictor never see a broken store."""
        store = RunStore(tmp_path / "runs", max_runs=2)
        for i in range(3):
            store.add(RunOutcome(run_id=f"r{i}", created_at=float(i),
                                 project_id="p", trace_name="t.blf", payload={}))

        def churn() -> None:
            for i in range(20):
                store.get(f"r{i}")   # may or may not exist — either is fine
                store.sweep()

        threads = [threading.Thread(target=churn) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(store) <= 2
