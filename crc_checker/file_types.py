"""Shared file-type constants for the CLI, config loader and web layer."""

from __future__ import annotations

TRACE_EXTENSIONS = frozenset({
    # Formats python-can's LogReader dispatches (``.db`` = SQLite, ``.log`` =
    # canutils). ``.mdf`` is routed to MF4Reader explicitly in the trace
    # reader. ``.txt`` is deliberately absent: python-can has no reader for it.
    ".blf", ".asc", ".mf4", ".mdf", ".trc", ".csv", ".log", ".db",
})
DBC_EXTENSIONS = frozenset({".dbc"})
DATAID_EXTENSIONS = frozenset({".json", ".xlsx", ".xls"})
