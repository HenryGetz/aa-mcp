"""Parsing helpers for Next.js RSC flight payloads (raw or embedded in HTML).

Artificial Analysis serves React Server Component (RSC) flight data. With the
``RSC: 1`` header the raw payload is returned; without it the same data is
embedded inside the rendered HTML as ``self.__next_f.push([1, "..."])`` chunks.

Nothing in this module touches the network or stdout.

The expensive work — joining HTML chunks and scanning a multi-megabyte payload
for its record arrays — is memoised on a *content address* (``len`` + ``hash``),
because callers re-read the same page into a fresh ``str`` on every call.  The
memos are bounded (entry count and a rough byte budget) and thread-safe.
"""

from __future__ import annotations

import html
import json
import re
import threading
from collections.abc import Iterable
from typing import Any

__all__ = [
    "find_array",
    "find_arrays",
    "find_arrays_at",
    "find_objects",
    "jsonld",
    "keyed_object",
    "payload",
    "text_strip_tags",
]

_WS = " \t\r\n"
_DECODER = json.JSONDecoder()

_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
#: array anchor: ``[`` then optional whitespace then a record ``{`` or a flight
#: reference string ``"``.  Matching the anchor in one C-level pass keeps a
#: pathological payload (megabytes of ``[``) from costing seconds in Python.
_ANCHOR_RE = re.compile(r'\[[ \t\r\n]*[{"\"]')


# --------------------------------------------------------------------------- #
# content-addressed memos
# --------------------------------------------------------------------------- #

#: Sentinel for "no entry"; cached values are never ``None``.
_MEMO_MISS = object()

#: Bound on the number of retained entries, and a rough byte budget (a decoded
#: 700-record array is ~6 MB, so the count alone would not cap memory).
_MEMO_MAXSIZE = 16
_MEMO_MAX_BYTES = 32 * 1024 * 1024
#: A decoded array occupies roughly twice the JSON text it was decoded from.
_DECODED_FACTOR = 2


class _Memo:
    """Bounded, thread-safe LRU of decoded flight values, keyed by content.

    The key is a *content address* — ``(len(text), hash(text), …)`` — never
    ``id(text)``: callers re-read the same multi-megabyte page into a fresh
    ``str`` on every call, so an identity key would always miss.  ``len`` plus the
    full 64-bit ``hash`` makes an accidental cross-payload collision irrelevant.

    The table is an immutable tuple rebound in a single assignment, so a
    concurrent reader always sees a complete snapshot, never a partial one.
    Readers are lock-free; writers serialize on a lock and eviction is by
    least-recent use (bounded by both an entry count and a rough byte budget).
    """

    __slots__ = ("_bytes", "_entries", "_lock", "_max_bytes", "_maxsize")

    def __init__(self, maxsize: int, max_bytes: int) -> None:
        self._maxsize = maxsize
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._entries: tuple[tuple[tuple, Any, int], ...] = ()
        self._bytes = 0

    def get(self, key: tuple) -> Any:
        entries = self._entries  # one atomic read of the published snapshot
        for index, (stored, value, _size) in enumerate(entries):
            if stored == key:
                if index + 1 != len(entries):
                    self._promote(key)
                return value
        return _MEMO_MISS

    def put(self, key: tuple, value: Any, size: int) -> None:
        with self._lock:
            entries = tuple(e for e in self._entries if e[0] != key)
            entries += ((key, value, size),)
            total = sum(e[2] for e in entries)
            while entries and (len(entries) > self._maxsize or total > self._max_bytes):
                total -= entries[0][2]
                entries = entries[1:]
            self._entries = entries
            self._bytes = total

    def clear(self) -> None:
        with self._lock:
            self._entries = ()
            self._bytes = 0

    def _promote(self, key: tuple) -> None:
        with self._lock:
            entries = self._entries
            for index, entry in enumerate(entries):
                if entry[0] == key:
                    if index + 1 != len(entries):
                        self._entries = entries[:index] + entries[index + 1:] + (entry,)
                    return


#: Joined HTML payloads (the raw-RSC passthrough is O(1) and needs no memo).
_PAYLOAD_MEMO = _Memo(8, 8 * 1024 * 1024)
#: ``(index, array)`` scan results — the expensive part on multi-MB payloads.
_SCAN_MEMO = _Memo(_MEMO_MAXSIZE, _MEMO_MAX_BYTES)


def _clear_memos() -> None:
    """Drop the flight memos (test hook; production never needs it)."""
    _PAYLOAD_MEMO.clear()
    _SCAN_MEMO.clear()


def _content_key(text: str, *rest: Any) -> tuple:
    """Content address for ``text`` plus the scan parameters that shaped the result."""
    return (len(text), hash(text), *rest)


def _join_chunks(text: str) -> str:
    """Concatenate the ``self.__next_f.push`` string chunks of an HTML page."""
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


def payload(text: str) -> str:
    """Return the concatenated flight payload from raw RSC text or full HTML.

    Raw RSC text is returned unchanged (O(1)); only the HTML chunk-join — the
    expensive branch — is memoised, keyed by the page content.
    """
    if "self.__next_f.push" not in text:
        return text

    key = _content_key(text)
    cached = _PAYLOAD_MEMO.get(key)
    if cached is not _MEMO_MISS:
        return cached
    joined = _join_chunks(text)
    _PAYLOAD_MEMO.put(key, joined, len(joined))
    return joined


