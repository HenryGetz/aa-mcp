"""Tests for the metric/benchmark registry and formatting."""

from __future__ import annotations

import pathlib

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
        assert b.unit in ("%", "Elo", "index", "mixed", "s", "tok/s", "USD/task",
                          "chars/s", "USD/query", "text")
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


def test_api_vocabulary_field_names_resolve():
    """AA's published API field names resolve to our canonical keys."""
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


def test_live_payload_fixtures_list_fields_we_map():
    """The captured live payloads carry the AA fields our registry maps."""
    payloads = (
        (FIXTURES / "leaderboard.rsc").read_text(encoding="utf-8")
        + (FIXTURES / "model_page_chart.rsc").read_text(encoding="utf-8")
    )
    for field in ("intelligenceIndex", "gpqa", "mmmuPro", "terminalBench21",
                  "gdpvalNormalized", "releaseDate"):
        assert field in payloads, field
    assert catalog.metric("intelligence") is not None
    assert catalog.benchmark("terminalBench21") is not None


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
    "cyberRefusalRate": ("pct", "low"),
    "cyberMitigationStatus": ("str", "high"),
}


def test_newly_registered_benchmark_metrics():
    for key, (kind, better) in _NEW_BENCHMARKS.items():
        bench = catalog.benchmark(key)
        assert bench is not None, key
        metric = catalog.metric(key)
        assert metric is not None and metric.kind == kind and metric.better == better


# --------------------------------------------------------------------------- #
# T8: benchmark source hints + untracked benchmarks
# --------------------------------------------------------------------------- #


def test_source_hint_classification():
    expect = {
        "gpqa": "leaderboard",
        "intelligence": "leaderboard",
        "livecodebench": "rich",
        "briefcaseElo": "rich",
        "aime25": "rich",
        "capabilities.legal": "rich",
        "coding": "none",
        "agentic": "none",
        "decisionIndex": "chart",
        "mmluPro": "chart",
        "wildguardtest": "chart",
    }
    for key, hint in expect.items():
        assert catalog.BENCHMARKS[key].source_hint == hint, key


def test_source_hint_values_are_known_and_counted():
    from collections import Counter

    hints = Counter(b.source_hint for b in catalog.BENCHMARKS.values())
    assert set(hints) <= {"leaderboard", "rich", "api", "chart", "none"}
    assert hints["leaderboard"] == 20
    # "none" = AA publishes the composite only through its paid data API
    assert hints["none"] == 2
    assert hints["api"] == 0
    assert sum(hints.values()) == len(catalog.BENCHMARKS)


def test_untracked_benchmarks_notes_are_factual():
    for key in ("mathvista", "docvqa", "human eval", "humaneval", "mbpp",
                "chatbot arena", "lmsys arena", "mt-bench", "alpaca eval"):
        note = catalog.UNTRACKED_BENCHMARKS[key]
        assert note.startswith("AA does not track")
        assert len(note) > 40


def test_partially_tracked_benchmark_notes_name_the_real_surface():
    """BFCL/IFStruct are *not* untracked: AA publishes them on the on-device set.

    The note must say so (and point at the surface) rather than claiming AA has
    nothing — that claim was wrong until 2026-10-16.
    """
    for key in ("bfcl", "berkeley function calling"):
        note = catalog.UNTRACKED_BENCHMARKS[key]
        assert "AA tracks BFCL only on its on-device benchmark set" in note
        assert "/hardware-inference-stack/mobile-phones" in note
        assert "bfcl_500" in note and "bfcl_small" in note
    ifstruct = catalog.UNTRACKED_BENCHMARKS["ifstruct"]
    assert ifstruct.startswith("AA tracks IFStruct only")
    assert "/hardware-inference-stack/mobile-phones" in ifstruct


# --------------------------------------------------------------------------- #
# Wave A: the lower-is-better set must cover every rankable metric that needs it
# --------------------------------------------------------------------------- #

