"""Tests for the web version: project catalog, runner sharing, API endpoints.

The API tests use the synthetic project under ``examples/example`` so the whole
path (upload → run → serialise → report) is exercised end to end.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import crc_checker.report.html as html_mod
from crc_checker.config import DEFAULT_MAX_FRAMES, load_config
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.protect.rolling_counter import RollingCounterVerifier
from crc_checker.trace.models import CanFrame
from crc_checker.verify.engine import VerifyEngine
from crc_checker.verify.runner import RunnerError, build_protection_map, run_config
from webapp.catalog import get_project, scan_projects
from webapp.main import create_app, safe_filename
from webapp.service import (RunStore, RunOutcome, report_to_dict,
                            resolve_max_frames)
from webapp.version import DeploymentVersion, read_revision

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "examples" / "example"
EXAMPLE_TRACE = EXAMPLE_DIR / "trace" / "example.blf"
BAD_TRACE = EXAMPLE_DIR / "trace" / "example_bad.blf"
EXAMPLE_PROJECT = "examples/example"


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
        assert resolve_max_frames(None, None) == DEFAULT_MAX_FRAMES  # 默认帧上限

    def test_run_store_evicts_oldest(self, tmp_path):
        """Only the newest runs stay downloadable."""
        store = RunStore(tmp_path, max_runs=2)
        for index in range(3):
            store.add(RunOutcome(run_id=f"r{index}", created_at=float(index),
                                 project_id="p", trace_name="t", payload={}))
        assert store.get("r0") is None
        assert store.get("r2") is not None

    def test_run_store_removes_split_parts_on_evict(self, tmp_path):
        """淘汰旧 run 时连分片一起删(只删主文件会把分片永久留在磁盘上)。"""
        store = RunStore(tmp_path, max_runs=1)
        for part in ("r0.html", "r0_p2.html", "r0_p3.html"):
            (tmp_path / part).write_text("x", encoding="utf-8")
        store.add(RunOutcome(run_id="r0", created_at=0.0, project_id="p",
                             trace_name="t", payload={}, html_path=tmp_path / "r0.html"))
        store.add(RunOutcome(run_id="r1", created_at=1.0, project_id="p",
                             trace_name="t", payload={}))
        assert not list(tmp_path.glob("*.html"))

    def test_new_store_purges_stale_reports(self, tmp_path):
        """重启后 run 索引没了,旧报告文件也应清掉(否则无限攒)。"""
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
        # 段数与帧数同口径:段数 ≤ 帧数,且每个错误点至少属于一段
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
        # 每个 run 一份独立子目录:主文件写在 runs/<run_id>/<run_id>.html
        run_id = body["run_id"]
        main = tmp_path / "runs" / run_id / f"{run_id}.html"
        assert main.is_file()
        assert not (tmp_path / "runs" / f"{run_id}.html").exists()

    def test_report_split_parts_served(self, client, monkeypatch):
        """超上限报告拆分:主文件带导航条,分片 URL 可下载,未知分片 404。"""
        monkeypatch.setattr(html_mod, "SPLIT_MAX_SECTIONS", 100)
        with open(EXAMPLE_TRACE, "rb") as handle:
            body = client.post("/api/verify", data={
                "project_id": EXAMPLE_PROJECT, "max_frames": "300",
            }, files={"file": (EXAMPLE_TRACE.name, handle)}).json()
        run_id = body["run_id"]
        main = client.get(body["report_url"])
        assert main.status_code == 200
        assert "page-nav" in main.text  # 拆分提示 + 上一/下一页链接
        assert f'href="{run_id}_p2.html"' in main.text
        # The nav's relative link resolves to the part route and works.
        part = client.get(f"/api/runs/{run_id}/{run_id}_p2.html")
        assert part.status_code == 200
        assert "page-nav" in part.text
        # Unknown part names (traversal / made-up) are rejected.
        assert client.get(f"/api/runs/{run_id}/{run_id}_p9.html").status_code == 404
        assert client.get(f"/api/runs/{run_id}/..%2F..%2Fetc.html").status_code == 404
        # 别的 run 的分片名也不能借当前 run 的 URL 取到(目录隔离)
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
    """报文汇总按「帧」计,不按折叠后的 verdict 计。"""

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
        """0,1,2,2,2 → 5 帧 / 3 通过 / 2 失败(verdict 只有一条 ×2)。"""
        report = self._report([0, 1, 2, 2, 2])
        assert report.fail_count == 1            # 折叠成一条 episode
        payload = report_to_dict(report)
        row = payload["frames"][0]
        assert (row["total"], row["pass"], row["fail"]) == (5, 3, 2)
        signal = row["signals"][0]
        assert (signal["total"], signal["pass"], signal["fail"]) == (5, 3, 2)
        assert signal["last_detail"].startswith("STALE")

    def test_check_totals_are_sample_based(self):
        """卡片口径:校验项/失败也按帧采样,不按折叠 verdict。"""
        payload = report_to_dict(self._report([0, 1, 2, 2, 2]))
        assert payload["check_total"] == 5
        assert payload["check_pass"] == 3
        assert payload["check_fail"] == 2
        assert payload["rc_pass"] == 3 and payload["rc_total"] == 5