#: How many leading elements the probe walks before giving up. It only needs the
#: first *dict* item, and real arrays lead with at most a handful of flight
#: references; the cap keeps a pathological array of strings from costing
#: thousands of decodes per anchor.
_PROBE_ELEMENTS = 32
#: Longest element the probe decodes. Chart records are ~1-2 kB, while the RSC
#: tree subtrees that dominate a page are megabytes; a decode of a truncated
#: slice simply fails, which is the right answer for "not a record".
_PROBE_WINDOW = 32768


def _first_dict(text: str, start: int) -> dict | None:
    """The first dict *element* of the array whose elements start at ``start``.

    Elements are decoded one at a time (from a bounded slice) and iteration stops
    at the first dict, so probing a huge array of strings, or a 200 kB RSC
    subtree, costs a few small bounded decodes instead of a full one.
    """
    n = len(text)
    i = start
    for _ in range(_PROBE_ELEMENTS):
        while i < n and (text[i] in _WS or text[i] == ","):
            i += 1
        if i >= n or text[i] == "]":
            return None
        try:
            value, end = _DECODER.raw_decode(text[i:i + _PROBE_WINDOW], 0)
        except ValueError:
            return None
        if isinstance(value, dict):
            return value
        i += end
    return None


def _scan(payload_text: str, required: frozenset[str], min_len: int, start: int):
    """Yield ``(index, array, span)`` for every array whose first *dict* item has ``required``.

    The anchor may be ``[`` followed by ``{`` (an array of records) **or** by
    ``"`` — model pages embed ``"initialModels":["<flight ref>", …]`` whose pool
    is ``[{…}, …]``, and requiring a dict *first item* hid both (audit H4).

    Only the first dict element is probed (:func:`_first_dict`); an array is
    decoded in full only once that probe carries every required key, which keeps
    the whole-file scan cheap on multi-megabyte payloads.  ``span`` is the length
    of the JSON text the array was decoded from, a cheap proxy for its memory.
    """
    for match in _ANCHOR_RE.finditer(payload_text, start):
        j = match.start()
        probe = _first_dict(payload_text, match.end() - 1)
        if probe is not None and required <= probe.keys():
            try:
                value, end = _DECODER.raw_decode(payload_text, j)
            except ValueError:
                value, end = None, j
            if isinstance(value, list) and len(value) >= min_len:
                yield j, value, end - j


def _matching(
    payload: str, required: frozenset[str], min_len: int, start: int
) -> list[tuple[int, list[dict]]]:
    """Every ``(index, array)`` :func:`_scan` finds, memoised by payload content.

    The key is the content address of ``payload`` plus the scan parameters, so a
    caller that re-read the same page (a fresh ``str``) reuses the decoded arrays
    instead of re-scanning megabytes of JSON.  The value is the *whole* match
    list, shared by :func:`find_array`, :func:`find_arrays` and
    :func:`find_arrays_at`, so one payload keeps a single decoded copy.
    """
    key = _content_key(payload, tuple(sorted(required)), min_len, start)
    cached = _SCAN_MEMO.get(key)
    if cached is not _MEMO_MISS:
        return cached
    pairs: list[tuple[int, list[dict]]] = []
    span = 0
    for j, value, width in _scan(payload, required, min_len, start):
        pairs.append((j, value))
        span += width
    _SCAN_MEMO.put(key, pairs, span * _DECODED_FACTOR)
    return pairs


def find_array(
    payload: str,
    required: Iterable[str],
    *,
    min_len: int = 1,
    start: int = 0,
    last: bool = False,
) -> list[dict]:
    """First (or last) JSON array of dicts whose first *dict* item has all ``required``.

    Arrays may be nested inside larger flight structures (e.g. media pages wrap
    them as ``32:[[null,[{...}]]]``); the inner array is found by scanning for
    every ``[`` anchor rather than only top-level rows.  An array may start with
    flight-reference strings — only its first *dict* element is probed for
    ``required`` (``"initialModels":["$e:…", {…}]``).

    The scan is memoised on the payload's content, so a caller that re-reads the
    same page (``server._prompt_speed``, the eval charts) does not pay the
    multi-megabyte scan twice.
    """
    req = frozenset(required)
    pairs = _matching(payload, req, min_len, start)
    if not pairs:
        raise LookupError(
            f"no JSON array of dicts containing keys {sorted(req)} in payload"
            + (f" (min_len={min_len})" if min_len != 1 else "")
        )
    return pairs[-1][1] if last else pairs[0][1]


def find_arrays(
    payload: str, required: Iterable[str], *, min_len: int = 1
) -> list[list[dict]]:
    """Every array of dicts whose first dict item contains all ``required`` keys."""
    req = frozenset(required)
    return [value for _index, value in _matching(payload, req, min_len, 0)]


def find_arrays_at(
    payload: str, required: Iterable[str], *, min_len: int = 1
) -> list[tuple[int, list[dict]]]:
    """Like :func:`find_arrays` but paired with the payload index of ``[``.

    Callers that must know *where* an array sits (the media arenas are told
    apart by the flight-row wrapper that precedes them) need the offset.
    """
    req = frozenset(required)
    return list(_matching(payload, req, min_len, 0))


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
