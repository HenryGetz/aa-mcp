"""Tests for the fetch/cache layer (offline + local HTTP server only)."""

from __future__ import annotations

import contextlib
import gzip
import http.server
import json
import os
import pathlib
import threading
import time

import pytest

from aa_mcp import fetch

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _bogus_url() -> str:
    # Port 1 refuses connections -> URLError (transient).
    return "http://127.0.0.1:1/nope"


def _put(
    cache: pathlib.Path,
    name: str,
    text: str,
    *,
    url: str = "",
    schema: int | None = fetch._CACHE_SCHEMA,
    ext: str = ".rsc",
) -> pathlib.Path:
    """Write a cache entry (and, unless ``schema`` is None, its sidecar)."""
    path = pathlib.Path(cache) / f"{name}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if schema is not None:
        path.with_name(path.name + ".meta.json").write_text(
            json.dumps({"schema": schema, "written": time.time(), "url": url}),
            encoding="utf-8",
        )
    return path


class _Server:
    def __init__(self, body: bytes, *, gzip_body: bool = False):
        self.body = body
        self.gzip_body = gzip_body
        self.headers: dict[str, str] = {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.headers = {k.lower(): v for k, v in self.headers.items()}
                data = gzip.compress(outer.body) if outer.gzip_body else outer.body
                self.send_response(200)
                if outer.gzip_body:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # silence
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}/data"

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)


class _CountingServer:
    """HTTP server that counts hits and (optionally) stalls before replying."""

    def __init__(self, body: bytes = b"counted-body", *, delay: float = 0.0,
                 status: int = 200, hang: bool = False):
        self.body = body
        self.delay = delay
        self.status = status
        self.hang = hang
        self.hits = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with outer._lock:
                    outer.hits += 1
                if outer.hang:
                    time.sleep(30)  # never replies within the test's timeout
                    return
                if outer.delay:
                    time.sleep(outer.delay)
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                with contextlib.suppress(OSError):  # pragma: no cover - client gone
                    self.wfile.write(outer.body)

            def log_message(self, *args):  # silence
                pass

        self._lock = threading.Lock()
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}/data"

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("AA_OFFLINE", raising=False)
    monkeypatch.delenv("AA_CACHE_TTL", raising=False)
    monkeypatch.delenv("AA_MAX_BYTES", raising=False)
    monkeypatch.delenv("AA_HTTP_TIMEOUT", raising=False)
    monkeypatch.delenv("AA_HTTP_DEADLINE", raising=False)
    return tmp_path / "cache"


# --------------------------------------------------------------------------- #
# network
# --------------------------------------------------------------------------- #

def test_network_gzip_and_rsc_header(env):
    body = b"<html>hello</html>" * 100
    with _Server(body, gzip_body=True) as url:
        f = fetch.get(url, "page", rsc=True)
        assert f.text == body.decode()
        assert f.cached is False and f.stale is False
        assert f.path.name == "page.rsc"
        assert f.path.exists()
    # headers were captured by the handler (checked via a second request)
    srv = _Server(body, gzip_body=True)
    with srv as url:
        fetch.get(url, "page2", rsc=True)
        assert srv.headers.get("rsc") == "1"
        assert "gzip" in srv.headers.get("accept-encoding", "")
        assert "Mozilla" in srv.headers.get("user-agent", "")


def test_fresh_cache_avoids_network(env):
    path = _put(env, "lb", "cached-body", url=_bogus_url())
    os.utime(path, (time.time(), time.time()))
    f = fetch.get(_bogus_url(), "lb")
    assert f.cached is True and f.stale is False
    assert f.text == "cached-body"


def test_entry_without_sidecar_is_refetched_then_served_stale(env):
    # A hand-saved file (no sidecar) is usable but never treated as fresh: the
    # loader refetches once and only falls back to it when the network fails.
    path = _put(env, "lb", "hand-saved", schema=None)
    os.utime(path, (time.time(), time.time()))
    with _CountingServer(b"fresh-body") as url:
        f = fetch.get(url, "lb")
        assert f.cached is False and f.text == "fresh-body"
    assert fetch._read_meta(path)["schema"] == fetch._CACHE_SCHEMA

    _put(env, "other", "hand-saved", schema=None)
    f = fetch.get(_bogus_url(), "other")
    assert f.stale is True and f.text == "hand-saved"


