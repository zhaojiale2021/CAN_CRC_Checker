"""Tests for signal name resolution and DBC parsing."""

import pytest
from crc_checker.dbc.resolver import SignalResolver, DEFAULT_PATTERNS
from crc_checker.dbc.models import SignalInfo, MessageProtection


class TestSignalResolver:
    """Test signal name matching and pairing."""

    def test_checksum_detection(self):
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("Checksum_ACC1")
        assert resolver.is_checksum_signal("CRC_Engine")
        assert resolver.is_checksum_signal("E2E_CRC_Main")
        assert resolver.is_checksum_signal("CheckSum_Front")
        assert not resolver.is_checksum_signal("RollingCounter_ACC1")
        assert not resolver.is_checksum_signal("SpeedValue")

    def test_rolling_counter_detection(self):
        resolver = SignalResolver()
        assert resolver.is_rolling_counter_signal("RollingCounter_ACC1")
        assert resolver.is_rolling_counter_signal("Rolling_Counter_Engine")
        assert resolver.is_rolling_counter_signal("RC_Main")
        assert resolver.is_rolling_counter_signal("LiveCounter_Front")
        assert resolver.is_rolling_counter_signal("AliveCounter_Rear")
        assert not resolver.is_rolling_counter_signal("Checksum_ACC1")
        assert not resolver.is_rolling_counter_signal("SpeedValue")

    def test_suffix_extraction(self):
        assert SignalResolver.extract_suffix("Checksum_ACC1") == "ACC1"
        assert SignalResolver.extract_suffix("RollingCounter_IFC2") == "IFC2"
        assert SignalResolver.extract_suffix("Checksum_ACC14") == "ACC14"
        assert SignalResolver.extract_suffix("CRC_MainEngine") == "MainEngine"
        assert SignalResolver.extract_suffix("RC_ECU1") == "ECU1"

    def test_pairing_logic(self):
        resolver = SignalResolver()
        frames = [{
            "frame_id": 0x323,
            "frame_name": "TestFrame",
            "dlc": 8,
            "signals": [
                {"name": "Checksum_ACC1", "start_bit": 71, "length": 8, "byte_order": "little_endian"},
                {"name": "RollingCounter_ACC1", "start_bit": 123, "length": 4, "byte_order": "little_endian"},
                {"name": "Checksum_ACC2", "start_bit": 135, "length": 8, "byte_order": "little_endian"},
                {"name": "RollingCounter_ACC2", "start_bit": 187, "length": 4, "byte_order": "little_endian"},
                {"name": "SpeedValue", "start_bit": 0, "length": 16, "byte_order": "little_endian"},
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
        custom = {
            "checksum": r"(?i)^MY_CRC_.*",
            "rolling_counter": r"(?i)^MY_RC_.*",
        }
        resolver = SignalResolver(custom)
        assert resolver.is_checksum_signal("MY_CRC_Engine")
        assert not resolver.is_checksum_signal("Checksum_ACC1")
        assert resolver.is_rolling_counter_signal("MY_RC_Engine")
        assert not resolver.is_rolling_counter_signal("RollingCounter_ACC1")
