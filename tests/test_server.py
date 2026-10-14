"""Tests for the server layer: the Pareto frontier, the rankable search index and
the comparison tool (spec parsing, diff view, bounds).

Everything here is offline: the data layer is replaced by a handful of hand-built
``Model`` objects, so these tests exercise the server's own logic (frontier
selection, axis resolution, coverage labels, YAML subset, response bounds).
"""

from __future__ import annotations

import inspect
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aa_mcp import catalog, server
from aa_mcp.normalize import Model

# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def _model(slug: str, name: str | None = None, **overrides) -> Model:
    """A minimal ``Model`` (the shape ``_panel_model`` builds), overridable."""
    values: dict = {
        "slug": slug, "name": name or slug.title(), "short_name": name or slug.title(),
        "creator": "Lab", "creator_slug": "lab", "release_date": "2026-01-01",
        "deprecated": False, "deprecated_to": None, "is_reasoning": False,
        "is_open_weights": False, "effort": None, "params_b": None,
        "active_params_b": None, "context_tokens": 128_000, "license": None,
        "license_url": None, "weights_url": None, "knowledge_cutoff": None,
        "size_class": None, "modalities_in": (), "modalities_out": (),
        "intelligence": None, "estimated": False, "indices": {}, "evals": {},
        "pricing": {}, "speed": {}, "cost_per_task": None, "cost_breakdown": None,
        "per_eval_cost": None, "per_eval": None, "source": "leaderboard",
    }
    values.update(overrides)
    return Model(**values)


@pytest.fixture
def fake(monkeypatch):
    """Four models + a patched data layer; returns ``{slug: Model}``."""
    alpha = _model(
        "alpha", "Alpha One", creator="LabA", intelligence=60.0, cost_per_task=1.0,
        evals={"gpqa": 0.50, "cyberIndex": 90.0},
        pricing={"in": 1.0, "out": 2.0},
        speed={"tps": 100.0, "ttft": 1.0, "out_tokens_per_task": 2_000.0},
        cost_breakdown={"index_total": 1_000.0},
        per_eval=[{"slug": "gpqa", "timePerTask": 10.0},
                  {"slug": "hle", "timePerTask": 20.0}],
    )
    beta = _model("beta", "Beta Two", creator="LabB", intelligence=50.0,
                  cost_per_task=0.5, evals={"gpqa": 0.40},
                  cost_breakdown={"index_total": 500.0},
                  per_eval=[{"slug": "gpqa", "timePerTask": 4.0}])
    gamma = _model("gamma", "Gamma Three", creator="LabC", intelligence=40.0,
                   cost_per_task=4.0)
    delta = _model("delta", "Delta Four", creator="LabD", intelligence=30.0)
    models = [alpha, beta, gamma, delta]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: models)
    monkeypatch.setattr(server, "_lb_cache", lambda: ("leaderboard", False))
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name, api=False: (None, False))
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [])
    return {m.slug: m for m in models}


# --------------------------------------------------------------------------- #
# aa_pareto: axes
# --------------------------------------------------------------------------- #

def test_pareto_axis_names_cover_the_documented_set():
    for name in ("cost_per_task", "index_total_cost", "out_tokens_per_task",
                 "time_per_task", "context_tokens", "params_b", "ttft",
                 "price_in", "price_out"):
        assert server._pareto_axis(name) == name


@pytest.mark.parametrize("alias,key", [
    ("cost", "cost_per_task"),
    ("$/task", "cost_per_task"),
    ("cost_per_task", "cost_per_task"),
    ("index_total_cost", "index_total_cost"),
    ("Cost to Run the Intelligence Index", "index_total_cost"),
    ("Output Tokens per Task", "out_tokens_per_task"),
    ("tokens per task", "out_tokens_per_task"),
    ("time_per_task", "time_per_task"),
    ("Time per Task", "time_per_task"),
    ("ctx", "context_tokens"),
    ("Context", "context_tokens"),
    ("params", "params_b"),
    ("TTFT", "ttft"),
    ("in", "price_in"),
    ("out", "price_out"),
])
def test_pareto_axis_aliases(alias, key):
    assert server._pareto_axis(alias) == key


def test_pareto_axis_unknown_lists_the_valid_axes():
    with pytest.raises(ValueError) as exc:
        server._pareto_axis("nonsense")
    assert "valid axes" in str(exc.value)
    assert "index_total_cost" in str(exc.value)


def test_axis_value_derives_the_model_page_axes():
    m = _model("m", cost_per_task=2.0, cost_breakdown={"index_total": 1_234.0},
               per_eval=[{"slug": "a", "timePerTask": 10.0},
                         {"slug": "b", "timePerTask": 20.0}],
               speed={"ttft": 3.0})
    assert server._axis_value(m, "cost_per_task") == 2.0
    assert server._axis_value(m, "index_total_cost") == 1_234.0
    assert server._axis_value(m, "time_per_task") == 15.0
    assert server._axis_value(m, "ttft") == 3.0
    assert server._axis_value(m, "gpqa") is None


def test_axis_value_without_model_page_data_is_none():
    m = _model("m", per_eval=[])
    assert server._axis_value(m, "index_total_cost") is None
    assert server._axis_value(m, "time_per_task") is None


def test_axis_text_and_ratio_text():
    assert server._axis_text("cost_per_task", 0.5) == "$0.50"
    assert server._axis_text("index_total_cost", 1_234.0) == "$1,234"
    assert server._axis_text("index_total_cost", 12.5) == "$12.50"
    assert server._axis_text("time_per_task", 15.0) == "15.0s"
    assert server._axis_text("gpqa", None) == "-"
    assert server._ratio_text(None) == "-"
    assert server._ratio_text(0.0105) == "0.011"
    assert server._ratio_text(9.64) == "9.6"
    assert server._ratio_text(1_134.2) == "1,134"


def test_score_label_prefers_the_full_rankable_name():
    assert server._score_label("intelligence") == "Intel"
    assert server._score_label("cyberIndex") == "Cyber Index"
    assert server._score_label("gpqa") == "GPQA Diamond"


# --------------------------------------------------------------------------- #
# aa_pareto: the frontier itself
# --------------------------------------------------------------------------- #

