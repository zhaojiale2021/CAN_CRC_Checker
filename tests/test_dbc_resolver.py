"""Tests for signal name resolution and DBC parsing."""

from crc_checker.crc.presets import get_preset
from crc_checker.dbc.resolver import SignalResolver
from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.dataid.parser import DataIDMap


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

    def test_fx12fl_suffix_detection(self):
        """fx12fl (Chery) suffix names: <Msg>_CRC / <Msg>_MsgCntr / <Msg>_MessageCounter."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("FCM_10_CRC")
        assert resolver.is_checksum_signal("FVC_0x2E1_Checksum")
        assert resolver.is_checksum_signal("YAS_1_Checksum")
        assert resolver.is_rolling_counter_signal("FCM_10_MsgCntr")
        assert resolver.is_rolling_counter_signal("FCM_2_MessageCounter")
        assert resolver.is_rolling_counter_signal("FVC_0x2E1_MessageCounter")
        # 'Cntrl' (Control) must NOT false-match: only the anchored _MsgCntr
        # suffix is a rolling counter, not the 'cntr' substring.
        assert not resolver.is_rolling_counter_signal("FCM_CntrlSysInvldNum")
        assert not resolver.is_rolling_counter_signal("CntrlEnblReq")

    def test_fx12fl_extract_suffix(self):
        """fx12fl suffix extraction yields the message name."""
        assert SignalResolver.extract_suffix("FCM_10_CRC") == "FCM_10"
        assert SignalResolver.extract_suffix("FCM_10_MsgCntr") == "FCM_10"
        assert SignalResolver.extract_suffix("FCM_2_MessageCounter") == "FCM_2"
        assert SignalResolver.extract_suffix("FVC_0x2E1_MessageCounter") == "FVC_0x2E1"
        assert SignalResolver.extract_suffix("YAS_1_Checksum") == "YAS_1"

    def test_b81vs_suffix_detection(self):
        """b81vs (BAIC) suffix names: *_Checksum / *_Chks CRC, *_RollingCounter / *Cntr RC."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("CMRR_RR1_Checksum")
        assert resolver.is_checksum_signal("FDCA1_CheckSum")
        assert resolver.is_checksum_signal("ADC_ADAS1Chks")
        assert resolver.is_checksum_signal("ADC_ADAS2Chks")
        assert resolver.is_rolling_counter_signal("CMRR_RR1_RollingCounter")
        assert resolver.is_rolling_counter_signal("ADC_ADAS1Cntr")
        assert resolver.is_rolling_counter_signal("ADC_APA3Cntr")
        # '_Cntr' must not false-match plain 'Cntr' substrings
        assert not resolver.is_rolling_counter_signal("CntrEnblReq")
        assert not resolver.is_rolling_counter_signal("FCM_CntrlSysInvldNum")

    def test_b81vs_extract_suffix(self):
        """b81vs suffix extraction yields the message name + segment index."""
        assert SignalResolver.extract_suffix("CMRR_RR1_Checksum") == "CMRR_RR1"
        assert SignalResolver.extract_suffix("CMRR_RR1_RollingCounter") == "CMRR_RR1"
        assert SignalResolver.extract_suffix("ADC_ADAS1Chks") == "ADC_ADAS1"
        assert SignalResolver.extract_suffix("ADC_ADAS1Cntr") == "ADC_ADAS1"
        assert SignalResolver.extract_suffix("ADC_ADAS2Chks") == "ADC_ADAS2"
        assert SignalResolver.extract_suffix("BleRpa1Chks") == "BleRpa1"

    def test_t1lfl1_suffix_detection(self):
        """t1lfl1 (Chery): *_CRCCheck checksum, *_Message_Counter and
        ALIVE_* counters."""
        resolver = SignalResolver()
        assert resolver.is_checksum_signal("SAS_1_CRCCheck")
        assert resolver.is_checksum_signal("EPS_2_CRC")
        # 'CRC' alone is a valid checksum signal name (IHU_MFS_2)
        assert resolver.is_checksum_signal("CRC")
        assert resolver.is_rolling_counter_signal("SAS_1_MessageCounter")
        assert resolver.is_rolling_counter_signal("EPS_2_Message_Counter")
        assert resolver.is_rolling_counter_signal("ALIVE_MFS_2")
        assert not resolver.is_checksum_signal("ALIVE_MFS_2")

    def test_t1lfl1_extract_suffix(self):
        """t1lfl1 suffix extraction yields the message name for pairing."""
        assert SignalResolver.extract_suffix("SAS_1_CRCCheck") == "SAS_1"
        assert SignalResolver.extract_suffix("EPS_2_Message_Counter") == "EPS_2"

    def test_t1lfl1_pairing(self):
        """t1lfl1 frames pair CRC with counter across naming variants."""
        resolver = SignalResolver()
        frames = [
            {
                "frame_id": 0xC4, "frame_name": "SAS_1_G", "dlc": 8,
                "signals": [
                    {"name": "SAS_1_CRCCheck", "start_bit": 56, "length": 8,
                     "byte_order": "big_endian"},
                    {"name": "SAS_1_MessageCounter", "start_bit": 40, "length": 4,
                     "byte_order": "big_endian"},
                    {"name": "SAS_1_SteeringAngle", "start_bit": 0, "length": 16,
                     "byte_order": "big_endian"},
                ],
            },
            {
                "frame_id": 0x394, "frame_name": "EPS_2", "dlc": 8,
                "signals": [
                    {"name": "EPS_2_CRC", "start_bit": 56, "length": 8,
                     "byte_order": "big_endian"},
                    {"name": "EPS_2_Message_Counter", "start_bit": 52, "length": 4,
                     "byte_order": "big_endian"},
                ],
            },
            {
                # IHU_MFS_2: checksum named just "CRC", counter "ALIVE_MFS_2"
                "frame_id": 0x360, "frame_name": "IHU_MFS_2", "dlc": 6,
                "signals": [
                    {"name": "CRC", "start_bit": 0, "length": 8,
                     "byte_order": "big_endian"},
                    {"name": "ALIVE_MFS_2", "start_bit": 8, "length": 4,
                     "byte_order": "big_endian"},
                    {"name": "MFS_Cancel", "start_bit": 26, "length": 2,
                     "byte_order": "big_endian"},
                ],
            },
        ]
        pm = resolver.build_protection_map(frames)

        sas = pm.messages[0xC4]
        assert len(sas) == 1
        assert sas[0].checksum_signal.name == "SAS_1_CRCCheck"
        assert sas[0].rolling_counter_signal.name == "SAS_1_MessageCounter"

        eps = pm.messages[0x394]
        assert len(eps) == 1
        assert eps[0].checksum_signal.name == "EPS_2_CRC"
        assert eps[0].rolling_counter_signal.name == "EPS_2_Message_Counter"

        # Single-pair fallback: no common suffix ("CRC" vs "ALIVE_MFS_2")
        ihu = pm.messages[0x360]
        assert len(ihu) == 1
        assert ihu[0].checksum_signal.name == "CRC"
        assert ihu[0].rolling_counter_signal.name == "ALIVE_MFS_2"

    def test_custom_rc_pattern_keeps_default_checksum_detection(self):
        """Supplying only rc_pattern must not turn every signal into a checksum."""
        resolver = SignalResolver({"rolling_counter": r"(?i)^MY_RC_"})
        # default checksum detection still applies
        assert resolver.is_checksum_signal("Checksum_ACC1")
        assert resolver.is_checksum_signal("SAS_1_CRCCheck")
        assert not resolver.is_checksum_signal("SpeedValue")
        # custom RC pattern applies as given
        assert resolver.is_rolling_counter_signal("MY_RC_Engine")
        assert not resolver.is_rolling_counter_signal("RollingCounter_ACC1")

    def test_fx12fl_comment_classification(self):
        """DBC comments flow through the resolver; auto-classification sets
        per-message checksum params (crc8 / sum_xor / xor_seed)."""
        resolver = SignalResolver()
        frames = [
            {
                "frame_id": 0x2E1, "frame_name": "FVC_02", "dlc": 8,
                "signals": [
                    {"name": "FVC_0x2E1_Checksum", "start_bit": 56, "length": 8,
                     "byte_order": "big_endian",
                     "comment": "Checksum(SAE J1850 CRC-8)"},
                    {"name": "FVC_0x2E1_MessageCounter", "start_bit": 48, "length": 4,
                     "byte_order": "big_endian"},
                ],
            },
            {
                "frame_id": 0x295, "frame_name": "YAS_1", "dlc": 8,
                "signals": [
                    {"name": "YAS_1_Checksum", "start_bit": 56, "length": 8,
                     "byte_order": "big_endian",
                     "comment": ("0x01 XOR 0x27 XOR Byte0 XOR Byte1 XOR Byte2 "
                                 "XOR Byte3 XOR Byte4 XOR Byte5 XOR Byte6")},
                    {"name": "YAS_1_MsgCntr", "start_bit": 48, "length": 4,
                     "byte_order": "big_endian"},
                ],
            },
            {
                "frame_id": 0x647, "frame_name": "ICM_5", "dlc": 8,
                "signals": [
                    {"name": "ICM_5_Checksum", "start_bit": 56, "length": 8,
                     "byte_order": "big_endian",
                     "comment": ("((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) "
                                 "AND 0xFF) XOR 0xFF")},
                    {"name": "ICM_5_MsgCntr", "start_bit": 48, "length": 4,
                     "byte_order": "big_endian"},
                ],
            },
        ]
        pm = resolver.build_protection_map(frames)

        # RC now pairs with the checksum for each fx12fl-style group
        fvc = pm.messages[0x2E1][0]
        assert fvc.rolling_counter_signal is not None
        assert fvc.checksum_comment == "Checksum(SAE J1850 CRC-8)"

        # Auto-classify: crc8 keeps default, sum_xor + xor_seed override
        applied = pm.apply_comment_classification(get_preset("CRC8/SAE-J1850"))
        assert applied == 3

        assert pm.messages[0x2E1][0].crc_params.checksum_type == "crc"
        assert pm.messages[0x2E1][0].crc_params.name == "CRC8/SAE-J1850"

        yas = pm.messages[0x295][0].crc_params
        assert yas.checksum_type == "xor_seed"
        assert yas.initial_value == 0x26  # 0x01 ^ 0x27

        icm = pm.messages[0x647][0].crc_params
        assert icm.checksum_type == "sum_xor"
        assert icm.final_xor == 0xFF