def test_payload_from_another_url_is_never_used(env):
    path = _put(env, "lb", "poisoned", url="https://elsewhere.example/x")
    os.utime(path, (time.time(), time.time()))
    with pytest.raises(fetch.AAFetchError) as ei:
        fetch.get(_bogus_url(), "lb")
    assert "poisoned" not in str(ei.value)
    with _CountingServer(b"real-body") as url:
        f = fetch.get(url, "lb")
        assert f.text == "real-body"
        assert fetch._read_meta(path)["url"] == url


def test_stale_schema_is_refetched(env):
    _put(env, "lb", "old-schema", url=_bogus_url(), schema=fetch._CACHE_SCHEMA + 1)
    with _CountingServer(b"new-body") as url:
        f = fetch.get(url, "lb", ttl=10_000)
        assert f.cached is False and f.text == "new-body"


def test_offline_serves_hand_saved_file(env, monkeypatch):
    _put(env, "lb", "hand-saved", schema=None)
    monkeypatch.setenv("AA_OFFLINE", "1")
    f = fetch.get("https://artificialanalysis.ai/leaderboards/models", "lb")
    assert f.text == "hand-saved" and f.stale is False


def test_ttl_expiry_refetches(env):
    body = b"fresh"
    path = pathlib.Path(env) / "x.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old", encoding="utf-8")
    os.utime(path, (time.time() - 100, time.time() - 100))
    with _Server(body) as url:
        f = fetch.get(url, "x", ttl=10)
        assert f.cached is False
        assert f.text == "fresh"


# --------------------------------------------------------------------------- #
# offline
# --------------------------------------------------------------------------- #

def test_offline_missing_raises(env, monkeypatch):
    monkeypatch.setenv("AA_OFFLINE", "1")
    with pytest.raises(fetch.AAFetchError) as ei:
        fetch.get("https://artificialanalysis.ai/leaderboards/models", "leaderboard")
    err = ei.value
    assert err.url
    assert err.path == pathlib.Path(env) / "leaderboard.rsc"
    assert "browser" in err.hint and str(err.path) in err.hint


def test_offline_uses_cache(env, monkeypatch):
    path = pathlib.Path(env) / "home.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("saved-html", encoding="utf-8")
    monkeypatch.setenv("AA_OFFLINE", "1")
    f = fetch.get("https://artificialanalysis.ai/", "home")
    assert f.text == "saved-html"
    assert f.cached is True and f.stale is False


def test_offline_never_touches_network(env, monkeypatch):
    monkeypatch.setenv("AA_OFFLINE", "1")
    # A URL that would succeed if contacted; offline must refuse to fetch it.
    with _Server(b"should-not-be-read") as url:
        with pytest.raises(fetch.AAFetchError):
            fetch.get(url, "missing")


# --------------------------------------------------------------------------- #
# stale fallback
# --------------------------------------------------------------------------- #

def test_stale_served_when_network_fails(env):
    path = pathlib.Path(env) / "lb.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale-body", encoding="utf-8")
    os.utime(path, (time.time() - 10_000, time.time() - 10_000))
    f = fetch.get(_bogus_url(), "lb", ttl=1)
    assert f.stale is True and f.cached is True
    assert f.text == "stale-body"


def test_refresh_failure_serves_stale(env):
    path = pathlib.Path(env) / "lb.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("cached-body", encoding="utf-8")
    f = fetch.get(_bogus_url(), "lb", refresh=True)
    assert f.stale is True
    assert f.text == "cached-body"


def test_network_failure_without_cache_raises(env):
    with pytest.raises(fetch.AAFetchError) as ei:
        fetch.get(_bogus_url(), "nothing")
    assert ei.value.hint


