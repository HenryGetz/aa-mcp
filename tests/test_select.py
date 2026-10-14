"""Tests for filter / sort / value / pareto / search / resolve."""

from __future__ import annotations

import pytest

from aa_mcp import normalize, select


def mk(slug, *, name=None, short=None, creator=None, intelligence=None,
       cost=None, tps=None, ttft=None, ctx=None, release=None,
       open_weights=False, reasoning=False, deprecated=False, evals=None,
       pricing=None, indices=None, speed=None):
    return normalize.Model(
        slug=slug,
        name=name or slug,
        short_name=short or name or slug,
        creator=creator,
        creator_slug=None,
        release_date=release,
        deprecated=deprecated,
        deprecated_to=None,
        is_reasoning=reasoning,
        is_open_weights=open_weights,
        effort=None,
        params_b=None,
        active_params_b=None,
        context_tokens=ctx,
        license=None,
        license_url=None,
        weights_url=None,
        knowledge_cutoff=None,
        size_class=None,
        modalities_in=(),
        modalities_out=(),
        intelligence=intelligence,
        estimated=False,
        indices=indices or {},
        evals=evals or {},
        pricing=pricing or {},
        speed=speed or {"tps": tps, "ttft": ttft},
        cost_per_task=cost,
        cost_breakdown=None,
        per_eval_cost=None,
        source="leaderboard",
    )


@pytest.fixture
def models():
    return [
        mk("a-fast", name="Alpha Fast", creator="Acme", intelligence=60, cost=1.0, tps=100, ttft=1.0, ctx=128000, release="2025-01-01"),
        mk("b-cheap", name="Beta Cheap", creator="Beta Inc", intelligence=40, cost=0.1, tps=50, ttft=0.5, ctx=32000, release="2024-06-01"),
        mk("c-open", name="Gamma Open", creator="Acme", intelligence=70, cost=5.0, tps=20, ttft=4.0, ctx=200000, release="2025-09-01", open_weights=True, reasoning=True),
        mk("d-old", name="Delta Old", creator="Delta", intelligence=None, cost=None, tps=None, ttft=None, ctx=8000, release="2023-01-01", deprecated=True),
    ]


# --------------------------------------------------------------------------- #
# filter
# --------------------------------------------------------------------------- #

def test_filter_excludes_deprecated_by_default(models):
    out = select.filter_models(models)
    assert {m.slug for m in out} == {"a-fast", "b-cheap", "c-open"}


def test_filter_include_deprecated(models):
    out = select.filter_models(models, exclude_deprecated=False)
    assert len(out) == 4


def test_filter_axes(models):
    assert [m.slug for m in select.filter_models(models, open_weights=True)] == ["c-open"]
    assert [m.slug for m in select.filter_models(models, reasoning=True)] == ["c-open"]
    assert [m.slug for m in select.filter_models(models, creator="acme")] == ["a-fast", "c-open"]
    assert [m.slug for m in select.filter_models(models, name="gamma")] == ["c-open"]
    assert [m.slug for m in select.filter_models(models, min_intelligence=50)] == ["a-fast", "c-open"]
    assert [m.slug for m in select.filter_models(models, max_cost_per_task=1.0)] == ["a-fast", "b-cheap"]
    assert [m.slug for m in select.filter_models(models, min_speed=60)] == ["a-fast"]
    assert [m.slug for m in select.filter_models(models, max_ttft=1.0)] == ["a-fast", "b-cheap"]
    assert [m.slug for m in select.filter_models(models, min_context=100000)] == ["a-fast", "c-open"]
    assert [m.slug for m in select.filter_models(models, released_after="2025-06-01")] == ["c-open"]


def test_filter_min_score(models):
    out = select.filter_models(models, min_score=45, score_key="intelligence", exclude_deprecated=False)
    assert {m.slug for m in out} == {"a-fast", "c-open"}


# --------------------------------------------------------------------------- #
# sort
# --------------------------------------------------------------------------- #

def test_sort_desc_by_intelligence_with_missing_last(models):
    out = select.sort_models(models, "intelligence")
    assert [m.slug for m in out] == ["c-open", "a-fast", "b-cheap", "d-old"]


def test_sort_asc_keeps_missing_last(models):
    out = select.sort_models(models, "cost_per_task", desc=False)
    assert [m.slug for m in out] == ["b-cheap", "a-fast", "c-open", "d-old"]


def test_sort_low_better_defaults_ascending(models):
    # ttft: lower is better -> ascending
    out = select.sort_models(models, "ttft")
    assert [m.slug for m in out] == ["b-cheap", "a-fast", "c-open", "d-old"]