class TestApplyCrcOverrides:
    """apply_crc_overrides: config-driven per-message algorithm overrides."""

    @staticmethod
    def _map_with(prot: MessageProtection) -> DBCProtectionMap:
        pm = DBCProtectionMap()
        pm.messages[prot.frame_id] = [prot]
        return pm

    @staticmethod
    def _prot(frame_id: int = 0x287, frame_name: str = "ICM_5") -> MessageProtection:
        prot = MessageProtection(frame_id=frame_id, frame_name=frame_name, dlc=8)
        prot.checksum_signal = SignalInfo(name="ICM_5_Checksum", start_bit=56, length=8)
        return prot

    def test_override_by_hex_frame_id(self):
        """Key "0x287" matches the frame and applies the preset."""
        prot = self._prot()
        pm = self._map_with(prot)
        applied = pm.apply_crc_overrides({"0x287": "SUM8/XOR-FF"})
        assert applied == 1
        assert prot.crc_params is get_preset("SUM8/XOR-FF")

    def test_override_by_int_and_frame_name(self):
        """Integer frame IDs and frame names are both accepted as keys."""
        prot = self._prot()
        assert self._map_with(prot).apply_crc_overrides({0x287: "SUM8"}) == 1
        assert prot.crc_params is get_preset("SUM8")

        prot2 = self._prot(frame_id=0x111, frame_name="ICM_9")
        assert self._map_with(prot2).apply_crc_overrides({"ICM_9": "SUM8"}) == 1
        assert prot2.crc_params is get_preset("SUM8")

    def test_override_wins_over_comment_classification(self):
        """An explicit override is applied after auto-classify and wins."""
        prot = self._prot()
        prot.checksum_comment = "((Byte0+Byte1+Byte6) AND 0xFF) XOR 0xFF"
        pm = self._map_with(prot)
        pm.apply_comment_classification(get_preset("CRC8/SAE-J1850"))
        assert prot.crc_params is get_preset("SUM8/XOR-FF")  # from comment
        pm.apply_crc_overrides({"0x287": "CRC8/SAE-J1850"})
        assert prot.crc_params is get_preset("CRC8/SAE-J1850")

    def test_override_by_name_matches_every_suffix_group(self):
        """A frame-name key applies to all protection groups of that frame."""
        pm = DBCProtectionMap()
        p1 = self._prot(frame_id=0x500, frame_name="Dual")
        p2 = self._prot(frame_id=0x500, frame_name="Dual")
        pm.messages[0x500] = [p1, p2]
        assert pm.apply_crc_overrides({"Dual": "SUM8"}) == 2
        assert p1.crc_params is p2.crc_params is get_preset("SUM8")

    def test_unmatched_override_is_noop(self):
        """Unknown IDs/names change nothing and return 0."""
        prot = self._prot()
        pm = self._map_with(prot)
        assert pm.apply_crc_overrides({"0x999": "SUM8", "NOPE": "SUM8"}) == 0
        assert prot.crc_params is None


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


