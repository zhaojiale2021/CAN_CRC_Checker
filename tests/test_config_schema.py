"""Keep ``config.schema.json`` in sync with the loader.

The schema is what editors autocomplete and validate against; the loader is
what actually runs. They are maintained separately, so this test is the guard
that keeps them from drifting apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from crc_checker.config import (
    _SECTION_KEYS,
    _TOP_LEVEL_KEYS,  # pylint: disable=protected-access
    generate_example_config,
)
from crc_checker.core.models import CHECKSUM_TYPES, VALID_RANGE_MODES

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "config.schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_is_a_valid_draft_2020_schema():
    """The shipped schema itself must be a valid 2020-12 document."""
    Draft202012Validator.check_schema(_schema())


def test_schema_top_level_and_section_keys_match_the_loader():
    """Every key the loader accepts is documented in the schema (and vice versa)."""
    schema = _schema()
    assert set(schema["properties"]) == _TOP_LEVEL_KEYS
    for section, keys in _SECTION_KEYS.items():
        assert set(schema["properties"][section]["properties"]) == keys, section


def test_schema_enums_match_the_python_constants():
    """Enums/minimums come from the same constants the loader validates with."""
    schema = _schema()
    crc = schema["properties"]["crc"]["properties"]
    assert set(crc["custom"]["properties"]["type"]["enum"]) == CHECKSUM_TYPES
    assert crc["custom"]["properties"]["width"]["minimum"] == 8
    for path in ("range", "crc.range_overrides"):
        node = schema["properties"]
        if path == "crc.range_overrides":
            enum = node["crc"]["properties"]["range_overrides"][
                "additionalProperties"]["properties"]["mode"]["enum"]
        else:
            enum = node["range"]["properties"]["mode"]["enum"]
        assert set(enum) == VALID_RANGE_MODES


@pytest.mark.parametrize("config_path", [
    "examples/example/config.json",
    "examples/example/config_bad.json",
])
def test_shipped_example_configs_validate(config_path):
    """The example configs are valid according to the public schema."""
    config = json.loads(
        (Path(__file__).resolve().parents[1] / config_path).read_text(encoding="utf-8"))
    Draft202012Validator(_schema()).validate(config)


def test_generated_example_config_validates(tmp_path):
    """``crc-check gen-config`` output validates against the schema."""
    path = tmp_path / "example.json"
    generate_example_config(str(path))
    Draft202012Validator(_schema()).validate(
        json.loads(path.read_text(encoding="utf-8")))


def test_dataid_mapping_accepts_a_name_or_an_inline_object():
    """dataid.mapping is either a named layout or an inline object."""
    validator = Draft202012Validator(_schema())
    base = {"dbc": "network.dbc", "traces": ["trace.blf"]}
    for mapping in ("hi_lo_two_cols", {"name": {"frame": 0, "dataid": 1}}):
        validator.validate({**base, "dataid": {"mapping": mapping}})
