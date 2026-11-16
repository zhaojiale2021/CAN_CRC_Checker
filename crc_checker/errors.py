"""Shared exception types.

They subclass the built-ins they replace (``ValueError`` / ``KeyError``) so
existing ``except`` clauses keep working while callers can catch a single
semantic type.
"""

from __future__ import annotations


class CheckerError(Exception):
    """Base class for errors caused by user input or input data."""


class ConfigError(CheckerError, ValueError):
    """The JSON configuration could not be loaded or is invalid."""


class PresetError(CheckerError, KeyError):
    """An unknown CRC/checksum preset name was requested."""


class VerificationError(CheckerError):
    """The verification run itself failed."""