def test_lower_is_better_marks_match_descriptions():
    """Every benchmark described as "lower is better" must rank that way (H2)."""
    lowered = {b.key for b in catalog.BENCHMARKS.values()
               if "lower is better" in b.desc.lower()}
    assert lowered == {
        "omniscienceHallucinationRate",
        "cweBenchRefusalRate",
        "cyberRefusalRate",
        "cybergymE2eRefusalRate",
        "deepsecBenchRefusalRate",
        # 2026-10-16: the speech/search boards' WER, latency and cost columns
        "sttWerIndex", "sttWordErrorRate", "sttEarnings22Wer", "sttVoxpopuliWer",
        "sttAgenttalkWer", "sttStreamingWerIndex", "sttStreamingEarnings22Wer",
        "sttStreamingAgenttalkWer", "sttStreamingTimeToFinal",
        "sttStreamingTimeToFirstPartial", "ttsGenerationTime", "searchAvgLatency",
        "searchCostPerQuery", "searchCostPerTask",
    }
    for key in lowered:
        assert catalog.metric(key).better == "low", key
    # ... and nothing else claims "low" among the benchmark-derived metrics
    assert {k for k, m in catalog.METRICS.items()
            if m.better == "low" and k in catalog.BENCHMARKS} == lowered


def test_every_metric_has_a_usable_direction():
    for key, metric in catalog.METRICS.items():
        assert metric.better in (None, "high", "low"), key
    for key in catalog.METRICS:
        # every sortable key must resolve, so select.sort_models finds a direction
        assert catalog.metric(key) is not None


# --------------------------------------------------------------------------- #
# every field name the reference advertises must resolve (audit M)
# --------------------------------------------------------------------------- #

#: the general (non-media-only) names listed by `aa_reference topic=fields`
_ADVERTISED_FIELDS = (
    "intelligence", "estimated", "coding", "agentic", "omniscience",
    "omniscience_accuracy", "omniscience_non_hallucination", "openness",
    "cost_per_task", "price_in", "price_out", "cache_read",
    "cache_write", "cache_hit_discount", "tps", "ttft", "ttfa",
    "e2e", "reasoning_time", "out_tokens_per_task", "context_tokens", "params_b",
    "active_params_b", "release_date", "knowledge_cutoff", "license", "weights_url",
    "is_open_weights", "is_reasoning", "effort", "deprecated", "size_class",
    "modalities_in", "modalities_out", "creator", "slug", "name",
)

#: template spellings in that text -> a concrete key they stand for
_ADVERTISED_TEMPLATES = (
    ("capabilities.<name>", "capabilities.legal"),
    ("blended_*", "blended_0_3_1"),
)


def test_reference_advertises_only_resolvable_fields():
    from aa_mcp import reference

    text = reference.TOPICS["fields"]
    for name in _ADVERTISED_FIELDS:
        assert name in text, name
        assert catalog.metric(name) is not None, name
    for spelling, example in _ADVERTISED_TEMPLATES:
        assert spelling in text, spelling
        assert catalog.metric(example) is not None, example


def test_reasoning_time_is_an_alias_of_reasoning_s():
    assert catalog.metric("reasoning_time").key == "reasoning_s"


def test_sequence_values_render_as_plus_joined():
    assert catalog.format_value("modalities_in", ("text", "image")) == "text+image"
    assert catalog.format_value("modalities_out", ()) == "-"
    assert catalog.format_value("modalities_in", ["image"]) == "image"
    assert catalog.format_value("weights_url", "https://huggingface.co/x").startswith(
        "https://"
    )


# --------------------------------------------------------------------------- #
# Wave C: the searchable rankable index
# --------------------------------------------------------------------------- #

#: every exact string the user named, and the rankable key it must resolve to
_USER_STRINGS = [
    ("Artificial Analysis Intelligence Index", "intelligence"),
    ("Speed", "tps"),
    ("Cost per Task", "cost_per_task"),
    ("Artificial Analysis Cyber Index", "cyberIndex"),
    ("AA-3D", "aa3dElo"),
    ("Provider Voice Arena Preference Elo", "text_to_speech"),
    ("Artificial Analysis Speech to Speech Index", "speech_to_speech"),
    ("Terminal-Bench 4.0", "terminalBench40"),
    ("Terminal-Bench-Science 0.1", "terminalBenchScience"),
    ("FrontierCode 1.1", "frontierCode"),
    ("ITBench-AA", "itbenchSre"),
    ("AA-Omniscience Index", "omniscience"),
    ("Openness Index", "openness"),
    ("Output Tokens per Intelligence Index Task", "out_tokens_per_task"),
    ("Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index",
     "intelligence_vs_index_total_cost"),
    ("Intelligence Index vs. Output Tokens per Intelligence Index Task",
     "intelligence_vs_out_tokens_per_task"),
]


