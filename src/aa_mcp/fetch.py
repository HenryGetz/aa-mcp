"""HTTP + on-disk cache for artificialanalysis.ai payloads.

Only stdlib is used (``urllib.request``). The cache lives in
``$AA_CACHE_DIR`` (default ``~/.cache/aa-mcp``) and every entry is a single
file named ``<name>.rsc`` (RSC payloads) or ``<name>.html`` (plain HTML).

The module never prints to stdout; diagnostics go to ``stderr`` via logging.
"""

from __future__ import annotations

import gzip
import logging
import os
import pathlib
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "AAFetchError",
    "Fetched",
    "get",
    "cache_dir",
    "clear_cache",
    "cache_age",
]

log = logging.getLogger("aa_mcp.fetch")

_DEFAULT_TTL = 3600
_TIMEOUT = 60.0
_BACKOFF = 0.7
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class AAFetchError(RuntimeError):
    """Raised when data cannot be fetched and no usable cache exists."""

    def __init__(self, message: str, *, url: str = "", path=None, hint: str = ""):
        super().__init__(message)
        self.url = url
        self.path = pathlib.Path(path) if path is not None else None
        self.hint = hint


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


def _offline() -> bool:
    return os.environ.get("AA_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _path_for(name: str, rsc: bool) -> pathlib.Path:
    return cache_dir() / f"{name}{'.rsc' if rsc else '.html'}"


def cache_age(name: str) -> float | None:
    """Seconds since the cached entry was last written, or ``None``."""
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

def _read_cache(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _download(url: str, rsc: bool, extra_headers: dict | None = None) -> str:
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
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    if isinstance(exc, gzip.BadGzipFile):
        return True
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
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
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

    ``headers`` are merged over the defaults (browser UA, ``Accept-Encoding:
    gzip`` and ``RSC: 1`` when ``rsc=True``); user-supplied values win on key
    collision, so callers can pass API keys or override the ``User-Agent``.
    """
    path = _path_for(name, rsc)
    cache_ttl = _ttl(ttl)
    offline = _offline()

    cached_text = _read_cache(path) if path.exists() else None
    if cached_text is not None and len(cached_text) < min_bytes and min_bytes:
        # A truncated/partial cache is no better than no cache.
        log.warning("cache entry %s is smaller than min_bytes, ignoring", path)
        cached_text = None

    if cached_text is not None and not refresh:
        age = max(0.0, time.time() - path.stat().st_mtime)
        if age <= cache_ttl:
            return Fetched(cached_text, path, path.stat().st_mtime, True, False)

    if offline:
        if cached_text is not None:
            return Fetched(cached_text, path, path.stat().st_mtime, True, False)
        raise AAFetchError(
            f"offline mode (AA_OFFLINE=1) and no usable cache for {name}",
            url=url,
            path=path,
            hint=_hint(url, path),
        )

    last_exc: BaseException | None = None
    for attempt in range(2):
        try:
            body = _download(url, rsc, headers)
            if min_bytes and len(body) < min_bytes:
                raise urllib.error.URLError(
                    f"body too small ({len(body)} < {min_bytes}); possible bot mitigation"
                )
            _write_atomic(path, body)
            return Fetched(body, path, time.time(), False, False)
        except BaseException as exc:  # noqa: BLE001 - classified below
            last_exc = exc
            if attempt == 0 and _is_transient(exc):
                time.sleep(_BACKOFF)
                continue
            break

    if cached_text is not None:
        log.warning(
            "network fetch for %s failed (%s); serving stale cache %s",
            url,
            last_exc,
            path,
        )
        return Fetched(cached_text, path, path.stat().st_mtime, True, True)

    raise AAFetchError(
        f"failed to fetch {url}: {last_exc}",
        url=url,
        path=path,
        hint=_hint(url, path),
    )
