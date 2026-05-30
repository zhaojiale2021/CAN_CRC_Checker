"""DBC file parser — wraps canmatrix to extract protection signal information."""

from __future__ import annotations

import canmatrix
from crc_checker.dbc.models import DBCProtectionMap
from crc_checker.dbc.resolver import SignalResolver


class DBCParser:
    """Parses DBC files and extracts protection signal information."""

    def __init__(self, patterns: dict[str, str] | None = None):
        self.resolver = SignalResolver(patterns)

    def parse(self, dbc_path: str) -> DBCProtectionMap:
        """Parse a DBC file and build the protection map.

        Args:
            dbc_path: Path to the .dbc file.

        Returns:
            DBCProtectionMap with all identified protection groups.
        """
        # Load DBC with canmatrix (loadp returns dict of name->CanMatrix)
        loaded = canmatrix.formats.loadp(dbc_path)
        db = list(loaded.values())[0]

        # Convert to frame dicts for resolver
        frames = []
        for frame in db.frames:
            signals = []
            for sig in frame.signals:
                signals.append({
                    "name": sig.name,
                    "start_bit": sig.get_startbit(),
                    "length": sig.size,
                    "byte_order": "little_endian" if sig.is_little_endian else "big_endian",
                })
            frames.append({
                "frame_id": frame.arbitration_id.to_compound_integer(),
                "frame_name": frame.name,
                "dlc": frame.size,
                "signals": signals,
            })

        prot_map = self.resolver.build_protection_map(frames)
        prot_map.dbc_path = dbc_path
        return prot_map


def parse_dbc(dbc_path: str, patterns: dict[str, str] | None = None) -> DBCProtectionMap:
    """Convenience function to parse a DBC file and get the protection map."""
    parser = DBCParser(patterns)
    return parser.parse(dbc_path)