@pytest.mark.parametrize("text,key", _USER_STRINGS)
def test_user_strings_resolve_via_rankable(text, key):
    r = catalog.rankable(text)
    assert r is not None, text
    assert r.key == key


@pytest.mark.parametrize("text,key", _USER_STRINGS)
def test_user_strings_surface_in_query(text, key):
    keys = {r.key for r in catalog.rankables(query=text)}
    assert key in keys, (text, keys)


def test_rankables_cover_every_benchmark():
    for key, b in catalog.BENCHMARKS.items():
        r = catalog.RANKABLES[key]
        assert r.kind == ("index" if b.unit == "index" else "benchmark"), key
        assert r.label and r.how and r.tags, key


def test_rankables_cover_required_derived_and_arena():
    derived = {"tps", "ttft", "ttfa", "e2e", "cost_per_task", "price_in", "price_out",
               "cache_read", "cache_write", "out_tokens_per_task", "index_total_cost",
               "time_per_task", "context_tokens", "params_b", "active_params_b",
               "release_date"}
    arenas = {"text_to_image", "image_editing", "text_to_video", "image_to_video",
              "video_editing", "text_to_speech", "text_to_speech_controlled",
              "music_instrumental", "music_with_vocals", "speech_to_text",
              "speech_to_text_streaming", "speech_to_speech"}
    for key in derived:
        assert catalog.RANKABLES[key].kind == "derived", key
    for key in arenas:
        assert catalog.RANKABLES[key].kind == "arena", key


def test_rankable_entries_have_valid_shape():
    units = {"%", "Elo", "index", "USD/task", "USD", "USD/1M", "s", "tok/s",
             "tokens", "params", "date", "text", "chars/s", "USD/query"}
    for key, r in catalog.RANKABLES.items():
        assert r.key == key
        assert r.kind in ("benchmark", "index", "derived", "arena", "view"), key
        assert r.unit in units, (key, r.unit)
        assert r.surface in ("leaderboard", "rich", "chart", "api", "board",
                             "none"), key
        assert r.tags and r.label and r.desc and r.how, key
        assert r.how.split()[0].startswith("aa_"), key


def test_version_suffix_tolerance():
    assert catalog.rankable("Terminal-Bench 4.0").key == "terminalBench40"
    assert catalog.rankable("terminalbench-4-0").key == "terminalBench40"
    assert catalog.rankable("FrontierCode 1.1").key == "frontierCode"
    assert catalog.rankable("frontiercode 1.1").key == "frontierCode"
    assert catalog.rankable("Terminal-Bench-Science 0.1").key == "terminalBenchScience"
    assert catalog.rankable("AA-3D").key == "aa3dElo"


def test_rankable_falls_back_to_metric_and_benchmarks():
    assert catalog.rankable("gpqa-diamond").key == "gpqa"
    assert catalog.rankable("intel").key == "intelligence"
    assert catalog.rankable("cost").key == "cost_per_task"
    assert catalog.rankable("text-to-image").key == "text_to_image"
    assert catalog.rankable("nope") is None
    assert catalog.rankable("") is None


def test_domains_cover_the_required_set():
    required = {"coding", "math", "science", "security", "agentic", "tool-use",
                "long-context", "instruction-following", "knowledge", "reasoning",
                "safety", "multimodal", "vision", "speech", "media", "music", "video",
                "business", "finance", "legal", "medical", "engineering", "economics",
                "cost", "speed", "openness"}
    assert required <= set(catalog.DOMAINS)
    for domain, tokens in catalog.DOMAINS.items():
        assert tokens and all(isinstance(t, str) and t for t in tokens), domain


def test_domain_expansion_security():
    keys = {r.key for r in catalog.rankables(domain="security")}
    assert {"cyberIndex", "cweBench", "deepsecBench", "cybergymE2e",
            "wildguardtest"} <= keys


