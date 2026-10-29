"""Tests for the configuration-driven layers: naming patterns, DataID mappings,
and preset validation status."""

from __future__ import annotations

import pytest

from crc_checker.config import RunConfig
from crc_checker.crc.presets import VALIDATED, UNVERIFIED, get_validation
from crc_checker.dataid.parser import (
    ColumnMapping,
    load_dataid_mappings,
    resolve_mapping,
)
from crc_checker.dbc.resolver import SignalResolver
from crc_checker.patterns import load_naming_patterns

CUSTOM_PATTERNS = """
checksum:
  prefix: ['(?i)^crc_']
  suffix: ['(?i)_sum$']
rolling_counter:
  prefix: ['(?i)^cnt_']
  suffix: ['(?i)_tick$']
  exclude: ['(?i)block_?counter']
bus_suffix: '_Bus[0-9]+$'
detect:
  min_suffix_matches: 2
"""


class TestNamingPatterns:
    """Signal-name rules are data, not code."""

    def test_defaults_cover_prefix_and_suffix(self):
        """The packaged YAML matches prefix and suffix naming."""
        naming = load_naming_patterns()
        assert naming.checksum_re.match("Checksum_A")
        assert naming.checksum_suffix_re.search("A_CRC")
        assert naming.rolling_counter_re.match("RollingCounter_A")
        assert naming.rolling_counter_suffix_re.search("A_MsgCntr")

    def test_custom_file_extends_matching(self, tmp_path):
        """A custom YAML replaces the packaged rules."""
        path = tmp_path / "patterns.yaml"
        path.write_text(CUSTOM_PATTERNS, encoding="utf-8")
        resolver = SignalResolver(naming=load_naming_patterns(path))
        assert resolver.is_checksum_signal("CRC_X")
        assert resolver.is_checksum_signal("Payload_sum")
        assert resolver.is_rolling_counter_signal("CNT_X")
        assert resolver.is_rolling_counter_signal("Payload_tick")
        # Names that only match the built-in rules are no longer checksums.
        assert not resolver.is_checksum_signal("Checksum_A")

    def test_bus_suffix_is_configurable(self, tmp_path):
        """The bus marker regex comes from the YAML file."""
        path = tmp_path / "patterns.yaml"
        path.write_text(CUSTOM_PATTERNS, encoding="utf-8")
        naming = load_naming_patterns(path)
        assert SignalResolver.strip_bus_suffix("Msg_tick_Bus03", naming) == "Msg_tick"

    def test_missing_file_raises(self, tmp_path):
        """A missing custom file fails loudly."""
        with pytest.raises(FileNotFoundError):
            load_naming_patterns(tmp_path / "nope.yaml")

    def test_inline_pattern_lists_from_config(self):
        """Inline pattern lists extend matching from config.json."""
        cfg = RunConfig()
        cfg.checksum_patterns = [r"(?i)^my_sum$"]
        naming = cfg.build_naming_patterns()
        resolver = SignalResolver(naming=naming)
        assert resolver.is_checksum_signal("MY_SUM")
        assert not resolver.is_checksum_signal("A_CRC")

    def test_single_regex_override_wins(self):
        """A single regex override replaces the inline lists."""
        cfg = RunConfig()
        cfg.checksum_patterns = [r"(?i)^ignored$"]
        cfg.checksum_pattern = r"(?i)^single$"
        resolver = SignalResolver({"checksum": cfg.checksum_pattern},
                                  naming=cfg.build_naming_patterns())
        assert resolver.is_checksum_signal("single")
        assert not resolver.is_checksum_signal("ignored_signal")


class TestDataIDMappings:
    """DataID column layouts are named entries in a YAML file."""

    def test_default_mappings_are_loaded(self):
        """The packaged mapping file exposes the documented names."""
        mappings = load_dataid_mappings()
        assert {"hi_lo_two_cols", "single_16bit", "generic_abc",
                "simple_8bit", "description_regex"} <= set(mappings)
        assert mappings["hi_lo_two_cols"].dataid_format == "hi_lo_two_cols"

    def test_unknown_field_is_rejected(self):
        """Unknown mapping fields fail loudly."""
        with pytest.raises(ValueError, match="Unknown ColumnMapping"):
            ColumnMapping.from_dict({"col_signal_name": 0, "typo": 1})

    def test_mapping_json_string(self):
        """A JSON object can define a mapping inline."""
        mapping = resolve_mapping(
            '{"col_signal_name": 0, "col_message_id": 1}')
        assert isinstance(mapping, ColumnMapping)
        assert mapping.col_signal_name == 0

    def test_custom_yaml_file(self, tmp_path):
        """A custom YAML file adds named mappings."""
        path = tmp_path / "mappings.yaml"
        path.write_text(
            "mappings:\n  mine:\n    col_signal_name: 4\n    col_message_id: 5\n",
            encoding="utf-8")
        mappings = load_dataid_mappings(path)
        assert mappings["mine"].col_signal_name == 4


class TestPresetValidation:
    """Each preset declares whether it was verified with real data."""

    def test_verified_algorithms(self):
        """Algorithms checked against real data are marked verified."""
        for name in ("CRC16/CCITT", "CRC8/SAE-J1850-ZERO", "CRC8/SAE-J1850",
                     "SUM8/XOR-FF", "XOR8/SEED", "SUM8"):
            assert get_validation(name)[0] == VALIDATED, name

    def test_unverified_algorithms(self):
        """Everything else is marked unverified."""
        for name in ("CRC8/AUTOSAR", "CRC8/H2F", "CRC16/ARC", "CRC16/MODBUS",
                     "CRC32/AUTOSAR", "CRC32/ETHERNET", "XOR8"):
            assert get_validation(name)[0] == UNVERIFIED, name