def test_pareto_default_columns_and_frontier(fake):
    out = server._pareto()
    head, table = out.splitlines()[0], out.splitlines()[1]
    assert "Intel vs $/task (Pareto frontier, cost ascending)" in head
    assert table == "| Model | Slug | Creator | Intel | $/task | Intel/$/task |"
    # beta (0.5, 50) and alpha (1.0, 60) are non-dominated; gamma (4.0, 40) is
    # dominated by beta and delta has no $/task at all.
    rows = [line for line in out.splitlines() if line.startswith("| ")][1:]
    assert [row.split("|")[2].strip() for row in rows] == ["beta", "alpha"]
    assert "gamma" not in out and "delta" not in out
    assert "— knee ≈ " in out


def test_pareto_is_cost_ascending(fake):
    out = server._pareto(x="cost_per_task", top=5)
    rows = [line for line in out.splitlines() if line.startswith("| ")][1:]
    costs = [float(row.split("|")[5].strip().lstrip("$")) for row in rows]
    assert costs == sorted(costs)


def test_pareto_axis_index_total_cost(fake):
    out = server._pareto(x="index_total_cost")
    assert "Intel vs $/index (Pareto frontier, cost ascending)" in out
    assert "| Intel | $/index | Intel/$/index |" in out
    assert "$500" in out and "$1,000" in out
    assert "model-page data (rich dataset)" in out


def test_pareto_axis_time_per_task(fake):
    out = server._pareto(x="time_per_task")
    assert "Intel vs s/task (Pareto frontier, time ascending)" in out
    assert "4.0s" in out and "15.0s" in out


def test_pareto_axis_out_tokens_per_task(fake):
    out = server._pareto(x="out_tokens_per_task")
    assert "Intel vs tok/task (Pareto frontier, tokens ascending)" in out
    assert "2k" in out


def test_pareto_benchmark_score_uses_its_own_label(fake):
    out = server._pareto(score="cyberIndex")
    assert "Cyber Index vs $/task" in out
    assert "90.0" in out


def test_pareto_top_and_include_all(fake):
    short = server._pareto(top=1)
    assert "1 of 2 frontier points" in short
    assert "include_all=true" in short
    every = server._pareto(include_all=True)
    assert "2 frontier points" in every
    assert "include_all=true" not in every


def test_pareto_missing_score_explains_itself(fake):
    with pytest.raises(ValueError) as exc:
        server._pareto(score="openness")
    assert "no values" in str(exc.value)


def test_pareto_missing_axis_explains_itself(fake, monkeypatch):
    lonely = _model("x", intelligence=50.0)          # no cost breakdown at all
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: ([lonely], rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: [lonely])
    with pytest.raises(ValueError) as exc:
        server._pareto(x="index_total_cost")
    assert "model-page data" in str(exc.value)


def test_pareto_joins_a_panel_score_onto_the_leaderboard_row(fake, monkeypatch):
    """A benchmark AA publishes only on a panel still gets a frontier."""
    panel = _model("beta", "Beta Two", evals={"terminalBench40": 0.70})
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda key, refresh=False: [panel] if key == "terminalBench40" else [])
    out = server._pareto(score="terminalBench40")
    assert "Terminal-Bench 4.0 vs $/task" in out
    assert "eval chart/panel" in out.splitlines()[0]
    assert "joined onto the leaderboard rows" in out
    # the x axis came from the leaderboard row, not the panel entry
    assert "$0.50" in out


def test_pareto_no_models_matching_returns_a_note(fake):
    out = server._pareto(creator="nobody")
    assert out.startswith("# no models match")


def test_pareto_frontier_drops_dominated_points():
    points = [(  # (slug, cost, score)
        _model("cheap", cost_per_task=1.0, intelligence=10.0), 1.0, 10.0),
        (_model("mid", cost_per_task=2.0, intelligence=20.0), 2.0, 20.0),
        (_model("dominated", cost_per_task=3.0, intelligence=15.0), 3.0, 15.0),
        (_model("expensive", cost_per_task=4.0, intelligence=25.0), 4.0, 25.0),
    ]
    front = server._pareto_frontier([m for m, _x, _s in points],
                                    lambda m: m.intelligence,
                                    lambda m: m.cost_per_task)
    assert [m.slug for m, _x, _s in front] == ["cheap", "mid", "expensive"]


def test_pareto_knee_stops_before_a_five_times_cliff():
    front = [(_model(f"m{i}"), x, s) for i, (x, s) in enumerate(
        [(1.0, 10.0), (2.0, 20.0), (3.0, 25.0), (100.0, 26.0)])]
    # ratios (x/s): 0.1, 0.1, 0.12, 3.85 -> 3.85 >= 5 * 0.1, so the knee is m2
    assert server._pareto_knee(front) == 2


def test_pareto_knee_ignores_a_zero_cost_point():
    front = [(_model("free"), 0.0, 30.0), (_model("a"), 1.0, 40.0),
             (_model("b"), 2.0, 45.0)]
    assert server._pareto_knee(front) == 2


def test_pareto_tool_signature_matches_the_brief():
    params = list(inspect.signature(server.aa_pareto).parameters)
    assert params == ["score", "x", "top", "creator", "open_weights",
                      "min_intelligence", "min_context", "include_deprecated",
                      "include_all", "refresh"]


def test_compare_tool_signature_matches_the_brief():
    params = list(inspect.signature(server.aa_compare).parameters)
    assert params == ["queries", "metrics", "view", "compact", "spec", "refresh"]


def test_benchmarks_tool_signature_matches_the_brief():
    params = list(inspect.signature(server.aa_benchmarks).parameters)
    assert params == ["query", "domain", "tag", "verbose"]


# --------------------------------------------------------------------------- #
# the rankable index
# --------------------------------------------------------------------------- #

USER_STRINGS = (
    "Artificial Analysis Intelligence Index", "Speed", "Cost per Task",
    "Artificial Analysis Cyber Index", "AA-3D",
    "Provider Voice Arena Preference Elo",
    "Artificial Analysis Speech to Speech Index", "Terminal-Bench 4.0",
    "Terminal-Bench-Science 0.1", "FrontierCode 1.1", "ITBench-AA",
    "AA-Omniscience Index", "Openness Index",
    "Output Tokens per Intelligence Index Task",
)