def test_domain_expansion_coding_math_science():
    assert {"livecodebench", "frontierCode", "scicode"} <= {
        r.key for r in catalog.rankables(domain="coding")}
    assert {"aime25", "math500"} <= {r.key for r in catalog.rankables(domain="math")}
    assert {"gpqa", "critpt"} <= {r.key for r in catalog.rankables(domain="science")}


def test_domain_expansion_speech_media_music_video():
    speech = {r.key for r in catalog.rankables(domain="speech")}
    assert {"text_to_speech", "speech_to_speech", "speech_to_text"} <= speech
    assert "music_with_vocals" in {r.key for r in catalog.rankables(domain="music")}
    assert "text_to_video" in {r.key for r in catalog.rankables(domain="video")}
    assert "text_to_image" in {r.key for r in catalog.rankables(domain="media")}


def test_domain_lookup_is_case_and_separator_insensitive():
    assert [r.key for r in catalog.rankables(domain="Tool Use")] == \
           [r.key for r in catalog.rankables(domain="tool-use")]


def test_query_search_speech():
    keys = {r.key for r in catalog.rankables(query="speech")}
    assert {"text_to_speech", "speech_to_speech", "speech_to_text"} <= keys


def test_query_and_domain_and_tag_combine():
    speed = {r.key for r in catalog.rankables(domain="speed")}
    combined = {r.key for r in catalog.rankables(domain="speed", query="ttft")}
    assert combined == {"ttft"}
    assert combined <= speed
    tagged = {r.key for r in catalog.rankables(tag="speed")}
    assert "tps" in tagged and "ttft" in tagged


def test_unknown_domain_and_tag_are_empty():
    assert catalog.rankables(domain="nope") == []
    assert catalog.rankables(tag="nope") == []


def test_rankables_all_by_default_sorted_and_unique():
    got = catalog.rankables()
    assert len(got) == len(catalog.RANKABLES)
    assert got == sorted(got, key=lambda r: (r.kind, r.key))
    assert len({r.key for r in got}) == len(got)


def test_rankable_how_hints_are_actionable():
    assert catalog.rankable("gpqa").how == "aa_leaderboard sort=gpqa"
    assert catalog.rankable("cyberIndex").how == "aa_leaderboard sort=cyberIndex"
    assert catalog.rankable("cyberRefusalRate").how == \
        "aa_leaderboard sort=cyberRefusalRate"
    assert catalog.rankable("cweBench").how == "aa_leaderboard sort=cweBench"
    # the Decision-Models evals now have a real chart set on their own pages
    assert catalog.rankable("when2call").how == "aa_leaderboard sort=when2call"
    assert catalog.rankable("wildguardtest").how == "aa_leaderboard sort=wildguardtest"
    # a container/breakdown kind names a *rankable* sub-score, never itself (a
    # hint must not point at an empty output)
    assert catalog.rankable("aa3dBreakdown").how == \
        "aa_benchmark_leaderboard benchmark=aa3dTurnsP50"
    assert catalog.rankable("briefcaseBreakdown").how == \
        "aa_benchmark_leaderboard benchmark=briefcaseRubricPassRate"
    assert catalog.rankable("tps").how == "aa_leaderboard sort=tps"
    assert catalog.rankable("cost_per_task").how == "aa_pareto x=cost_per_task"
    assert catalog.rankable("text_to_speech").how == "aa_media board=text_to_speech"
    assert catalog.rankable("speech_to_speech").how == "aa_media board=speech_to_speech"


# --------------------------------------------------------------------------- #
# Wave E: every ``how`` hint must be executable and internally consistent
# --------------------------------------------------------------------------- #

#: tool -> the single argument each hint is built from
_HOW_TOOLS = {
    "aa_leaderboard": "sort",
    "aa_benchmark_leaderboard": "benchmark",
    "aa_media": "board",
    "aa_agents": "board",
    "aa_pareto": "x",
}
#: axes ``aa_pareto x=`` accepts (mirrors server._PARETO_AXES)
_PARETO_AXES = {"cost_per_task", "index_total_cost", "out_tokens_per_task",
                "time_per_task", "tps", "context_tokens", "params_b", "ttft",
                "price_in", "price_out"}