def test_sort_attribute_name(models):
    asc = select.sort_models(models, "slug", desc=False)
    assert [m.slug for m in asc] == ["a-fast", "b-cheap", "c-open", "d-old"]
    # unknown-attribute direction defaults to descending
    desc = select.sort_models(models, "slug")
    assert [m.slug for m in desc] == ["d-old", "c-open", "b-cheap", "a-fast"]


def test_sort_by_eval_key():
    ms = [mk("x", evals={"gpqa": 0.2}), mk("y", evals={"gpqa": 0.9}), mk("z")]
    out = select.sort_models(ms, "gpqa")
    assert [m.slug for m in out] == ["y", "x", "z"]


# --------------------------------------------------------------------------- #
# value / pareto
# --------------------------------------------------------------------------- #

def test_value_rank(models):
    out = select.value_rank(models)
    by = {m.slug: m.value for m in out}
    assert by["a-fast"] == pytest.approx(60.0)
    assert by["b-cheap"] == pytest.approx(400.0)
    assert by["d-old"] is None


def test_value_rank_skips_zero_cost():
    m = mk("free", intelligence=10, cost=0.0)
    out = select.value_rank([m])
    assert out[0].value is None
    assert m.value is None              # the input object is never written to


def test_pareto_frontier(models):
    front = select.pareto(models)
    # b-cheap (0.1,40) dominated by a-fast (1.0,60)? no. frontier: (0.1,40),(1.0,60),(5.0,70)
    assert [m.slug for m in front] == ["b-cheap", "a-fast", "c-open"]


def test_pareto_drops_dominated():
    ms = [
        mk("dominated", intelligence=50, cost=2.0),
        mk("better", intelligence=60, cost=1.0),
    ]
    assert [m.slug for m in select.pareto(ms)] == ["better"]


# --------------------------------------------------------------------------- #
# search / resolve
# --------------------------------------------------------------------------- #

def test_search_ranks_exact_first(models):
    out = select.search(models, "gamma")
    assert out[0].slug == "c-open"
    assert all(len(out) >= 1 for _ in [0])


def test_search_creator(models):
    out = select.search(models, "acme")
    assert {m.slug for m in out} == {"a-fast", "c-open"}


def test_resolve_exact_slug(models):
    assert select.resolve(models, "a-fast").slug == "a-fast"


def test_resolve_exact_name(models):
    assert select.resolve(models, "Alpha Fast").slug == "a-fast"
    assert select.resolve(models, "alpha_fast").slug == "a-fast"


def test_resolve_unique_substring(models):
    assert select.resolve(models, "gamma").slug == "c-open"


def test_resolve_ambiguous(models):
    ambiguous = [
        mk("claude-opus-5-5", short="Claude Opus 5.5", intelligence=60),
        mk("claude-opus-5-5-high", short="Claude Opus 5.5 High", intelligence=55),
    ]
    with pytest.raises(select.AmbiguousError) as ei:
        select.resolve(ambiguous, "claude opus")
    assert 1 <= len(ei.value.candidates) <= 8
    # intel-sorted candidates
    assert ei.value.candidates[0].slug == "claude-opus-5-5"


def test_resolve_not_found(models):
    with pytest.raises(LookupError):
        select.resolve(models, "zzzzz")


def test_resolve_candidates_capped(models):
    many = [mk(f"model-{i}", short=f"Model {i}") for i in range(20)]
    with pytest.raises(select.AmbiguousError) as ei:
        select.resolve(many, "model")
    assert len(ei.value.candidates) == 8


# --------------------------------------------------------------------------- #
# T8: tokenized search / name filter
# --------------------------------------------------------------------------- #

_TOKEN_MODELS = [
    mk("claude-opus-5-5", name="Claude Opus 5.5 (Max, Default Fallback)",
       short="Claude Opus 5.5 (max with fallback)", creator="Anthropic", intelligence=57.6),
    mk("claude-opus-5-5-xhigh", name="Claude Opus 5.5 (Xhigh, Default Fallback)",
       creator="Anthropic", intelligence=56.0),
    mk("gemini-4-argon", name="Gemini 4 Argon (high)", creator="Google", intelligence=61.0),
    mk("kimi-k3", name="Kimi K3 (Max)", creator="Moonshot", intelligence=43.6),
]


