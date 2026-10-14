"""Tests for the fetch/cache layer (offline + local HTTP server only)."""

from __future__ import annotations

import gzip
import http.server
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


class _Server:
    def __init__(self, body: bytes, *, gzip_body: bool = False):
        self.body = body
        self.gzip_body = gzip_body
        self.headers: dict[str, str] = {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("AA_OFFLINE", raising=False)
    monkeypatch.delenv("AA_CACHE_TTL", raising=False)
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
    path = pathlib.Path(env) / "lb.rsc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("cached-body", encoding="utf-8")
    os.utime(path, (time.time(), time.time()))
    f = fetch.get(_bogus_url(), "lb")
    assert f.cached is True and f.stale is False
    assert f.text == "cached-body"


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

    def read(self):
        return self._body

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