def test_every_rankable_how_hint_is_well_formed():
    """Every hint names a known tool with a valid, resolvable argument."""
    arena_keys = {k for k, r in catalog.RANKABLES.items() if r.kind == "arena"}
    for key, r in catalog.RANKABLES.items():
        tool, sep, arg = r.how.partition(" ")
        assert sep and tool in _HOW_TOOLS, (key, r.how)
        name, eq, value = arg.partition("=")
        assert eq == "=" and value, (key, r.how)
        assert name == _HOW_TOOLS[tool], (key, r.how)
        # the argument value resolves through the catalog vocabulary
        assert (catalog.rankable(value) is not None
                or catalog.metric(value) is not None
                or catalog.benchmark(value) is not None), (key, r.how)
        if tool == "aa_leaderboard":
            assert catalog.metric(value) is not None or catalog.rankable(value) is not None
        elif tool == "aa_benchmark_leaderboard":
            assert catalog.benchmark(value) is not None, (key, r.how)
        elif tool in ("aa_media", "aa_agents"):
            assert r.kind == "arena" and value == r.key and value in arena_keys, key
        elif tool == "aa_pareto":
            assert value in _PARETO_AXES, (key, r.how)


def test_aa_leaderboard_hint_covers_every_reachable_surface():
    """``aa_leaderboard sort=`` is the default path for every reachable key.

    Wave F made the leaderboard's sort/filter/field path join a key's values from
    AA's eval chart set / homepage panel by slug, so a chart/panel-backed index
    (the Cyber Index) is now first-class like ``intelligence``. Keys that are
    genuinely unreachable — the JSON-API-only indexes, container/breakdown kinds,
    and chart keys with no eval-page slug — keep the explanatory error path.
    """
    for key, r in catalog.RANKABLES.items():
        bench = catalog.BENCHMARKS.get(key)
        if bench is None:
            continue
        if r.how.startswith("aa_leaderboard sort="):
            assert r.surface in {"leaderboard", "rich", "chart"}, (key, r.surface)
            assert bench.unit != "mixed", (key, bench.unit)
            if r.surface == "chart":
                assert bench.slug, (key, r.slug)
        else:
            assert (bench.unit == "mixed" or bench.source_hint == "api"
                    or not bench.slug), (key, r.how)
    # the audited panel/chart index and its companions are now first-class
    for key in ("cyberIndex", "cyberRefusalRate", "cyberMitigationStatus"):
        assert catalog.RANKABLES[key].surface == "chart"
        assert catalog.RANKABLES[key].how == f"aa_leaderboard sort={key}"


# --------------------------------------------------------------------------- #
# Wave D: a single-word query naming a domain expands to that domain (D3)
# --------------------------------------------------------------------------- #

def test_query_domain_recognises_only_bare_domain_words():
    assert catalog.query_domain("security") == "security"
    assert catalog.query_domain("Tool Use") is None      # multi-word stays a query
    assert catalog.query_domain("cyber") is None         # not a domain name
    assert catalog.query_domain("") is None


def test_single_word_domain_query_equals_the_domain():
    assert ({r.key for r in catalog.rankables(query="security")}
            == {r.key for r in catalog.rankables(domain="security")})
    assert "cyberIndex" in {r.key for r in catalog.rankables(query="security")}


def test_multiword_query_keeps_the_tokenised_and_behaviour():
    keys = {r.key for r in catalog.rankables(query="cyber index")}
    assert "cyberIndex" in keys
    assert "cweBench" not in keys       # no "index" token in its text


# --------------------------------------------------------------------------- #
# Wave C polish: comparison views + deterministic query ordering
# --------------------------------------------------------------------------- #

_VIEW_STRINGS = [
    ("Intelligence Index vs. Cost per Task", "intelligence_vs_cost_per_task"),
    ("Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index",
     "intelligence_vs_index_total_cost"),
    ("Intelligence Index vs. Output Tokens per Intelligence Index Task",
     "intelligence_vs_out_tokens_per_task"),
    ("Intelligence Index vs. Speed", "intelligence_vs_speed"),
]


@pytest.mark.parametrize("text,key", _VIEW_STRINGS)
def test_comparison_views_resolve_and_search(text, key):
    r = catalog.rankable(text)
    assert r is not None and r.kind == "view" and r.key == key, text
    assert key in {x.key for x in catalog.rankables(query=text)}