@pytest.mark.parametrize("text", USER_STRINGS)
def test_user_strings_resolve_to_a_rankable(text):
    assert server._rankable(text) is not None


def test_every_benchmark_key_is_rankable():
    missing = [key for key in catalog.BENCHMARKS if server._rankable(key) is None]
    assert missing == []


def test_rankable_list_covers_benchmarks_derived_and_arenas():
    keys = {str(r.key) for r in server._rankable_list()}
    assert set(catalog.BENCHMARKS) <= keys
    assert {"cost_per_task", "index_total_cost", "time_per_task", "tps"} <= keys
    assert {"text_to_speech", "speech_to_speech", "text_to_image"} <= keys


def test_rankable_list_filters_by_domain_and_query():
    security = server._rankable_list(domain="security")
    assert security and all(
        any("cyber" in str(t).lower() or "security" in str(t).lower()
            for t in (r.tags + (r.key,)))
        or str(r.key).lower().startswith(("cwe", "cyber", "deepsec", "wildguard"))
        for r in security)
    speech = server._rankable_list(query="speech")
    assert {str(r.key) for r in speech} >= {"speech_to_speech", "text_to_speech"}
    assert server._rankable_list(domain="security", query="speech") == []


def test_domain_tokens_and_match():
    assert "cyber" in (server._domain_tokens("security") or ())
    assert server._domain_tokens("Security") == server._domain_tokens("security")
    assert server._domain_tokens("nope") is None
    r = server._rankable("cyberIndex")
    assert server._domain_match(r, server._domain_tokens("security") or ())
    assert not server._domain_match(r, ("speech",))


def test_fallback_index_is_self_contained():
    """The BENCHMARKS/METRICS fallback must stand in for catalog.rankables()."""
    table = server._build_fallback_rankables()
    assert set(catalog.BENCHMARKS) <= set(table)
    for key, _label, _unit, _tags, _how in server._DERIVED_RANKABLES:
        assert key in table
    for board in server._ARENAS:
        assert board in table
    for r in table.values():
        assert r.kind in ("benchmark", "index", "derived", "arena")
        assert r.how.startswith("aa_")
        assert r.label and r.unit and r.desc


def test_fallback_list_filters_and_version_tolerance():
    assert server._fallback_rankable("Terminal-Bench 4.0") is not None
    assert server._fallback_rankable("FrontierCode 1.1") is not None
    assert server._fallback_rankable("AA-3D") is not None
    assert server._fallback_rankable("Provider Voice Arena Preference Elo") is not None
    assert server._fallback_rankable("nonsense") is None
    hits = server._fallback_list(domain="speech")
    assert {r.key for r in hits} >= {"speech_to_speech", "text_to_speech"}
    with pytest.raises(ValueError):
        server._fallback_list(domain="nope")


def test_strip_version():
    assert server._strip_version("terminalbench40") == "terminalbench"
    assert server._strip_version("frontiercode11") == "frontiercode"
    assert server._strip_version("v4") == ""
    assert server._strip_version("plain") == "plain"


# --------------------------------------------------------------------------- #
# aa_benchmarks
# --------------------------------------------------------------------------- #

def test_benchmarks_unknown_domain_lists_the_valid_ones(fake):
    with pytest.raises(ValueError) as exc:
        server._benchmarks(domain="nope")
    assert "unknown domain" in str(exc.value)
    assert "security" in str(exc.value)


def test_benchmarks_unknown_tag_lists_the_valid_ones(fake):
    with pytest.raises(ValueError) as exc:
        server._benchmarks(tag="nope")
    assert "unknown tag" in str(exc.value)
    assert "speech" in str(exc.value)


def test_benchmarks_zero_results_suggests_close_labels(fake):
    with pytest.raises(ValueError) as exc:
        server._benchmarks(query="zzzqqq")
    assert "closest" in str(exc.value)
    assert "no arguments lists every rankable" in str(exc.value)


def test_benchmarks_untracked_name_answers_without_a_table(fake):
    out = server._benchmarks(query="MathVista")
    assert "AA does not track MathVista" in out


def test_benchmarks_rows_carry_the_how_hint(fake):
    out = server._benchmarks(query="speech")
    assert "How to query" in out
    assert "aa_media board=speech_to_speech" in out
    assert "arena board" in out


def test_benchmarks_domain_rows_and_count(fake):
    out = server._benchmarks(domain="security")
    assert "domain=security" in out.splitlines()[0]
    assert "of" in out.splitlines()[0] and "rankables" in out.splitlines()[0]
    assert "aa_benchmark_leaderboard benchmark=cweBench" in out


def test_benchmarks_hides_measures_for_large_results(fake):
    out = server._benchmarks()
    assert "| Measures |" not in out
    assert "descriptions hidden at this size" in out


# --------------------------------------------------------------------------- #
# aa_compare: spec parsing
# --------------------------------------------------------------------------- #

def test_parse_spec_json_object():
    doc = server._parse_spec('{"models": ["a", "b"], "metrics": "all", "view": "diff"}')
    assert doc == {"models": ["a", "b"], "metrics": "all", "view": "diff"}


def test_parse_spec_yaml_subset():
    doc = server._parse_spec(
        "# a comment\n"
        "models:\n"
        "  - alpha   # inline comment\n"
        "  - beta\n"
        "metrics: [gpqa, tps]\n"
        "view: diff\n"
        "compact: false\n"
        "filters:\n"
        "  open_weights: true\n"
        "  min_intelligence: 30\n"
    )
    assert doc == {"models": ["alpha", "beta"], "metrics": ["gpqa", "tps"],
                   "view": "diff", "compact": False,
                   "filters": {"open_weights": True, "min_intelligence": 30}}


def test_parse_spec_empty_is_empty_mapping():
    assert server._parse_spec("   \n# only a comment\n") == {}


@pytest.mark.parametrize("text,message", [
    ("models:\n\t- a\n", "tabs are not supported"),
    ('{"a": 1} ', None),
    ("[1, 2]", "must be an object"),
    ("- alpha\n- beta\n", "must be a mapping"),
    ("models alpha\n", "expected 'key: value'"),
])
def test_parse_spec_rejects_bad_documents(text, message):
    if message is None:                      # a JSON object is fine
        assert server._parse_spec(text) == {"a": 1}
        return
    with pytest.raises(ValueError) as exc:
        server._parse_spec(text)
    assert message in str(exc.value)