# --------------------------------------------------------------------------- #
# min_bytes / housekeeping
# --------------------------------------------------------------------------- #

def test_min_bytes_rejects_truncated_body(env):
    with _Server(b"tiny") as url:
        with pytest.raises(fetch.AAFetchError):
            fetch.get(url, "lb", min_bytes=200_000)


def test_min_bytes_ignores_small_cache(env):
    path = pathlib.Path(env) / "lb.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("tiny", encoding="utf-8")
    os.utime(path, (time.time(), time.time()))
    body = b"x" * 300_000
    with _Server(body) as url:
        f = fetch.get(url, "lb", min_bytes=200_000)
    assert f.cached is False
    assert len(f.text) == 300_000


def test_cache_age_and_clear(env):
    path = pathlib.Path(env) / "lb.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("data", encoding="utf-8")
    os.utime(path, (time.time() - 120, time.time() - 120))
    age = fetch.cache_age("lb")
    assert age is not None and 110 < age < 200
    assert fetch.cache_age("missing") is None
    removed, freed = fetch.clear_cache()
    assert removed == 1 and freed == 4
    assert not path.exists()


# --------------------------------------------------------------------------- #
# custom headers
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def read(self, size: int = -1):
        if size is None or size < 0:
            body, self._body = self._body, b""
            return body
        body, self._body = self._body[:size], self._body[size:]
        return body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_headers_defaults_and_overrides(env, monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResp(b"api-body")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", fake_urlopen)

    f = fetch.get(
        "https://artificialanalysis.ai/api/v2/language/models",
        "api_models",
        rsc=False,
        headers={"x-api-key": "SECRET", "User-Agent": "custom/1.0"},
    )
    assert f.text == "api-body"
    h = captured["headers"]
    assert h["x-api-key"] == "SECRET"
    assert h["user-agent"] == "custom/1.0"          # user wins over default UA
    assert "gzip" in h["accept-encoding"]
    assert "rsc" not in h                           # rsc=False -> no RSC header


def test_headers_rsc_default_present(env, monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResp(b"rsc-body")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", fake_urlopen)
    fetch.get("https://artificialanalysis.ai/leaderboards/models", "lb_headers")
    assert captured["headers"]["rsc"] == "1"


def test_cache_dir_honours_env(env):
    assert fetch.cache_dir() == pathlib.Path(env)


# --------------------------------------------------------------------------- #
# name sanitization (A42/A43)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", [
    "../../x",
    "../../../../tmp/ESCAPED",
    "a/b",
    "a\\b",
    ".hidden",
    "",
    "..",
    "a" * 200,
    "x\x00y",
    "x\ny",
    "%2e%2e%2fx",
    "/abs/path",
    "a b",
])
def test_unsafe_cache_names_are_refused(env, name):
    with pytest.raises(ValueError) as ei:
        fetch.get("https://artificialanalysis.ai/evaluations/x", name)
    assert repr(name) in str(ei.value)
    # refused before any filesystem access: the cache dir is not even created
    assert not pathlib.Path(env).exists()


def test_unsafe_names_refused_by_cache_age(env):
    with pytest.raises(ValueError):
        fetch.cache_age("../../x")


def test_safe_names_are_accepted(env, monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(b"ok"))
    for name in ("leaderboard", "model_claude-opus-5-5", "eval_mlcr-aa",
                 "providers_model_flat", "media_text_to_speech", "a" * 120,
                 "a.b-c_d"):
        assert fetch.get("https://x/y", name).text == "ok"


# --------------------------------------------------------------------------- #
# bounded downloads (A27/A28)
# --------------------------------------------------------------------------- #

