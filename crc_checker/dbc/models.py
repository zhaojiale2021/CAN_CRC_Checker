"""Data models for DBC-parsed protection signal information."""

from __future__ import annotations

from dataclasses import dataclass, field
from crc_checker.crc.models import CRCParams, CRCRange


@dataclass
class SignalInfo:
    """Extracted information about a single protection signal from DBC."""
    name: str                # "Checksum_ACC1"
    start_bit: int           # bit position within payload
    length: int              # bit length (8 for CRC8, 4 for RC)
    byte_order: str = "little_endian"  # "little_endian" or "big_endian"


@dataclass
class MessageProtection:  # pylint: disable=too-many-instance-attributes
    """Protection information for one CAN message.

    A message may have multiple protection groups (e.g., ACC1, ACC2).
    Each group is a (checksum, rolling_counter) pair identified by a common suffix.
    """
    frame_id: int
    frame_name: str
    dlc: int
    pair_suffix: str = ""                                      # e.g. "ACC1"
    checksum_signal: SignalInfo | None = None
    rolling_counter_signal: SignalInfo | None = None
    crc_params: CRCParams | None = None                        # Algorithm (set by user/config)
    crc_range: CRCRange | None = None                          # Data range (set by user/config)
    dataid: int | None = None                                  # 16-bit DataID from AUTOSAR E2E
    crc_profile: str = ""                                      # Profile hint from DataID (e.g. "Profile 1A")
    frame_protection_count: int = 1                            # How many protection groups
    rc_max_valid: int | None = None                            # Max RC before wrap
    dbc_source: str = ""                                       # Source DBC file name