def test_compare_spec_template_is_parseable():
    doc = server._parse_spec(server._COMPARE_SPEC_TEMPLATE)
    assert doc["models"] == ["claude-opus-5-5", "gpt-6-luna", "gemini-3-5-flash"]
    assert doc["metrics"] == "all" and doc["view"] == "diff"
    assert doc["filters"]["open_weights"] is True


def test_spec_yaml_round_trips_through_the_parser():
    doc = {"models": ["a", "b"], "metrics": "all", "view": "diff",
           "compact": False, "filters": {"open_weights": True, "min_intelligence": 30}}
    assert server._parse_spec(server._spec_yaml(doc)) == doc


@pytest.mark.parametrize("text", [
    "plain", "has: colon", "true", "42", "3.5", "x,y", "has #hash", "", "  pad  ",
    "quote\"inside", "back\\slash",
])
def test_yaml_scalars_round_trip(text):
    assert server._yaml_scalar(server._yaml_text(text)) == text


# --------------------------------------------------------------------------- #
# aa_compare: table, diff, spec, bounds
# --------------------------------------------------------------------------- #

def test_compare_table_puts_models_in_columns(fake):
    out = server._compare(["alpha", "beta"])
    assert out.splitlines()[1].startswith("| Metric | Alpha One | Beta Two |")
    assert "| Intelligence | 60.0 | 50.0 |" in out
    assert "| Intel/$ | 60.0 | 100.0 |" in out
    assert "metrics: default" in out


def test_compare_diff_shows_deltas_against_the_first_model(fake):
    out = server._compare(["alpha", "beta"], metrics="intelligence,gpqa,tps",
                          view="diff")
    assert "diff: each cell is value (Δ vs Alpha One" in out.splitlines()[0]
    assert "| Artificial Analysis Intelligence Index | 60.0 | 50.0 (-10.0) |" in out
    assert "| GPQA Diamond | 50.0% | 40.0% (-10.0pp) |" in out
    assert "| Speed (output tokens/s) | 100.0 | - |" in out


def test_compare_explicit_metrics_accept_labels_and_aliases(fake):
    out = server._compare(["alpha", "beta"], metrics="GPQA Diamond, Speed, intel")
    assert "| GPQA Diamond |" in out and "| Speed (output tokens/s) |" in out
    assert "| Artificial Analysis Intelligence Index |" in out


def test_compare_metrics_all_lists_every_shared_rankable(fake):
    out = server._compare(["alpha", "beta"], metrics="all")
    assert "Artificial Analysis Intelligence Index" in out
    assert "GPQA Diamond" in out
    # arena boards are not per-model numbers and must not appear
    assert "Arena Elo" not in out


def test_compare_metrics_benchmarks_limits_the_kinds(fake):
    out = server._compare(["alpha", "beta"], metrics="benchmarks")
    assert "GPQA Diamond" in out
    assert "Cost per Task" not in out


def test_compare_spec_round_trip_reproduces_the_call(fake):
    explicit = server._compare(["alpha", "beta"], metrics="all", view="diff")
    spec = explicit.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert server._compare(spec=spec) == explicit


def test_compare_spec_merges_with_explicit_arguments(fake):
    spec = "models:\n  - alpha\n  - beta\nmetrics: gpqa\n"
    out = server._compare(spec=spec, view="diff")
    assert "| GPQA Diamond |" in out and "(-10.0pp)" in out


def test_compare_spec_filters_gate_fuzzy_matching(fake):
    spec = "models: [alpha, beta]\nfilters:\n  open_weights: true\n"
    # every fixture model is closed-weights, so the fuzzy pool is empty; the
    # exact slugs must still resolve (never silently dropped).
    out = server._compare(spec=spec)
    assert "Alpha One" in out and "Beta Two" in out
    assert "filters: open_weights=True" in out


def test_compare_page_fallback_merges_a_model_page(fake, monkeypatch):
    calls: list[str] = []

    def page(slug, refresh=False):
        calls.append(slug)
        return {slug: _model(slug, "Beta Two", evals={"frontierCode": 0.42})}

    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: [])
    monkeypatch.setattr(server.loaders, "model", page)
    out = server._compare(["alpha", "beta"], metrics="all")
    assert calls == ["alpha", "beta"]
    assert "model page fetched + merged for alpha, beta" in out
    assert "| FrontierCode |" in out and "42.0%" in out


@pytest.mark.parametrize("queries,message", [
    ([], "2-12 models"),
    (["alpha"], "2-12 models"),
    ([f"m{i}" for i in range(13)], "2-12 models"),
])
def test_compare_model_count_is_bounded(fake, queries, message):
    with pytest.raises(ValueError) as exc:
        server._compare(queries)
    assert message in str(exc.value)


def test_compare_unknown_view_lists_the_valid_ones(fake):
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], view="sparkline")
    assert "table, diff" in str(exc.value)


def test_compare_unknown_metric_suggests_alternatives(fake):
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], metrics="gpqqa")
    assert "closest" in str(exc.value)


def test_compare_metric_list_argument_is_accepted(fake):
    out = server._compare(["alpha", "beta"], metrics=["gpqa", "tps"])
    assert "| GPQA Diamond |" in out and "| Speed (output tokens/s) |" in out


def test_compare_without_any_metric_value_explains_itself(fake, monkeypatch):
    bare = _model("bare", "Bare Model", release_date=None, context_tokens=None)
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: ([bare], rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: [bare])
    with pytest.raises(ValueError) as exc:
        server._compare(["bare", "bare"], metrics="all")
    assert "no metric rows" in str(exc.value)


def test_compare_wide_tables_carry_a_slug_row(fake, monkeypatch):
    many = [_model(f"m{i}", f"Model {i}", intelligence=float(60 - i)) for i in range(8)]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (many, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: many)
    out = server._compare([m.slug for m in many])
    assert "| Slug | m0 | m1 |" in out


