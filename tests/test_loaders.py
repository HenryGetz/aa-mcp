"""Offline tests for :mod:`aa_mcp.loaders` — every surface, fixture-backed.

Counts and spot values come from the real 2026-10-14 captures in
``tests/fixtures/``.  Parsing is exercised directly through the ``parse_*``
functions; the loader wrappers are exercised with ``fetch.get`` monkeypatched to
serve the same fixtures, so nothing here touches the network.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

from aa_mcp import fetch, flight, loaders, source

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _force_rsc_source(monkeypatch: pytest.MonkeyPatch):
    """These fixtures exercise the RSC path; keep the dual source inert."""
    monkeypatch.delenv("AA_API_KEY", raising=False)
    monkeypatch.delenv("AA_SOURCE", raising=False)
    monkeypatch.delenv("AA_BASE_URL", raising=False)
    monkeypatch.delenv("AA_OFFLINE", raising=False)
    monkeypatch.setattr(source, "_probe_cache", None)
    yield


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# leaderboard / model pages
# --------------------------------------------------------------------------- #


def test_leaderboard_count() -> None:
    models = loaders.parse_leaderboard(_text("leaderboard.rsc"))
    assert len(models) == 700
    assert all(m.slug for m in models)


def test_model_chart_set() -> None:
    models = loaders.parse_chart(_text("model_page_chart.rsc"))
    slugs = [m.slug for m in models]
    assert len(models) == 27
    assert "claude-fable-5-1" in slugs


def test_legacy_model_page() -> None:
    model = loaders.parse_legacy_model(_text("model_page_legacy.rsc"))
    assert model is not None
    assert model.slug == "glm-4-5v"
    assert model.source == "legacy"


def test_chart_without_initial_models_is_empty() -> None:
    # T7: a page with no usable chart array yields [] instead of crashing.
    assert loaders.parse_chart('<script>{"currentModel":{"slug":"x"}}</script>') == []


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #


def test_provider_endpoints_spot_values() -> None:
    endpoints = loaders.parse_provider_endpoints(_text("providers_model.rsc"))
    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep.host == "Novita"
    assert ep.host_slug == "novita"
    assert ep.model_slug == "glm-4-5v"
    assert ep.precision is None
    assert ep.price_in == 0.6
    assert ep.price_out == 1.8
    assert ep.cache_read == 0.11
    assert ep.function_calling is True
    assert ep.json_mode is True
    assert ep.cost_per_task is None
    assert ep.source == "providers_model"


def test_provider_board_counts() -> None:
    endpoints = loaders.parse_provider_board(_text("providers_board.rsc"))
    assert len(endpoints) == 1201
    assert len({e.model_slug for e in endpoints}) == 453
    assert len({e.host_slug for e in endpoints}) == 64


def test_provider_board_spot_row() -> None:
    endpoints = loaders.parse_provider_board(_text("providers_board.rsc"))
    ep = next(e for e in endpoints if e.host == "Novita" and e.model_slug == "glm-4-5v")
    assert ep.model_name == "GLM-4.5V (non-reasoning)"
    assert ep.price_in == 0.6
    assert ep.price_out == 1.8
    assert ep.cache_read == 0.11
    assert ep.context_tokens == 65536
    assert ep.openai_compatible is True
    assert ep.source == "providers_board"


# --------------------------------------------------------------------------- #
# homepage boards
# --------------------------------------------------------------------------- #


def test_home_boards_counts_and_order() -> None:
    boards = loaders.parse_home_boards(_text("home.rsc"))
    assert len(boards["stt"]) == 15
    assert len(boards["stt_streaming"]) == 28
    assert len(boards["sts"]) == 15
    assert set(boards) >= {
        "eval:artificial-analysis-cyber-index",
        "eval:cwe-bench-aa",
        "eval:deepsecbench-aa",
        "eval:cybergym-e2e-aa",
    }
    assert all(len(boards[k]) == 20 for k in boards if k.startswith("eval:"))

    wer = [m["werIndex"] for m in boards["stt"]]
    assert wer == sorted(wer)
    sts = [m["stsIndex"] for m in boards["sts"]]
    assert sts == sorted(sts, reverse=True)


# --------------------------------------------------------------------------- #
# media arenas
# --------------------------------------------------------------------------- #


def _jsonld_leader(text: str) -> tuple[str, int]:
    """Leader + Elo as stated by the page's own embedded JSON-LD FAQ."""
    payload = flight.payload(text)
    questions = flight.find_array(payload, ("@type", "acceptedAnswer"))
    for question in questions:
        block = question.get("acceptedAnswer") or {}
        match = re.search(
            r"^(.+?) currently leads .*? Elo score of (\d+)", block.get("text", "")
        )
        if match:
            return match.group(1).strip(), int(match.group(2))
    raise AssertionError("no JSON-LD 'currently leads' answer found")


