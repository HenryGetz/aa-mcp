"""Tests for raw-record -> canonical Model normalization."""

from __future__ import annotations

import pathlib

import pytest

from aa_mcp import flight, normalize

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def leaderboard_records():
    p = flight.payload(_read("leaderboard.rsc"))
    return flight.find_array(p, ["intelligenceIndex"])


@pytest.fixture(scope="module")
def chart_records():
    p = flight.payload(_read("model_page_chart.rsc"))
    return {r["slug"]: r for r in flight.find_array(p, ["intelligenceIndexCostPerTask"])}


@pytest.fixture(scope="module")
def legacy_record():
    p = flight.payload(_read("model_page_legacy.rsc"))
    return flight.keyed_object(p, "currentModel")


# --------------------------------------------------------------------------- #
# from_leaderboard
# --------------------------------------------------------------------------- #

def test_from_leaderboard_count_and_source(leaderboard_records):
    models = [normalize.from_leaderboard(r) for r in leaderboard_records]
    assert len(models) == 700
    assert all(m.source == "leaderboard" for m in models)
    assert sum(1 for m in models if m.cost_per_task is not None) >= 180


def test_from_leaderboard_float_cost_and_fields(leaderboard_records):
    rec = next(r for r in leaderboard_records if r["slug"] == "claude-opus-5-5")
    m = normalize.from_leaderboard(rec)
    assert m.slug == "claude-opus-5-5"
    assert m.intelligence > 50
    assert isinstance(m.cost_per_task, float)
    assert m.pricing["in"] == 4.0
    assert m.pricing["out"] == 20.0
    assert m.evals["hle"] is not None and 0 < m.evals["hle"] < 1
    assert m.speed["tps"] is not None
    assert m.indices["omniscience"] is not None
    assert m.source == "leaderboard"


def test_from_leaderboard_estimated_flag(leaderboard_records):
    estimated = [normalize.from_leaderboard(r) for r in leaderboard_records
                 if r.get("intelligenceIndexIsEstimated")]
    assert estimated and all(m.estimated for m in estimated)


# --------------------------------------------------------------------------- #
# from_chart
# --------------------------------------------------------------------------- #

def test_from_chart_acceptance(chart_records):
    assert len(chart_records) == 27
    m = normalize.from_chart(chart_records["claude-fable-5-1"])
    assert m.source == "chart"
    assert m.cost_per_task == pytest.approx(7.629706364004841)
    assert m.indices["capabilities.legal"] == pytest.approx(60.4916320056283)
    assert m.evals["briefcaseElo"] == pytest.approx(1673.52)
    assert m.effort == "max"
    assert m.pricing["in"] == 10


def test_from_chart_cost_and_speed_breakdown(chart_records):
    m = normalize.from_chart(chart_records["claude-fable-5-1"])
    assert m.cost_breakdown["total"] == pytest.approx(7.629706364004841)
    assert m.cost_breakdown["reasoning"] is not None
    assert m.per_eval_cost and m.per_eval_cost[0]["slug"]
    assert "weighted_cost_per_task" in m.per_eval_cost[0]
    assert m.speed["tps"] == pytest.approx(71.5897671255643)
    assert m.speed["out_tokens_per_task"] == pytest.approx(78110.80621282545)
    assert m.creator == "Anthropic" and m.creator_slug == "anthropic"
    assert m.release_date == "2026-02-01" or m.release_date is not None
    caps = [k for k in m.indices if k.startswith("capabilities.")]
    assert len(caps) == 6


def test_chart_elo_not_divided_by_100(chart_records):
    m = normalize.from_chart(chart_records["claude-fable-5-1"])
    assert m.evals["briefcaseElo"] > 100  # raw Elo, not scaled to a fraction


# --------------------------------------------------------------------------- #
# from_legacy
# --------------------------------------------------------------------------- #