class TestApplyDataIDName:
    """apply_dataid_map must record the matched entry name for display."""

    @staticmethod
    def _prot(frame_id: int, frame_name: str, checksum: str) -> MessageProtection:
        prot = MessageProtection(frame_id=frame_id, frame_name=frame_name, dlc=8)
        prot.checksum_signal = SignalInfo(name=checksum, start_bit=56, length=8)
        return prot

    def test_exact_checksum_signal_match(self):
        """Strategy 1: dataid_name is the checksum signal name."""
        pm = DBCProtectionMap()
        prot = self._prot(0x100, "FrameA", "Checksum_X")
        pm.messages[0x100] = [prot]
        dm = DataIDMap()
        dm.add(0x100, "Checksum_X", 0x1234)
        assert pm.apply_dataid_map(dm) == 1
        assert prot.dataid == 0x1234
        assert prot.dataid_name == "Checksum_X"

    def test_frame_name_match(self):
        """Strategy 2: dataid_name is the frame name."""
        pm = DBCProtectionMap()
        prot = self._prot(0x200, "FrameB", "Checksum_Y")
        pm.messages[0x200] = [prot]
        dm = DataIDMap()
        dm.add(0x200, "FrameB", 0x5678)
        pm.apply_dataid_map(dm)
        assert prot.dataid_name == "FrameB"

    def test_fuzzy_match_records_index_name(self):
        """Strategy 4: dataid_name is the entry name from the reverse index."""
        pm = DBCProtectionMap()
        prot = self._prot(0x300, "FrameSigABC", "Checksum_Z")
        pm.messages[0x300] = [prot]
        dm = DataIDMap()
        dm.add(0x300, "SigABC", 0x9ABC)
        pm.apply_dataid_map(dm)
        assert prot.dataid_name == "SigABC"
