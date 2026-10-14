"""Markdown rendering helpers (tables, header line, inline numbers)."""

from __future__ import annotations

import time
from typing import Sequence

__all__ = ["table", "header", "note", "num", "usd", "pct", "ctx", "ago"]


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a GitHub markdown table; empty ``rows`` returns ``""``."""
    rows = list(rows)
    if not rows:
        return ""
    headers = list(headers)
    if not headers:
        return ""
    lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
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
    note: str = "",
    source: str = "",
    as_of: float | None = None,
) -> str:
    """One-line table header, e.g. ``# 42/700 models · 3m ago · aa:rsc``."""
    count = f"{shown}/{total}" if total is not None else f"{shown}"
    left = f"{count} {note}".strip()
    parts = [f"# {left}"]
    if as_of is not None:
        parts.append(ago(as_of))
    parts.append(f"aa:{source or 'rsc'}")
    return " · ".join(parts)


def note(lines: Sequence[str]) -> str:
    """Trailing footnote line(s), each prefixed with ``—``."""
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