def test_from_legacy_acceptance(legacy_record):
    m = normalize.from_legacy(legacy_record)
    assert m.slug == "glm-4-5v"
    assert m.source == "legacy"
    assert m.context_tokens == 64000
    assert m.license == "MIT"
    assert m.params_b == 108
    assert m.active_params_b == 12
    assert m.indices["openness"] == pytest.approx(52.77777777777778)
    assert m.speed["tps"] == pytest.approx(46.3084707052531)
    assert m.speed["e2e"] == pytest.approx(13.557405914521295)
    assert m.deprecated is True
    assert m.deprecated_to == "glm-4-6v"
    assert m.modalities_in == ("text",) or "text" in m.modalities_in


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #

def test_merge_later_non_none_wins(leaderboard_records, chart_records):
    lb = normalize.from_leaderboard(
        next(r for r in leaderboard_records if r["slug"] == "claude-opus-5-5")
    )
    # Same model, richer chart record (identity slug aligned as loaders would).
    chart_rec = dict(chart_records["claude-fable-5-1"])
    chart_rec["slug"] = lb.slug
    rich = normalize.from_chart(chart_rec)
    merged = normalize.merge(lb, rich)
    assert merged.slug == "claude-opus-5-5"
    assert merged.source == "chart"               # source from last
    assert merged.cost_per_task == pytest.approx(7.629706364004841)
    assert merged.evals["briefcaseElo"] == pytest.approx(1673.52)
    # union of evals: leaderboard-only keys survive
    assert merged.evals["hle"] is not None
    assert merged.pricing["in"] == rich.pricing["in"]
    assert merged.license is None


def test_merge_single_model_is_identity(leaderboard_records):
    m = normalize.from_leaderboard(leaderboard_records[0])
    assert normalize.merge(m) is m


def test_merge_requires_models():
    with pytest.raises(ValueError):
        normalize.merge()


# --------------------------------------------------------------------------- #
# T6 fidelity fixes
# --------------------------------------------------------------------------- #


def test_from_leaderboard_keeps_speed_distribution(leaderboard_records):
    rec = next(
        r for r in leaderboard_records
        if r.get("percentile95OutputTokensPerSecond") is not None
        and r.get("percentile95TimeToFirstTokenSeconds") is not None
    )
    m = normalize.from_leaderboard(rec)
    assert m.speed["tps_p05"] == rec["percentile05OutputTokensPerSecond"]
    assert m.speed["tps_q25"] == rec["quartile25OutputTokensPerSecond"]
    assert m.speed["tps_q75"] == rec["quartile75OutputTokensPerSecond"]
    assert m.speed["tps_p95"] == rec["percentile95OutputTokensPerSecond"]
    assert m.speed["ttft_p05"] == rec["percentile05TimeToFirstTokenSeconds"]
    assert m.speed["ttft_q25"] == rec["quartile25TimeToFirstTokenSeconds"]
    assert m.speed["ttft_q75"] == rec["quartile75TimeToFirstTokenSeconds"]
    assert m.speed["ttft_p95"] == rec["percentile95TimeToFirstTokenSeconds"]


def test_from_leaderboard_missing_percentiles_stay_none(leaderboard_records):
    rec = next(r for r in leaderboard_records if r.get("percentile95OutputTokensPerSecond") is None)
    m = normalize.from_leaderboard(rec)
    assert m.speed["tps_p95"] is None
    assert m.speed["ttft_p95"] is None


def test_from_chart_per_eval_and_index_cost(chart_records):
    m = normalize.from_chart(chart_records["claude-fable-5-1"])
    assert m.per_eval is not None and len(m.per_eval) == 10
    assert m.per_eval[0]["slug"] == "aa-briefcase"
    assert m.per_eval[0]["score"] == pytest.approx(1673.52)
    assert set(m.per_eval[0]) == {"slug", "score", "outputTokensPerTask", "costPerTask", "timePerTask"}
    assert m.cost_breakdown["index_total"] == pytest.approx(13128.859210511622)
    assert m.cost_breakdown["briefcase_total"] == pytest.approx(2066.9247375353966)
    assert m.speed["reasoning_tokens"] is not None
    assert normalize.from_chart(chart_records["step-5"]).speed["reasoning_tokens"] == 2000


