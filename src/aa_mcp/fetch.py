"""HTTP + on-disk cache for artificialanalysis.ai payloads.

Only stdlib is used (``urllib.request``). The cache lives in
``$AA_CACHE_DIR`` (default ``~/.cache/aa-mcp``) and every entry is a single
file named ``<name>.rsc`` (RSC payloads) or ``<name>.html`` (plain HTML), plus a
``<entry>.meta.json`` sidecar recording the schema version and the URL the
payload came from.

Cache entry names come from user input (``model_<slug>``, ``eval_<slug>`` …), so
:func:`get` validates the name as a single safe path segment before it touches
the filesystem (audit A42/A43) and the resolved path is checked to stay inside
:func:`cache_dir`.

The module never prints to stdout; diagnostics go to ``stderr`` via logging.

Decoded cache text is memoised in-process on ``(path, mtime_ns, size)`` so a warm
read returns the already-decoded ``str`` instead of re-reading a multi-megabyte
file; a rewrite changes the key and the memo is bounded (entry count + bytes).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "AAFetchError",
    "Fetched",
    "cache_age",
    "cache_dir",
    "clear_cache",
    "get",
]

log = logging.getLogger("aa_mcp.fetch")

_DEFAULT_TTL = 3600
_TIMEOUT = 30.0
_DEADLINE = 45.0
_BACKOFF = 0.7
_MAX_BYTES = 48 * 1024 * 1024
_CHUNK = 256 * 1024
#: decoded bytes produced per zlib call, so a bomb's working set stays ~the cap
_DECOMPRESS_CHUNK = 1024 * 1024
#: cache layout version; a payload whose sidecar does not carry it is refetched.
_CACHE_SCHEMA = 1

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

#: A cache name must be one safe path segment: no separators, no dot-prefix, no
#: ``..``, no NUL/newline, at most 120 chars.
_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")


class AAFetchError(RuntimeError):
    """Raised when data cannot be fetched and no usable cache exists."""

    def __init__(self, message: str, *, url: str = "", path=None, hint: str = ""):
        super().__init__(message)
        self.url = url
        self.path = pathlib.Path(path) if path is not None else None
        self.hint = hint


class _TooSmall(urllib.error.URLError):
    """Body shorter than ``min_bytes`` — usually bot mitigation; one retry is cheap."""


@dataclass(slots=True)
class Fetched:
    text: str
    path: pathlib.Path
    fetched_at: float
    cached: bool
    stale: bool


# --------------------------------------------------------------------------- #
# cache helpers
# --------------------------------------------------------------------------- #

def cache_dir() -> pathlib.Path:
    """Return the cache directory, creating it if necessary."""
    raw = os.environ.get("AA_CACHE_DIR")
    p = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".cache" / "aa-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_name(name: str) -> str:
    """Validate a cache entry name, returning it unchanged.

    Cache names are built from user input (model/eval slugs, board keys), so a
    name that is not a single safe path segment is a refusal, never a path:
    ``..``, ``/``, ``\\``, a leading dot, an absolute path, NUL/newline, more
    than 120 characters or any character outside ``[A-Za-z0-9._-]``.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name) or ".." in name:
        raise ValueError(
            f"unsafe cache name {name!r}: expected one path segment of "
            "[A-Za-z0-9._-] (no '/', no '..', no leading dot, <= 120 chars)"
        )
    return name


def _ttl(ttl: int | None) -> int:
    if ttl is not None:
        return int(ttl)
    raw = os.environ.get("AA_CACHE_TTL")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_TTL


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _timeout() -> float:
    """Per-attempt socket timeout (``AA_HTTP_TIMEOUT``, default 30 s)."""
    return _env_float("AA_HTTP_TIMEOUT", _TIMEOUT)


def _deadline() -> float:
    """Total budget for one :func:`get` (``AA_HTTP_DEADLINE``, default 45 s)."""
    return _env_float("AA_HTTP_DEADLINE", _DEADLINE)


def _max_bytes() -> int:
    """Decoded-body cap (``AA_MAX_BYTES``, default 48 MB)."""
    raw = os.environ.get("AA_MAX_BYTES")
    if raw:
        try:
            limit = int(raw)
        except ValueError:
            limit = _MAX_BYTES
        if limit > 0:
            return limit
    return _MAX_BYTES