@pytest.mark.parametrize(
    "board, fixture, count",
    [
        ("text_to_image", "media_t2i.rsc", 102),
        ("text_to_video", "media_t2v.rsc", 32),
        ("text_to_speech", "media_tts.rsc", 97),
    ],
)
def test_media_counts(board: str, fixture: str, count: int) -> None:
    text = _text(fixture)
    rows = loaders.parse_media(text, board)
    assert len(rows) == count
    elos = [r["elo"] for r in rows]
    assert elos == sorted(elos, reverse=True)


def test_media_t2i_leader_matches_jsonld() -> None:
    text = _text("media_t2i.rsc")
    rows = loaders.parse_media(text, "text_to_image")
    assert rows[0]["name"] == "GPT Image 2.5 Sunburst (max)"
    assert abs(rows[0]["elo"] - 1217) < 1

    name, elo = _jsonld_leader(text)
    assert rows[0]["name"] == name
    assert abs(rows[0]["elo"] - elo) < 1
    assert rows[0]["price"] == 210.72
    assert rows[0]["price_unit"] == "/1k imgs"
    assert rows[0]["rank"] == 1
    assert rows[0]["open_weights"] is False


def _jsonld_leaders(text: str) -> list[tuple[str, int]]:
    payload = flight.payload(text)
    out: list[tuple[str, int]] = []
    for question in flight.find_array(payload, ("@type", "acceptedAnswer")):
        block = question.get("acceptedAnswer") or {}
        match = re.search(
            r"^(.+?) currently leads .*? Elo score of (\d+)", block.get("text", "")
        )
        if match:
            out.append((match.group(1).strip(), int(match.group(2))))
    return out


def test_media_t2v_leader() -> None:
    text = _text("media_t2v.rsc")
    rows = loaders.parse_media(text, "text_to_video")
    assert rows[0]["name"] == "Wan 3.0"
    assert rows[0]["price_unit"] == "/min"
    # leader identification must agree with the page's own JSON-LD
    assert any(
        name == rows[0]["name"] and abs(elo - rows[0]["elo"]) < 1
        for name, elo in _jsonld_leaders(text)
    )


def test_media_tts_shape() -> None:
    rows = loaders.parse_media(_text("media_tts.rsc"), "text_to_speech")
    assert rows[0]["name"] == "Eleven v4 Turbo"
    assert rows[0]["price_unit"] == "/1M chars"
    assert rows[0]["extra"].get("voiceCount") == 8


# --------------------------------------------------------------------------- #
# agents
# --------------------------------------------------------------------------- #


def test_agents_coding_board() -> None:
    rows = loaders.parse_agents(_text("agents_coding.rsc"), "coding_agents")
    assert len(rows) == 39
    assert [r["rank"] for r in rows] == list(range(1, 40))
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert rows[0]["name"].startswith("Claude Code")
    assert all(r["rank"] is not None for r in rows)


# --------------------------------------------------------------------------- #
# evaluations
# --------------------------------------------------------------------------- #


def test_eval_chart_set_gpqa() -> None:
    # The gpqa-diamond capture embeds 19 chart models (the brief's "32" holds
    # for wider eval pages such as aa-briefcase, but not for this one).
    models = loaders.parse_chart(_text("eval_page.rsc"))
    assert len(models) == 19
    assert any(m.slug == "claude-fable-5-1" for m in models)


def test_eval_models_sorts_by_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch, {"eval_gpqa-diamond": "eval_page.rsc"})
    models = loaders.eval_models("gpqa-diamond")
    assert len(models) == 19
    scores = [m.evals.get("gpqa") for m in models]
    assert scores == sorted((s or 0.0 for s in scores), reverse=True)