def test_gzip_bomb_is_refused(env, monkeypatch):
    monkeypatch.setenv("AA_MAX_BYTES", "100000")
    # ~5 MB of NUL compressed to ~5 kB: a 1000:1 bomb.
    with _Server(b"\x00" * 5_000_000, gzip_body=True) as url, \
            pytest.raises(fetch.AAFetchError) as ei:
        fetch.get(url, "bomb")
    assert "AA_MAX_BYTES" in str(ei.value)
    assert url in str(ei.value)
    assert not (pathlib.Path(env) / "bomb.rsc").exists()   # nothing cached


def test_oversized_plain_body_is_refused(env, monkeypatch):
    monkeypatch.setenv("AA_MAX_BYTES", "1000")
    with _Server(b"x" * 5000) as url, pytest.raises(fetch.AAFetchError) as ei:
        fetch.get(url, "big")
    assert "AA_MAX_BYTES" in str(ei.value)


def test_slow_upstream_is_bounded_and_not_retried(env, monkeypatch):
    monkeypatch.setenv("AA_HTTP_TIMEOUT", "0.4")
    srv = _CountingServer(hang=True)
    started = time.monotonic()
    with srv as url:
        try:
            fetch.get(url, "hang")
        except fetch.AAFetchError:
            pass
        else:  # pragma: no cover - the upstream never replies
            pytest.fail("a stalled upstream must raise")
        elapsed = time.monotonic() - started
        hits = srv.hits
    assert hits == 1, f"{hits} attempts against a stalled upstream"
    assert elapsed < 3.0, f"stalled {elapsed:.1f}s"


def test_total_deadline_caps_retries(env, monkeypatch):
    monkeypatch.setenv("AA_HTTP_TIMEOUT", "0.3")
    monkeypatch.setenv("AA_HTTP_DEADLINE", "0.5")
    with _CountingServer(status=500) as url:
        started = time.monotonic()
        with pytest.raises(fetch.AAFetchError):
            fetch.get(url, "boom")
        elapsed = time.monotonic() - started
    assert elapsed < 3.0, f"took {elapsed:.1f}s"


def test_retry_only_on_5xx_and_connect_errors(env, monkeypatch):
    monkeypatch.delenv("AA_HTTP_DEADLINE", raising=False)
    with _CountingServer(b"nope", status=404) as url:
        with pytest.raises(fetch.AAFetchError):
            fetch.get(url, "notfound")
        assert url
    # 5xx is retried once: two hits.
    srv = _CountingServer(b"nope", status=503)
    with srv as url:
        with pytest.raises(fetch.AAFetchError):
            fetch.get(url, "unavailable")
        assert srv.hits == 2


# --------------------------------------------------------------------------- #
# in-process single flight (A31/A33)
# --------------------------------------------------------------------------- #

def _hammer(fn, count: int) -> list:
    out: list = [None] * count
    start = threading.Barrier(count)

    def worker(i: int) -> None:
        start.wait()
        out[i] = fn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return out


def test_concurrent_cold_calls_share_one_download(env):
    srv = _CountingServer(b"shared-body", delay=0.3)
    with srv as url:
        results = _hammer(lambda: fetch.get(url, "shared"), 8)
    assert srv.hits == 1, f"{srv.hits} downloads for 8 concurrent calls"
    assert all(r.text == "shared-body" for r in results)
    assert all(r.stale is False for r in results)


def test_concurrent_refresh_calls_share_one_download(env):
    _put(env, "shared", "old-body", url="http://127.0.0.1:9/data")
    srv = _CountingServer(b"fresh-body", delay=0.3)
    with srv as url:
        results = _hammer(lambda: fetch.get(url, "shared", refresh=True), 8)
    assert srv.hits == 1, f"{srv.hits} downloads for 8 concurrent refreshes"
    assert all(r.text == "fresh-body" for r in results)


def test_sequential_refresh_refetches(env):
    srv = _CountingServer(b"body-1")
    with srv as url:
        fetch.get(url, "twice", refresh=True)
        fetch.get(url, "twice", refresh=True)
    assert srv.hits == 2


# --------------------------------------------------------------------------- #
# decoded-text memo
# --------------------------------------------------------------------------- #

