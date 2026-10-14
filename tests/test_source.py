"""Tests for source selection and the API→RSC downgrade in :mod:`aa_mcp.source`."""

from __future__ import annotations

import pytest

from aa_mcp import api, fetch, source


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AA_API_KEY", raising=False)
    monkeypatch.delenv("AA_SOURCE", raising=False)
    monkeypatch.setattr(source, "_probe_cache", None)
    monkeypatch.setattr(source, "_downgrade_logged", False)
    yield


def _counting_ok(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]

    def fake(refresh: bool = False):
        calls[0] += 1
        return []

    monkeypatch.setattr(api, "fetch_models_free", fake)
    return calls


def _counting_auth(monkeypatch: pytest.MonkeyPatch, status: int = 401) -> list[int]:
    calls = [0]

    def fake(refresh: bool = False):
        calls[0] += 1
        raise api.ApiAuthError("rejected", status=status)

    monkeypatch.setattr(api, "fetch_models_free", fake)
    return calls


# --------------------------------------------------------------------------- #
# AA_SOURCE matrix
# --------------------------------------------------------------------------- #


def test_no_key_auto_is_rsc(monkeypatch: pytest.MonkeyPatch) -> None:
    assert source.api_key() is None
    assert source.active_source() == "rsc"
    assert source.source_label() == "aa:rsc"


def test_key_auto_is_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    _counting_ok(monkeypatch)
    assert source.active_source() == "api"
    assert source.source_label() == "aa:api"


def test_forced_rsc_never_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setenv("AA_SOURCE", "rsc")
    calls = _counting_ok(monkeypatch)
    assert source.active_source() == "rsc"
    assert source.source_label() == "aa:rsc"
    assert calls[0] == 0


def test_forced_api_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_SOURCE", "api")
    with pytest.raises(fetch.AAFetchError) as excinfo:
        source.active_source()
    assert "AA_API_KEY" in str(excinfo.value)
    assert excinfo.value.hint == "set AA_API_KEY or use AA_SOURCE=rsc"


def test_forced_api_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setenv("AA_SOURCE", "api")
    _counting_ok(monkeypatch)
    assert source.active_source() == "api"


def test_unknown_mode_behaves_like_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setenv("AA_SOURCE", "banana")
    _counting_ok(monkeypatch)
    assert source.active_source() == "api"
    monkeypatch.delenv("AA_API_KEY")
    monkeypatch.setattr(source, "_probe_cache", None)
    assert source.active_source() == "rsc"


def test_api_key_whitespace_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "   ")
    assert source.api_key() is None


# --------------------------------------------------------------------------- #
# probing / downgrade
# --------------------------------------------------------------------------- #


def test_probe_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    calls = _counting_ok(monkeypatch)
    assert source.probe_api() == (True, "ok")
    assert source.probe_api() == (True, "ok")
    assert source.active_source() == "api"
    assert calls[0] == 1


def test_probe_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert source.probe_api() == (False, "no-key")


def test_auth_failure_downgrades_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "bad")
    calls = _counting_auth(monkeypatch, 401)
    assert source.active_source() == "rsc"
    assert source.active_source() == "rsc"
    assert calls[0] == 1  # cached probe; the API is not re-tried
    assert source._probe_cache == (False, "auth:401")
    assert source._downgrade_logged is True
    assert source.source_label() == "aa:rsc"


def test_forbidden_key_downgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "bad")
    calls = _counting_auth(monkeypatch, 403)
    assert source.active_source() == "rsc"
    assert calls[0] == 1
    assert source._probe_cache == (False, "auth:403")


def test_transport_failure_downgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    calls = [0]

    def fake(refresh: bool = False):
        calls[0] += 1
        raise fetch.AAFetchError("network down")

    monkeypatch.setattr(api, "fetch_models_free", fake)
    assert source.active_source() == "rsc"
    assert calls[0] == 1
    assert source._probe_cache == (False, "error:network down")


def test_probe_never_escapes_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")

    def fake(refresh: bool = False):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api, "fetch_models_free", fake)
    usable, reason = source.probe_api()
    assert usable is False
    assert reason.startswith("error:")
