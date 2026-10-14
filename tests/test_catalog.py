"""Tests for the metric/benchmark registry and formatting."""

from __future__ import annotations

import pathlib
import re

import pytest

from aa_mcp import catalog

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# registries
# --------------------------------------------------------------------------- #

def test_every_scalar_benchmark_has_a_metric():
    for key, b in catalog.BENCHMARKS.items():
        if b.unit == "mixed":
            continue
        assert key in catalog.METRICS, key


def test_index_members():
    members = {
        "briefcaseElo", "gdpvalNormalized", "automationBenchPartialScore",
        "terminalBench40", "scicode", "lcr", "omniscience", "hle",
        "gdpPdfAllPass", "critpt",
    }
    got = {k for k, b in catalog.BENCHMARKS.items() if b.index_member}
    assert got == members


def test_all_33_eval_slugs_are_covered():
    import json

    catalog_cards = json.loads((FIXTURES / "eval_catalog.json").read_text())
    slugs = {c["slug"] for c in catalog_cards}
    covered = {b.slug for b in catalog.BENCHMARKS.values() if b.slug}
    assert slugs <= covered, slugs - covered


def test_benchmarks_have_unit_and_desc():
    for b in catalog.BENCHMARKS.values():
        assert b.unit in ("%", "Elo", "index", "mixed", "s", "tok/s", "USD/task")
        assert b.desc and b.key


# --------------------------------------------------------------------------- #
# aliases
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("alias,key", [
    ("gpqa", "gpqa"),
    ("GPQA Diamond", "gpqa"),
    ("gpqa-diamond", "gpqa"),
    ("GPQA_DIAMOND", "gpqa"),
    ("intel", "intelligence"),
    ("intelligence", "intelligence"),
    ("cost", "cost_per_task"),
    ("ttft", "ttft"),
    ("tps", "tps"),
    ("ctx", "context_tokens"),
    ("params", "params_b"),
    ("open", "is_open_weights"),
    ("n", "name"),
    ("tau3-banking", "tauBanking"),
    ("TERMINAL-BENCH 4.0", "terminalBench40"),
])
def test_field_aliases(alias, key):
    assert catalog.metric(alias) is not None, alias
    assert catalog.metric(alias).key == key


def test_openapi_vocabulary_aliases():
    for name, key in [
        ("artificial_analysis_intelligence_index", "intelligence"),
        ("gpqa_diamond", "gpqa"),
        ("aa_lcr", "lcr"),
        ("mmmu_pro", "mmmuPro"),
        ("termInalbench_v2_1".lower(), "terminalBench21"),
        ("gdpval_aa_normalized", "gdpvalNormalized"),
    ]:
        assert catalog.metric(name) is not None, name
        assert catalog.metric(name).key == key


def test_openapi_fixture_lists_our_keys():
    """The captured OpenAPI fixture must contain fields we knowingly map."""
    text = (FIXTURES / "openapi.yaml").read_text(encoding="utf-8")
    props = re.findall(r"^        ([a-z][a-z0-9_]*):$", text, re.MULTILINE)
    assert "artificial_analysis_intelligence_index" in props
    assert "gpqa_diamond" in props
    assert catalog.metric("artificial_analysis_intelligence_index") is not None


def test_benchmark_lookup():
    assert catalog.benchmark("gpqa-diamond").key == "gpqa"
    assert catalog.benchmark("AA-Briefcase Elo").key == "briefcaseElo"
    assert catalog.benchmark("nope") is None


def test_field_names_nonempty():
    names = catalog.field_names()
    assert "gpqa" in names and "intelligence" in names
    assert names == sorted(names)


# --------------------------------------------------------------------------- #
# format_value
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key,value,expected", [
    ("intelligence", None, "-"),
    ("gpqa", 0.572727272727273, "57.3%"),
    ("hle", 0.0, "0.0%"),
    ("briefcaseElo", 1673.52, "1674"),
    ("openness", 52.7777777, "52.8"),
    ("cost_per_task", 7.629706, "$7.63"),
    ("cost_per_task", 0.00512, "$0.0051"),
    ("price_in", 0.6, "$0.60"),
    ("tps", 49.5248, "49.5"),
    ("ttft", 2.7602, "2.8s"),
    ("out_tokens_per_task", 78110.8, "78k"),
    ("context_tokens", 128000, "128k"),
    ("params_b", 108, "108"),
    ("is_open_weights", True, "yes"),
    ("is_open_weights", False, "no"),
    ("release_date", "2025-08-11", "2025-08-11"),
])
def test_format_value(key, value, expected):
    assert catalog.format_value(key, value) == expected


def test_format_value_accepts_aliases():
    assert catalog.format_value("GPQA Diamond", 0.5) == "50.0%"
    assert catalog.format_value("cost", 1.5) == "$1.50"


# --------------------------------------------------------------------------- #
# T6 fidelity fixes
# --------------------------------------------------------------------------- #

_SPEED_DISTRIBUTION = {
    "tps_p05": ("tps", "high"),
    "tps_q25": ("tps", "high"),
    "tps_q75": ("tps", "high"),
    "tps_p95": ("tps", "high"),
    "ttft_p05": ("sec", "low"),
    "ttft_q25": ("sec", "low"),
    "ttft_q75": ("sec", "low"),
    "ttft_p95": ("sec", "low"),
}


def test_speed_distribution_metrics_registered():
    for key, (kind, better) in _SPEED_DISTRIBUTION.items():
        metric = catalog.metric(key)
        assert metric is not None, key
        assert metric.group == "speed"
        assert metric.kind == kind
        assert metric.better == better
        assert catalog.VALUE_SOURCE[key] == ("speed", key)


def test_enterprise_ops_gym_is_catalogued():
    bench = catalog.benchmark("enterpriseOpsGym")
    assert bench is not None
    assert bench.slug == "enterprise-ops-gym-aa"


# --------------------------------------------------------------------------- #
# T7 audit: newly-registered payload metrics
# --------------------------------------------------------------------------- #

_NEW_BENCHMARKS = {
    "mlcrAccuracy": ("pct", "high"),
    "mlcrCompleteness": ("pct", "high"),
    "mlcrConciseness": ("pct", "high"),
    "analystAgentPassAt1": ("pct", "high"),
    "analystAgentPassAtK": ("pct", "high"),
    "cweBenchRefusalRate": ("pct", "low"),
    "cybergymE2eRefusalRate": ("pct", "low"),
    "deepsecBenchRefusalRate": ("pct", "low"),
}


def test_newly_registered_benchmark_metrics():
    for key, (kind, better) in _NEW_BENCHMARKS.items():
        bench = catalog.benchmark(key)
        assert bench is not None, key
        metric = catalog.metric(key)
        assert metric is not None and metric.kind == kind and metric.better == better
