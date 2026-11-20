"""Tests for RunConfig JSON loading (crc.overrides, dbc_merge)."""

import json
from pathlib import Path

import pytest

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


class TestLoadConfigTypeValidation:
    """Wrongly typed nested options fail at load time, not mid-run."""

    @pytest.mark.parametrize("crc, needle", [
        ({"profiles": [1]}, "crc.profiles"),
        ({"skip": 5}, "crc.skip"),
        ({"overrides": ["SUM8"]}, "crc.overrides"),
        ({"range_overrides": ["x"]}, "crc.range_overrides"),
        ({"profile_by_width": "yes"}, "crc.profile_by_width"),
    ])
    def test_crc_section_types(self, tmp_path, crc, needle):
        """CRC sub-sections reject wrong types with the offending key named."""
        path = _write_config(tmp_path, {
            "dbc": "x.dbc", "traces": ["t.blf"], "crc": crc,
        })
        with pytest.raises(ValueError, match=needle):
            load_config(path)

    @pytest.mark.parametrize("section, needle", [
        ({"filter": {"frame_ids": "0x143"}}, "filter.frame_ids"),
        ({"filter": {"frame_ids": ["nope"]}}, "filter.frame_ids"),
        ({"signals": {"patterns_file": 3}}, "signals.patterns_file"),
        ({"output": {"only_failures": "true"}}, "output.only_failures"),
        ({"dataid": {"mapping": [1]}}, "dataid.mapping"),
        ({"dataid": {"default": 0x10000}}, "dataid.default"),
    ])
    def test_other_section_types(self, tmp_path, section, needle):
        """Filter/signals/output/dataid option types are checked at load time."""
        data = {"dbc": "x.dbc", "traces": ["t.blf"]}
        data.update(section)
        with pytest.raises(ValueError, match=needle):
            load_config(_write_config(tmp_path, data))


class TestCrcWidthWarning:  # pylint: disable=too-few-public-methods
    """A preset width that cannot match the DBC signal is reported up front."""

    def test_width_mismatch_warns(self):
        """An 8-bit preset against a 16-bit CRC signal produces a warning."""
        # pylint: disable=import-outside-toplevel
        from crc_checker.config import RunConfig, apply_crc_config
        from crc_checker.dbc.parser import parse_dbc

        dbc = str(Path(__file__).resolve().parent.parent
                  / "examples" / "example" / "dbc" / "network.dbc")
        map_ = parse_dbc(dbc)
        cfg = RunConfig(dbc=dbc, traces=["trace.blf"], crc_preset="CRC8/AUTOSAR")
        apply_crc_config(cfg, map_)
        # Beta_CRC is a 16-bit signal; the 8-bit preset can never match it.
        assert any("Beta_CRC" in warning and "16 bits" in warning
                   for warning in cfg.warnings)


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


class TestConfigValidation:
    """Misspelled keys warn; crash-prone values fail at load time."""

    def test_unknown_keys_are_reported(self, tmp_path):
        """A typo is surfaced instead of silently doing nothing."""
        path = _write_config(tmp_path, {
            "dbc": "dbc", "traces": ["t.blf"],
            "crc": {"presett": "CRC8/SAE-J1850"},
            "filtre": {},
        })
        warnings = load_config(path).warnings
        assert any("crc.presett" in w for w in warnings)
        assert any("filtre" in w for w in warnings)

    def test_comment_keys_do_not_warn(self, tmp_path):
        """``_comment``-style documentation keys are allowed."""
        path = _write_config(tmp_path, {
            "_comment": "doc", "dbc": "dbc", "traces": ["t.blf"],
            "crc": {"_comment": "doc", "preset": "CRC8/SAE-J1850"},
        })
        assert not load_config(path).warnings

    def test_max_frames_must_be_int(self, tmp_path):
        """A string would crash mid-run on ``frame_count >= max_frames``."""
        path = _write_config(tmp_path, {
            "dbc": "dbc", "traces": ["t.blf"],
            "filter": {"max_frames": "6000"},
        })
        with pytest.raises(ValueError, match="filter.max_frames"):
            load_config(path)

    def test_bad_dataid_position_is_rejected(self, tmp_path):
        """Anything but prepend/append used to silently mean prepend."""
        path = _write_config(tmp_path, {
            "dbc": "dbc", "traces": ["t.blf"],
            "dataid": {"position": "middle"},
        })
        with pytest.raises(ValueError, match="dataid.position"):
            load_config(path)

    def test_custom_crc_requires_width_and_poly(self, tmp_path):
        """Missing keys must not surface as a bare KeyError later."""
        path = _write_config(tmp_path, {
            "dbc": "dbc", "traces": ["t.blf"],
            "crc": {"custom": {"width": 8}},
        })
        with pytest.raises(ValueError, match="poly"):
            load_config(path)
