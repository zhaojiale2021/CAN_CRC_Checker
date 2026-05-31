"""Tests for signal name resolution and DBC parsing."""

from crc_checker.dbc.resolver import SignalResolver
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection


class TestSignalResolver:
    """Test signal name matching and pairing."""

    def test_checksum_detection(self):
        """Checksum patterns match checksum names, exclude RC/speed names."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("Checksum_ACC1")
        assert resolver.is_checksum_signal("CRC_Engine")
        assert resolver.is_checksum_signal("E2E_CRC_Main")
        assert resolver.is_checksum_signal("CheckSum_Front")
        assert not resolver.is_checksum_signal("RollingCounter_ACC1")
        assert not resolver.is_checksum_signal("SpeedValue")

    def test_rolling_counter_detection(self):
        """RC patterns match rolling counter names, exclude checksum/speed."""
        resolver = SignalResolver()
        assert resolver.is_rolling_counter_signal("RollingCounter_ACC1")
        assert resolver.is_rolling_counter_signal("Rolling_Counter_Engine")
        assert resolver.is_rolling_counter_signal("RC_Main")
        assert resolver.is_rolling_counter_signal("LiveCounter_Front")
        assert resolver.is_rolling_counter_signal("AliveCounter_Rear")
        assert not resolver.is_rolling_counter_signal("Checksum_ACC1")
        assert not resolver.is_rolling_counter_signal("SpeedValue")

    def test_suffix_extraction(self):
        """Suffix extraction splits after last underscore segment."""
        assert SignalResolver.extract_suffix("Checksum_ACC1") == "ACC1"
        assert SignalResolver.extract_suffix("RollingCounter_IFC2") == "IFC2"
        assert SignalResolver.extract_suffix("Checksum_ACC14") == "ACC14"
        assert SignalResolver.extract_suffix("CRC_MainEngine") == "MainEngine"
        assert SignalResolver.extract_suffix("RC_ECU1") == "ECU1"

    def test_pairing_logic(self):
        """Checksum and RC with same suffix get paired into one group."""
        resolver = SignalResolver()
        frames = [{
            "frame_id": 0x323,
            "frame_name": "TestFrame",
            "dlc": 8,
            "signals": [
                {"name": "Checksum_ACC1", "start_bit": 71, "length": 8,
                 "byte_order": "little_endian"},
                {"name": "RollingCounter_ACC1", "start_bit": 123, "length": 4,
                 "byte_order": "little_endian"},
                {"name": "Checksum_ACC2", "start_bit": 135, "length": 8,
                 "byte_order": "little_endian"},
                {"name": "RollingCounter_ACC2", "start_bit": 187, "length": 4,
                 "byte_order": "little_endian"},
                {"name": "SpeedValue", "start_bit": 0, "length": 16,
                 "byte_order": "little_endian"},
            ],
        }]

        prot_map = resolver.build_protection_map(frames)
        assert 0x323 in prot_map.messages
        groups = prot_map.messages[0x323]
        assert len(groups) == 2

        # Find ACC1 group
        acc1 = next(g for g in groups if g.pair_suffix == "ACC1")
        assert acc1.checksum_signal.name == "Checksum_ACC1"
        assert acc1.rolling_counter_signal.name == "RollingCounter_ACC1"

        # Find ACC2 group
        acc2 = next(g for g in groups if g.pair_suffix == "ACC2")
        assert acc2.checksum_signal.name == "Checksum_ACC2"
        assert acc2.rolling_counter_signal.name == "RollingCounter_ACC2"

    def test_custom_patterns(self):
        """Custom regex patterns override default checksum/RC detection."""
        custom = {
            "checksum": r"(?i)^MY_CRC_.*",
            "rolling_counter": r"(?i)^MY_RC_.*",
        }
        resolver = SignalResolver(custom)
        assert resolver.is_checksum_signal("MY_CRC_Engine")
        assert not resolver.is_checksum_signal("Checksum_ACC1")
        assert resolver.is_rolling_counter_signal("MY_RC_Engine")
        assert not resolver.is_rolling_counter_signal("RollingCounter_ACC1")


class TestDBCProtectionMapMerge:
    """Test DBCProtectionMap merge and backward compat."""

    def test_merge_adds_new_suffixes(self):
        """Same frame_id with different suffix: appended. Same suffix: skipped."""

        map1 = DBCProtectionMap(dbc_paths=["a.dbc"])
        map1.messages[0x100] = [
            MessageProtection(frame_id=0x100, frame_name="FrameA", dlc=8, pair_suffix="X")
        ]

        map2 = DBCProtectionMap(dbc_paths=["b.dbc"])
        map2.messages[0x100] = [
            # duplicate suffix, skipped:
            MessageProtection(frame_id=0x100, frame_name="FrameA_Dup", dlc=8,
                              pair_suffix="X"),
            # new suffix, added:
            MessageProtection(frame_id=0x100, frame_name="FrameA_New", dlc=8,
                              pair_suffix="Y"),
        ]
        map2.messages[0x200] = [
            MessageProtection(frame_id=0x200, frame_name="FrameB", dlc=8, pair_suffix="Z")
        ]

        added = map1.merge(map2)
        assert added == 2  # Y + Z added, X skipped
        assert 0x100 in map1.messages
        assert len(map1.messages[0x100]) == 2  # X + Y
        assert 0x200 in map1.messages
        assert map1.messages[0x100][0].frame_name == "FrameA"  # first DBC's definition wins
        assert map1.dbc_paths == ["a.dbc", "b.dbc"]

    def test_dbc_path_property(self):
        """dbc_path returns joined string of all paths."""

        map1 = DBCProtectionMap(dbc_paths=["a.dbc", "b.dbc"])
        assert map1.dbc_path == "a.dbc, b.dbc"

        map2 = DBCProtectionMap(dbc_paths=[])
        assert map2.dbc_path == ""

    def test_dbc_path_setter(self):
        """Backward compat setter stores single path."""

        map1 = DBCProtectionMap()
        map1.dbc_path = "single.dbc"
        assert map1.dbc_paths == ["single.dbc"]
        assert map1.dbc_path == "single.dbc"

    def test_merge_empty_other(self):
        """Merging an empty map changes nothing."""

        map1 = DBCProtectionMap(dbc_paths=["a.dbc"])
        map1.messages[0x100] = [
            MessageProtection(frame_id=0x100, frame_name="FrameA", dlc=8, pair_suffix="X")
        ]
        map2 = DBCProtectionMap(dbc_paths=["empty.dbc"])

        added = map1.merge(map2)
        assert added == 0
        assert len(map1.messages) == 1
