"""DataID mapping model and JSON serialization."""

from __future__ import annotations

import json
import re


def normalize_signal_key(name: str) -> str:
    """Normalize a signal/message name for fuzzy-but-exact DataID matching.

    DataID tables often name the CRC signal in a remark column
    ("CCU_1_CRC2") while the DBC spells it "CCU_1_CRC_2"; underscores and case
    are not significant, so both collapse to "ccu1crc2".
    """
    return re.sub(r'[^0-9a-z]', '', (name or '').lower())


class DataIDMap:
    """Maps (frame_id, checksum_signal_name) → 16-bit DataID value.

    Also stores optional profile info per entry (e.g. "Profile 1A").
    """

    def __init__(self, sheet_name: str = ""):
        self.sheet_name = sheet_name
        self._map: dict[tuple[int, str], int] = {}  # (frame_id, signal_name) → dataid
        self._profiles: dict[tuple[int, str], str] = {}  # (frame_id, signal_name) → profile
        self._frame_names: dict[tuple[int, str], str] = {}  # (frame_id, signal_name) → msg name
        # Normalized index: (frame_id, normalize_signal_key(name)) → dataid
        self._norm: dict[tuple[int, str], int] = {}
        self._norm_profiles: dict[tuple[int, str], str] = {}

    def add(self, frame_id: int, signal_name: str, dataid: int, profile: str = ""):
        """Register a DataID for a specific checksum signal.

        Args:
            frame_id: CAN arbitration ID.
            signal_name: Signal name from DBC (checksum or message name).
            dataid: 16-bit DataID value.
            profile: Optional profile hint (e.g. "Profile 1A", "Profile 5").
        """
        self._map[(frame_id, signal_name)] = dataid
        key = (frame_id, signal_name)
        if profile:
            self._profiles[key] = profile
        else:
            self._profiles.pop(key, None)
        norm_key = normalize_signal_key(signal_name)
        if norm_key:
            norm_pair = (frame_id, norm_key)
            self._norm[norm_pair] = dataid
            if profile:
                self._norm_profiles[norm_pair] = profile
            else:
                self._norm_profiles.pop(norm_pair, None)

    def get(self, frame_id: int, signal_name: str) -> int | None:
        """Get DataID for a frame/signal pair, or None if not found."""
        return self._map.get((frame_id, signal_name))

    def get_normalized(self, frame_id: int, signal_name: str) -> int | None:
        """Get DataID by normalized (underscore/case-insensitive) signal name."""
        return self._norm.get((frame_id, normalize_signal_key(signal_name)))

    def get_profile(self, frame_id: int, signal_name: str) -> str | None:
        """Get profile hint for a frame/signal pair, or None."""
        return self._profiles.get((frame_id, signal_name))

    def get_profile_normalized(self, frame_id: int, signal_name: str) -> str | None:
        """Get profile hint by normalized signal name, or None."""
        return self._norm_profiles.get((frame_id, normalize_signal_key(signal_name)))

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: tuple[int, str]) -> bool:
        return key in self._map

    def to_json(self, file_path: str, source: str = "", mapping: str = "",
                sheets: list[str] | None = None) -> None:
        """Serialize DataIDMap to a standardized JSON file.

        Args:
            file_path: Output JSON file path.
            source: Original Excel file path (for traceability).
            mapping: Column mapping name used.
            sheets: Sheet names that were parsed.
        """
        entries = []
        for (fid, sig), did in sorted(self._map.items()):
            entry = {
                "frame_id": f"0x{fid:03X}",
                "dataid": f"0x{did:04X}",
            }
            if sig:
                entry["signal_name"] = sig
            profile = self._profiles.get((fid, sig), "")
            if profile:
                entry["profile"] = profile
            frame_name = self._frame_names.get((fid, sig), "")
            if frame_name:
                entry["frame_name"] = frame_name
            entries.append(entry)
        data = {
            "format": "dataid_map_v2",
            "source": source,
            "mapping": mapping,
            "sheets": sheets or ([self.sheet_name] if self.sheet_name else []),
            "entries": entries,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, file_path: str) -> "DataIDMap":
        """Load a DataIDMap from a standardized JSON file.

        Supports v1 and v2 formats.

        Args:
            file_path: Path to the JSON file.

        Returns:
            DataIDMap with all entries loaded.

        Raises:
            ValueError: If the format version is unsupported.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fmt = data.get("format", "")
        if fmt not in ("dataid_map_v1", "dataid_map_v2"):
            raise ValueError(
                f"Unsupported DataID JSON format: '{fmt}'. "
                f"Expected 'dataid_map_v1' or 'dataid_map_v2'."
            )

        sheets = data.get("sheets", [])
        sheet_name = sheets[0] if sheets else ""
        result = cls(sheet_name=sheet_name)
        for entry in data.get("entries", []):
            fid = entry["frame_id"]
            did = entry["dataid"]
            if isinstance(fid, str):
                fid = int(fid, 16)
            if isinstance(did, str):
                did = int(did, 16)
            result.add(
                frame_id=fid,
                signal_name=entry.get("signal_name", ""),
                dataid=did,
                profile=entry.get("profile", ""),
            )
            # Store frame_name if present (v2)
            fname = entry.get("frame_name", "")
            if fname:
                key = (fid, entry.get("signal_name", ""))
                result._frame_names[key] = fname
        return result

    def update(self, other: "DataIDMap") -> int:
        """Merge another DataIDMap into this one.

        Duplicate keys are overwritten by the other (last-wins).

        Returns:
            Number of entries overwritten.
        """
        overwritten = 0
        for key, value in other._map.items():  # pylint: disable=protected-access
            if key in self._map:
                overwritten += 1
            self._map[key] = value
            profile = other._profiles.get(key, "")  # pylint: disable=protected-access
            if profile:
                self._profiles[key] = profile
            else:
                self._profiles.pop(key, None)
        # Merge normalized index (kept in sync with the exact map)
        for key, value in other._norm.items():  # pylint: disable=protected-access
            self._norm[key] = value
            profile = other._norm_profiles.get(key, "")  # pylint: disable=protected-access
            if profile:
                self._norm_profiles[key] = profile
            else:
                self._norm_profiles.pop(key, None)
        for key, fname in other._frame_names.items():  # pylint: disable=protected-access
            if fname:
                self._frame_names[key] = fname
        return overwritten
