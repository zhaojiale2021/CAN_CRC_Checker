"""DBC file parser — wraps canmatrix to extract protection signal information."""

from __future__ import annotations

import logging
from pathlib import Path

import canmatrix
import canmatrix.formats   # 子包不会随 `import canmatrix` 自动加载(canmatrix 1.2
#                          在 py3.10 上就没有),缺了这行 canmatrix.formats 会 AttributeError
from crc_checker.dbc.models import DBCProtectionMap
from crc_checker.dbc.resolver import SignalResolver
from crc_checker.patterns import NamingPatterns

logger = logging.getLogger("crc_checker")


class DBCParser:
    """Parses DBC files and extracts protection signal information."""

    def __init__(self, patterns: dict[str, str] | None = None,
                 use_suffix: bool | None = None,
                 naming: NamingPatterns | None = None):
        self._explicit_patterns = patterns
        self._explicit_suffix = use_suffix
        self._naming = naming
        self.resolver = SignalResolver(patterns, use_suffix=bool(use_suffix),
                                       naming=naming)

    @staticmethod
    def _collect_dbc_files(paths: list[str]) -> list[str]:
        """Expand a list of paths (files or directories) into a flat list of .dbc files.

        Directories are scanned for *.dbc (top-level only), sorted alphabetically.
        """
        result: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                dbc_files = sorted(path.glob("*.dbc"))
                if not dbc_files:
                    raise FileNotFoundError(f"No .dbc files found in directory: {p}")
                result.extend(str(f) for f in dbc_files)
            elif path.is_file():
                result.append(str(path))
            else:
                raise FileNotFoundError(f"DBC path not found: {p}")
        return result

    @staticmethod
    def _detect_encoding(dbc_path: str) -> str:
        """Guess the text encoding of a DBC file.

        DBCs come from many tools: most are ASCII/UTF-8, but matrices with
        Chinese comments are frequently saved as GBK. canmatrix falls back to
        latin-1, which turns the comments into mojibake and breaks
        comment-driven parsing (e.g. a "DataID:0x00EB" annotation).

        Returns:
            Name of the first codec that decodes the whole file strictly
            ("utf-8", "gbk"), else "latin-1" (never raises).
        """
        raw = Path(dbc_path).read_bytes()
        for encoding in ("utf-8", "gbk"):
            try:
                raw.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue
        return "latin-1"

    def parse(self, dbc_path: str) -> DBCProtectionMap:
        """Parse a DBC file and build the protection map.

        Args:
            dbc_path: Path to the .dbc file.

        Returns:
            DBCProtectionMap with all identified protection groups.
        """
        dbc_name = Path(dbc_path).name

        # Load DBC with canmatrix (loadp returns dict of name->CanMatrix).
        # Pass the detected encoding so non-ASCII comments survive the load.
        loaded = canmatrix.formats.loadp(
            dbc_path, dbcImportEncoding=self._detect_encoding(dbc_path))
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
                    "comment": getattr(sig, "comment", "") or "",
                })
            frames.append({
                "frame_id": frame.arbitration_id.to_compound_integer(),
                "frame_name": frame.name,
                "dlc": frame.size,
                "signals": signals,
            })

        # Auto-detect suffix-based naming if not explicitly set.
        use_suffix = self._explicit_suffix
        if use_suffix is None and not self._explicit_patterns:
            use_suffix = SignalResolver.detect_naming_convention(
                frames, self._naming)

        # Rebuild resolver with the correct suffix setting.
        resolver = SignalResolver(self._explicit_patterns,
                                  use_suffix=bool(use_suffix),
                                  naming=self._naming)

        prot_map = resolver.build_protection_map(frames)
        prot_map.dbc_paths = [dbc_path]
        # Tag each protection group with its source DBC
        for prot_list in prot_map.messages.values():
            for prot in prot_list:
                prot.dbc_source = dbc_name
        return prot_map

    def parse_multiple(self, paths: list[str]) -> DBCProtectionMap:
        """Parse multiple DBC files/directories and merge into one protection map.

        First-match-wins: the first DBC that defines a frame_id wins.
        """
        dbc_files = self._collect_dbc_files(paths)
        if not dbc_files:
            raise ValueError("No DBC files specified.")

        combined = self.parse(dbc_files[0])
        for dbc_file in dbc_files[1:]:
            other = self.parse(dbc_file)
            added = combined.merge(other)
            if added >= 0:
                logger.debug(
                    "DBC merge: added %d protection group(s) from %s",
                    added, dbc_file
                )
        return combined