@dataclass
class DBCProtectionMap:
    """Complete map of all protection signals across all messages."""
    dbc_paths: list[str] = field(default_factory=list)
    messages: dict[int, list[MessageProtection]] = field(default_factory=dict)
    # key = frame_id, value = list of protection groups within that message

    @property
    def dbc_path(self) -> str:
        """Backward-compat: joined display string of all DBC paths."""
        return ", ".join(self.dbc_paths)

    @dbc_path.setter
    def dbc_path(self, value: str):
        """Backward-compat setter: sets dbc_paths to a single-element list."""
        self.dbc_paths = [value] if value else []

    def get_protections(self, frame_id: int, channel: int = 0) -> list[MessageProtection]:  # pylint: disable=unused-argument
        """Get all protection groups for a given CAN ID.

        The channel parameter is accepted for API compatibility with
        ChannelProtectionMap but ignored (single-DBC mode applies to all channels).
        """
        return self.messages.get(frame_id, [])

    def all_frame_ids(self) -> list[int]:
        """Get all CAN IDs that have protection signals."""
        return list(self.messages.keys())

    def apply_crc_params(self, params: CRCParams):
        """Apply the same CRC params to all protection groups."""
        for prot_list in self.messages.values():
            for prot in prot_list:
                prot.crc_params = params

    def apply_crc_range(self, crc_range: CRCRange):
        """Apply the same CRC range to all protection groups."""
        for prot_list in self.messages.values():
            for prot in prot_list:
                prot.crc_range = crc_range

    def apply_dataid_map(self, dataid_map):
        """Apply DataID values from a DataIDMap to matching protection groups.

        Match strategy (tried in order):
        1. Exact match by (frame_id, checksum_signal_name) — default GWM style
        2. Exact match by (frame_id, frame_name) — GAC style (Excel uses message names)
        3. Match by (frame_id, pair_suffix) — fallback for suffix-based naming
        4. Fuzzy match: if frame_name contains the DataID signal name, or vice versa

        Also stores profile info (e.g. "Profile 1A") from DataID entries.
        """
        # Pre-build a reverse index: frame_id → list of (signal_name, dataid, profile)
        rev_index: dict[int, list[tuple[str, int, str]]] = {}
        for (fid, sig), did in dataid_map._map.items():
            if fid not in rev_index:
                rev_index[fid] = []
            profile = dataid_map._profiles.get((fid, sig), "")
            rev_index[fid].append((sig, did, profile))

        def _try_lookup(fid, key):
            """Try exact lookup in DataIDMap."""
            did = dataid_map.get(fid, key)
            if did is not None:
                return did, dataid_map.get_profile(fid, key) or ""
            return None, ""

        applied = 0
        for prot_list in self.messages.values():
            for prot in prot_list:
                if not prot.checksum_signal:
                    continue
                dataid = None
                profile = ""

                # Strategy 1: exact checksum signal name match
                dataid, profile = _try_lookup(prot.frame_id, prot.checksum_signal.name)

                # Strategy 2: match by frame/message name
                if dataid is None and prot.frame_name:
                    dataid, profile = _try_lookup(prot.frame_id, prot.frame_name)

                # Strategy 3: match by pair_suffix
                if dataid is None and prot.pair_suffix:
                    dataid, profile = _try_lookup(prot.frame_id, prot.pair_suffix)

                # Strategy 4: fuzzy substring match in reverse index
                if dataid is None and prot.frame_id in rev_index:
                    fname = prot.frame_name.lower()
                    for sig, did, prof in rev_index[prot.frame_id]:
                        sig_lower = sig.lower()
                        if sig_lower in fname or fname in sig_lower:
                            dataid, profile = did, prof
                            break

                if dataid is not None:
                    prot.dataid = dataid
                    prot.crc_profile = profile
                    applied += 1
        return applied

    def apply_dataid_map_fallback(self, dataid_map) -> int:
        """Apply DataID only to protection groups that currently have dataid=None.

        Used for multi-channel fallback: CH1/CH2 borrow DataID from CH0
        for messages that couldn't find their own DataID but share the same
        (frame_id, checksum_signal_name) as CH0.

        Also copies profile info for matched entries.
        """
        applied = 0
        for prot_list in self.messages.values():
            for prot in prot_list:
                if prot.checksum_signal and prot.dataid is None:
                    dataid = dataid_map.get(prot.frame_id, prot.checksum_signal.name)
                    if dataid is not None:
                        prot.dataid = dataid
                        prot.crc_profile = dataid_map.get_profile(
                            prot.frame_id, prot.checksum_signal.name) or ""
                        applied += 1
        return applied

    def apply_profile_crc_params(self, default_params, profile_overrides=None):
        """Apply CRC params per protection group based on crc_profile.

        Protection groups with crc_profile containing "Profile 1" get
        CRC8/SAE-J1850-ZERO (init=0x00, xor=0x00). All others use the
        default params.

        Args:
            default_params: CRCParams for the default profile (e.g. Profile 5).
            profile_overrides: Optional dict mapping profile pattern → CRCParams.
                               Defaults to {"Profile 1": CRC8/SAE-J1850-ZERO}.
        """
        from crc_checker.crc.presets import get_preset

        if profile_overrides is None:
            profile_overrides = {
                "profile 1": get_preset("CRC8/SAE-J1850-ZERO"),
            }

        for prot_list in self.messages.values():
            for prot in prot_list:
                if prot.crc_profile and "profile 1" in prot.crc_profile.lower():
                    # Profile 1 → CRC8/SAE-J1850-ZERO
                    prot.crc_params = profile_overrides["profile 1"]
                else:
                    # Default → Profile 5 (CRC8/SAE-J1850)
                    prot.crc_params = default_params

    def apply_rc_config(self, max_valid: int | None = None):
        """Apply RC range config to all protection groups."""
        if max_valid is not None:
            for prot_list in self.messages.values():
                for prot in prot_list:
                    prot.rc_max_valid = max_valid

    def merge(self, other: "DBCProtectionMap") -> int:
        """Merge another DBCProtectionMap into this one.

        Within each frame_id, protection groups are merged by pair_suffix:
        existing suffixes are kept (first-wins), new suffixes are appended.

        Returns:
            Number of new protection groups added.
        """
        added = 0
        for frame_id, prot_list in other.messages.items():
            if frame_id in self.messages:
                existing_suffixes = {p.pair_suffix for p in self.messages[frame_id]}
                for prot in prot_list:
                    if prot.pair_suffix and prot.pair_suffix not in existing_suffixes:
                        self.messages[frame_id].append(prot)
                        existing_suffixes.add(prot.pair_suffix)
                        added += 1
            else:
                self.messages[frame_id] = list(prot_list)
                added += len(prot_list)
        self.dbc_paths.extend(other.dbc_paths)
        return added