def test_compare_rejects_unknown_spec_keys_and_filters(fake):
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], spec="sparkline: true\n")
    assert "unknown key" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], spec="filters:\n  nope: 1\n")
    assert "unknown filter" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], spec="filters: 3\n")
    assert "filters must be a mapping" in str(exc.value)


def test_compare_unresolvable_model_errors_with_candidates(fake):
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "not-a-model"])
    assert "no model matches" in str(exc.value)


def test_fit_compare_truncates_and_says_so():
    labels = ["Metric", "Alpha", "Beta"]
    rows = [[f"Metric {i}", str(i), str(i + 1)] for i in range(60)]
    out = server._fit_compare("# 2 models · 60 metrics", labels, rows, "— spec",
                              limit=1_200)
    assert "response capped at 1 kB: showing" in out
    assert "of 60 table rows" in out
    assert len(out) <= 1_200
    assert out.rstrip().endswith("— spec")


def test_fit_compare_keeps_everything_when_it_fits():
    labels = ["Metric", "Alpha"]
    rows = [["Intel", "60.0"], ["Cost", "$1.00"]]
    out = server._fit_compare("# 1 model · 2 metrics", labels, rows, "— spec",
                              limit=6_000)
    assert "capped" not in out
    assert "| Intel | 60.0 |" in out


def test_delta_text_uses_the_display_unit():
    assert server._delta_text("gpqa", -0.125) == "-12.5pp"
    assert server._delta_text("briefcaseElo", -468.1) == "-468"
    assert server._delta_text("intelligence", 4.9) == "+4.9"
    assert server._delta_text("context_tokens", 2_000.0) == "+2,000"


def test_metric_arg_coerces_strings_and_lists():
    assert server._metric_arg(None) == ""
    assert server._metric_arg("all") == "all"
    assert server._metric_arg(["gpqa", "tps"]) == "gpqa,tps"
    assert server._metric_arg(["gpqa", " ", "tps"]) == "gpqa,tps"


# --------------------------------------------------------------------------- #
# resources
# --------------------------------------------------------------------------- #

def test_rankables_resource_is_a_json_list():
    data = json.loads(server._r_rankables())
    assert isinstance(data, list) and data
    keys = {row["key"] for row in data}
    assert "gpqa" in keys and "cost_per_task" in keys
    assert all({"key", "label", "kind", "unit", "tags", "how", "desc"} <= set(row)
               for row in data)


def test_rankables_yaml_resource_lists_every_rankable():
    text = server._r_rankables_yaml()
    lines = [line for line in text.splitlines() if line.startswith("- key: ")]
    assert len(lines) == len(server._rankable_list())
    assert "- key: gpqa" in text
    assert "how: aa_benchmark_leaderboard benchmark=gpqa" in text


def test_compare_spec_resource_is_the_template():
    assert server._r_compare_spec() == server._COMPARE_SPEC_TEMPLATE


# --------------------------------------------------------------------------- #
# the MCP boundary still turns failures into actionable ToolError text
# --------------------------------------------------------------------------- #

def test_tool_boundary_reports_the_axis_error():
    with pytest.raises(ToolError) as exc:
        server.aa_pareto(x="nonsense")
    assert "valid axes" in str(exc.value)


def test_tool_boundary_reports_the_domain_error():
    with pytest.raises(ToolError) as exc:
        server.aa_benchmarks(domain="nope")
    assert "unknown domain" in str(exc.value)


def test_tool_boundary_reports_the_model_count_error():
    with pytest.raises(ToolError) as exc:
        server.aa_compare(queries=["only-one"])
    assert "2-12 models" in str(exc.value)


def test_tool_boundary_validates_arguments():
    with pytest.raises(ToolError) as exc:
        server.aa_pareto(x="a" * 400)
    assert "limit 256" in str(exc.value)


# --------------------------------------------------------------------------- #
# Wave D / round-4: comparison completeness (D1-D5) and regressions (D6)
# --------------------------------------------------------------------------- #

def test_compare_missing_cells_get_one_grouped_footer(fake):
    # alpha has gpqa + tps, beta has gpqa only -> exactly one blank cell
    out = server._compare(["alpha", "beta"], metrics="gpqa,tps")
    assert "— missing: Speed (output tokens/s) (Beta Two)" in out


def test_compare_partial_model_lists_only_its_blank_cells(fake):
    out = server._compare(["alpha", "gamma"], metrics="gpqa,cost_per_task")
    assert "— missing: GPQA Diamond (Gamma Three)" in out
    assert "has no published" not in out


def test_compare_all_dash_model_is_stated_not_listed(fake):
    # delta has neither a price nor a speed -> the whole-model line, no row list
    out = server._compare(["alpha", "delta"], metrics="cost_per_task,tps")
    assert ("Delta Four has no published pricing or speed on AA; "
            "0/2 requested metrics available") in out
    assert "missing:" not in out


def test_compare_fills_a_row_from_a_chart_set_score(fake, monkeypatch):
    chart = _model("beta", "Beta Two", evals={"cweBench": 0.68})
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda key, refresh=False: [chart] if key == "cweBench" else [])
    monkeypatch.setattr(server, "_extra_score_meta",
                        lambda key: ("chart set", 20) if key == "cweBench" else ("", 0))
    out = server._compare(["alpha", "beta"], metrics="gpqa,cweBench")
    assert "| CWE-Bench-AA | - | 68.0% |" in out
    assert "— missing: CWE-Bench-AA (Alpha One)" in out
    assert "CWE-Bench-AA from AA's eval chart set (top ~20 models)" in out


def test_compare_metrics_all_reaches_a_chart_set_metric(fake, monkeypatch):
    chart = _model("beta", "Beta Two", evals={"cweBench": 0.68})
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda key, refresh=False: [chart] if key == "cweBench" else [])
    monkeypatch.setattr(server, "_extra_score_meta",
                        lambda key: ("chart set", 20) if key == "cweBench" else ("", 0))
    out = server._compare(["alpha", "beta"], metrics="all")
    assert "| CWE-Bench-AA |" in out
    assert "— metrics=all" in out