def parse_dbc(dbc_path: str, patterns: dict[str, str] | None = None,
              naming: NamingPatterns | None = None) -> DBCProtectionMap:
    """Parse a single DBC file and get the protection map.

    Args:
        dbc_path: Path to a single .dbc file.
        patterns: Optional single-regex overrides per category.
        naming: Optional naming-pattern set (see ``crc_checker.patterns``).
    """
    parser = DBCParser(patterns, naming=naming)
    return parser.parse(dbc_path)


def parse_all_dbc(paths: list[str],
                  patterns: dict[str, str] | None = None,
                  naming: NamingPatterns | None = None) -> list[DBCProtectionMap]:
    """Parse multiple DBC files/directories, returning individual maps (no merge).

    Args:
        paths: List of .dbc files or directories.
        patterns: Optional single-regex overrides per category.
        naming: Optional naming-pattern set (see ``crc_checker.patterns``).
    """
    parser = DBCParser(patterns, naming=naming)
    files = parser._collect_dbc_files(paths)  # pylint: disable=protected-access
    return [parser.parse(f) for f in files]


def select_best_dbc(dbc_maps: list[DBCProtectionMap],
                     trace_ids: set[int]) -> tuple[DBCProtectionMap | None, int, int]:
    """Select the DBC with the most frame_ids present in the trace.

    Returns:
        Tuple of (best_map, matched_count, total_dbc_ids).
        Returns (None, 0, 0) if no DBC matches any trace frame.
    """
    best, best_matched = None, 0
    best_total = 0
    for pm in dbc_maps:
        dbc_ids = set(pm.all_frame_ids())
        if not dbc_ids:
            continue
        matched = len(dbc_ids & trace_ids)
        if matched > best_matched:
            best, best_matched = pm, matched
            best_total = len(dbc_ids)
    return best, best_matched, best_total


def select_best_dbc_per_channel(
    dbc_maps: list[DBCProtectionMap],
    channel_ids: dict[int, set[int]],
) -> dict[int, DBCProtectionMap]:
    """Select the best DBC for each channel independently.

    Args:
        dbc_maps: List of individual DBC protection maps.
        channel_ids: Dict of channel -> set of frame_ids seen in that channel.

    Returns:
        Dict of channel -> best DBCProtectionMap for that channel.
    """
    result: dict[int, DBCProtectionMap] = {}
    for ch, ids in channel_ids.items():
        best, _, _ = select_best_dbc(dbc_maps, ids)
        if best is not None:
            result[ch] = best
    return result


def sample_trace_channels(trace_path: str, max_frames: int = 500) -> dict[int, set[int]]:
    """Sample trace to collect unique CAN IDs per channel.

    Returns:
        Dict of channel -> set of unique arbitration_ids.
    """
    from collections import defaultdict  # pylint: disable=import-outside-toplevel
    from crc_checker.trace.reader import open_log_reader  # pylint: disable=import-outside-toplevel
    ch_ids: dict[int, set[int]] = defaultdict(set)
    reader = open_log_reader(trace_path)
    count = 0
    try:
        for msg in reader:
            if not msg.is_error_frame and not msg.is_remote_frame:
                ch_ids[msg.channel].add(msg.arbitration_id)
            count += 1
            if count >= max_frames:
                break
    finally:
        reader.stop()
    return dict(ch_ids)


def sample_trace_ids(trace_path: str, max_frames: int = 500) -> set[int]:
    """Sample the first N frames of a trace to collect unique CAN IDs."""
    from crc_checker.trace.reader import open_log_reader  # pylint: disable=import-outside-toplevel
    ids: set[int] = set()
    reader = open_log_reader(trace_path)
    count = 0
    try:
        for msg in reader:
            if not msg.is_error_frame and not msg.is_remote_frame:
                ids.add(msg.arbitration_id)
            count += 1
            if count >= max_frames:
                break
    finally:
        reader.stop()
    return ids