@pytest.mark.parametrize("text,key", [
    ("Intelligence Index vs Cost to Run AA Intelligence Index",
     "intelligence_vs_index_total_cost"),
    ("Intelligence Index versus Cost to Run Artificial Analysis Intelligence Index",
     "intelligence_vs_index_total_cost"),
    ("Cost to Run AA Intelligence Index", "intelligence_vs_index_total_cost"),
    ("Intelligence Index vs. Cost per Index Task", "intelligence_vs_cost_per_task"),
    ("Intelligence Index vs Output Tokens per Task",
     "intelligence_vs_out_tokens_per_task"),
    ("Speed vs. Intelligence Index", "intelligence_vs_speed"),
])
def test_view_alias_variants_resolve(text, key):
    r = catalog.rankable(text)
    assert r is not None and r.key == key, text


def test_view_how_points_at_the_pareto_axis():
    assert catalog.rankable("Intelligence Index vs. Speed").how == "aa_pareto x=tps"
    assert catalog.rankable(
        "Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index"
    ).how == "aa_pareto x=index_total_cost"


def test_query_orders_exact_match_then_numeric_unit():
    keys = [r.key for r in catalog.rankables(query="AA-3D")]
    assert keys[0] == "aa3dElo"                                  # exact alias first
    assert keys.index("aa3dElo") < keys.index("aa3dBreakdown")  # Elo before container


def test_query_ordering_is_deterministic():
    a = [r.key for r in catalog.rankables(query="index")]
    b = [r.key for r in catalog.rankables(query="index")]
    assert a == b and a


# --------------------------------------------------------------------------- #
# task domains AA publishes no benchmark for (wave G, G8)
# --------------------------------------------------------------------------- #

def test_task_domains_are_factual_and_never_claim_equivalence():
    assert catalog.TASK_DOMAINS
    for task, note in catalog.TASK_DOMAINS.items():
        assert note.startswith(f"AA does not measure {task}") or \
            "AA does not measure" in note, task
        assert "closest AA measure" in note or "the closest AA measure" in note, task
        assert "does not track" not in note


def test_task_domains_cover_the_briefed_task_words():
    for word in ("classification", "summarization", "translation", "retrieval",
                 "rag", "sql", "data analysis", "tool calling"):
        hit = catalog.task_domain(word)
        assert hit is not None, word
        assert hit[0] in catalog.TASK_DOMAINS


def test_task_domains_name_only_measures_aa_publishes():
    """Every AA measure named in a task note is a real catalog key or a flag set."""
    known = set(catalog.BENCHMARKS) | set(catalog.METRICS) | {
        "IFBench", "MMLU-Pro", "Global-MMLU-Lite", "GDP.pdf", "AA-LCR",
        "AA-AnalystAgent", "\u03c4\u00b2-Bench", "\u03c4\u00b3-Banking",
        "WildGuardTest", "MMMU-Pro", "functionCalling", "jsonMode",
    }
    for note in catalog.TASK_DOMAINS.values():
        for named in ("IFBench", "MMLU-Pro", "Global-MMLU-Lite", "GDP.pdf", "AA-LCR",
                      "AA-AnalystAgent", "\u03c4\u00b2-Bench", "\u03c4\u00b3-Banking",
                      "WildGuardTest", "MMMU-Pro"):
            if named in note:
                assert named in known, named


def test_task_domain_matches_a_free_text_query():
    assert catalog.task_domain("best model for classification")[0] == "classification"
    assert catalog.task_domain("classif")[0] == "classification"
    assert catalog.task_domain("SUMMARIZATION")[0] == "summarization"
    assert catalog.task_domain("function calling")[0] == "function calling"
    assert catalog.task_domain("") is None
    assert catalog.task_domain("a") is None
    assert catalog.task_domain("zzzqqq") is None


def test_task_domain_is_exported():
    assert "TASK_DOMAINS" in catalog.__all__
    assert "task_domain" in catalog.__all__


# --------------------------------------------------------------------------- #
# 2026-10-16: the surfaces added after the coverage audit
# --------------------------------------------------------------------------- #

