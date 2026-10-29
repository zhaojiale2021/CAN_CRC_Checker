"""Tests for RunConfig JSON loading (crc.overrides, dbc_merge)."""

import json

from crc_checker.config import load_config


def _write_config(tmp_path, data: dict) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestLoadConfigCrcOverrides:
    """crc.overrides: per-message algorithm overrides."""

    def test_overrides_parsed(self, tmp_path):
        """overrides map is parsed verbatim."""
        path = _write_config(tmp_path, {
            "dbc": "x.dbc",
            "traces": ["t.blf"],
            "crc": {
                "preset": "CRC8/SAE-J1850",
                "auto_classify": True,
                "overrides": {"0x287": "SUM8/XOR-FF", "Msg_9": "SUM8"},
            },
        })
        cfg = load_config(path)
        assert cfg.crc_overrides == {"0x287": "SUM8/XOR-FF", "Msg_9": "SUM8"}
        assert cfg.crc_auto_classify is True

    def test_overrides_default_empty(self, tmp_path):
        """Missing overrides key yields an empty dict (not None)."""
        path = _write_config(tmp_path, {
            "dbc": "x.dbc", "traces": ["t.blf"],
            "crc": {"preset": "CRC8/SAE-J1850"},
        })
        cfg = load_config(path)
        assert not cfg.crc_overrides

    def test_overrides_without_crc_section(self, tmp_path):
        """No crc section at all still yields an empty overrides dict."""
        path = _write_config(tmp_path, {"dbc": "x.dbc", "traces": ["t.blf"]})
        cfg = load_config(path)
        assert not cfg.crc_overrides


class TestLoadConfigDbcMerge:
    """dbc_merge: merge all DBCs into one map instead of per-channel selection."""

    def test_dbc_merge_true(self, tmp_path):
        """Top-level dbc_merge is parsed."""
        path = _write_config(tmp_path, {
            "dbc": "dbc", "dbc_merge": True, "traces": ["t.blf"],
        })
        assert load_config(path).dbc_merge is True

    def test_dbc_merge_default_false(self, tmp_path):
        """Omitted dbc_merge defaults to False (per-channel selection)."""
        path = _write_config(tmp_path, {"dbc": "dbc", "traces": ["t.blf"]})
        assert load_config(path).dbc_merge is False
