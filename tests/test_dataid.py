"""Tests for DataID parsing, JSON serialization, and multi-sheet merge."""
import json
import os
import tempfile
import pytest
from crc_checker.dataid.parser import DataIDMap


class TestDataIDMapSerialization:
    """Test JSON round-trip serialization."""

    def test_to_json_and_from_json_roundtrip(self):
        dm = DataIDMap(sheet_name="TestSheet")
        dm.add(0x143, "Checksum_ACC1", 0x0054)
        dm.add(0x143, "Checksum_ACC2", 0x0055)
        dm.add(0x299, "Checksum_IFC1", 0x00AB)

        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_roundtrip.json")
        try:
            dm.to_json(tmp_path, source="test.xlsx", mapping="greatwall_j6m",
                       sheets=["TestSheet"])

            with open(tmp_path, "r") as f:
                raw = json.load(f)
            assert raw["format"] == "dataid_map_v1"
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
            with open(tmp_path, "w") as f:
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
        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_empty.json")
        try:
            with open(tmp_path, "w") as f:
                json.dump({"format": "dataid_map_v1", "entries": []}, f)
            dm = DataIDMap.from_json(tmp_path)
            assert len(dm) == 0
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_from_json_bad_format(self):
        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_bad_fmt.json")
        try:
            with open(tmp_path, "w") as f:
                json.dump({"format": "unknown_v2", "entries": []}, f)
            with pytest.raises(ValueError, match="Unsupported.*format"):
                DataIDMap.from_json(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_to_json_no_sheets_defaults_to_sheet_name(self):
        dm = DataIDMap(sheet_name="MySheet")
        dm.add(0x100, "Checksum_X", 0x0010)

        tmp_path = os.path.join(tempfile.gettempdir(), "test_dataid_nosheets.json")
        try:
            dm.to_json(tmp_path)
            with open(tmp_path, "r") as f:
                raw = json.load(f)
            assert raw["sheets"] == ["MySheet"]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestDataIDMapUpdate:
    """Test merging of DataIDMap instances."""

    def test_update_adds_new_and_overwrites_duplicates(self):
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

    def test_update_empty_other(self):
        dm1 = DataIDMap()
        dm1.add(0x100, "Checksum_X", 0x0010)
        dm2 = DataIDMap()

        overwritten = dm1.update(dm2)
        assert overwritten == 0
        assert len(dm1) == 1