def test_per_eval_defaults_to_none_off_chart_surface(leaderboard_records):
    assert normalize.from_leaderboard(leaderboard_records[0]).per_eval is None


def test_from_chart_reads_enterprise_ops_gym(chart_records):
    m = normalize.from_chart(chart_records["step-5"])
    assert m.evals["enterpriseOpsGym"] == pytest.approx(0.4717994628469114)


def test_every_chart_numeric_benchmark_is_reachable(chart_records):
    from aa_mcp import catalog

    surfaced = set()
    for rec in chart_records.values():
        m = normalize.from_chart(rec)
        surfaced |= {k for k, v in m.evals.items() if v is not None}
        surfaced |= {k for k, v in m.indices.items() if v is not None}
    for key in catalog.BENCHMARKS:
        present = any(
            isinstance(rec.get(key), (int, float)) and not isinstance(rec.get(key), bool)
            for rec in chart_records.values()
        )
        if present:
            assert key in surfaced, f"{key} present in chart payload but unreachable"


def test_merge_prefers_first_non_empty_per_eval(chart_records, leaderboard_records):
    chart = normalize.from_chart(chart_records["claude-fable-5-1"])
    leader = normalize.from_leaderboard(leaderboard_records[0])
    assert leader.per_eval is None
    assert normalize.merge(chart, leader).per_eval == chart.per_eval
    assert normalize.merge(leader, chart).per_eval == chart.per_eval


# --------------------------------------------------------------------------- #
# T7 fidelity: briefcase Elo shapes, itbench casing, eval sub-scores
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def eval_records():
    p = flight.payload(_read("eval_page.rsc"))
    return {r["slug"]: r for r in flight.find_array(p, ["chartDefaultSelected", "releaseDate", "suffix"])}


@pytest.mark.parametrize(
    "rec",
    [
        {"briefcaseElo": 1111.0},
        {"briefcaseBreakdown": {"elo": 2222.0}},
        {"briefcaseBreakdown": {"overall": {"elo": 3333.0}}},
    ],
)
def test_briefcase_elo_all_three_shapes(rec):
    assert normalize.from_chart(rec).evals["briefcaseElo"] in (1111.0, 2222.0, 3333.0)
    assert normalize.from_legacy(rec).evals["briefcaseElo"] in (1111.0, 2222.0, 3333.0)


def test_briefcase_elo_prefers_direct_key():
    rec = {"briefcaseElo": 1819.43, "briefcaseBreakdown": {"elo": 1.0, "overall": {"elo": 2.0}}}
    assert normalize.from_chart(rec).evals["briefcaseElo"] == 1819.43


def test_chart_briefcase_elo_from_breakdown(chart_records):
    m = normalize.from_chart(chart_records["claude-sonnet-5-5"])
    assert m.evals["briefcaseElo"] == pytest.approx(1819.43)


def test_itbench_payload_key_casing_is_aliased(chart_records):
    m = normalize.from_chart(chart_records["step-5"])
    assert m.evals["itbenchSre"] == pytest.approx(0.555555555555556)
    assert "itBenchSre" not in m.evals


def test_eval_page_sub_scores_are_reachable(eval_records):
    m = normalize.from_chart(eval_records["claude-fable-5-1"])
    assert m.evals["briefcaseElo"] == pytest.approx(1673.52)  # direct key on eval pages
    assert m.evals["mlcrAccuracy"] == pytest.approx(0.9483870967741935)
    assert m.evals["analystAgentPassAt1"] == pytest.approx(0.6575)
    assert m.evals["analystAgentPassAtK"] == pytest.approx(0.725)
    assert m.evals["cweBenchRefusalRate"] == pytest.approx(0.15966386554621848)