def test_model_benchmarks_join_a_panel_score(monkeypatch):
    m = _model("alpha", "Alpha One", evals={"gpqa": 0.5})
    chart = _model("alpha", "Alpha One", evals={"cweBench": 0.68})
    monkeypatch.setattr(server, "_home_rows",
                        lambda refresh=False: {"eval:cwe-bench-aa": [{"score": 0.68}]})
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda key, refresh=False: [chart] if key == "cweBench" else [])
    out = server._model_benchmarks(m)
    assert "| GPQA Diamond | 50.0% |" in out
    assert "| CWE-Bench-AA | 68.0% |" in out
    assert "joined from AA's eval chart set / homepage panel" in out


def test_benchmarks_single_word_domain_query_expands(fake):
    out = server._benchmarks(query="security")
    assert "query=security (domain match)" in out
    assert "Artificial Analysis Cyber Index" in out


def test_benchmarks_multiword_query_stays_tokenised(fake):
    out = server._benchmarks(query="cyber index")
    assert "(domain match)" not in out
    assert "Artificial Analysis Cyber Index" in out


def test_rankable_coverage_is_computed_live_for_a_chart_benchmark(monkeypatch):
    r = catalog.rankable("aa3dElo")
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [1, 2])
    monkeypatch.setattr(server, "_extra_score_meta", lambda key: ("chart set", 2))
    assert server._rankable_coverage(r, [], []) == "chart set (2 scored)"


def test_rankable_coverage_chart_without_live_values(monkeypatch):
    r = catalog.rankable("aa3dElo")
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    assert server._rankable_coverage(r, [], []) == \
        "chart set (no live values in current source)"


def test_rankable_coverage_prefers_the_live_leaderboard():
    row = _model("m", evals={"gpqa": 0.5})
    assert server._rankable_coverage(catalog.rankable("gpqa"), [row], [row]) == \
        "leaderboard (1/1)"


def test_compare_spec_echo_includes_effective_view_and_compact(fake):
    out = server._compare(["alpha", "beta"])
    spec = out.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert "view: table" in spec
    assert "compact: true" in spec
    assert server._compare(spec=spec) == out


def test_compare_spec_echo_reproduces_a_non_default_call(fake):
    out = server._compare(["alpha", "beta"], metrics="all", view="diff", compact=False)
    spec = out.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    assert "metrics: all" in spec and "view: diff" in spec and "compact: false" in spec
    assert server._compare(spec=spec) == out


def test_compare_compact_is_documented_when_metrics_given(fake):
    assert "compact is ignored when metrics= is given" in \
        server._compare(["alpha", "beta"], metrics="gpqa")
    assert "compact is ignored" not in server._compare(["alpha", "beta"])


def test_compare_sanitizes_a_hostile_scraped_name(monkeypatch):
    hostile = _model("bad", "Bad|Name\n`x`\ud800" + "A" * 10_000)
    alpha = _model("alpha", "Alpha One", intelligence=60.0, cost_per_task=1.0)
    models = [hostile, alpha]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: models)
    monkeypatch.setattr(server, "_lb_cache", lambda: ("leaderboard", False))
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name, api=False: (None, False))
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    out = server.aa_compare(queries=["bad", "alpha"], metrics="cost_per_task")
    assert "\ud800" not in out            # no lone surrogate reaches the client
    assert "\ufffd" in out                # it is sanitized to U+FFFD
    assert "| Bad\\|Name" in out          # the pipe is escaped, not a new column
    assert "|---|---|---|" in out          # the table keeps its three columns
    assert len(out) <= 6000               # the response cap holds


def test_media_speech_boards_end_to_end(monkeypatch):
    home = {
        "stt": [{"name": "Whisper Z", "creatorName": "OpenAI", "werIndex": 0.05}],
        "stt_streaming": [{"name": "Stream Z", "creatorName": "X", "werIndex": 0.09}],
        "sts": [{"name": "Voice Z", "hostName": "LabX", "stsIndex": 80.0}],
    }
    monkeypatch.setattr(server, "_home_rows", lambda refresh=False: home)
    assert "| 1 | Whisper Z | OpenAI | 5.0% |" in server.aa_media(board="speech_to_text")
    streaming = server.aa_media(board="speech_to_text_streaming")
    assert "Stream Z" in streaming and "9.0%" in streaming
    sts = server.aa_media(board="speech_to_speech")
    assert "| 1 | Voice Z | LabX | 80.0 |" in sts
    assert server.aa_media(board="realtime_voice") == sts


def test_benchmark_leaderboard_ranks_a_lower_is_better_metric(monkeypatch):
    models = [
        _model("a", "A", evals={"omniscienceHallucinationRate": 0.9}),
        _model("b", "B", evals={"omniscienceHallucinationRate": 0.1}),
        _model("c", "C", evals={"omniscienceHallucinationRate": 0.5}),
    ]
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_cache", lambda: ("leaderboard", False))
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name, api=False: (None, False))
    out = server.aa_benchmark_leaderboard(
        benchmark="omniscienceHallucinationRate", top=5)
    assert "lower is better" in out
    assert out.index("10.0%") < out.index("50.0%") < out.index("90.0%")


def test_pareto_frontier_knee_is_order_independent(fake, monkeypatch):
    a = _model("a", "A", intelligence=30.0, cost_per_task=0.1)
    b = _model("b", "B", intelligence=50.0, cost_per_task=0.2)
    c = _model("c", "C", intelligence=55.0, cost_per_task=5.0)

    def run(order):
        monkeypatch.setattr(server, "_models_state",
                            lambda refresh=False, rich=True: (list(order), rich))
        monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: list(order))
        return server._pareto(top=10)

    forward = run([a, b, c])
    backward = run([c, b, a])
    assert forward == backward
    assert "knee ≈ B:" in forward


def test_tool_boundary_rejects_non_finite_filters():
    for kwargs in ({"min_intelligence": float("nan")},
                   {"max_cost_per_task": float("inf")}):
        with pytest.raises(ToolError) as exc:
            server.aa_leaderboard(**kwargs)
        assert "finite" in str(exc.value)


def test_tool_boundary_rejects_overlong_fields():
    with pytest.raises(ToolError) as exc:
        server.aa_leaderboard(fields="a" * 3000)
    assert "limit 2000" in str(exc.value)


