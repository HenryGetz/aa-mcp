"""Tests for the free-tier JSON API source (:mod:`aa_mcp.api`).

No live API key exists on this machine, so authentication/envelope handling is
exercised with a static fixture derived from the OpenAPI spec
(``tests/fixtures/openapi.yaml``, example ``free_tier``) and with a
monkeypatched ``fetch.get``.  401/403 downgrade behaviour lives in
``tests/test_source.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aa_mcp import api, fetch

FIXTURES = Path(__file__).parent / "fixtures"
_SAMPLE = json.loads((FIXTURES / "api_models_free.json").read_text(encoding="utf-8"))


def _payload() -> dict:
    return json.loads(json.dumps(_SAMPLE))  # defensive copy


def _faked(text: str, calls: list | None = None):
    def fake_get(url, name, *, refresh=False, rsc=True, ttl=None, min_bytes=0, headers=None):
        if calls is not None:
            calls.append({"url": url, "name": name, "rsc": rsc, "ttl": ttl, "headers": headers})
        return fetch.Fetched(text=text, path=Path("/fake") / name, fetched_at=0.0, cached=True, stale=False)

    return fake_get


# --------------------------------------------------------------------------- #
# pure parsing
# --------------------------------------------------------------------------- #


def test_envelope_unwrap() -> None:
    models = api.parse_models_free(_payload())
    assert len(models) == 3
    assert [m.slug for m in models] == ["gpt-oss-20b", "unmeasured-model", "llama-4-1-405b"]


def test_full_model_mapping() -> None:
    model = api.parse_models_free(_payload())[0]
    assert model.name == "gpt-oss-20B (high)"
    assert model.source == "api"
    assert model.creator == "OpenAI"
    assert model.creator_slug is None  # FreeModelCreator carries no slug
    assert model.release_date == "2025-08-05"
    assert model.intelligence == 24.5
    assert model.indices["intelligence"] == 24.5
    assert model.indices["coding"] == 18.5
    assert model.indices["agentic"] == 27.6
    assert model.pricing == {
        "in": 0.06,
        "out": 0.2,
        "cache_read": 0.015,
        "cache_write": 0.075,
    }
    assert model.speed == {"tps": 296.47, "ttft": 0.65, "ttfa": 7.4, "e2e": 9.09}
    assert model.cost_per_task == 0.1678
    assert model.evals == {}
    assert model.is_open_weights is None  # free shape omits licensing → unknown, not False


def test_capability_indices() -> None:
    model = api.parse_models_free(_payload())[0]
    caps = {k: v for k, v in model.indices.items() if k.startswith("capabilities.")}
    assert caps == {
        "capabilities.financeAndAccounting": 7.3,
        "capabilities.strategyAndOps": 4.8,
        "capabilities.legal": 7.3,
        "capabilities.healthcareAndMedical": 6.6,
        "capabilities.engineering": 11.7,
        "capabilities.economics": 11.3,
    }


def test_nulls_become_none_not_zero() -> None:
    model = api.parse_models_free(_payload())[1]
    assert model.release_date is None
    assert model.creator is None
    assert model.intelligence is None
    assert all(v is None for v in model.indices.values())
    assert all(v is None for v in model.pricing.values())
    assert all(v is None for v in model.speed.values())
    assert model.cost_per_task is None


def test_null_cost_per_task() -> None:
    model = api.parse_models_free(_payload())[2]
    assert model.name == "Llama 4.1 405B (instruct)"
    assert model.creator == "Meta"
    assert model.cost_per_task is None  # cost_per_task object present but null
    assert model.pricing["cache_read"] is None


def test_non_dict_payload() -> None:
    assert api.parse_models_free(None) == []
    assert api.parse_models_free({"data": "nope"}) == []


# --------------------------------------------------------------------------- #
# HTTP wiring (monkeypatched fetch.get; no network)
# --------------------------------------------------------------------------- #


def test_fetch_models_free_url_name_ttl_and_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.delenv("AA_API_TTL", raising=False)
    calls: list = []
    monkeypatch.setattr(api.fetch, "get", _faked(json.dumps(_SAMPLE), calls))

    models = api.fetch_models_free()

    assert len(models) == 3
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == api.MODELS_FREE_URL
    assert call["name"] == "api_models_free"
    assert call["rsc"] is False
    assert call["ttl"] == api.DEFAULT_API_TTL
    assert call["headers"] == {"x-api-key": "test"}


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setenv("AA_API_TTL", "123")
    calls: list = []
    monkeypatch.setattr(api.fetch, "get", _faked(json.dumps(_SAMPLE), calls))
    api.fetch_models_free()
    assert calls[0]["ttl"] == 123


def test_pagination_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    page1 = _payload()
    page1["pagination"]["has_more"] = True
    page2 = _payload()
    page2["data"] = [page2["data"][0]]
    calls: list = []

    def fake_get(url, name, *, refresh=False, rsc=True, ttl=None, min_bytes=0, headers=None):
        calls.append(url)
        text = json.dumps(page1 if url == api.MODELS_FREE_URL else page2)
        return fetch.Fetched(text=text, path=Path("/fake") / name, fetched_at=0.0, cached=True, stale=False)

    monkeypatch.setattr(api.fetch, "get", fake_get)
    models = api.fetch_models_free()
    assert len(models) == 4  # 3 + 1
    assert calls == [api.MODELS_FREE_URL, api.MODELS_FREE_URL + "?page=2"]


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AA_API_KEY", raising=False)
    with pytest.raises(fetch.AAFetchError) as excinfo:
        api.fetch_models_free()
    assert "AA_API_KEY" in str(excinfo.value)
    assert excinfo.value.hint


def test_auth_error_converted_from_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "bad")

    def boom(url, name, *, refresh=False, rsc=True, ttl=None, min_bytes=0, headers=None):
        raise fetch.AAFetchError(f"failed to fetch {url}: HTTP Error 401: Unauthorized")

    monkeypatch.setattr(api.fetch, "get", boom)
    with pytest.raises(api.ApiAuthError) as excinfo:
        api.fetch_models_free()
    assert excinfo.value.status == 401
    assert isinstance(excinfo.value, fetch.AAFetchError)
    assert "AA_API_KEY" in excinfo.value.hint


def test_non_json_payload_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setattr(api.fetch, "get", _faked("<html>nope</html>"))
    with pytest.raises(fetch.AAFetchError):
        api.fetch_models_free()


# --------------------------------------------------------------------------- #
# loader integration
# --------------------------------------------------------------------------- #


def test_leaderboard_uses_api_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    from aa_mcp import loaders, source

    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setattr(source, "_probe_cache", None)
    monkeypatch.setattr(api, "fetch_models_free", lambda refresh=False: api.parse_models_free(_payload()))
    monkeypatch.setattr(loaders.fetch, "get", _faked(json.dumps(_SAMPLE)))

    models = loaders.leaderboard()
    assert [m.source for m in models] == ["api", "api", "api"]
    assert loaders.data_source() == "aa:api"


def test_aa_source_rsc_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from aa_mcp import loaders, source

    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setenv("AA_SOURCE", "rsc")
    monkeypatch.setattr(source, "_probe_cache", None)

    def forbidden(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("API must not be touched when AA_SOURCE=rsc")

    monkeypatch.setattr(api, "fetch_models_free", forbidden)
    cipher = (FIXTURES / "leaderboard.rsc").read_text(encoding="utf-8")
    monkeypatch.setattr(loaders.fetch, "get", _faked(cipher))

    assert len(loaders.leaderboard()) == 700
    assert loaders.data_source() == "aa:rsc"


def test_aa_source_api_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from aa_mcp import source

    monkeypatch.delenv("AA_API_KEY", raising=False)
    monkeypatch.setenv("AA_SOURCE", "api")
    monkeypatch.setattr(source, "_probe_cache", None)
    with pytest.raises(fetch.AAFetchError) as excinfo:
        source.active_source()
    assert "AA_API_KEY" in str(excinfo.value)
    assert source.source_label() == "aa:rsc"


def test_licensing_read_when_payload_provides_it() -> None:
    payload = _payload()
    payload["data"][0]["licensing"] = {"is_open_weights": True}
    assert api.parse_models_free(payload)[0].is_open_weights is True

    payload = _payload()
    payload["data"][0]["is_open_weights"] = False
    assert api.parse_models_free(payload)[0].is_open_weights is False


def test_free_shape_leaves_licensing_unknown() -> None:
    assert all(m.is_open_weights is None for m in api.parse_models_free(_payload()))
