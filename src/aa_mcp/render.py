"""Markdown rendering helpers (tables, header line, inline numbers).

Scraped values are untrusted text: :func:`table` neutralizes markdown structure
(``|``, backticks, newlines) and control characters and caps every cell, so a
hostile payload cannot forge table rows or blow up a response.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

__all__ = ["ago", "clean", "ctx", "header", "note", "num", "pct", "table", "usd"]

#: every rendered cell is capped at this many characters (ellipsis beyond)
MAX_CELL = 120

#: characters that would restructure a markdown table or inject markup
_CELL_REPLACE = {
    "|": "\\|",   # keep the cell inside its column
    "`": "'",     # no inline code spans
    "\t": " ",
    "\r": " ",
    "\n": " ",
    "<": "&lt;",
    ">": "&gt;",
}


def clean(value: Any, limit: int | None = MAX_CELL) -> str:
    """Return ``value`` as one sanitized markdown-safe line.

    Newlines/tabs/CRs collapse to spaces, ``|``/backticks/angle brackets are
    neutralized, other control characters and lone surrogates are dropped, and
    an over-long string is truncated with ``…``. Numbers pass through
    unchanged. ``limit=None`` disables truncation (sanitizing only).
    """
    text = "-" if value in (None, "") else str(value)
    out: list[str] = []
    for ch in text:
        repl = _CELL_REPLACE.get(ch)
        if repl is not None:
            out.append(repl)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F or 0xD800 <= ord(ch) <= 0xDFFF:
            out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    if limit is not None and len(text) > limit:
        text = text[: max(1, limit - 1)] + "…"
    return text


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a GitHub markdown table; empty ``rows`` returns ``""``.

    Every cell is passed through :func:`clean` (see :data:`MAX_CELL`).
    """
    rows = list(rows)
    if not rows:
        return ""
    headers = list(headers)
    if not headers:
        return ""
    lines = ["| " + " | ".join(clean(h) for h in headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    for row in rows:
        lines.append("| " + " | ".join(clean(c) for c in row) + " |")
    return "\n".join(lines)


def ago(ts: float | None) -> str:
    """Humanise an epoch timestamp as ``12m ago`` (s/m/h/d)."""
    if ts is None:
        return ""
    delta = time.time() - float(ts)
    if delta < 0:
        delta = 0.0
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def header(
    total: int | None,
    shown: int,
    *,
    count: str | None = None,
    note: str = "",
    source: str = "",
    as_of: float | None = None,
) -> str:
    """One-line table header, e.g. ``# 42/700 models · 3m ago · aa:rsc``.

    ``count`` overrides the ``shown/total`` left-hand text (the server passes a
    ready-made ``"15 of 270 scored (700 tracked)"``); ``note`` is appended to it
    with a space, matching the historical shape.
    """
    count_txt = count if count is not None else (
        f"{shown}/{total}" if total is not None else f"{shown}")
    left = f"{count_txt} {note}".strip()
    parts = [f"# {left}"]
    if as_of is not None:
        parts.append(ago(as_of))
    parts.append(f"aa:{source or 'rsc'}")
    return " · ".join(parts)


def note(lines: Sequence[str]) -> str:
    """Trailing footnote line(s), each prefixed with ``—``.

    Footnotes are authored text (tool code), so they keep their markdown;
    anything scraped or caller-supplied is passed through :func:`clean` where it
    is interpolated.
    """
    out = [f"— {line}" for line in lines if line]
    return "\n".join(out)


def num(v, digits: int = 1) -> str:
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def usd(v, digits: int = 2) -> str:
    if v is None:
        return "-"
    v = float(v)
    if 0 < abs(v) < 0.01:
        digits = 4
    return f"${v:.{digits}f}"


def pct(v, digits: int = 1) -> str:
    """Format a fraction (0-1) as a percentage."""
    if v is None:
        return "-"
    return f"{float(v) * 100:.{digits}f}%"


def ctx(v) -> str:
    """Compact context window: ``128000 -> 128k``, ``1000000 -> 1.0M``."""
    if v is None:
        return "-"
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}k"
    return str(int(v))