def test_tool_boundary_rejects_unknown_tag():
    with pytest.raises(ToolError) as exc:
        server.aa_benchmarks(tag="nope")
    assert "unknown tag" in str(exc.value)


# --------------------------------------------------------------------------- #
# Wave E: E2 container benchmarks, E3 arena models, E4 footer scaling
# --------------------------------------------------------------------------- #

def _arena_entry(name, board, *, kind="media", creator="Lab",
                 metric=("elo", "Elo", 1200.0, "Elo"), rank=1, appearances=100,
                 price=None, price_unit=None, release_date="2026-01-01",
                 open_weights=False, ci_lower=None, ci_upper=None):
    return server._ArenaEntry(
        name=name, board=board, kind=kind, creator=creator, metrics=(metric,),
        rank=rank, appearances=appearances, price=price, price_unit=price_unit,
        release_date=release_date, open_weights=open_weights,
        ci_lower=ci_lower, ci_upper=ci_upper)


_MIXED_BENCHMARKS = sorted(k for k, b in catalog.BENCHMARKS.items()
                           if b.unit == "mixed")


def test_there_are_container_benchmarks_to_guard():
    assert _MIXED_BENCHMARKS and "aa3dBreakdown" in _MIXED_BENCHMARKS
    for key in _MIXED_BENCHMARKS:
        assert catalog.RANKABLES[key].unit == "text"


@pytest.mark.parametrize("key", _MIXED_BENCHMARKS)
def test_breakdown_benchmark_reports_a_container_not_a_typeerror(key):
    with pytest.raises(ValueError) as exc:
        server._benchmark_leaderboard(benchmark=key)
    msg = str(exc.value)
    assert "container benchmark" in msg
    assert "TypeError" not in msg


def test_breakdown_benchmark_names_its_scalar_sibling():
    with pytest.raises(ValueError) as exc:
        server._benchmark_leaderboard(benchmark="aa3dBreakdown")
    assert "aa_benchmark_leaderboard benchmark=aa3dElo" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        server._benchmark_leaderboard(benchmark="harveyLabBreakdown")
    assert "aa_benchmark_leaderboard benchmark=harveyLab" in str(exc.value)


def test_breakdown_benchmark_is_honest_through_the_tool_boundary():
    with pytest.raises(ToolError) as exc:
        server.aa_benchmark_leaderboard(benchmark="aa3dBreakdown")
    assert "container benchmark" in str(exc.value)
    assert "TypeError" not in str(exc.value)


def test_leaderboard_and_pareto_reject_a_container_key():
    for call in (lambda: server._leaderboard(sort="aa3dBreakdown"),
                 lambda: server._pareto(score="aa3dBreakdown")):
        with pytest.raises(ValueError) as exc:
            call()
        assert "container benchmark" in str(exc.value)


def test_search_resolves_an_arena_model(fake, monkeypatch):
    entries = [_arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                            creator="SpaceXAI",
                            metric=("sts", "STS Index", 86.9, "index"),
                            rank=None, appearances=None)]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server.aa_search(query="Grok Voice 3.0")
    assert "Grok Voice 3.0" in out
    assert "speech_to_speech (arena)" in out
    assert "| STS Index | 86.9 |" in out
    assert "not language models" in out


def test_search_keeps_language_models_and_adds_arena_rows(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries",
                        lambda refresh=False: [_arena_entry("Voice Z", "text_to_speech")])
    out = server.aa_search(query="alpha")
    assert "| Alpha One |" in out          # the language model table is unchanged
    assert "Voice Z" not in out            # no arena row for an unrelated query


def test_compare_arena_models_renders_board_metrics(fake, monkeypatch):
    entries = [
        _arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                     creator="SpaceXAI",
                     metric=("sts", "STS Index", 86.9, "index"),
                     rank=None, appearances=None),
        _arena_entry("GPT-Live-1 (Astra, medium)", "speech_to_speech", kind="speech",
                     creator="OpenAI",
                     metric=("sts", "STS Index", 83.2, "index"),
                     rank=None, appearances=None),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["Grok Voice 3.0", "GPT-Live-1 (Astra, medium)"])
    assert "| STS Index | 86.9 | 83.2 |" in out
    assert "| Board | speech_to_speech | speech_to_speech |" in out
    assert "not comparable" in out
    assert "source: aa_media board=speech_to_speech" in out


def test_compare_arena_elo_with_ci_and_metadata(fake, monkeypatch):
    entries = [
        _arena_entry("Eleven v4 Turbo", "text_to_speech", creator="ElevenLabs",
                     metric=("elo", "Elo", 1327.7, "Elo"), rank=1,
                     appearances=1802, price=40.0, price_unit="/1M chars",
                     ci_lower=1309.7, ci_upper=1345.7),
        _arena_entry("Eleven v4", "text_to_speech", creator="ElevenLabs",
                     metric=("elo", "Elo", 1326.36, "Elo"), rank=2,
                     appearances=2102, price=80.0, price_unit="/1M chars",
                     ci_lower=1309.36, ci_upper=1343.36),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["Eleven v4 Turbo", "Eleven v4"],
                          metrics="elo,ci,appearances,price,release,open_weights")
    assert "| Elo | 1328 | 1326 |" in out
    assert "| 95% CI | 1310–1346 | 1309–1343 |" in out
    assert "| Appearances | 1,802 | 2,102 |" in out
    assert "| Price | $40.00/1M chars | $80.00/1M chars |" in out
    assert "| Open | no | no |" in out


def test_compare_arena_diff_view_shows_deltas(fake, monkeypatch):
    entries = [
        _arena_entry("Arena One", "text_to_image", metric=("elo", "Elo", 1200.0, "Elo")),
        _arena_entry("Arena Two", "text_to_image", metric=("elo", "Elo", 1150.0, "Elo")),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["Arena One", "Arena Two"], metrics="elo", view="diff")
    assert "1150 (-50)" in out


def test_compare_mixed_language_and_arena_explains(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                     metric=("sts", "STS Index", 86.9, "index"))])
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "Grok Voice 3.0"])
    msg = str(exc.value)
    assert "either language models or arena-board models" in msg
    assert "speech_to_speech" in msg