def _offline() -> bool:
    return os.environ.get("AA_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _path_for(name: str, rsc: bool) -> pathlib.Path:
    cache_name(name)
    base = cache_dir()
    path = base / f"{name}{'.rsc' if rsc else '.html'}"
    resolved = path.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(
            f"unsafe cache name {name!r}: resolves outside the cache directory {base}"
        )
    return path


def _meta_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(path.name + ".meta.json")


def _read_meta(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(_meta_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cache_age(name: str) -> float | None:
    """Seconds since the cached entry was last written, or ``None``."""
    cache_name(name)
    for ext in (".rsc", ".html"):
        p = cache_dir() / f"{name}{ext}"
        if p.exists():
            try:
                return max(0.0, time.time() - p.stat().st_mtime)
            except OSError:
                return None
    return None


def clear_cache() -> tuple[int, int]:
    """Delete every cached file. Returns ``(files_removed, bytes_freed)``."""
    _TEXT_MEMO.clear()
    removed = 0
    freed = 0
    for p in cache_dir().iterdir():
        try:
            if p.is_file():
                freed += p.stat().st_size
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed, freed


# --------------------------------------------------------------------------- #
# network
# --------------------------------------------------------------------------- #

#: Bound on the decoded-text memo: an entry count plus a rough byte budget (a
#: 700-model page is ~3 MB of text, so the count alone would not cap memory).
_TEXT_MEMO_MAXSIZE = 24
_TEXT_MEMO_MAX_BYTES = 32 * 1024 * 1024
_TEXT_MEMO_MISS = object()


class _TextMemo:
    """Bounded, thread-safe LRU of decoded cache-file text.

    Keyed by ``(path, mtime_ns, size)`` — a rewrite changes the key, so a stale
    entry is never served.  The table is an immutable tuple rebound in a single
    assignment, so a concurrent reader always sees a complete snapshot; readers
    are lock-free and writers serialise on a lock (eviction is by least-recent
    use, bounded by both an entry count and a rough byte budget).
    """

    __slots__ = ("_bytes", "_entries", "_lock", "_max_bytes", "_maxsize")

    def __init__(self, maxsize: int, max_bytes: int) -> None:
        self._maxsize = maxsize
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._entries: tuple[tuple[tuple[str, int, int], str, int], ...] = ()
        self._bytes = 0

    def get(self, key: tuple[str, int, int]) -> str | object:
        entries = self._entries  # one atomic read of the published snapshot
        for index, (stored, text, _size) in enumerate(entries):
            if stored == key:
                if index + 1 != len(entries):
                    self._promote(key)
                return text
        return _TEXT_MEMO_MISS

    def put(self, key: tuple[str, int, int], text: str) -> None:
        size = len(text)
        with self._lock:
            entries = tuple(e for e in self._entries if e[0] != key)
            entries += ((key, text, size),)
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

    def _promote(self, key: tuple[str, int, int]) -> None:
        with self._lock:
            entries = self._entries
            for index, entry in enumerate(entries):
                if entry[0] == key:
                    if index + 1 != len(entries):
                        self._entries = entries[:index] + entries[index + 1:] + (entry,)
                    return


_TEXT_MEMO = _TextMemo(_TEXT_MEMO_MAXSIZE, _TEXT_MEMO_MAX_BYTES)


def _clear_memos() -> None:
    """Drop the decoded-text memo (test hook; production never needs it)."""
    _TEXT_MEMO.clear()


def _cache_key(path: pathlib.Path, st: os.stat_result) -> tuple[str, int, int]:
    return (str(path), st.st_mtime_ns, st.st_size)


def _memo_store(path: pathlib.Path, text: str) -> None:
    """Record freshly written text so the next read does not touch the disk."""
    try:
        st = path.stat()
    except OSError:  # pragma: no cover - the write just happened
        return
    _TEXT_MEMO.put(_cache_key(path, st), text)


def _read_cache(path: pathlib.Path) -> str | None:
    """Return the cache file's text, reusing the decoded ``str`` when unchanged.

    The memo key is ``(path, mtime_ns, size)``, so a rewrite (or a
    ``refresh=True`` refetch) invalidates it.  A file that changes while we read
    it is returned but not memoised — the key would no longer describe the bytes
    we decoded.
    """
    try:
        before = path.stat()
    except OSError:
        return None
    key = _cache_key(path, before)
    cached = _TEXT_MEMO.get(key)
    if cached is not _TEXT_MEMO_MISS:
        return cached
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        after = path.stat()
    except OSError:
        return None
    if (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size):
        _TEXT_MEMO.put(key, text)
    return text


def _read_body(resp, limit: int, url: str) -> bytes:
    """Read ``resp`` in chunks, refusing a body past ``limit`` bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AAFetchError(
                f"body for {url} exceeds the {limit} byte cap (AA_MAX_BYTES)",
                url=url,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decompress_capped(raw: bytes, limit: int, url: str) -> bytes:
    """gunzip ``raw`` incrementally, refusing more than ``limit`` decoded bytes.

    ``gzip.decompress`` on the whole body is what let a 60 kB gzip bomb expand to
    ~182 MB of RSS (audit A28).  Output is produced in bounded chunks, so the
    peak working set is the cap itself plus one chunk, never a second copy.
    """
    obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    data = raw
    while data:
        room = min(limit - len(out) + 1, _DECOMPRESS_CHUNK)
        out += obj.decompress(data, room)
        if len(out) > limit:
            raise AAFetchError(
                f"body for {url} decompresses past the {limit} byte cap (AA_MAX_BYTES)",
                url=url,
            )
        data = obj.unconsumed_tail
    out += obj.flush()
    if len(out) > limit:
        raise AAFetchError(
            f"body for {url} decompresses past the {limit} byte cap (AA_MAX_BYTES)",
            url=url,
        )
    return bytes(out)


def _download(
    url: str,
    rsc: bool,
    extra_headers: Mapping[str, str] | None = None,
    *,
    timeout: float,
) -> str:
    """Fetch ``url`` once (no retry) and return the decoded body text."""
    headers = {
        "User-Agent": _UA,
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
    }
    if rsc:
        headers["RSC"] = "1"
    if extra_headers:
        headers.update(extra_headers)
    limit = _max_bytes()
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        raw = _read_body(resp, limit, url)
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        if raw[:2] != b"\x1f\x8b":
            raise urllib.error.URLError(f"body for {url} claims gzip but is not")
        raw = _decompress_capped(raw, limit, url)
    return raw.decode("utf-8", errors="replace")


def _is_transient(exc: BaseException) -> bool:
    """Whether a failed attempt is worth exactly one more try.

    Timeouts are **not** retried (a 60 s timeout retried once stalled a tool for
    two minutes, audit A27); neither are 4xx responses, bad gzip bodies or
    cache/validation errors.  Connect errors and HTTP 5xx are.
    """
    if isinstance(exc, _TooSmall):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, TimeoutError):
        return False
    if isinstance(exc, urllib.error.URLError):
        return not isinstance(exc.reason, TimeoutError)
    return False


def _hint(url: str, path: pathlib.Path) -> str:
    return (
        f"render {url} in a browser and save the HTML at {path}, then retry "
        f"(AA_OFFLINE=1 will use the saved file without a network call)"
    )


def _write_atomic(path: pathlib.Path, text: str) -> None:
    import fcntl

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        with contextlib.suppress(OSError):  # pragma: no cover - best-effort lock
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _write_meta(path: pathlib.Path, url: str) -> None:
    """Record the payload's provenance next to it (schema, write time, URL)."""
    payload = json.dumps(
        {"schema": _CACHE_SCHEMA, "written": time.time(), "url": url},
        ensure_ascii=False,
    )
    try:
        _write_atomic(_meta_path(path), payload)
    except OSError:  # pragma: no cover - a cache we cannot annotate is still usable
        log.warning("could not write cache metadata for %s", path)


# --------------------------------------------------------------------------- #
# in-process single flight
# --------------------------------------------------------------------------- #

class _Flight:
    """One in-process lock per cache name, plus the last completed fetch."""

    __slots__ = ("done_at", "lock", "url")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.url = ""
        self.done_at = 0.0


_FLIGHT_GUARD = threading.Lock()
_FLIGHT: dict[str, _Flight] = {}


def _flight(name: str) -> _Flight:
    with _FLIGHT_GUARD:
        state = _FLIGHT.get(name)
        if state is None:
            state = _Flight()
            _FLIGHT[name] = state
        return state


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def get(
    url: str,
    name: str,
    *,
    refresh: bool = False,
    rsc: bool = True,
    ttl: int | None = None,
    min_bytes: int = 0,
    headers: Mapping[str, str] | None = None,
) -> Fetched:
    """Return the payload for ``url``, transparently using the disk cache.

    ``AA_OFFLINE=1`` forces cache-only mode: the network is never touched and a
    missing cache raises :class:`AAFetchError`. On a network failure a cached
    copy is served with ``stale=True`` when available.

    The cache is untrusted input: an entry whose sidecar says it came from a
    different URL is never used, and an entry without a current-schema sidecar is
    refetched once (a hand-saved ``AA_OFFLINE`` file still works, it is just not
    treated as fresh). Concurrent calls for the same ``name`` share one download.

    A ``ValueError`` is raised for a ``name`` that is not a single safe path
    segment; that check happens before any filesystem access.

    ``headers`` are merged over the defaults (browser UA, ``Accept-Encoding:
    gzip`` and ``RSC: 1`` when ``rsc=True``); user-supplied values win on key
    collision, so callers can pass API keys or override the ``User-Agent``.
    """
    cache_name(name)
    started = time.monotonic()
    state = _flight(name)
    with state.lock:
        if state.done_at >= started and state.url == url:
            # A call that started before we acquired the lock already fetched
            # this payload; coalesce instead of downloading it again (A31/A33).
            path = _path_for(name, rsc)
            text = _read_cache(path)
            if text is not None:
                return Fetched(text, path, path.stat().st_mtime, True, False)
        return _get_locked(
            url, name, refresh=refresh, rsc=rsc, ttl=ttl,
            min_bytes=min_bytes, headers=headers, state=state, started=started,
        )


def _get_locked(
    url: str,
    name: str,
    *,
    refresh: bool,
    rsc: bool,
    ttl: int | None,
    min_bytes: int,
    headers: Mapping[str, str] | None,
    state: _Flight,
    started: float,
) -> Fetched:
    path = _path_for(name, rsc)
    cache_ttl = _ttl(ttl)
    offline = _offline()

    cached_text = _read_cache(path) if path.exists() else None
    if cached_text is not None and min_bytes and len(cached_text) < min_bytes:
        # A truncated/partial cache is no better than no cache.
        log.warning("cache entry %s is smaller than min_bytes, ignoring", path)
        cached_text = None

    # Provenance: a payload whose stored URL differs from the requested one must
    # never be used; a payload without a current-schema sidecar is stale.
    alien = False
    verified = False
    if cached_text is not None:
        meta = _read_meta(path)
        if meta is not None:
            if meta.get("url") not in (None, url):
                log.warning(
                    "cache entry %s was written for %s, not %s: ignoring it",
                    path, meta.get("url"), url,
                )
                alien = True
            verified = not alien and meta.get("schema") == _CACHE_SCHEMA

    if cached_text is not None and not refresh and verified:
        age = max(0.0, time.time() - path.stat().st_mtime)
        if age <= cache_ttl:
            return Fetched(cached_text, path, path.stat().st_mtime, True, False)

    usable = None if alien else cached_text

    if offline:
        if usable is not None:
            return Fetched(usable, path, path.stat().st_mtime, True, False)
        raise AAFetchError(
            f"offline mode (AA_OFFLINE=1) and no usable cache for {name}",
            url=url,
            path=path,
            hint=_hint(url, path),
        )

    if cached_text is not None and not alien and not verified:
        log.info("cache entry %s has no usable provenance metadata; refetching", path)

    deadline = _deadline()
    last_exc: BaseException | None = None
    for attempt in range(2):
        remaining = deadline - (time.monotonic() - started)
        if remaining <= 0:
            last_exc = TimeoutError(f"total budget of {deadline:.0f}s exceeded")
            break
        try:
            body = _download(
                url, rsc, headers, timeout=min(_timeout(), remaining)
            )
            if min_bytes and len(body) < min_bytes:
                raise _TooSmall(
                    f"body too small ({len(body)} < {min_bytes}); possible bot mitigation"
                )
            _write_atomic(path, body)
            _write_meta(path, url)
            _memo_store(path, body)  # refresh the entry: the next read is free
            state.url = url
            state.done_at = time.monotonic()
            return Fetched(body, path, time.time(), False, False)
        except AAFetchError:
            raise
        except BaseException as exc:
            last_exc = exc
            if attempt == 0 and _is_transient(exc):
                time.sleep(_BACKOFF)
                continue
            break

    if usable is not None:
        log.warning(
            "network fetch for %s failed (%s); serving stale cache %s",
            url,
            last_exc,
            path,
        )
        return Fetched(usable, path, path.stat().st_mtime, True, True)

    raise AAFetchError(
        f"failed to fetch {url}: {last_exc}",
        url=url,
        path=path,
        hint=_hint(url, path),
    )