def test_eval_catalog_matches_reference() -> None:
    cards = loaders.parse_eval_catalog(_text("eval_index.html"))
    reference = json.loads((FIXTURES / "eval_catalog.json").read_text(encoding="utf-8"))

    assert len(cards) == 33
    assert [c["slug"] for c in cards] == [r["slug"] for r in reference]
    for card, ref in zip(cards, reference):
        assert card["title"] == ref["title"]
        assert card["tags"] == ref["tags"]
        assert card["description"]
        text = " ".join(ref["text"].split())
        assert card["title"] in text
        assert card["description"][:40] in text


def test_eval_catalog_collapses_whitespace() -> None:
    cards = loaders.parse_eval_catalog(_text("eval_index.html"))
    briefcase = next(c for c in cards if c["slug"] == "aa-briefcase")
    assert "  " not in briefcase["description"]
    assert briefcase["tags"][0] == "Updated"


# --------------------------------------------------------------------------- #
# sitemap
# --------------------------------------------------------------------------- #

_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://artificialanalysis.ai</loc></url>
<url><loc>https://artificialanalysis.ai/models</loc></url>
<url><loc>https://artificialanalysis.ai/models/claude-opus-5-5</loc></url>
<url><loc>https://artificialanalysis.ai/evaluations/gpqa-diamond</loc></url>
<url><loc>https://artificialanalysis.ai/models</loc></url>
</urlset>
"""


def test_sitemap_paths() -> None:
    paths = loaders.parse_sitemap(_SITEMAP)
    assert paths == [
        "/",
        "/models",
        "/models/claude-opus-5-5",
        "/evaluations/gpqa-diamond",
    ]


# --------------------------------------------------------------------------- #
# loader wiring (fetch monkeypatched with fixtures; no network)
# --------------------------------------------------------------------------- #

_CACHE_MAP = {
    "leaderboard": "leaderboard.rsc",
    "model_claude-fable-5-1": "model_page_chart.rsc",
    "model_glm-4-5v": "model_page_legacy.rsc",
    "providers_claude-opus-5-5": "providers_model.rsc",
    "providers_board": "providers_board.rsc",
    "home": "home.rsc",
    "media_text_to_image": "media_t2i.rsc",
    "media_text_to_video": "media_t2v.rsc",
    "media_text_to_speech": "media_tts.rsc",
    "agents_coding_agents": "agents_coding.rsc",
    "eval_gpqa-diamond": "eval_page.rsc",
    "eval_catalog": "eval_index.html",
    "sitemap": None,
}


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, extra: dict[str, str] | None = None) -> None:
    mapping = dict(_CACHE_MAP)
    if extra:
        mapping.update(extra)

    def fake_get(url: str, name: str, **kwargs):
        fixture = mapping[name]
        text = _SITEMAP if fixture is None else _text(fixture)
        return fetch.Fetched(
            text=text,
            path=Path("/fake-cache") / name,
            fetched_at=1_700_000_000.0,
            cached=True,
            stale=False,
        )

    monkeypatch.setattr(loaders.fetch, "get", fake_get)


def test_loader_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch)

    assert len(loaders.leaderboard()) == 700

    chart = loaders.model("claude-fable-5-1")
    assert len(chart) == 27 and "claude-fable-5-1" in chart

    legacy = loaders.model("glm-4-5v")
    assert set(legacy) == {"glm-4-5v"}

    assert len(loaders.provider_endpoints("claude-opus-5-5")) == 1
    assert len(loaders.provider_board()) == 1201

    boards = loaders.home_boards()
    assert (len(boards["stt"]), len(boards["stt_streaming"]), len(boards["sts"])) == (15, 28, 15)

    assert len(loaders.media("text_to_image")) == 102
    assert len(loaders.agents("coding_agents")) == 39
    assert len(loaders.eval_models("gpqa-diamond")) == 19
    assert len(loaders.eval_catalog()) == 33
    assert "/models/claude-opus-5-5" in loaders.sitemap_paths()


def test_unknown_board_raises() -> None:
    with pytest.raises(ValueError):
        loaders.media("nope")
    with pytest.raises(ValueError):
        loaders.agents("nope")


def test_leaderboard_memo_is_keyed_by_fetch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch(monkeypatch)
    first = loaders.leaderboard()
    assert loaders.leaderboard() is first  # served from the memo


# --------------------------------------------------------------------------- #
# real transport test (loopback http.server; exercises fetch.get for real)
# --------------------------------------------------------------------------- #


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, bytes] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        body = self.routes.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/evaluations" else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence the test server
        pass


def test_url_helper_is_absolute_and_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert loaders.url("/leaderboards/models") == f"{loaders.BASE_URL}/leaderboards/models"
    monkeypatch.setenv("AA_BASE_URL", "http://example.test/")
    assert loaders.url("/models/x") == "http://example.test/models/x"


def test_real_transport_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _FixtureHandler.routes = {
        "/leaderboards/models": (FIXTURES / "leaderboard.rsc").read_bytes(),
        "/evaluations": (FIXTURES / "eval_index.html").read_bytes(),
    }
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("AA_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("AA_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(loaders, "_LEADERBOARD_MEMO", None)

        # No monkeypatching of fetch.get: the real HTTP + cache path runs.
        assert len(loaders.leaderboard()) == 700
        assert len(loaders.eval_catalog()) == 33
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# T6 fidelity fixes
# --------------------------------------------------------------------------- #


def test_leaderboard_release_date_join() -> None:
    models = loaders.parse_leaderboard(_text("leaderboard.rsc"))
    assert len(models) == 700
    assert sum(1 for m in models if m.release_date) > 0
    by_slug = {m.slug: m for m in models}
    base = by_slug["claude-opus-5-5"]
    variant = by_slug["claude-opus-5-5-xhigh"]
    assert base.release_date == "2026-09-22"
    assert variant.release_date == base.release_date  # effort variant joins to same release
    assert base.creator_slug == "anthropic" == variant.creator_slug
    # a genuinely unmatched variant must stay None (no false-positive prefix join)
    assert by_slug["gemma-3-4b"].release_date is None


def test_provider_endpoints_flat_cost_per_task() -> None:
    endpoints = loaders.parse_provider_endpoints(_text("providers_model_flat.rsc"))
    assert len(endpoints) == 4
    costs = [e.cost_per_task for e in endpoints]
    assert all(c is not None for c in costs)  # the bug: all None before the fix
    assert costs == sorted(costs)  # cheapest first
    anthropic = next(e for e in endpoints if e.host == "Anthropic")
    assert anthropic.cost_per_task == pytest.approx(5.982012019521066)
    google = next(e for e in endpoints if e.host == "Google")
    assert google.cost_per_task == pytest.approx(11.62770976536921)


# --------------------------------------------------------------------------- #
# API licensing claims + optional RSC enrichment
# --------------------------------------------------------------------------- #

_CLAUDE_SLUG = "claude-opus-5-5"


def _api_envelope(items: list[dict]) -> dict:
    return {
        "tier": "free",
        "intelligence_index_version": 4.1,
        "pagination": {"page": 1, "page_size": 200, "total_pages": 1, "has_more": False},
        "data": items,
    }


def _api_item(slug: str) -> dict:
    item = json.loads(json.dumps(json.loads((FIXTURES / "api_models_free.json").read_text())["data"][0]))
    item["slug"] = slug
    item["name"] = "Claude Opus 5.5"
    item["model_creator"] = {"id": "f0aa413f", "name": "Anthropic"}
    return item


def _faked_fetch(text: str, fetched_at: float = 42.0):
    def fake_get(url, name, *, refresh=False, rsc=True, ttl=None, min_bytes=0, headers=None):
        return fetch.Fetched(text=text, path=Path("/fake") / name, fetched_at=fetched_at, cached=True, stale=False)
    return fake_get


def _api_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from aa_mcp import api

    monkeypatch.setenv("AA_API_KEY", "test")
    monkeypatch.setattr(source, "_probe_cache", None)
    envelope = _api_envelope([_api_item(_CLAUDE_SLUG)])
    monkeypatch.setattr(api, "fetch_models_free", lambda refresh=False: api.parse_models_free(envelope))


def test_api_leaderboard_licensing_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _api_source(monkeypatch)
    models = loaders.leaderboard()
    assert len(models) == 1
    assert models[0].is_open_weights is None  # unknown, not a false "proprietary"
    assert models[0].license is None
    assert models[0].indices["capabilities.engineering"] == 11.7
    assert models[0].source == "api"


def test_api_leaderboard_with_licensing_enriches_from_rsc(monkeypatch: pytest.MonkeyPatch) -> None:
    _api_source(monkeypatch)
    monkeypatch.setattr(loaders, "_LEADERBOARD_MEMO", None)
    monkeypatch.setattr(loaders.fetch, "get", _faked_fetch(_text("leaderboard.rsc")))

    models = loaders.leaderboard(with_licensing=True)
    model = models[0]
    assert model.is_open_weights is False  # claude-opus-5-5 from the RSC fixture
    assert model.creator_slug == "anthropic"
    assert model.release_date == "2026-09-22"
    # API-provided indices survive; RSC's leaderboard indices are not injected.
    assert model.indices["capabilities.engineering"] == 11.7
    assert "omniscience" not in model.indices
    assert model.source == "api"


def test_api_leaderboard_with_licensing_survives_rsc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _api_source(monkeypatch)

    def boom(url, name, **kwargs):
        raise fetch.AAFetchError("rsc down")

    monkeypatch.setattr(loaders.fetch, "get", boom)
    models = loaders.leaderboard(with_licensing=True)
    assert len(models) == 1
    assert models[0].is_open_weights is None
    assert models[0].indices["capabilities.engineering"] == 11.7


# --------------------------------------------------------------------------- #
# T7: ref-string robustness, agents boards, rich dataset
# --------------------------------------------------------------------------- #

import gzip  # noqa: E402


def _rich_page() -> str:
    records = json.loads(gzip.open(FIXTURES / "rich_dataset.json.gz", "rb").read())
    refs = json.loads((FIXTURES / "initial_models_refs.json").read_text(encoding="utf-8"))
    current = json.loads((FIXTURES / "rich_current_model.json").read_text(encoding="utf-8"))
    return json.dumps({"currentModel": current, "initialModels": refs,
                       "props": {"models": records}})


def test_parse_chart_ref_snippet_does_not_crash() -> None:
    refs = (FIXTURES / "initial_models_refs.json").read_text(encoding="utf-8")
    page = '{"initialModels":' + refs + "}"
    models = loaders.parse_chart(page)  # no rich pool -> nothing resolvable
    assert models == []


def test_parse_chart_resolves_refs_to_chart_set() -> None:
    models = loaders.parse_chart(_rich_page())
    slugs = [m.slug for m in models]
    assert len(models) == 28
    assert "qwen3-8-2-4t-a95b" in slugs  # resolved from the currentModel ref
    assert all(isinstance(m, type(models[0])) for m in models)


def test_parse_rich_dataset_counts() -> None:
    models = loaders.parse_rich_dataset(_rich_page())
    assert len(models) >= 600
    capped = sum(1 for m in models if m.indices.get("capabilities.legal") is not None)
    assert capped >= 200


def test_parse_rich_dataset_fixture_has_90_plus_keys() -> None:
    records = json.loads(gzip.open(FIXTURES / "rich_dataset.json.gz", "rb").read())
    dicts = [r for r in records if isinstance(r, dict)]
    assert len(dicts) >= 600
    assert max(len(r) for r in dicts) >= 90
    assert len({k for r in dicts for k in r}) >= 90  # 94-key union


def test_parse_rich_dataset_absent_on_plain_page() -> None:
    assert loaders.parse_rich_dataset(_text("model_page_chart.rsc")) == []


def test_rich_dataset_offline_uses_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records = json.loads(gzip.open(FIXTURES / "rich_dataset.json.gz", "rb").read())
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "rich_dataset.json").write_text(json.dumps(records), encoding="utf-8")
    (cache / "rich_seed.json").write_text(json.dumps({"slug": "step-5", "ts": 0}), encoding="utf-8")
    monkeypatch.setenv("AA_OFFLINE", "1")
    monkeypatch.setenv("AA_CACHE_DIR", str(cache))
    monkeypatch.setattr(loaders, "_RICH_MEMO", None)
    assert loaders.rich_seed() == "step-5"
    models = loaders.rich_dataset()
    assert len(models) >= 600


def test_rich_dataset_offline_without_cache_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AA_OFFLINE", "1")
    monkeypatch.setenv("AA_CACHE_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr(loaders, "_RICH_MEMO", None)
    monkeypatch.setattr(loaders, "rich_seed", lambda: None)
    assert loaders.rich_dataset() == []


def test_model_resolves_ref_page_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "model_qwen3-8-2-4t-a95b.rsc").write_text(_rich_page(), encoding="utf-8")
    monkeypatch.setenv("AA_OFFLINE", "1")
    monkeypatch.setenv("AA_CACHE_DIR", str(cache))
    models = loaders.model("qwen3-8-2-4t-a95b")
    assert len(models) == 28
    assert "qwen3-8-2-4t-a95b" in models


def test_agent_row_tolerates_string_creator() -> None:
    rec = {"agentName": "Cursor", "creator": "Cursor", "indexScore": 0.5,
           "display": {"model": "Claude Sonnet 5.5"}}
    row = loaders._agent_row(rec)
    assert row["creator"] == "Cursor"
    assert row["agent"] == "Cursor"


def test_agent_row_unwraps_values_formatted() -> None:
    rec = {"values": {"agentName": "Devin", "creator": {"name": "Cognition"}, "score": 0.4},
           "formatted": {"score": "0.4"}}
    row = loaders._agent_row(rec)
    assert row["agent"] == "Devin"
    assert row["creator"] == "Cognition"


def test_parse_agents_chatbot_and_search_shapes() -> None:
    chatbots = json.dumps({"blob": [{"name": "ChatGPT Pro", "tier": "premium",
                                     "featuresScore": 5.45, "creatorName": "OpenAI",
                                     "modelName": "GPT-6 Astra (max)", "priceMonthly": 200}]})
    rows = loaders.parse_agents(chatbots, "chatbots")
    assert len(rows) == 1
    assert rows[0]["name"] == "ChatGPT Pro" and rows[0]["creator"] == "OpenAI"

    search = json.dumps({"blob": [{"providerKey": "perplexity-medium",
                                   "providerName": "Perplexity Search",
                                   "aaSearchQualityIndex": 0.79,
                                   "searchApiCostPerTaskUsd": 0.06}]})
    rows = loaders.parse_agents(search, "search_api")
    assert len(rows) == 1
    assert rows[0]["name"] == "Perplexity Search"
    assert rows[0]["cost_per_task"] == pytest.approx(0.06)


# --------------------------------------------------------------------------- #
# T7b: agent flight-reference resolution + no "$…" leakage
# --------------------------------------------------------------------------- #


def _ref_leaks(obj, path="") -> list:
    found = []
    if isinstance(obj, str):
        if obj.startswith("$"):
            found.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found += _ref_leaks(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found += _ref_leaks(v, f"{path}[{i}]")
    return found


def test_agent_creator_refs_resolved_in_fixture() -> None:
    rows = loaders.parse_agents(_text("agents_coding.rsc"), "coding_agents")
    assert len(rows) == 39
    assert all(r["creator"] for r in rows)
    assert rows[1]["creator"] == "Meta"       # Muse Code
    assert rows[2]["creator"] == "Anthropic"  # Claude Code
    assert _ref_leaks(rows) == []


def test_agent_row_resolves_named_array_ref() -> None:
    page = json.dumps({
        "benchmarkRows": [
            {"agentName": "A", "indexScore": 0.5,
             "agentCreator": "$1:props:children:props:rows:0:agentCreator"}
        ],
        "rows": [{"agentCreator": {"name": "Acme", "slug": "acme"}}],
    })
    rows = loaders.parse_agents(page, "coding_agents")
    assert len(rows) == 1
    assert rows[0]["creator"] == "Acme"


def test_agent_row_drops_unresolved_ref() -> None:
    row = loaders._agent_row(
        {"agentName": "X", "creator": "$30:props:children:props:rows:99:agentCreator"}
    )
    assert row["creator"] is None
    assert _ref_leaks(row) == []


def test_no_ref_literals_in_media_and_providers() -> None:
    for fixture, board in (("media_t2i.rsc", "text_to_image"),
                           ("media_t2v.rsc", "text_to_video"),
                           ("media_tts.rsc", "text_to_speech")):
        rows = loaders.parse_media(_text(fixture), board)
        assert _ref_leaks(rows) == [], fixture

    assert _ref_leaks([e.__slots__ and {k: getattr(e, k) for k in e.__slots__}
                       for e in loaders.parse_provider_endpoints(_text("providers_model_flat.rsc"))]) == []
    assert _ref_leaks([{k: getattr(e, k) for k in e.__slots__}
                       for e in loaders.parse_provider_board(_text("providers_board.rsc"))]) == []


# --------------------------------------------------------------------------- #
# T7c: provider endpoint names + completeness
# --------------------------------------------------------------------------- #


def test_provider_board_model_name_populated() -> None:
    endpoints = loaders.parse_provider_board(_text("providers_board.rsc"))
    assert len(endpoints) == 1201
    assert all(e.model_name for e in endpoints)
    assert endpoints[0].model_name == "GLM-4.5V (non-reasoning)"
    assert endpoints[0].model_slug == "glm-4-5v"


def test_provider_endpoints_model_name_falls_back_to_slug() -> None:
    endpoints = loaders.parse_provider_endpoints(_text("providers_model_flat.rsc"))
    assert len(endpoints) == 4
    assert all(e.model_name for e in endpoints)
    assert {e.model_name for e in endpoints} == {"claude-opus-5-5"}


def test_endpoint_keeps_every_row_and_sorts_none_last() -> None:
    page = json.dumps({"hostModels": [
        {"host": {"name": "H1", "slug": "h1"}, "model": {"slug": "m"},
         "pricing": {"price1mInputTokens": 1.0}, "jsonMode": True,
         "performance": {"intelligenceIndexCostPerTask": {"total": 9.0}}},
        {"host": {"name": "H2", "slug": "h2"}, "model": {"slug": "m"},
         "pricing": {"price1mInputTokens": 0.5}, "jsonMode": True,
         "performance": {}},  # no cost -> must be kept, sorted last
        {"host": {"name": "H3", "slug": "h3"}, "model": {"slug": "m"},
         "pricing": {"price1mInputTokens": 2.0}, "jsonMode": True,
         "performance": {"intelligenceIndexCostPerTask": {"total": 1.5}}},
    ]})
    endpoints = loaders.parse_provider_endpoints(page)
    assert len(endpoints) == 3  # nothing dropped
    assert [e.cost_per_task for e in endpoints] == [1.5, 9.0, None]
    assert endpoints[-1].host_slug == "h2"


def test_endpoint_model_name_ignores_reference_label() -> None:
    page = json.dumps({"hostModels": [
        {"host": {"name": "H", "slug": "h"}, "model": {"slug": "m-slug"},
         "label": "$30:props:children:props:rows:0:label", "jsonMode": True,
         "pricing": {}, "performance": {}},
    ]})
    endpoints = loaders.parse_provider_endpoints(page)
    assert endpoints[0].model_name == "m-slug"


# --------------------------------------------------------------------------- #
# T8: precision from labels (slug suffix stays a fallback)
# --------------------------------------------------------------------------- #


def test_precision_from_host_label_and_model_label() -> None:
    page = json.dumps({"hostModels": [
        {"host": {"name": "Supernova", "label": "Supernova (FP4)", "slug": "supernova"},
         "model": {"slug": "m"}, "jsonMode": True, "pricing": {}, "performance": {}},
        {"host": {"name": "Crusoe", "label": "Crusoe (FP8)", "slug": "crusoe"},
         "model": {"slug": "m"}, "jsonMode": True, "pricing": {}, "performance": {}},
        {"host": {"name": "X", "label": "X (NVFP4)", "slug": "x"},
         "model": {"slug": "m"}, "jsonMode": True, "pricing": {}, "performance": {}},
        {"host": {"name": "Plain", "slug": "plain"},
         "model": {"slug": "m", "name": "DeepSeek V3.2 (FP8)"},
         "jsonMode": True, "pricing": {}, "performance": {}},
    ]})
    by_host = {e.host: e.precision for e in loaders.parse_provider_endpoints(page)}
    assert by_host == {"Supernova": "fp4", "Crusoe": "fp8", "X": "fp4", "Plain": "fp8"}


def test_precision_slug_suffix_still_works() -> None:
    page = json.dumps({"hostModels": [
        {"host": {"name": "H", "slug": "h"}, "model": {"slug": "m"},
         "slug": "h_m_fp8", "jsonMode": True, "pricing": {}, "performance": {}},
    ]})
    assert loaders.parse_provider_endpoints(page)[0].precision == "fp8"


def test_precision_none_when_absent() -> None:
    page = json.dumps({"hostModels": [
        {"host": {"name": "GMI", "slug": "gmi"}, "model": {"slug": "m"},
         "slug": "gmi_m", "jsonMode": True, "pricing": {}, "performance": {}},
    ]})
    assert loaders.parse_provider_endpoints(page)[0].precision is None