def test_every_eval_numeric_benchmark_is_reachable(eval_records):
    from aa_mcp import catalog

    surfaced = set()
    for rec in eval_records.values():
        m = normalize.from_chart(rec)
        surfaced |= {k for k, v in m.evals.items() if v is not None}
        surfaced |= {k for k, v in m.indices.items() if v is not None}
    for key in catalog.BENCHMARKS:
        present = any(
            isinstance(rec.get(key), (int, float)) and not isinstance(rec.get(key), bool)
            for rec in eval_records.values()
        )
        if present:
            assert key in surfaced, f"{key} present in eval payload but unreachable"


# --------------------------------------------------------------------------- #
# T7: non-dict guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fn", [normalize.from_chart, normalize.from_legacy,
                                normalize.from_leaderboard])
def test_non_dict_records_raise_type_error(fn):
    with pytest.raises(TypeError):
        fn("$e:props:children:0:props:currentModel")


# --------------------------------------------------------------------------- #
# Wave G-B1: AA's published time-per-task vs our derived mean
# --------------------------------------------------------------------------- #

def test_chart_reads_aa_published_time_per_task(chart_records):
    rec = chart_records["claude-opus-5-5"]
    m = normalize.from_chart(rec)
    assert m.speed["time_per_task"] == pytest.approx(rec["intelligenceIndexTimePerTask"])
    assert m.speed["time_per_task"] == pytest.approx(789.2354834132094)


def test_derived_time_per_task_is_the_per_eval_mean(chart_records):
    m = normalize.from_chart(chart_records["claude-opus-5-5"])
    times = [r["timePerTask"] for r in m.per_eval if r["timePerTask"] is not None]
    assert len(times) == 10
    assert m.speed["time_per_task_derived"] == pytest.approx(sum(times) / len(times))
    # The published aggregate and our mean are different numbers (median -6.7 %
    # across the 189 rich records carrying both): the fallback must not shadow it.
    assert m.speed["time_per_task_derived"] == pytest.approx(689.9289088216383)
    assert abs(m.speed["time_per_task"] - m.speed["time_per_task_derived"]) > 1.0


def test_derived_mean_is_the_only_value_when_aa_publishes_none(chart_records):
    rec = dict(chart_records["step-5"])
    assert rec.pop("intelligenceIndexTimePerTask") is not None
    m = normalize.from_chart(rec)
    assert m.speed["time_per_task"] is None
    assert m.speed["time_per_task_derived"] == pytest.approx(606.145853280145)


def test_both_time_per_task_values_are_none_without_chart_data(chart_records):
    # no published field and every per-eval timePerTask is null
    m = normalize.from_chart(chart_records["muse-wonder-full"])
    assert m.speed["time_per_task"] is None
    assert m.speed["time_per_task_derived"] is None


def test_leaderboard_and_legacy_carry_no_time_per_task(leaderboard_records, legacy_record):
    lb = normalize.from_leaderboard(leaderboard_records[0])
    assert lb.speed["time_per_task"] is None
    assert lb.speed["time_per_task_derived"] is None
    legacy = normalize.from_legacy(legacy_record)
    assert legacy.speed["time_per_task"] is None
    assert legacy.speed["time_per_task_derived"] is None


def test_merge_keeps_the_published_time_per_task(chart_records, leaderboard_records):
    chart = normalize.from_chart(chart_records["claude-opus-5-5"])
    leader = next(m for m in map(normalize.from_leaderboard, leaderboard_records)
                  if m.slug == "claude-opus-5-5")
    for merged in (normalize.merge(leader, chart), normalize.merge(chart, leader)):
        assert merged.speed["time_per_task"] == pytest.approx(789.2354834132094)
        assert merged.speed["time_per_task_derived"] == pytest.approx(689.9289088216383)
