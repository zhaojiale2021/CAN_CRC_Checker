"""Match DataID workbook sheets to DBC filenames."""

from __future__ import annotations

import re


def match_sheet_to_dbc(dbc_name: str, sheet_names: list[str]) -> str | None:  # pylint: disable=too-many-locals,too-many-branches
    """Find the sheet name that best matches a DBC filename.

    Uses token matching + substring bonus.
    Returns the best-matching sheet, or None if no match.

    Fallback: if no token matches, prefers sheets containing "Config"
    over "History" / "Revision".
    """

    def _weight(tok: str) -> float:
        # Alphabetic tokens are stronger signals than pure numbers
        if tok.isdigit():
            return 0.4
        return 1.0

    def _tokenize(name: str) -> tuple[set[str], str]:
        # Remove extension
        cleaned = re.sub(r'\.(dbc|xlsx)$', '', name, flags=re.IGNORECASE).lower()
        tokens = set()
        for part in re.split(r'[\s_\-\.]+', cleaned):
            part = part.strip()
            if part:
                tokens.add(part)
        return tokens, cleaned

    dbc_tokens, dbc_clean = _tokenize(dbc_name)
    if not dbc_tokens:
        return None

    best, best_score = None, -1.0
    for sname in sheet_names:
        sheet_tokens, sheet_clean = _tokenize(sname)
        # Exact token matches (primary)
        exact_set = dbc_tokens & sheet_tokens
        exact = sum(_weight(t) for t in exact_set)
        bonus = 0.0
        # Substring bonus: only for tokens >= 4 chars, not exact matches,
        # and not substrings of any token on the other side.
        for st in sheet_tokens:
            if len(st) >= 4 and st not in exact_set and st in dbc_clean:
                if not any(st in dt for dt in dbc_tokens if len(dt) > len(st)):
                    bonus += 0.3 * _weight(st)
        for dt in dbc_tokens:
            if len(dt) >= 4 and dt not in exact_set and dt in sheet_clean:
                if not any(dt in st for st in sheet_tokens if len(st) > len(dt)):
                    bonus += 0.3 * _weight(dt)
        score = exact + bonus
        if score > best_score:
            best, best_score = sname, score

    # Fallback: if no token match, prefer sheets containing "Config" over "History"
    if best_score <= 0:
        for sname in sheet_names:
            sname_lower = sname.lower()
            if "config" in sname_lower and "history" not in sname_lower:
                return sname
        # Last resort: first sheet that's not "History"/"Revision"
        for sname in sheet_names:
            sname_lower = sname.lower()
            if "history" not in sname_lower and "revision" not in sname_lower:
                return sname

    return best
