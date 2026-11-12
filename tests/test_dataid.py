"""Tests for DataID parsing, JSON serialization, and multi-sheet merge."""
import json
import os
import tempfile
import pytest
from crc_checker.dataid import mappings, matching, models, multi, parser
from crc_checker.dataid.parser import (
    ColumnMapping,
    DataIDMap,
    _add_dataid_row,
)


class TestDataIDMapSerialization:
    """Test JSON round-trip serialization."""

    def test_to_json_and_from_json_roundtrip(self):
        """Full roundtrip: to_json → from_json preserves all entries."""
        dm = DataIDMap(sheet_name="TestSheet")
        dm.add(0x143, "Checksum_ACC1", 0x0054)
        dm.add(0x143, "Checksum_ACC2", 0x0055)
        dm.add(0x299, "Checksum_IFC1", 0x00AB)

        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_roundtrip.json")
        try:
            dm.to_json(tmp_path, source="test.xlsx", mapping="hi_lo_two_cols",
                       sheets=["TestSheet"])

            with open(tmp_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            assert raw["format"] == "dataid_map_v2"
            assert raw["source"] == "test.xlsx"
            assert len(raw["entries"]) == 3
            # Verify hex format
            assert raw["entries"][0]["frame_id"] == "0x143"
            assert raw["entries"][0]["dataid"] == "0x0054"

            loaded = DataIDMap.from_json(tmp_path)
            assert len(loaded) == 3
            assert loaded.get(0x143, "Checksum_ACC1") == 0x0054
            assert loaded.get(0x143, "Checksum_ACC2") == 0x0055
            assert loaded.get(0x299, "Checksum_IFC1") == 0x00AB
            assert loaded.get(0x999, "nonexistent") is None
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_from_json_integer_compat(self):
        """Backward compat: integer frame_id/dataid still parse correctly."""
        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_intcompat.json")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({
                    "format": "dataid_map_v1",
                    "entries": [
                        {"frame_id": 323, "signal_name": "Checksum_X", "dataid": 84}
                    ]
                }, f)
            dm = DataIDMap.from_json(tmp_path)
            assert len(dm) == 1
            assert dm.get(323, "Checksum_X") == 84
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_from_json_empty(self):
        """Empty entries list → empty DataIDMap."""
        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_empty.json")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"format": "dataid_map_v1", "entries": []}, f)
            dm = DataIDMap.from_json(tmp_path)
            assert len(dm) == 0
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_from_json_bad_format(self):
        """Unknown format version raises ValueError."""
        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_bad_fmt.json")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"format": "unknown_v2", "entries": []}, f)
            with pytest.raises(ValueError, match="Unsupported.*format"):
                DataIDMap.from_json(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_to_json_no_sheets_defaults_to_sheet_name(self):
        """No sheets arg → sheet_name used as default."""
        dm = DataIDMap(sheet_name="MySheet")
        dm.add(0x100, "Checksum_X", 0x0010)

        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_nosheets.json")
        try:
            dm.to_json(tmp_path)
            with open(tmp_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            assert raw["sheets"] == ["MySheet"]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


def test_parser_facade_preserves_public_and_private_imports():
    """Legacy parser imports remain aliases of the decomposed modules."""
    assert parser.DataIDMap is models.DataIDMap
    assert parser.normalize_signal_key is models.normalize_signal_key
    assert parser.ColumnMapping is mappings.ColumnMapping
    assert parser.BUILTIN_MAPPINGS is mappings.BUILTIN_MAPPINGS
    assert parser.resolve_mapping is mappings.resolve_mapping
    assert parser.match_sheet_to_dbc is matching.match_sheet_to_dbc
    assert parser.parse_dataid_xlsx_multi is multi.parse_dataid_xlsx_multi

    for name in parser.__all__:
        assert hasattr(parser, name)


class TestDataIDMapUpdate:
    """Test merging of DataIDMap instances."""

    def test_add_without_profile_clears_previous_profile(self):
        """An overwrite without profile metadata clears the old profile."""
        data = DataIDMap()
        data.add(0x100, "Checksum_X", 0x10, "Profile 5")
        data.add(0x100, "Checksum_X", 0x20)
        assert data.get(0x100, "Checksum_X") == 0x20
        assert data.get_profile(0x100, "Checksum_X") is None
        assert data.get_profile_normalized(0x100, "checksum_x") is None

    def test_update_without_profile_clears_previous_profile(self):
        """Updating an entry without profile metadata clears the old profile."""
        current = DataIDMap()
        current.add(0x100, "Checksum_X", 0x10, "Profile 5")
        replacement = DataIDMap()
        replacement.add(0x100, "Checksum_X", 0x20)
        current.update(replacement)
        assert current.get(0x100, "Checksum_X") == 0x20
        assert current.get_profile(0x100, "Checksum_X") is None
        assert current.get_profile_normalized(0x100, "checksum_x") is None

    def test_update_adds_new_and_overwrites_duplicates(self):
        """Update adds new entries, overwrites duplicates; existing kept."""
        dm1 = DataIDMap()
        dm1.add(0x100, "Checksum_X", 0x0010)
        dm1.add(0x200, "Checksum_Y", 0x0020)

        dm2 = DataIDMap()
        dm2.add(0x200, "Checksum_Y", 0x0099)  # duplicate, overwrites
        dm2.add(0x300, "Checksum_Z", 0x0030)  # new

        overwritten = dm1.update(dm2)
        assert overwritten == 1
        assert len(dm1) == 3
        assert dm1.get(0x100, "Checksum_X") == 0x0010  # unchanged
        assert dm1.get(0x200, "Checksum_Y") == 0x0099  # overwritten
        assert dm1.get(0x300, "Checksum_Z") == 0x0030  # new

    def test_row_skips_missing_message_id_header(self):
        """A missing header column never reads the row's final cell as an ID."""

        mapping = ColumnMapping(
            col_signal_name="Signal", col_message_id="Message ID",
            col_dataid_hi="DataID", col_dataid_lo=-1,
            dataid_format="single_16bit", use_header_names=True,
            signal_name_filter=[],
        ).resolve_columns(["Signal", "DataID"])
        target = DataIDMap()
        assert _add_dataid_row(["Checksum_X", "0x1234"], mapping, target) is False
        assert len(target) == 0

    def test_update_empty_other(self):
        """Merging empty DataIDMap is a no-op."""
        dm1 = DataIDMap()
        dm1.add(0x100, "Checksum_X", 0x0010)
        dm2 = DataIDMap()

        overwritten = dm1.update(dm2)
        assert overwritten == 0
        assert len(dm1) == 1
