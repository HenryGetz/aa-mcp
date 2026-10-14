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
    select.value_rank([m])
    assert m.value is None


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
