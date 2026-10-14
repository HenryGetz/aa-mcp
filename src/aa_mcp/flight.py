"""Parsing helpers for Next.js RSC flight payloads (raw or embedded in HTML).

Artificial Analysis serves React Server Component (RSC) flight data. With the
``RSC: 1`` header the raw payload is returned; without it the same data is
embedded inside the rendered HTML as ``self.__next_f.push([1, "..."])`` chunks.

Nothing in this module touches the network or stdout.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Iterable

__all__ = [
    "payload",
    "find_array",
    "find_arrays",
    "find_objects",
    "keyed_object",
    "jsonld",
    "text_strip_tags",
]

_WS = " \t\r\n"
_DECODER = json.JSONDecoder()

_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def payload(text: str) -> str:
    """Return the concatenated flight payload from raw RSC text or full HTML."""
    if "self.__next_f.push" not in text:
        return text

    chunks: list[str] = []
    needle = "self.__next_f.push("
    i = 0
    n = len(text)
    while True:
        j = text.find(needle, i)
        if j < 0:
            break
        k = j + len(needle)
        while k < n and text[k] in _WS:
            k += 1
        if k < n and text[k] == "[":
            try:
                value, end = _DECODER.raw_decode(text, k)
            except ValueError:
                value, end = None, k
            if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str):
                chunks.append(value[1])
                i = end
                continue
        i = k + 1
    return "".join(chunks)


def _scan(payload_text: str, required: frozenset[str], min_len: int, start: int):
    """Yield every array of dicts whose first item contains all ``required`` keys."""
    n = len(payload_text)
    i = start
    while i < n:
        j = payload_text.find("[", i)
        if j < 0:
            return
        k = j + 1
        while k < n and payload_text[k] in _WS:
            k += 1
        if k < n and payload_text[k] == "{":
            try:
                value, _end = _DECODER.raw_decode(payload_text, j)
            except ValueError:
                value = None
            if (
                isinstance(value, list)
                and len(value) >= min_len
                and value
                and isinstance(value[0], dict)
                and required <= value[0].keys()
            ):
                yield value
        i = j + 1


def find_array(
    payload: str,
    required: Iterable[str],
    *,
    min_len: int = 1,
    start: int = 0,
    last: bool = False,
) -> list[dict]:
    """First (or last) JSON array of dicts whose first item has all ``required``.

    Arrays may be nested inside larger flight structures (e.g. media pages wrap
    them as ``32:[[null,[{...}]]]``); the inner array is found by scanning for
    every ``[{`` anchor rather than only top-level rows.
    """
    req = frozenset(required)
    result: list[dict] | None = None
    for value in _scan(payload, req, min_len, start):
        if not last:
            return value
        result = value
    if result is None:
        raise LookupError(
            f"no JSON array of dicts containing keys {sorted(req)} in payload"
            + (f" (min_len={min_len})" if min_len != 1 else "")
        )
    return result


def find_arrays(
    payload: str, required: Iterable[str], *, min_len: int = 1
) -> list[list[dict]]:
    """Every array of dicts whose first item contains all ``required`` keys."""
    req = frozenset(required)
    return list(_scan(payload, req, min_len, 0))


def _enclosing_object_start(payload: str, pos: int) -> int | None:
    """Index of the ``{`` of the object that directly contains the key at ``pos``."""
    i = pos - 1
    depth = 0
    while i >= 0:
        c = payload[i]
        if c == '"':
            # closing quote of a preceding string token: skip to its opener
            j = i - 1
            while j >= 0:
                if payload[j] == '"':
                    k = j - 1
                    bs = 0
                    while k >= 0 and payload[k] == "\\":
                        bs += 1
                        k -= 1
                    if bs % 2 == 0:
                        break
                j -= 1
            if j < 0:
                return None
            i = j - 1
            continue
        if c in "}]":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
        elif c == "[":
            if depth == 0:
                return None
            depth -= 1
        i -= 1
    return None


def find_objects(
    payload: str,
    required: Iterable[str],
    *,
    limit: int | None = None,
) -> list[dict]:
    """Return every JSON object in ``payload`` containing ALL ``required`` keys.

    Unlike :func:`find_array` this does not require the objects to sit inside an
    array, which matters for the homepage where eval panels are embedded as
    ``["$","$L7b",null,{"evalSlug":"...","models":[...]}]``. To stay fast on
    multi-megabyte payloads the scan is driven by occurrences of the first
    required key: its directly enclosing object is located by a cheap backward
    scan and decoded at most once, so no large object is re-parsed.
    """
    req = list(required)
    if not req:
        return []
    for k in req:
        if '"' + k + '"' not in payload:
            return []

    anchor = '"' + req[0] + '"'
    out: list[dict] = []
    decoded: set[int] = set()
    i = payload.find(anchor)
    while i >= 0:
        j = _enclosing_object_start(payload, i)
        if j is not None and j not in decoded:
            decoded.add(j)
            try:
                value, _end = _DECODER.raw_decode(payload, j)
            except ValueError:
                value = None
            if isinstance(value, dict) and all(k in value for k in req):
                out.append(value)
                if limit is not None and len(out) >= limit:
                    return out
        i = payload.find(anchor, i + len(anchor))
    return out


def keyed_object(payload: str, key: str) -> dict | None:
    """Return the object value of ``"key":{...}`` in a flight payload.

    Occurrences of ``"key"`` inside unrelated strings are skipped: decoding
    starts at the nearest following ``{`` and the result must be a dict.
    """
    needle = '"' + key + '":'
    n = len(payload)
    i = 0
    while True:
        j = payload.find(needle, i)
        if j < 0:
            return None
        k = j + len(needle)
        while k < n and payload[k] in _WS:
            k += 1
        if k < n and payload[k] == "{":
            try:
                value, _end = _DECODER.raw_decode(payload, k)
            except ValueError:
                value = None
            if isinstance(value, dict):
                return value
        i = j + 1


def jsonld(text: str) -> list[dict]:
    """Extract JSON-LD blocks from a page.

    For HTML, every ``<script type="application/ld+json">`` block is parsed and
    flattened to a list of dicts. For a raw RSC payload (no script tags, as the
    media pages return them) the embedded JSON-LD objects have no wrapper, so
    this falls back to :func:`find_objects` looking for ``@type`` +
    ``acceptedAnswer`` (the FAQPage ``Question`` objects that carry the leader
    and its score).
    """
    out: list[dict] = []
    if "application/ld+json" in text:
        for raw in _JSONLD_RE.findall(text):
            raw = raw.strip()
            if not raw:
                continue
            try:
                value: Any = json.loads(raw)
            except ValueError:
                continue
            if isinstance(value, dict):
                out.append(value)
            elif isinstance(value, list):
                out.extend(item for item in value if isinstance(item, dict))
    if not out:
        out = find_objects(text, ("@type", "acceptedAnswer"))
    return out


def text_strip_tags(text: str) -> str:
    """Strip HTML tags, unescape entities and collapse whitespace."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