def test_compare_ambiguous_arena_name_picks_a_shared_board(fake, monkeypatch):
    entries = [
        _arena_entry("Eleven v4 Turbo", "text_to_speech",
                     metric=("elo", "Elo", 1327.7, "Elo")),
        _arena_entry("Eleven v4 Turbo", "text_to_speech_controlled",
                     metric=("elo", "Elo", 1158.5, "Elo")),
        _arena_entry("Eleven v4", "text_to_speech",
                     metric=("elo", "Elo", 1326.36, "Elo")),
        _arena_entry("Eleven v4", "text_to_speech_controlled",
                     metric=("elo", "Elo", 1100.0, "Elo")),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["Eleven v4 Turbo", "Eleven v4"], metrics="elo")
    assert "| Elo | 1328 | 1326 |" in out
    assert "board text_to_speech chosen" in out
    assert "text_to_speech_controlled" in out


def test_compare_arena_names_without_a_common_board_explain(fake, monkeypatch):
    entries = [
        _arena_entry("Eleven v4 Turbo", "text_to_speech"),
        _arena_entry("Suno v6", "music_instrumental"),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    with pytest.raises(ValueError) as exc:
        server._compare(["Eleven v4 Turbo", "Suno v6"])
    assert "not published on one board" in str(exc.value)


def test_compare_arena_board_selector_pins_the_board(fake, monkeypatch):
    entries = [
        _arena_entry("Eleven v4 Turbo", "text_to_speech",
                     metric=("elo", "Elo", 1327.7, "Elo")),
        _arena_entry("Eleven v4 Turbo", "text_to_speech_controlled",
                     metric=("elo", "Elo", 1158.5, "Elo")),
        _arena_entry("Eleven v4", "text_to_speech",
                     metric=("elo", "Elo", 1326.36, "Elo")),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["text_to_speech", "Eleven v4 Turbo", "Eleven v4"],
                          metrics="elo")
    assert "| Elo | 1328 | 1326 |" in out
    assert "text_to_speech_controlled" not in out
    # the "board: name" prefix form pins the board per model too
    out2 = server._compare(["text_to_speech: Eleven v4 Turbo",
                            "text_to_speech: Eleven v4"], metrics="elo")
    assert "| Elo | 1328 | 1326 |" in out2


def test_compare_arena_board_mismatch_is_explained(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                     metric=("sts", "STS Index", 86.9, "index"))])
    with pytest.raises(ValueError) as exc:
        server._compare(["text_to_speech", "Grok Voice 3.0", "Grok Voice 3.0"])
    assert "is not on arena board text_to_speech" in str(exc.value)


def test_compare_footer_scales_to_a_per_model_summary(fake):
    out = server._compare(["alpha", "gamma", "delta"], metrics="all")
    assert "missing on requested metrics:" in out
    assert "missing: " not in out          # per-metric detail dropped when wide
    assert "… (+" not in out               # never truncated


def test_compare_footer_keeps_detail_when_the_gap_is_small(fake):
    out = server._compare(["alpha", "beta"], metrics="gpqa,tps")
    assert "missing on requested metrics: Beta Two 1" in out
    assert "missing: Speed (output tokens/s) (Beta Two)" in out


def test_every_rankable_how_hint_is_accepted_by_its_tool():
    """The server's own resolvers accept every hint argument (E1).

    Catches a hint whose tool would reject the argument (the round-5
    ``aa_leaderboard sort=cyberIndex`` and ``aa_pareto x=tps`` defects).
    """
    for key, r in catalog.RANKABLES.items():
        tool, _, arg = r.how.partition(" ")
        _name, _, value = arg.partition("=")
        if tool == "aa_leaderboard":
            assert server._metric_key(value, "sort"), (key, r.how)
        elif tool == "aa_benchmark_leaderboard":
            assert catalog.benchmark(value) is not None, (key, r.how)
        elif tool == "aa_media":
            assert (value in server.loaders.MEDIA_BOARDS
                    or value in server._SPEECH_BOARDS), (key, r.how)
        elif tool == "aa_pareto":
            assert server._pareto_axis(value) == value, (key, r.how)
        else:  # pragma: no cover - the tool set is asserted in test_catalog
            raise AssertionError((key, r.how))


def _speech_pair():
    return [
        _arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                     creator="SpaceXAI", metric=("sts", "STS Index", 86.9, "index"),
                     rank=None, appearances=None, release_date=None),
        _arena_entry("GPT-Live-1 (Astra, medium)", "speech_to_speech", kind="speech",
                     creator="OpenAI", metric=("sts", "STS Index", 83.2, "index"),
                     rank=None, appearances=None, release_date=None),
    ]


def test_compare_arena_unpublished_metrics_fall_back_to_native(fake, monkeypatch):
    """F1: a metric the board does not publish never yields an all-dash table."""
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: _speech_pair())
    out = server._compare(["Grok Voice 3.0", "GPT-Live-1 (Astra, medium)"],
                          metrics="elo,ci,price,release")
    assert "| STS Index | 86.9 | 83.2 |" in out
    assert "| Elo |" not in out
    assert ("publishes STS Index, not Elo, 95% CI, Price, Release; showing the "
            "board's own metrics") in out


def test_compare_arena_partly_unpublished_marks_the_gap(fake, monkeypatch):
    entries = [
        _arena_entry("Arena One", "text_to_image", metric=("elo", "Elo", 1200.0, "Elo"),
                     ci_lower=1190.0, ci_upper=1210.0),
        _arena_entry("Arena Two", "text_to_image", metric=("elo", "Elo", 1150.0, "Elo"),
                     ci_lower=1140.0, ci_upper=1160.0),
    ]
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: entries)
    out = server._compare(["Arena One", "Arena Two"], metrics="elo,ci,price")
    assert "| Elo | 1200 | 1150 |" in out
    assert "| 95% CI |" in out
    assert "| Price | - | - |" in out
    assert "Price not published on" in out


def test_view_rankable_coverage_is_not_absence(fake):
    r = catalog.RANKABLES["intelligence_vs_cost_per_task"]
    out = server._rankable_coverage(r, list(fake.values()), list(fake.values()))
    assert "no live values" not in out
    assert "models scored on both axes" in out
    assert "Intel vs $/task" in out

