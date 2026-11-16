"""Shared file-type constants for the CLI, config loader and web layer."""

from __future__ import annotations

TRACE_EXTENSIONS = frozenset({
    ".blf", ".asc", ".mf4", ".trc", ".csv", ".log", ".txt",
})
DBC_EXTENSIONS = frozenset({".dbc"})
DATAID_EXTENSIONS = frozenset({".json", ".xlsx", ".xls"})