#: (key, aliases that must resolve to it)
_NEW_RANKABLES = [
    ("multilingual", ("multilingual", "Multilingual Index",
                      "Artificial Analysis Multilingual Index",
                      "artificial_analysis_multilingual_index", "languages")),
    ("multilingual.ar", ("multilingual.ar",)),
    ("hleMultichoice", ("hleMultichoice", "hle-multichoice", "HLE-MultiChoice")),
    ("omniscienceDecision", ("omniscienceDecision", "aa-omniscience-decision",
                             "AA-Omniscience-Decision")),
    ("omniscienceDecisionNonHallucination",
     ("omniscienceDecisionNonHallucination",
      "Omniscience-Decision Non-Hallucination")),
    ("when2call", ("when2call", "When2Call")),
    ("wildguardtest", ("wildguardtest", "WildGuardTest")),
    ("mobile.gpqa", ("mobile.gpqa", "On-device GPQA")),
    ("mobile.bfcl_500", ("mobile.bfcl_500", "BFCL-500", "BFCL")),
    ("mobile.ifstruct", ("mobile.ifstruct", "IFStruct")),
    ("openness.modelAvailability", ("openness.modelAvailability",)),
    ("omniscience.domain.law", ("omniscience.domain.law",)),
    ("omniscience.language.python", ("omniscience.language.python",)),
    ("terminalBenchScience.domain.life-sciences",
     ("terminalBenchScience.domain.life-sciences",)),
    ("enterpriseOpsGym.domain.hybrid", ("enterpriseOpsGym.domain.hybrid",)),
    ("briefcaseAnalyticalQualityElo", ("briefcaseAnalyticalQualityElo",)),
    ("harveyCriteriaPass", ("harveyCriteriaPass",)),
    ("gdpPdfMacroPassRate", ("gdpPdfMacroPassRate",)),
    ("automationBenchStrictScore", ("automationBenchStrictScore",)),
    ("itbenchAvgTurnsPerTask", ("itbenchAvgTurnsPerTask",)),
    ("medianCanonicalAnswerOutputSpeed", ("medianCanonicalAnswerOutputSpeed",)),
    # the speech / TTS / search board columns
    ("sttWerIndex", ("sttWerIndex", "AA-WER", "STT WER", "Word Error Rate")),
    ("sttEarnings22Wer", ("sttEarnings22Wer", "Earnings22")),
    ("sttVoxpopuliWer", ("sttVoxpopuliWer", "VoxPopuli")),
    ("sttAgenttalkWer", ("sttAgenttalkWer", "AgentTalk")),
    ("sttStreamingTimeToFinal", ("sttStreamingTimeToFinal",)),
    ("sts", ("sts", "STS Index", "Realtime Voice Index")),
    ("stsBigBenchAudio", ("stsBigBenchAudio", "Big Bench Audio", "BBA")),
    ("stsTauVoice", ("stsTauVoice", "tau3-Voice")),
    ("stsAgenticElo", ("stsAgenticElo",)),
    ("ttsPronunciationPassRate", ("ttsPronunciationPassRate",
                                  "Pronunciation Robustness")),
    ("ttsCharactersPerSecond", ("ttsCharactersPerSecond",
                                "Characters Per Second", "TTS Throughput")),
    ("searchBrowsecompAccuracy", ("searchBrowsecompAccuracy", "BrowseComp")),
    ("searchCostPerQuery", ("searchCostPerQuery", "Cost per Search Query")),
    ("searchQualityIndex", ("searchQualityIndex", "AA Search Index")),
]


@pytest.mark.parametrize("key,aliases", _NEW_RANKABLES)
def test_new_rankables_exist_and_resolve(key, aliases):
    rank = catalog.rankable(key)
    assert rank is not None, key
    assert rank.key == key
    for alias in aliases:
        got = catalog.rankable(alias)
        assert got is not None and got.key == key, (alias, got)


def test_new_chart_benchmarks_declare_a_chart_slug():
    """A chart-set key with no slug can never be reached by the join."""
    for key in ("multilingual", "hleMultichoice", "omniscienceDecision",
                "when2call", "wildguardtest", "mobile.gpqa", "mobile.bfcl_small",
                "openness.modelAvailability", "omniscience.domain.law",
                "terminalBenchScience.domain.life-sciences",
                "briefcaseRubricPassRate", "medianCanonicalAnswerOutputSpeed"):
        bench = catalog.BENCHMARKS[key]
        assert bench.source_hint == "chart", key
        assert bench.slug, key


