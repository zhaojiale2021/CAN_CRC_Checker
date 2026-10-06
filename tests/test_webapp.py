"""Tests for the web version: project catalog, runner sharing, API endpoints.

The API tests use the trace files committed under ``customers/*/trace/`` so the
whole path (upload → run → serialise → report) is exercised for real.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crc_checker.config import load_config
from crc_checker.verify.runner import RunnerError, build_protection_map, run_config
from webapp.catalog import get_project, scan_projects
from webapp.main import create_app, safe_filename
from webapp.service import RunStore, RunOutcome, resolve_max_frames
from webapp.version import DeploymentVersion, read_revision

REPO_ROOT = Path(__file__).resolve().parent.parent
T1LFL1_TRACE = next((REPO_ROOT / "customers/chery/t1lfl1/trace").glob("*.blf"))
T1JFL3_TRACE = next((REPO_ROOT / "customers/chery/t1jfl3/trace").glob("*.blf"))
GWM_TRACE = next((REPO_ROOT / "customers/gwm/b06-5/trace").glob("*.blf"))


@pytest.fixture(name="client")
def client_fixture(tmp_path):
    """API client backed by a throwaway run store (no writes into data/)."""
    return TestClient(create_app(store=RunStore(tmp_path / "runs", max_runs=3)))


# ---------------------------------------------------------------------------
# Project catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    """customers/<oem>/<model>/config.json scanning."""

    def test_finds_shipped_projects(self):
        """Every customer directory with a config.json is listed."""
        projects = scan_projects()
        ids = {p.id for p in projects}
        assert "gac/eea40" in ids
        assert "baic/b81vs" in ids
        assert len(ids) >= 10

    def test_skips_directories_without_config(self, tmp_path):
        """Directories without a config are not runnable projects."""
        (tmp_path / "oem" / "empty").mkdir(parents=True)
        (tmp_path / "oem" / "real").mkdir(parents=True)
        (tmp_path / "oem" / "real" / "config.json").write_text(
            json.dumps({"dbc": "dbc", "traces": ["trace"]}), encoding="utf-8")
        assert [p.id for p in scan_projects(tmp_path)] == ["oem/real"]

    def test_summary_does_not_leak_paths(self):
        """The picker payload carries names only, never paths."""
        project = get_project("gac/eea40")
        assert project is not None
        summary = project.to_dict()["summary"]
        assert summary["crc"] == "按 CRC 位宽选 Profile(p01)"
        # The DataID label names the file actually loaded (the JSON fast path).
        assert summary["dataid"] == "dataid.json / gac_eea4 / append"
        # Only file names leave the server, never filesystem paths.
        blob = json.dumps(project.to_dict(), ensure_ascii=False)
        assert str(REPO_ROOT) not in blob

    def test_get_project_unknown(self):
        """Unknown ids resolve to None (API turns that into 404)."""
        assert get_project("nope/nothing") is None

    def test_dbc_files_and_traces_listed(self):
        """DBC and sample trace names come from the project dir."""
        project = get_project("cherry/t1jfl3".replace("cherry", "chery"))
        assert project is not None
        assert len(project.dbc_files) == 2
        assert project.sample_traces


# ---------------------------------------------------------------------------
# Deployment version (commit 节点)
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

    def test_read_revision_survives_non_ascii_subject(self, tmp_path):
        """A Chinese commit subject must not break decoding (locale is GBK here)."""
        if not shutil.which("git"):
            pytest.skip("git not available")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env={**os.environ, **env})
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, env={**os.environ, **env})
        subprocess.run(["git", "commit", "-q", "-m", "修复:CRC 校验中文标题"],
                       cwd=tmp_path, check=True, env={**os.environ, **env})
        revision = read_revision(tmp_path)
        assert revision["commit"] and len(revision["commit"]) == 40
        assert "修复" in revision["subject"]

    def test_info_shape(self):
        """The /api/version payload keeps its contract."""
        info = DeploymentVersion(REPO_ROOT).info()
        assert set(info) == {"running", "checkout", "checkout_changed",
                             "started_at", "path"}
        assert set(info["running"]) == {"commit", "branch", "subject",
                                        "committed_at", "dirty"}
        assert info["started_at"].endswith("+00:00")

    def test_unknown_checkout_is_none_not_false(self, tmp_path):
        """No .git -> "版本未知": checkout_changed must be JSON null, not false."""
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
        cfg = load_config(str(REPO_ROOT / "customers/chery/t1lfl1/config.json"))
        cfg.max_frames = 200
        setup, reports = run_config(cfg, [str(T1LFL1_TRACE)])
        assert len(reports) == 1
        assert reports[0].total_verdicts > 0
        assert reports[0].dbc_paths
        assert any(note.startswith("Merged 2 DBCs") for note in setup.notes)

    def test_missing_dbc_raises_runner_error(self, tmp_path):
        """A missing DBC path surfaces as RunnerError, not FileNotFoundError."""
        cfg = load_config(str(REPO_ROOT / "customers/gwm/b06-5/config.json"))
        cfg.dbc = str(tmp_path / "gone")
        cfg.dbcs = []
        with pytest.raises(RunnerError):
            build_protection_map(cfg)

    def test_auto_classify_fallback_algorithm(self):
        """fx12fl sets auto_classify without a preset: the runner supplies one."""
        cfg = load_config(str(REPO_ROOT / "customers/chery/fx12fl/config.json"))
        assert cfg.crc_preset == "CRC8/SAE-J1850"
        setup, _ = run_config(cfg, [str(T1LFL1_TRACE)])
        assert setup.counts["auto_classify"] >= 0

    def test_max_frames_is_exact(self):
        """max_frames caps the run exactly, even when frames carry no protection."""
        cfg = load_config(str(REPO_ROOT / "customers/chery/t1jfl3/config.json"))
        cfg.max_frames = 50
        _, reports = run_config(cfg, [str(T1JFL3_TRACE)])
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
        """None = config default, 0 = unlimited, >0 = explicit cap."""
        assert resolve_max_frames(None, 2000) == 2000     # config default
        assert resolve_max_frames(500, 2000) == 500       # explicit override
        assert resolve_max_frames(0, 2000) is None        # unlimited
        assert resolve_max_frames(None, None) is None

    def test_run_store_evicts_oldest(self, tmp_path):
        """Only the newest runs stay downloadable."""
        store = RunStore(tmp_path, max_runs=2)
        for index in range(3):
            store.add(RunOutcome(run_id=f"r{index}", created_at=float(index),
                                 project_id="p", trace_name="t", payload={}))
        assert store.get("r0") is None
        assert store.get("r2") is not None


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
        with open(T1LFL1_TRACE, "rb") as handle:
            response = client.post("/api/verify", data={
                "project_id": "chery/t1lfl1", "max_frames": "1500",
            }, files={"file": (T1LFL1_TRACE.name, handle)})
        assert response.status_code == 200, response.text
        body = response.json()
        report = body["reports"][0]
        assert report["total_frames"] > 0
        assert report["fail_count"] == 0
        assert report["pass_rate"] == 1.0
        assert body["report_url"].endswith("/report.html")

    def test_verify_reports_failures(self, client):
        """gwm/b06-5 is a known partial-pass project — exercises failure serialisation."""
        with open(GWM_TRACE, "rb") as handle:
            response = client.post("/api/verify", data={
                "project_id": "gwm/b06-5", "max_frames": "500",
            }, files={"file": (GWM_TRACE.name, handle)})
        assert response.status_code == 200, response.text
        report = response.json()["reports"][0]
        assert report["fail_count"] > 0
        first = report["failures"][0]
        assert {"frame_id_hex", "signal", "expected_hex", "actual_hex", "detail"} <= set(first)
        assert report["frames"][0]["fail"] >= report["frames"][-1]["fail"]

    def test_report_download_and_cache(self, client):
        """The HTML report is downloadable; unknown runs 404."""
        with open(T1LFL1_TRACE, "rb") as handle:
            body = client.post("/api/verify", data={
                "project_id": "chery/t1lfl1", "max_frames": "300",
            }, files={"file": (T1LFL1_TRACE.name, handle)}).json()
        report = client.get(body["report_url"])
        assert report.status_code == 200
        assert "CAN CRC Check Report" in report.text
        assert client.get("/api/runs/does-not-exist/report.html").status_code == 404

    def test_verify_unknown_project(self, client):
        """An unknown project id is rejected with 404."""
        response = client.post("/api/verify", data={"project_id": "nope/none"},
                               files={"file": ("t.blf", b"x")})
        assert response.status_code == 404

    def test_verify_rejects_empty_file(self, client):
        """An empty upload is rejected before any parsing."""
        response = client.post("/api/verify", data={"project_id": "chery/t1lfl1"},
                               files={"file": ("t.blf", b"")})
        assert response.status_code == 400
        assert "空" in response.json()["detail"]

    def test_verify_rejects_bad_frame_limit(self, client):
        """A non-numeric frame limit is a 400, not a 500."""
        response = client.post("/api/verify",
                               data={"project_id": "chery/t1lfl1", "max_frames": "abc"},
                               files={"file": ("t.blf", b"x")})
        assert response.status_code == 400

    def test_verify_rejects_oversized_upload(self, client, monkeypatch):
        """The upload cap is enforced while streaming."""
        monkeypatch.setenv("CRC_WEB_MAX_UPLOAD_MB", "1")
        payload = b"\0" * (2 * 1024 * 1024)
        response = client.post("/api/verify", data={"project_id": "chery/t1lfl1"},
                               files={"file": ("big.blf", payload)})
        assert response.status_code == 413

    def test_upload_is_deleted_after_run(self, client):
        """The temp trace must not survive the request."""
        with open(T1LFL1_TRACE, "rb") as handle:
            client.post("/api/verify", data={
                "project_id": "chery/t1lfl1", "max_frames": "200",
            }, files={"file": (T1LFL1_TRACE.name, handle)})
        uploads = REPO_ROOT / "data" / "web" / "uploads"
        assert not uploads.exists() or not any(uploads.iterdir())
