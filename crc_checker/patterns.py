"""Configurable signal-name patterns.

The rules that decide whether a signal is a Checksum / CRC or a Rolling Counter
live in ``crc_checker/data/patterns.yaml`` rather than in code, so a new naming
convention is a configuration change. ``signals.patterns_file`` in the run
config can point at a different file; ``signals.checksum_pattern`` /
``signals.rc_pattern`` still accept a single custom regex that replaces the
whole prefix+suffix logic for that category.

Regex lists are combined with OR. A missing pattern list is treated as "never
match" instead of "match everything".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATTERNS_FILE = Path(__file__).resolve().parent / "data" / "patterns.yaml"

# Used only when the packaged YAML file is unavailable (e.g. a stripped build).
_FALLBACK: dict[str, Any] = {
    "checksum": {
        "prefix": [r"(?i)^(checksum|check_sum|crc|e2e_crc)"],
        "suffix": [
            r"(?i)(_crc$|_checksum$|_e2e_crc$|_crccheck$|_chks$|_chks[0-9]*$)"
        ],
    },
    "rolling_counter": {
        "prefix": [
            r"(?i)^(rolling.?counter|rolling_?cntr|rc_|live.?counter"
            r"|alive.?counter|alive_)"
        ],
        "suffix": [
            r"(?i)(_counter$|_alive$|_msgcntr$|_messagecounter$"
            r"|_message_counter$|_alivecounter$|_alivecnt$|_cntr$"
            r"|_rollgcntr$|_rollingcounter$)"
        ],
        "exclude": [r"(?i)block_?counter"],
    },
    "bus_suffix": r"_Can[0-9]+$",
    "detect": {"min_suffix_matches": 3},
}

_NEVER_MATCH = r"(?!x)x"


def _list_of_strings(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) for item in value):
        raise ValueError(f"pattern key {key!r} must be a string or a list of strings")
    return tuple(value)


def join_patterns(patterns: tuple[str, ...]) -> str:
    """OR the patterns; an empty list matches nothing."""
    if not patterns:
        return _NEVER_MATCH
    if len(patterns) == 1:
        return patterns[0]
    return "|".join(f"(?:{pattern})" for pattern in patterns)


@dataclass(frozen=True)
class NamingPatterns:  # pylint: disable=too-many-instance-attributes
    """Compiled signal-name rules (see ``crc_checker/data/patterns.yaml``)."""

    checksum_prefix: tuple[str, ...] = ()
    checksum_suffix: tuple[str, ...] = ()
    rolling_counter_prefix: tuple[str, ...] = ()
    rolling_counter_suffix: tuple[str, ...] = ()
    rolling_counter_exclude: tuple[str, ...] = ()
    bus_suffix: str = _NEVER_MATCH
    min_suffix_matches: int = 3

    checksum_re: re.Pattern = field(init=False, repr=False, compare=False)
    checksum_suffix_re: re.Pattern = field(init=False, repr=False, compare=False)
    rolling_counter_re: re.Pattern = field(init=False, repr=False, compare=False)
    rolling_counter_suffix_re: re.Pattern = field(
        init=False, repr=False, compare=False)
    exclude_re: re.Pattern = field(init=False, repr=False, compare=False)
    bus_suffix_re: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checksum_re",
                           re.compile(join_patterns(self.checksum_prefix)))
        object.__setattr__(self, "checksum_suffix_re",
                           re.compile(join_patterns(self.checksum_suffix)))
        object.__setattr__(self, "rolling_counter_re",
                           re.compile(join_patterns(self.rolling_counter_prefix)))
        object.__setattr__(self, "rolling_counter_suffix_re",
                           re.compile(join_patterns(self.rolling_counter_suffix)))
        object.__setattr__(self, "exclude_re",
                           re.compile(join_patterns(self.rolling_counter_exclude)))
        object.__setattr__(self, "bus_suffix_re", re.compile(self.bus_suffix))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NamingPatterns":
        """Build from the YAML structure (missing sections keep the defaults)."""
        if not isinstance(data, dict):
            raise ValueError("naming pattern file must contain a mapping")
        checksum = data.get("checksum") or {}
        counter = data.get("rolling_counter") or {}
        detect = data.get("detect") or {}
        return cls(
            checksum_prefix=_list_of_strings(checksum.get("prefix"), "checksum.prefix"),
            checksum_suffix=_list_of_strings(checksum.get("suffix"), "checksum.suffix"),
            rolling_counter_prefix=_list_of_strings(
                counter.get("prefix"), "rolling_counter.prefix"),
            rolling_counter_suffix=_list_of_strings(
                counter.get("suffix"), "rolling_counter.suffix"),
            rolling_counter_exclude=_list_of_strings(
                counter.get("exclude"), "rolling_counter.exclude"),
            bus_suffix=str(data.get("bus_suffix") or _NEVER_MATCH),
            min_suffix_matches=int(detect.get("min_suffix_matches", 3)),
        )

    def with_overrides(self, checksum_pattern: str | None = None,
                       rc_pattern: str | None = None) -> "NamingPatterns":
        """Return a copy whose custom regex replaces prefix+suffix matching.

        A custom regex is used with ``re.search`` over the whole name, matching
        the historical behaviour of ``signals.checksum_pattern``.
        """
        checksum_prefix = self.checksum_prefix
        checksum_suffix = self.checksum_suffix
        counter_prefix = self.rolling_counter_prefix
        counter_suffix = self.rolling_counter_suffix
        if checksum_pattern:
            checksum_prefix = (checksum_pattern,)
            checksum_suffix = ()
        if rc_pattern:
            counter_prefix = (rc_pattern,)
            counter_suffix = ()
        return NamingPatterns(
            checksum_prefix=checksum_prefix,
            checksum_suffix=checksum_suffix,
            rolling_counter_prefix=counter_prefix,
            rolling_counter_suffix=counter_suffix,
            rolling_counter_exclude=self.rolling_counter_exclude,
            bus_suffix=self.bus_suffix,
            min_suffix_matches=self.min_suffix_matches,
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"naming pattern file is not a mapping: {path}")
    return data


@lru_cache(maxsize=32)
def load_naming_patterns(path: str | Path | None = None) -> NamingPatterns:
    """Load naming patterns from ``path`` (default: the packaged YAML file)."""
    if path is None:
        if DEFAULT_PATTERNS_FILE.is_file():
            return NamingPatterns.from_dict(_load_yaml(DEFAULT_PATTERNS_FILE))
        return NamingPatterns.from_dict(_FALLBACK)

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"naming pattern file not found: {resolved}")
    try:
        return NamingPatterns.from_dict(_load_yaml(resolved))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid naming pattern file {resolved}: {exc}") from exc


DEFAULT_NAMING = load_naming_patterns()