def test_search_tokenizes_multi_word_query():
    hits = select.search(_TOKEN_MODELS, "opus max")
    assert hits and hits[0].slug == "claude-opus-5-5"
    # every token must match; the Xhigh variant has no "max"
    assert all(m.slug != "claude-opus-5-5-xhigh" for m in hits)


def test_search_resolves_noncontiguous_name():
    hits = select.search(_TOKEN_MODELS, "gemini 4 argon")
    assert [m.slug for m in hits] == ["gemini-4-argon"]


def test_search_unknown_token_returns_nothing():
    assert select.search(_TOKEN_MODELS, "zzz") == []


def test_search_single_token_unchanged():
    assert select.search(_TOKEN_MODELS, "opus")[0].slug == "claude-opus-5-5"
    assert select.search(_TOKEN_MODELS, "kimi-k3")[0].slug == "kimi-k3"


def test_filter_name_tokenizes_like_search():
    rows = select.filter_models(_TOKEN_MODELS, name="opus max")
    assert [m.slug for m in rows] == ["claude-opus-5-5"]
    assert select.filter_models(_TOKEN_MODELS, name="zzz") == []


# --------------------------------------------------------------------------- #
# Wave A: functional value pairs (audit H3) + finite numeric filters (A2)
# --------------------------------------------------------------------------- #

def test_value_rank_does_not_mutate_inputs(models):
    before = [m.value for m in models]
    out = select.value_rank(models, score_key="intelligence")
    assert [m.value for m in models] == before          # inputs untouched
    assert all(m is not orig for m, orig in zip(out, models, strict=False))   # copies, not aliases
    by = {m.slug: m.value for m in out}
    assert by["a-fast"] == pytest.approx(60.0)
    assert by["b-cheap"] == pytest.approx(400.0)
    assert by["d-old"] is None
    assert any(m.value is not None for m in out)


def test_value_pairs_is_functional_and_stable(models):
    first = select.value_pairs(models, score_key="intelligence")
    assert [id(m) for m, _ in first] == [
        id(m) for m in models if m.intelligence is not None and m.cost_per_task
    ]
    values = {m.slug: v for m, v in first}
    assert values["a-fast"] == pytest.approx(60.0)
    assert values["b-cheap"] == pytest.approx(400.0)
    assert values["c-open"] == pytest.approx(14.0)
    # an intervening call with a different score key must not change the result
    select.value_pairs(models, score_key="omniscience")
    select.value_rank(models, score_key="omniscience")
    second = select.value_pairs(models, score_key="intelligence")
    assert [(m.slug, v) for m, v in second] == [(m.slug, v) for m, v in first]
    assert all(m.value is None for m in models)          # nothing was written back


def test_value_pairs_honours_cost_key(models):
    pairs = select.value_pairs(models, score_key="tps", cost_key="ttft")
    values = {m.slug: v for m, v in pairs}
    assert values["a-fast"] == pytest.approx(100.0)
    assert values["b-cheap"] == pytest.approx(100.0)
    assert values["c-open"] == pytest.approx(5.0)


def test_value_pairs_skips_missing_and_zero_cost():
    ms = [mk("free", intelligence=10, cost=0.0),
          mk("priceless", intelligence=10, cost=None),
          mk("unscored", intelligence=None, cost=1.0),
          mk("ok", intelligence=10, cost=2.0)]
    assert [(m.slug, v) for m, v in select.value_pairs(ms)] == [("ok", 5.0)]


@pytest.mark.parametrize("kwargs", [
    {"min_intelligence": float("nan")},
    {"max_cost_per_task": float("nan")},
    {"min_speed": float("inf")},
    {"max_ttft": float("-inf")},
    {"min_context": float("nan")},
    {"min_score": float("nan")},
])
def test_non_finite_filters_raise(models, kwargs):
    key = next(iter(kwargs))
    with pytest.raises(ValueError) as ei:
        select.filter_models(models, **kwargs)
    assert key in str(ei.value)


def test_finite_filters_still_work(models):
    assert [m.slug for m in select.filter_models(models, min_intelligence=50)] == [
        "a-fast", "c-open",
    ]


def test_better_desc_follows_catalog_direction():
    assert select.better_desc("intelligence") is True
    assert select.better_desc("cost_per_task") is False
    assert select.better_desc("omniscienceHallucinationRate") is False
    assert select.better_desc("not-a-metric") is True


def test_lookup_finds_attribute_backed_identity_fields():
    m = mk("attr", intelligence=10, cost=1.0)
    assert select.lookup(m, "modalities_in") == ()
    assert select.lookup(m, "weights_url") is None
    assert select.lookup(m, "context_tokens") is None