def test_read_cache_reuses_the_identical_text(env):
    fetch._clear_memos()
    path = _put(env, "lb", "cached-body", url=_bogus_url())
    os.utime(path, (1_600_000_000, 1_600_000_000))
    assert fetch._read_cache(path) is fetch._read_cache(path)
    # the whole get() path reuses it too
    first = fetch.get(_bogus_url(), "lb", ttl=10 ** 9)
    second = fetch.get(_bogus_url(), "lb", ttl=10 ** 9)
    assert first.text is second.text


def test_cache_text_memo_invalidated_by_mtime(env):
    fetch._clear_memos()
    path = _put(env, "lb", "cached-body", url=_bogus_url())
    os.utime(path, (1_600_000_000, 1_600_000_000))
    assert fetch.get(_bogus_url(), "lb", ttl=10 ** 9).text == "cached-body"
    path.write_text("other-body!", encoding="utf-8")   # same length, new mtime
    os.utime(path, (1_600_000_100, 1_600_000_100))
    assert fetch.get(_bogus_url(), "lb", ttl=10 ** 9).text == "other-body!"


def test_cache_text_memo_rereads_a_truncated_file(env):
    fetch._clear_memos()
    path = _put(env, "lb", "cached-body", url=_bogus_url())
    os.utime(path, (1_600_000_000, 1_600_000_000))
    assert fetch.get(_bogus_url(), "lb", ttl=10 ** 9).text == "cached-body"
    path.write_text("truncated", encoding="utf-8")     # different size and mtime
    os.utime(path, (1_600_000_200, 1_600_000_200))
    assert fetch.get(_bogus_url(), "lb", ttl=10 ** 9).text == "truncated"


def test_cache_text_memo_is_not_served_across_refresh(env):
    fetch._clear_memos()
    srv = _CountingServer(b"fresh-body")
    with srv as url:
        path = _put(env, "shared", "stale-body", url=url)
        os.utime(path, (time.time(), time.time()))            # fresh (within TTL)
        assert fetch.get(url, "shared").text == "stale-body"  # memoised
        refreshed = fetch.get(url, "shared", refresh=True)    # must refetch
        assert refreshed.cached is False and refreshed.text == "fresh-body"
    assert srv.hits == 1
    assert fetch.get(url, "shared").text == "fresh-body"      # entry refreshed


def test_cache_text_memo_keeps_offline_behaviour(env, monkeypatch):
    fetch._clear_memos()
    path = _put(env, "lb", "hand-saved", schema=None)
    os.utime(path, (1_600_000_000, 1_600_000_000))
    monkeypatch.setenv("AA_OFFLINE", "1")
    url = "https://artificialanalysis.ai/leaderboards/models"
    first = fetch.get(url, "lb")
    assert first.text == "hand-saved" and first.stale is False
    assert fetch.get(url, "lb").text is first.text                # memo hit offline
    # offline still refuses an entry that is not cached
    with pytest.raises(fetch.AAFetchError):
        fetch.get(url, "missing")


def test_cache_text_memo_is_bounded(env):
    fetch._clear_memos()
    for i in range(fetch._TEXT_MEMO_MAXSIZE * 3):
        path = _put(env, f"page{i}", f"body-{i}", url=_bogus_url())
        os.utime(path, (1_600_000_000 + i, 1_600_000_000 + i))
        fetch.get(_bogus_url(), f"page{i}", ttl=10 ** 9)
    assert len(fetch._TEXT_MEMO._entries) <= fetch._TEXT_MEMO_MAXSIZE
    assert fetch._TEXT_MEMO._bytes <= fetch._TEXT_MEMO_MAX_BYTES


def test_text_memo_publication_is_thread_safe():
    memo = fetch._TextMemo(8, 1024 * 1024)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(500):
                memo.put((f"p{n % 16}", i, i), "x" * 16)
                memo.get((f"p{(n + i) % 16}", i, i))
        except BaseException as exc:  # pragma: no cover - a race would surface here
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(memo._entries) <= 8
    assert memo._bytes <= 1024 * 1024