class ChannelProtectionMap:
    """Wraps per-channel DBC protection maps for multi-channel trace verification.

    Each channel has its own DBC; frames are looked up by (channel, frame_id).
    """

    def __init__(self):
        self._maps: dict[int, DBCProtectionMap] = {}
        self._fallback: DBCProtectionMap | None = None

    def set_channel(self, channel: int, pm: DBCProtectionMap):
        """Assign a DBC protection map to a specific channel."""
        self._maps[channel] = pm

    def set_fallback(self, pm: DBCProtectionMap):
        """Set fallback DBC for channels without an explicit mapping."""
        self._fallback = pm

    def get_protections(self, frame_id: int, channel: int = 0) -> list[MessageProtection]:
        """Get protection groups for a frame, using channel-specific DBC."""
        pm = self._maps.get(channel, self._fallback)
        if pm is None:
            return []
        return pm.get_protections(frame_id)

    @property
    def dbc_paths(self) -> list[str]:
        """All DBC paths across all channels."""
        seen = set()
        paths = []
        for pm in self._maps.values():
            for p in pm.dbc_paths:
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        if self._fallback:
            for p in self._fallback.dbc_paths:
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        return paths

    @property
    def dbc_path(self) -> str:
        """Backward-compat: joined display string of all DBC paths."""
        return ", ".join(self.dbc_paths)

    @property
    def messages(self) -> dict[int, list[MessageProtection]]:
        """Flattened view for backward compat (engine pre-population)."""
        result: dict[int, list[MessageProtection]] = {}
        for pm in self._maps.values():
            for fid, prots in pm.messages.items():
                if fid not in result:
                    result[fid] = prots
        if self._fallback:
            for fid, prots in self._fallback.messages.items():
                if fid not in result:
                    result[fid] = prots
        return result

    def apply_crc_params(self, params):
        """Apply CRC parameters to all channel maps."""
        for pm in self._maps.values():
            pm.apply_crc_params(params)
        if self._fallback:
            self._fallback.apply_crc_params(params)

    def apply_crc_range(self, crc_range):
        """Apply CRC range to all channel maps."""
        for pm in self._maps.values():
            pm.apply_crc_range(crc_range)
        if self._fallback:
            self._fallback.apply_crc_range(crc_range)

    def apply_dataid_map(self, dataid_map):
        """Apply DataID map to all channel maps."""
        for pm in self._maps.values():
            pm.apply_dataid_map(dataid_map)
        if self._fallback:
            self._fallback.apply_dataid_map(dataid_map)

    def apply_dataid_map_fallback(self, dataid_map) -> int:
        """Apply DataID as fallback to all channel maps (only where dataid=None)."""
        applied = 0
        for pm in self._maps.values():
            applied += pm.apply_dataid_map_fallback(dataid_map)
        if self._fallback:
            applied += self._fallback.apply_dataid_map_fallback(dataid_map)
        return applied

    def apply_profile_crc_params(self, default_params, profile_overrides=None):
        """Apply profile-based CRC params to all channel maps."""
        for pm in self._maps.values():
            pm.apply_profile_crc_params(default_params, profile_overrides)
        if self._fallback:
            self._fallback.apply_profile_crc_params(default_params, profile_overrides)

    def apply_rc_config(self, max_valid=None):
        """Apply RC config to all channel maps."""
        for pm in self._maps.values():
            pm.apply_rc_config(max_valid)
        if self._fallback:
            self._fallback.apply_rc_config(max_valid)