def test_mobile_evals_are_namespaced_in_the_catalog():
    keys = [b.key for b in catalog.BENCHMARKS.values() if b.slug == "mobile"]
    assert keys == [f"mobile.{name}" for name in catalog.MOBILE_EVALS]


def test_every_breakdown_container_hint_names_a_rankable_sub_score():
    """A hint must never point at the container itself (that output is empty)."""
    for key, bench in catalog.BENCHMARKS.items():
        if bench.unit != "mixed":
            continue
        rank = catalog.rankable(key)
        assert rank is not None
        tool, _sep, arg = rank.how.partition(" ")
        if tool == "aa_benchmark_leaderboard":
            assert arg.startswith("benchmark=")
            target = arg.split("=", 1)[1]
            assert target != key, f"{key} points at itself"
            assert catalog.rankable(target) is not None, (key, target)
            assert catalog.BENCHMARKS[target].unit != "mixed", (key, target)


def test_domains_expand_to_the_new_surfaces():
    multi = {r.key for r in catalog.rankables(domain="multilingual")}
    assert {"multilingual", "multilingual.ar"} <= multi
    on_device = {r.key for r in catalog.rankables(domain="mobile")}
    assert "mobile.bfcl_500" in on_device
    langs = {r.key for r in catalog.rankables(query="multilingual")}
    assert "multilingual" in langs


# --------------------------------------------------------------------------- #
# 2026-10-16: Elo display rounding and the 12-character column headers
# --------------------------------------------------------------------------- #

def test_elo_cells_round_half_away_from_zero():
    """AA's own table rounds ``.5`` up; Python's ``:.0f`` rounds half-to-even.

    The site ships its rendered string in the payload's ``formatted.elo``, so the
    convention is observable rather than assumed: raw 1146.5 -> "1147",
    1092.5 -> "1093", 1138.5 -> "1139".  Display only — the stored value stays the
    exact float.
    """
    assert catalog.format_value("briefcaseElo", 1146.5) == "1147"
    assert catalog.format_value("briefcaseElo", 1092.5) == "1093"
    assert catalog.format_value("briefcaseElo", 1138.5) == "1139"
    assert catalog.format_value("briefcaseElo", 1173.94) == "1174"
    assert catalog.format_value("briefcaseElo", 1174.5) == "1175"
    assert catalog.format_value("briefcaseElo", -0.5) == "-1"
    assert catalog.format_value("briefcaseElo", 1200.0) == "1200"


def test_metric_labels_fit_the_column_and_stay_distinguishable():
    """A header cell is 12 characters; two benchmarks must not share one label."""
    seen: dict[str, str] = {}
    for key in catalog.BENCHMARKS:
        metric = catalog.METRICS.get(key)
        if metric is None:
            continue
        assert len(metric.label) <= 12, (key, metric.label)
        assert metric.label not in seen, (metric.label, seen.get(metric.label), key)
        seen[metric.label] = key


def test_new_long_labels_get_a_short_display_label():
    """The long labels the audit added must not collapse into one header."""
    assert catalog.metric("mobile.bfcl_500").label == "Dev BFCL-500"
    assert catalog.metric("mobile.bfcl_small").label == "Dev BFCL-Sm"
    assert catalog.metric("mobile.gpqa").label == "Dev GPQA"
    assert catalog.metric("hleMultichoice").label == "HLE-MCQ"
    assert catalog.metric("globalMmluLiteScore").label == "Global-MMLU"
    assert catalog.metric("multilingual").label == "Multilingual"
    assert catalog.metric("multilingual.ja").label == "Japanese"
    assert catalog.metric("openness.modelTransparency").label == "Open Model"
    assert catalog.metric("openness.transparencyMethodology").label == "Open Method"
    # the canonical keys are unchanged
    assert catalog.metric("mobile.bfcl_500").key == "mobile.bfcl_500"
    assert catalog.benchmark("mobile.bfcl_500").label == "On-device BFCL-500"
