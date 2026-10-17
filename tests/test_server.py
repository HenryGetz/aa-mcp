"""Tests for the server layer: the Pareto frontier, the rankable search index and
the comparison tool (spec parsing, diff view, bounds).

Everything here is offline: the data layer is replaced by a handful of hand-built
``Model`` objects, so these tests exercise the server's own logic (frontier
selection, axis resolution, coverage labels, YAML subset, response bounds).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aa_mcp import catalog, loaders, server
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
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
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
    assert "no per-model values" in str(exc.value)


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


# --------------------------------------------------------------------------- #
# Wave F: aa_leaderboard ranks any key with per-model values on any surface
# --------------------------------------------------------------------------- #


def _patch_leaderboard(monkeypatch, base, extra):
    """Point the leaderboard's data layer at ``base`` rows + an ``extra`` source."""
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (list(base), rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: list(base))
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda key, refresh=False: list(extra.get(key, [])))


def test_leaderboard_ranks_a_panel_backed_index_like_intelligence(monkeypatch):
    """``sort=cyberIndex`` ranks the chart/panel subset and labels the coverage."""
    base = [_model("gpt-x", "GPT X", intelligence=50.0, cost_per_task=1.0),
            _model("llama-y", "Llama Y", intelligence=40.0, cost_per_task=0.5)]
    chart = [_model("gpt-x", "GPT X", evals={"cyberIndex": 68.7}),
             _model("llama-y", "Llama Y", evals={"cyberIndex": 20.0}),
             _model("panel-only", "Panel Only", evals={"cyberIndex": 55.0})]
    _patch_leaderboard(monkeypatch, base, {"cyberIndex": chart})

    out = server._leaderboard(sort="cyberIndex", top=5)
    lines = out.splitlines()
    assert "3 of 3 scored (2 tracked)" in lines[0]          # honest coverage
    assert "chart set" in lines[0]                          # and source
    assert "joined onto the leaderboard rows" in out        # and a footnote
    # ranked by the joined score, descending (higher is better), panel-only included
    body = out.index("GPT X") < out.index("Panel Only") < out.index("Llama Y")
    assert body
    # the x-columns still come from the leaderboard row the score was joined onto
    assert "$1.00" in out and "$0.50" in out


def test_leaderboard_value_mode_works_for_a_panel_backed_score(monkeypatch):
    base = [_model("gpt-x", "GPT X", cost_per_task=1.0),
            _model("llama-y", "Llama Y", cost_per_task=0.5)]
    chart = [_model("gpt-x", "GPT X", evals={"cyberIndex": 68.7}),
             _model("llama-y", "Llama Y", evals={"cyberIndex": 20.0})]
    _patch_leaderboard(monkeypatch, base, {"cyberIndex": chart})
    out = server._leaderboard(mode="value", sort="cyberIndex")
    assert "value = AA Cyber Ind per $/task" in out
    assert "68.7" in out and "20.0" in out


def test_leaderboard_frontier_mode_works_for_a_panel_backed_score(monkeypatch):
    base = [_model("gpt-x", "GPT X", cost_per_task=1.0),
            _model("llama-y", "Llama Y", cost_per_task=0.5)]
    chart = [_model("gpt-x", "GPT X", evals={"cyberIndex": 68.7}),
             _model("llama-y", "Llama Y", evals={"cyberIndex": 20.0})]
    _patch_leaderboard(monkeypatch, base, {"cyberIndex": chart})
    out = server._leaderboard(mode="frontier", sort="cyberIndex")
    assert "Cyber Index vs $/task" in out.splitlines()[0]
    assert "eval chart/panel" in out.splitlines()[0]
    assert "joined onto the leaderboard rows" in out


def test_leaderboard_fields_carry_the_companion_metrics(monkeypatch):
    base = [_model("gpt-x", "GPT X", cost_per_task=1.0)]
    panel = [_model("gpt-x", "GPT X",
                    evals={"cyberRefusalRate": 0.1, "cyberMitigationStatus": "standard"}),
             _model("llama-y", "Llama Y",
                    evals={"cyberRefusalRate": 0.4,
                           "cyberMitigationStatus": "unmitigated"})]
    _patch_leaderboard(monkeypatch, base,
                       {"cyberRefusalRate": panel, "cyberMitigationStatus": panel})
    out = server._leaderboard(
        sort="cyberRefusalRate",
        fields="cyberRefusalRate,cyberMitigationStatus")
    assert "Cyber Refus" in out and "Cyber Mitiga" in out
    assert "10.0%" in out and "40.0%" in out          # refusal rate, % formatted
    assert "standard" in out and "unmitigated" in out  # mitigation status
    assert out.index("10.0%") < out.index("40.0%")     # lower refusal ranks first


@pytest.mark.parametrize("key,value,evals", [
    ("cyberIndex", "68.7", {"cyberIndex": 68.7}),      # eval chart set / panel
    ("frontierCode", "50.0%", {"frontierCode": 0.5}),  # rich dataset
    ("gpqa", "40.0%", {"gpqa": 0.4}),                  # 700-row leaderboard
])
def test_leaderboard_reaches_a_key_from_each_surface(monkeypatch, key, value, evals):
    base = [_model("beta", "Beta Two", cost_per_task=0.5)]
    row = _model("beta", "Beta Two", evals=evals)
    _patch_leaderboard(monkeypatch, base, {key: [row]})
    out = server._leaderboard(sort=key, top=5)
    assert "Beta Two" in out and value in out
    assert "scored" in out.splitlines()[0]


def test_leaderboard_explains_a_deprecated_only_key(monkeypatch):
    base = [_model("old", "Old", deprecated=True, evals={"mmluPro": 0.9}),
            _model("new", "New", intelligence=50.0)]
    _patch_leaderboard(monkeypatch, base, {})
    with pytest.raises(ValueError) as exc:
        server._leaderboard(sort="mmluPro")
    assert "only published for deprecated models" in str(exc.value)
    out = server._leaderboard(sort="mmluPro", include_deprecated=True)
    assert "1 of 1 scored" in out.splitlines()[0]


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
    """``domain=`` narrows the catalog, and the header count matches the rows shown."""
    out = server._benchmarks(domain="security")
    header = out.splitlines()[0]
    body_rows = [line for line in out.splitlines()
                 if line.startswith("| ") and "---" not in line][1:]  # drop header row
    assert "domain=security" in header
    assert body_rows                                     # the domain is not empty
    assert len(body_rows) < len(catalog.RANKABLES)       # it actually filtered
    assert f"{len(body_rows)} of {len(catalog.RANKABLES)} rankables" in header
    assert "aa_leaderboard sort=cweBench" in out


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
    assert "showing the default 8-row subset, not every metric" in out
    assert "metrics=all selects every published row" in out


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
    assert "how: aa_leaderboard sort=gpqa" in text


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


def test_compare_compact_controls_slug_row_and_null_rows(fake):
    # with metrics=, compact=true (default) omits the Slug row and says so
    compact = server._compare(["alpha", "beta"], metrics="gpqa,tps")
    assert "| Slug |" not in compact
    assert "compact=true: Slug row omitted (compact=false adds it)" in compact
    # compact=false adds the Slug row
    full = server._compare(["alpha", "beta"], metrics="gpqa,tps", compact=False)
    assert "| Slug | alpha | beta |" in full
    assert "Slug row omitted" not in full
    # the default path is unchanged (Slug row only when it disambiguates)
    assert "compact=true: Slug row omitted" not in server._compare(["alpha", "beta"])


def test_compare_compact_drops_all_null_rows(fake):
    compact = server._compare(["alpha", "beta"],
                              metrics="gpqa,cost_per_task,cache_write")
    assert "| Cache Write Price" not in compact      # all-null row dropped
    assert "1 all-null rows omitted" in compact
    full = server._compare(["alpha", "beta"],
                           metrics="gpqa,cost_per_task,cache_write", compact=False)
    assert "| Cache Write Price" in full
    assert "all-null rows omitted" not in full


def _endpoint(slug, host, **kw):
    base = dict(model_slug=slug, model_name=slug, host=host, host_slug=host.lower(),
                precision=None, price_in=1.0, price_out=2.0, cache_read=None,
                cache_write=None, cache_hit_discount=None, cost_per_task=0.5,
                tps=10.0, ttft=1.0, e2e=None, function_calling=True, json_mode=True,
                openai_compatible=None, context_tokens=128_000, intelligence=50.0,
                source="providers_model")
    base.update(kw)
    return loaders.Endpoint(**base)


def test_providers_shows_the_column_it_sorted_by(fake, monkeypatch):
    eps = [_endpoint("alpha", "hostA", ttft=0.7), _endpoint("alpha", "hostB", ttft=1.9)]
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: eps)
    out = server._providers(model="alpha", sort="ttft", top=3)
    assert "TTFT" in out.splitlines()[1]            # the sort column is visible
    assert "0.7s" in out and "1.9s" in out
    assert "by ttft" in out
    # an explicit fields= list is still respected (no surprise column)
    narrow = server._providers(model="alpha", sort="ttft", fields="host", top=3)
    assert "TTFT" not in narrow


def test_provider_sort_error_lists_closest():
    with pytest.raises(ValueError) as exc:
        server._prov_sort_key("speeed")
    assert "closest" in str(exc.value) and "speed" in str(exc.value)


def test_leaderboard_accepts_value_sort_tokens(fake):
    out = server._leaderboard(sort="intel_per_cost", top=3)
    assert "value = Intel per $/task (sort=intel_per_cost)" in out
    assert "Intel/$" in out
    assert server._leaderboard(sort="intel/$", top=2).count("(sort=intel/$)") == 1
    assert server._leaderboard(sort="value", top=2).count("(sort=value)") == 1
    # the explicit mode=value path is unchanged
    assert "value = Intel per $/task, active only" in \
        server._leaderboard(mode="value", top=3)


def test_cols_accepts_a_wildcard_field():
    cols = server._cols([("a", "A"), ("b", "B")], "all", ("c", "d"), [("id", "Id")])
    assert [k for k, _ in cols][:3] == ["id", "a", "b"]
    assert set(k for k, _ in cols) == {"id", "a", "b", "c", "d"}
    assert [k for k, _ in server._cols([("a", "A")], "*", ("b",))] == ["a", "b"]
    assert [k for k, _ in server._cols([("a", "A")], "everything", ())] == ["a"]


def test_compare_sanitizes_a_hostile_scraped_name(monkeypatch):
    hostile = _model("bad", "Bad|Name\n`x`\ud800" + "A" * 10_000)
    alpha = _model("alpha", "Alpha One", intelligence=60.0, cost_per_task=1.0)
    models = [hostile, alpha]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: models)
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
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
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
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


def test_breakdown_benchmark_names_a_rankable_sub_score():
    """The container error points at a call that ranks something (the catalog hint)."""
    for key, sub in (("aa3dBreakdown", "aa3dTurnsP50"),
                     ("harveyLabBreakdown", "harveyCriteriaPass")):
        with pytest.raises(ValueError) as exc:
            server._benchmark_leaderboard(benchmark=key)
        msg = str(exc.value)
        assert "container benchmark" in msg
        assert f"aa_benchmark_leaderboard benchmark={sub}" in msg
        assert "aa_model <slug> sections=benchmarks" in msg


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


def test_elo_values_round_half_away_from_zero_everywhere(fake, monkeypatch):
    """One Elo rule: ``.5`` rounds up in arena, media and benchmark-leaderboard cells.

    ``catalog.format_value`` matches AA's own rendered Elo strings; a bare ``:.0f``
    (half-to-even) would print 1146.5 as 1146 in these keyless cells while the
    metric columns say 1147.  Confidence-interval bounds follow the same rule.
    """
    # arena compare: the Elo metric cell and the 95% CI cell
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _arena_entry("Arena One", "text_to_image", metric=("elo", "Elo", 1146.5, "Elo"),
                     ci_lower=1092.5, ci_upper=1200.5),
        _arena_entry("Arena Two", "text_to_image", metric=("elo", "Elo", 1000.0, "Elo"),
                     ci_lower=900.0, ci_upper=1100.0),
    ])
    arena = server._compare(["Arena One", "Arena Two"], metrics="elo,ci")
    assert "| Elo | 1147 | 1000 |" in arena
    assert "| 95% CI | 1093–1201 | 900–1100 |" in arena

    # arena diff view: a .5 Elo delta follows the same rule (1000 - 1146.5)
    diff = server._compare(["Arena One", "Arena Two"], metrics="elo", view="diff")
    assert "1000 (-147)" in diff

    # media board: the Elo cell and its CI columns
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: [
        {"name": "Ideogram 4.0", "elo": 1146.5, "ci_lower": 1092.5,
         "ci_upper": 1200.5}])
    media = server.aa_media(board="text_to_image",
                            fields="name,elo,ci_lower,ci_upper,ci", top=1)
    assert "| 1147 |" in media
    assert "1093" in media and "1201" in media

    # benchmark leaderboard: the CI columns (chart-set bounds, no published truth)
    monkeypatch.setattr(server, "_chart_ci",
                        lambda slug, refresh=False: {"alpha": (1092.5, 1200.5)})
    bench = server.aa_benchmark_leaderboard(benchmark="gpqa", fields="score,ci", top=2)
    assert "1093–1201" in bench


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
        elif tool == "aa_agents":
            assert value in server.loaders.AGENT_BOARDS, (key, r.how)
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


def _arena_multi():
    return [
        _arena_entry("Grok Voice 3.0", "speech_to_speech", kind="speech",
                     creator="SpaceXAI", metric=("sts", "STS Index", 86.9, "index"),
                     rank=None, appearances=None, release_date=None),
        _arena_entry("Grok Voice 1.0", "speech_to_speech", kind="speech",
                     creator="SpaceXAI", metric=("sts", "STS Index", 73.7, "index"),
                     rank=None, appearances=None, release_date=None),
        _arena_entry("GPT Image 1 (high)", "image_editing", creator="OpenAI",
                     metric=("elo", "Elo", 991.0, "Elo")),
        _arena_entry("GPT-Realtime-2 (High)", "speech_to_speech", kind="speech",
                     creator="OpenAI", metric=("sts", "STS Index", 73.6, "index"),
                     rank=None, appearances=None, release_date=None),
    ]


def test_arena_matcher_requires_every_token():
    entries = _arena_multi()
    rows, partial, hits = server._arena_matches("gpt 6 luna high", entries, 10)
    assert partial and hits == 2
    assert {e.name for e in rows} == {"GPT Image 1 (high)", "GPT-Realtime-2 (High)"}
    full, is_partial, hits = server._arena_matches("grok voice", entries, 10)
    assert not is_partial and hits == 2
    assert {e.name for e in full} == {"Grok Voice 3.0", "Grok Voice 1.0"}
    exact, is_partial, _h = server._arena_matches("Grok Voice 3.0", entries, 10)
    assert not is_partial and [e.name for e in exact] == ["Grok Voice 3.0"]


def test_search_labels_partial_arena_matches(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: _arena_multi())
    out = server.aa_search(query="gpt 6 luna high")
    assert "# 2 partial arena-board matches (2/4 tokens)" in out
    assert "GPT Image 1 (high)" in out
    assert "not every query token appears" in out
    assert "# 2 arena-board matches" not in out      # never a plain heading


def test_search_exact_and_full_arena_matches_are_not_partial(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: _arena_multi())
    exact = server.aa_search(query="Grok Voice 3.0")
    assert "# 1 arena-board match ·" in exact
    assert "partial" not in exact
    fuzzy = server.aa_search(query="grok voice")
    assert "# 2 arena-board matches ·" in fuzzy
    assert "Grok Voice 3.0" in fuzzy
    assert "partial" not in fuzzy


def test_compare_exact_arena_names_are_not_partial(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: _arena_multi())
    out = server._compare(["Grok Voice 3.0", "Grok Voice 1.0"], metrics="elo")
    assert "| STS Index | 86.9 | 73.7 |" in out
    assert "arena match was partial" not in out


def test_compare_partial_arena_match_is_labelled(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: _arena_multi())
    out = server._compare(["grok voice zzz", "grok voice yyy"], metrics="elo")
    assert "arena match was partial" in out
    assert "Grok Voice" in out


def _patch_models(monkeypatch, models):
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: models)
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])


def test_search_hints_partial_arena_rows_when_lm_matches(monkeypatch):
    """A strong language-model answer gets one hint line, never a fuzzy table."""
    models = [_model("alpha-2026", "Alpha One 2026", intelligence=60.0)]
    _patch_models(monkeypatch, models)
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _arena_entry("Alpha One", "text_to_image")])
    out = server.aa_search(query="alpha one 2026")
    assert "| Alpha One 2026 |" in out
    assert "partial arena matches" in out
    assert "partial arena-board match" not in out    # no fuzzy table
    assert "| Board |" not in out


def test_search_names_a_rankable_instead_of_dead_ending(fake):
    out = server.aa_search(query="gpqa")
    assert "names a benchmark, not a model" in out
    assert catalog.rankable("gpqa").how in out
    assert "no models match" not in out
    assert "| Model |" not in out                    # one/two lines, no table


def test_search_prefers_a_rankable_over_fuzzy_arena_rows(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _arena_entry("Ideogram 4.0", "text_to_image")])
    out = server.aa_search(query="terminal-bench 4.0")
    assert "Terminal-Bench 4.0" in out
    assert "not a model" in out
    assert "partial arena-board match" not in out
    assert "| Model |" not in out


def test_search_still_dead_ends_when_nothing_matches(fake, monkeypatch):
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [])
    out = server.aa_search(query="nonexistentmodel")
    assert "no models match" in out
    assert "names a" not in out



# --------------------------------------------------------------------------- #
# Wave G: comparison trust (deterministic sourcing, identity, partial lists,
# ties, name announcements, task domains, rounding to zero)
# --------------------------------------------------------------------------- #

def _patch_dual_source(monkeypatch, lb, page):
    """A leaderboard snapshot (``lb``) plus the first-party model page (``page``).

    ``_models_state(rich=True)`` is the merged record the model page produced and
    ``_lb_rows`` the snapshot the same metric also exists on (G1). An empty
    ``page`` means the model page is unavailable in this source.
    """
    merged = list(page or lb)
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (list(merged if rich else lb), rich))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: list(lb))
    monkeypatch.setattr(server, "_rich_models", lambda refresh=False: list(page))
    monkeypatch.setattr(server, "_lb_cache", lambda: "leaderboard")
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(server, "_fresh", lambda name: (None, False))
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [])


def test_rich_needed_resolves_a_rankable_only_alias(fake):
    """``time_to_first_token`` is the same key as ``ttft`` — not a rich-only one."""
    assert server._rich_needed(fields="time_to_first_token") is False
    assert server._rich_needed(fields="ttft") is False
    assert server._rich_needed(fields="capabilities.legal") is True


def test_rich_needed_ignores_a_name_that_resolves_to_nothing(fake):
    """An unknown field carries no data, so it cannot re-source the reply (G1/G6)."""
    assert server._rich_needed(fields="tps,ttft,not_a_field") is False


@pytest.mark.parametrize("metrics", ["ttft", "time_to_first_token"])
def test_compare_sources_a_speed_metric_deterministically(monkeypatch, metrics):
    """One metric, one number: both aliases use the first-party model page (G1)."""
    lb = [_model("alpha", "Alpha One", cost_per_task=1.0, speed={"ttft": 100.0}),
          _model("beta", "Beta Two", cost_per_task=1.0, speed={"ttft": 200.0})]
    page = [_model("alpha", "Alpha One", cost_per_task=1.0, speed={"ttft": 90.0}),
            _model("beta", "Beta Two", cost_per_task=1.0, speed={"ttft": 200.0})]
    _patch_dual_source(monkeypatch, lb, page)
    out = server._compare(["alpha", "beta"], metrics=metrics, compact=False)
    assert "| Time to First Token | 90.0s | 200.0s |" in out
    assert "model page 90.0s vs leaderboard snapshot 100.0s" in out
    assert "using the model page" in out
    assert "first-party model page" in out and "long-prompt median" in out


def test_compare_default_view_agrees_with_an_explicit_speed_metric(monkeypatch):
    """The default rows include tps/ttft, so they must resolve the same way (G1)."""
    lb = [_model("alpha", "Alpha One", cost_per_task=1.0, speed={"ttft": 100.0}),
          _model("beta", "Beta Two", cost_per_task=1.0, speed={"ttft": 200.0})]
    page = [_model("alpha", "Alpha One", cost_per_task=1.0, speed={"ttft": 90.0}),
            _model("beta", "Beta Two", cost_per_task=1.0, speed={"ttft": 200.0})]
    _patch_dual_source(monkeypatch, lb, page)
    default = server._compare(["alpha", "beta"])
    explicit = server._compare(["alpha", "beta"], metrics="ttft", compact=False)
    assert "| TTFT | 90.0s | 200.0s |" in default
    assert "| Time to First Token | 90.0s | 200.0s |" in explicit


def test_compare_states_a_leaderboard_only_speed_value(monkeypatch):
    """No model-page value: the snapshot is shown and said to be the snapshot (G1)."""
    lb = [_model("alpha", "Alpha One", cost_per_task=1.0, speed={"ttft": 100.0}),
          _model("beta", "Beta Two", cost_per_task=1.0, speed={"ttft": 200.0})]
    _patch_dual_source(monkeypatch, lb, [])
    out = server._compare(["alpha", "beta"], metrics="ttft", compact=False)
    assert "| Time to First Token | 100.0s | 200.0s |" in out
    assert "leaderboard snapshot" in out
    assert "long-prompt median" not in out


def test_compare_metrics_all_includes_the_derived_ratio_rows(fake):
    """``all`` must carry the row the default view shows (G4)."""
    out = server._compare(["alpha", "beta"], metrics="all", compact=False)
    assert "| Intel/$ |" in out
    assert "derived here as score ÷ $/task" in out


def test_compare_ratio_row_for_a_non_default_score_axis(fake, monkeypatch):
    """``score/$`` is a derived ratio for any axis, not the plain score (G4)."""
    models = [_model("alpha", "Alpha One", cost_per_task=2.0,
                     indices={"coding": 50.0}),
              _model("beta", "Beta Two", cost_per_task=1.0,
                     indices={"coding": 40.0})]
    _patch_dual_source(monkeypatch, models, models)
    explicit = server._compare(["alpha", "beta"], metrics="coding/$", compact=False)
    assert "| Coding/$ | 25.0 | 40.0 |" in explicit
    assert "derived here as score ÷ $/task" in explicit
    everything = server._compare(["alpha", "beta"], metrics="all", compact=False)
    assert "| Coding/$ |" in everything


def test_compare_partial_metric_list_renders_what_resolves(fake):
    """One bad name in a list must not abort the whole comparison (G6)."""
    out = server._compare(["alpha", "beta"],
                          metrics=["gpqa", "swe-bench-verified", "tps"],
                          compact=False)
    assert "| GPQA Diamond |" in out and "| Speed (output tokens/s) |" in out
    assert "unknown, ignored: swe-bench-verified (closest:" in out


def test_compare_all_unknown_metrics_still_errors_with_candidates(fake):
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "beta"], metrics="nonsense,alsononsense")
    assert "closest" in str(exc.value)


def test_compare_announces_a_fuzzy_name_and_an_effort_variant(monkeypatch):
    """A silently corrected name (or picked variant) is announced (G5)."""
    rows = [_model("luna-prime", "Luna Prime (Max)", cost_per_task=1.0, intelligence=50.0),
            _model("luna-prime-high", "Luna Prime (High)", cost_per_task=1.0,
                   intelligence=48.0),
            _model("luna-prime-xhigh", "Luna Prime (Xhigh)", cost_per_task=1.0,
                   intelligence=49.0),
            _model("other", "Other Model", cost_per_task=1.0, intelligence=40.0)]
    _patch_dual_source(monkeypatch, rows, rows)
    fuzzy = server._compare(["Luna Prime", "other"], metrics="intelligence")
    assert "matched 'Luna Prime' → luna-prime (exact slug for that name)" in fuzzy
    assert "matched the Max variant of luna-prime; siblings: luna-prime-xhigh, -high" in fuzzy
    exact = server._compare(["luna-prime-high", "other"], metrics="intelligence")
    assert "matched " not in exact          # the caller named the variant itself
    assert "siblings" not in exact


def test_compare_notes_a_cost_that_rounds_to_zero(monkeypatch):
    """``$0.00`` is explained instead of standing as a measured zero (G9)."""
    rows = [_model("free", "Free Model", cost_per_task=0.0, is_open_weights=True),
            _model("paid", "Paid Model", cost_per_task=0.5)]
    _patch_dual_source(monkeypatch, rows, rows)
    out = server._compare(["free", "paid"], metrics="cost_per_task", compact=False)
    assert "$0.00 = measured under $0.005/task" in out
    assert "open-weights models" in out


def test_zero_cost_note_ignores_a_value_that_displays_further_precision():
    assert server._zero_cost_note("cache_read", [("m", 0.0036, True)]) == ""
    assert "under $0.005" in server._zero_cost_note("cost_per_task", [("m", 0.0, False)])


def test_tie_note_names_the_secondary_ordering(fake):
    tie = [_model("a", "A", cost_per_task=0.13, intelligence=46.3),
           _model("b", "B", cost_per_task=0.13, intelligence=41.0),
           _model("c", "C", cost_per_task=0.20, intelligence=50.0)]
    note = server._tie_note(tie, lambda m: f"${m.cost_per_task:.2f}", unit="/task")
    assert note == "2 models tie at $0.13/task; ordered by intelligence (46.3 vs 41.0)"
    assert server._tie_note(tie[:1], lambda m: "$0.13") == ""


def test_break_display_ties_orders_by_intelligence_then_slug(fake):
    rows = [_model("b", "B", cost_per_task=0.13, intelligence=41.0),
            _model("a", "A", cost_per_task=0.13, intelligence=46.3),
            _model("c", "C", cost_per_task=0.9, intelligence=None)]
    out = server._break_display_ties(rows, lambda m: f"{m.cost_per_task:.2f}")
    assert [m.slug for m in out] == ["a", "b", "c"]


def test_tie_note_is_silent_without_a_tie(fake):
    rows = [_model("sol", "Sol Low", cost_per_task=0.1267, intelligence=42.1),
            _model("haiku", "Haiku", cost_per_task=0.12, intelligence=41.2)]
    assert server._tie_note(rows, lambda m: f"${m.cost_per_task:.2f}") == ""


def test_leaderboard_orders_a_displayed_tie_by_intelligence(fake, monkeypatch):
    rows = [_model("sol", "Sol Low", cost_per_task=0.1267, intelligence=42.1),
            _model("mimo", "MiMo", cost_per_task=0.1332, intelligence=46.3),
            _model("haiku", "Haiku", cost_per_task=0.12, intelligence=41.2)]
    _patch_dual_source(monkeypatch, rows, rows)
    out = server._leaderboard(sort="cost_per_task", top=3)
    assert out.index("MiMo") < out.index("Sol Low")   # displayed tie, by intelligence
    assert "2 models tie at $0.13/task; ordered by intelligence (46.3 vs 42.1)" in out


def test_leaderboard_identity_fields_resolve_and_are_never_no_data(fake):
    out = server._leaderboard(top=2, fields="model,slug,creator,tps")
    assert "| Model | Slug | Creator | tok/s |" in out
    assert "no data for" not in out
    assert "| Alpha One | alpha | LabA |" in out


def test_leaderboard_ignores_an_unknown_field_and_names_it(fake):
    out = server._leaderboard(top=2, fields="tps,not_a_field")
    assert "| tok/s |" in out
    assert "unknown, ignored: not_a_field (closest:" in out


def test_cols_resolves_identity_names_to_the_surface_column():
    surface = [("host", "Host"), ("model_name", "Model")]
    model_cols = server._cols([], "model", (), surface)
    assert ("model_name", "Model") in model_cols
    assert not any(key == "name" for key, _ in model_cols)
    assert ("host", "Host") in server._cols([], "host", (), surface)
    # a surface whose identity column is `model_slug` resolves `slug` via its map
    mapped = server._cols([], "slug", (), surface, None, {"slug": "model_slug"})
    assert ("model_slug", "Model Slug") in mapped
    assert not any(key == "slug" for key, _ in mapped)


def test_cols_ignores_unknown_fields_when_given_a_sink():
    sink: list[str] = []
    cols = server._cols([("name", "Model")], "name,not_a_field", (), (), sink)
    assert cols == [("name", "Model")]
    assert sink == ["not_a_field"]
    with pytest.raises(ValueError):
        server._cols([("name", "Model")], "name,not_a_field")


def test_endpoint_cells_resolve_identity_fields():
    e = _endpoint("alpha", "hostA", precision="bf16")
    assert server._endpoint_cell(e, "name") == "alpha"
    assert server._endpoint_cell(e, "model_name") == "alpha"
    assert server._endpoint_cell(e, "slug") == "alpha"
    assert server._endpoint_cell(e, "host") == "hostA"
    assert server._endpoint_cell(e, "creator", {"alpha": "Lab"}) == "Lab"


def test_providers_model_fields_model_is_never_blank(fake, monkeypatch):
    eps = [_endpoint("alpha", "hostA"), _endpoint("alpha", "hostB")]
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: eps)
    out = server._providers(model="alpha", fields="model,price_in", top=3)
    assert "| Model | In $/M |" in out
    assert "no data for" not in out
    assert out.count("| alpha |") == 2


def test_providers_explains_a_model_with_no_endpoints(fake, monkeypatch):
    def boom(*a, **k):
        raise server.AAFetchError("no JSON array of dicts containing keys [...]")

    monkeypatch.setattr(server, "_load", boom)
    monkeypatch.setattr(server, "_publishes_no_endpoints", lambda slug: True)
    out = server._providers(model="alpha", fields="model,price_in")
    assert "AA lists no API providers for Alpha One (alpha)" in out
    assert "no published pricing or endpoint measurements" in out
    assert "aa_model" in out


def test_providers_still_errors_on_a_broken_payload(fake, monkeypatch):
    def boom(*a, **k):
        raise server.AAFetchError("payload unusable")

    monkeypatch.setattr(server, "_load", boom)
    monkeypatch.setattr(server, "_publishes_no_endpoints", lambda slug: False)
    with pytest.raises(server.AAFetchError):
        server._providers(model="alpha")


def test_media_ignores_an_unknown_field(fake, monkeypatch):
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: [
        {"name": "Ideogram 4.0", "elo": 1024.0, "creator": "Ideogram"}])
    out = server._media("text_to_image", fields="elo,nonsense")
    assert "| Elo |" in out
    assert "unknown, ignored: nonsense (closest:" in out


def test_media_category_ranks_the_sub_board_and_says_so(fake, monkeypatch):
    """``category=`` is forwarded to the loader and surfaced in the header/footer."""
    seen: dict = {}

    def fake_load(name, fn, *a, **k):
        seen["category"] = k.get("category")
        return [{"name": f"row-{k.get('category')}", "elo": 1000.0}]

    monkeypatch.setattr(server, "_load", fake_load)
    out = server.aa_media(board="text_to_image", top=2,
                          category="marketing-and-advertising")
    assert seen["category"] == "marketing-and-advertising"      # forwarded
    assert "category=marketing-and-advertising" in out          # surfaced
    assert "not the overall board" in out
    assert "row-marketing-and-advertising" in out


def test_media_without_a_category_uses_the_primary_board(fake, monkeypatch):
    """Omitting ``category`` ranks the board itself (empty string reaches the loader)."""
    seen: dict = {}
    monkeypatch.setattr(server, "_load",
                        lambda name, fn, *a, **k: seen.update(k) or [{"name": "x",
                                                                     "elo": 1.0}])
    out = server.aa_media(board="text_to_image", top=1)
    assert seen.get("category") == ""
    assert "category=" not in out


def test_media_unknown_category_lists_the_published_ones(fake, monkeypatch):
    """A bad category is an argument error: the published slugs, no cache noise."""
    def boom(name, fn, *a, **k):
        raise ValueError(
            "unknown category 'nope' for board 'text_to_image' — published "
            "categories: animation-and-gaming, marketing-and-advertising — the "
            "payload cached at /tmp/x.rsc is unusable — retry with refresh=true to "
            "refetch https://example.invalid/x")

    monkeypatch.setattr(server, "_load", boom)
    with pytest.raises(ValueError) as exc:
        server._media("text_to_image", category="nope")
    msg = str(exc.value)
    assert "published categories" in msg and "marketing-and-advertising" in msg
    assert "unusable" not in msg and "refresh=true" not in msg   # cache noise dropped


def test_media_category_is_rejected_on_a_speech_panel(fake):
    """The homepage speech panels publish no category split — say so, don't ignore it."""
    with pytest.raises(ValueError) as exc:
        server._media("speech_to_text", category="ja")
    assert "not available" in str(exc.value)


def test_search_answers_a_task_word_aa_does_not_measure(fake, monkeypatch):
    """A task word is answered with the closest AA measures, never a dead end (G8)."""
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [])
    out = server.aa_search(query="best model for classification")
    assert "AA does not measure classification" in out
    assert "IFBench" in out


def test_benchmarks_answers_a_task_word_aa_does_not_measure(fake):
    out = server._benchmarks(query="classif")
    assert "AA does not measure classification" in out
    assert "closest AA measures" in out


def test_benchmarks_still_errors_for_a_word_with_no_task_domain(fake):
    with pytest.raises(ValueError) as exc:
        server._benchmarks(query="zzzqqq")
    assert "closest" in str(exc.value)


def test_unknown_field_note_lists_the_closest_names():
    note = server._unknown_field_note(["gpqqa"])
    assert note.startswith("unknown, ignored: gpqqa (closest: ")
    assert "gpqa" in note


def test_axis_value_prefers_aa_published_time_per_task():
    published = _model("m", speed={"time_per_task": 797.5})
    derived = _model("m", speed={"time_per_task_derived": 697.1})
    fallback = _model("m", per_eval=[{"slug": "a", "timePerTask": 10.0},
                                     {"slug": "b", "timePerTask": 20.0}])
    assert server._axis_value(published, "time_per_task") == 797.5
    assert server._axis_value(derived, "time_per_task") == 697.1
    assert server._axis_value(fallback, "time_per_task") == 15.0
    assert server._time_per_task_derived(published) is False
    assert server._time_per_task_derived(derived) is True


def test_pareto_labels_a_recomputed_time_per_task(monkeypatch):
    rows = [_model("m", "M", intelligence=50.0, cost_per_task=1.0,
                   speed={"time_per_task_derived": 12.0})]
    _patch_dual_source(monkeypatch, rows, rows)
    out = server._pareto(x="time_per_task", top=3)
    assert "recomputed mean of the per-evaluation timePerTask values" in out


def test_prov_label_names_the_rich_overlay_age(monkeypatch):
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(loaders, "rich_age", lambda: 180.0, raising=False)
    monkeypatch.setattr(loaders, "rich_seed", lambda: "step-5", raising=False)
    label = server._prov_label(True)
    assert label.startswith("rsc + rich dataset (overlay 3m ago, seed step-5")
    assert server._prov_label(False) == "rsc"


def test_prov_label_falls_back_without_the_overlay_age(monkeypatch):
    monkeypatch.setattr(server, "_source_key", lambda: "rsc")
    monkeypatch.setattr(loaders, "rich_age", lambda: None, raising=False)
    assert server._prov_label(True) == "rsc + rich dataset"


def test_source_key_is_always_rsc_and_warns_once(monkeypatch, caplog):
    """The keyed backend is gone: the label is always ``aa:rsc`` and a stray
    ``AA_API_KEY``/``AA_SOURCE`` is reported exactly once per process."""
    monkeypatch.setenv("AA_API_KEY", "bogus")
    monkeypatch.setenv("AA_SOURCE", "api")
    monkeypatch.setattr(server, "_keyed_env_warned", False)
    with caplog.at_level("WARNING", logger="aa_mcp.server"):
        assert server._source_key() == "rsc"
        assert server._source_key() == "rsc"
    msgs = [r.getMessage() for r in caplog.records if r.name == "aa_mcp.server"]
    assert len(msgs) == 1
    assert "AA_API_KEY" in msgs[0] and "AA_SOURCE" in msgs[0]
    assert "aa:api" not in server._header(count="1 of 1")


def test_lb_cache_and_cache_ttl_ignore_api_settings(monkeypatch):
    """No keyed cache: ``_lb_cache`` is a constant and ``AA_API_TTL`` is ignored."""
    monkeypatch.setenv("AA_API_TTL", "123")
    monkeypatch.delenv("AA_CACHE_TTL", raising=False)
    assert server._lb_cache() == "leaderboard"
    assert server._cache_ttl() == 3600          # AA_API_TTL is never read
    monkeypatch.setenv("AA_CACHE_TTL", "456")
    assert server._cache_ttl() == 456
    # a TTL that is not an integer is ignored, not fatal
    monkeypatch.setenv("AA_CACHE_TTL", "not-a-number")
    assert server._cache_ttl() == 3600


# --------------------------------------------------------------------------- #
# AA's index pages: the six Capability Indexes + the Openness / Decision indexes
# --------------------------------------------------------------------------- #

def _index_page_model(slug: str, value: float, subs: dict | None = None, **overrides):
    """A model shaped like ``loaders.capability_models`` output (score + sub-scores)."""
    indices = {"capabilities.legal": value}
    for key, sub_value in (subs or {}).items():
        indices[f"capabilities.legal.{key}"] = sub_value
    return _model(slug, **{**overrides, "indices": indices, "source": "capability"})


def _own_page(monkeypatch, key: str, models: list, source: str, published: int):
    """Point the index-page join for ``key`` at ``models``."""
    monkeypatch.setattr(server, "_extra_score_models",
                        lambda k, refresh=False: models if k == key else [])
    monkeypatch.setattr(server, "_extra_score_meta",
                        lambda k: (source, len(models)) if k == key else ("", 0))
    monkeypatch.setattr(server, "_index_page_meta",
                        lambda k: (source, len(models), published) if k == key else ("", 0, 0))


def test_join_lets_the_index_page_win_its_own_key(monkeypatch):
    """AA's own page for an index is authoritative for that index's value."""
    page = _index_page_model("alpha", 63.26, {"knowledge": 64.2})
    _own_page(monkeypatch, "capabilities.legal", [page], "/models/capabilities/legal", 26)
    base = [_model("alpha", indices={"capabilities.legal": 40.0}, cost_per_task=1.0)]

    joined, source = server._join_extra_scores(base, "capabilities.legal")
    assert source == "/models/capabilities/legal"
    assert joined[0].indices["capabilities.legal"] == pytest.approx(63.26)   # page wins
    assert joined[0].indices["capabilities.legal.knowledge"] == pytest.approx(64.2)
    # everything the leaderboard/rich record knows survives the join
    assert joined[0].cost_per_task == 1.0
    assert joined[0].source == "leaderboard"


def test_join_keeps_the_merged_value_for_a_chart_surface(monkeypatch):
    """A chart-set / panel record is merged *under* the merged record, as before."""
    panel = _model("alpha", evals={"cyberIndex": 99.0})
    _own_page(monkeypatch, "cyberIndex", [panel], "homepage panel", 1)
    base = [_model("alpha", evals={"cyberIndex": 12.0}, cost_per_task=1.0)]

    joined, source = server._join_extra_scores(base, "cyberIndex")
    assert source == "homepage panel"
    assert joined[0].evals["cyberIndex"] == 12.0     # the merged record still wins


def test_join_appends_a_model_only_the_index_page_has(monkeypatch):
    page = _index_page_model("newbie", 55.0)
    _own_page(monkeypatch, "capabilities.legal", [page], "/models/capabilities/legal", 26)
    base = [_model("alpha", indices={"capabilities.legal": 40.0})]

    joined, _source = server._join_extra_scores(base, "capabilities.legal")
    assert [m.slug for m in joined] == ["alpha", "newbie"]


def test_leaderboard_ranks_a_capability_index(monkeypatch, fake):
    """``sort=capabilities.legal`` ranks on real values and says where they came from."""
    models = [_model("alpha", "Alpha One", indices={"capabilities.legal": 60.0}),
              _model("beta", "Beta Two", indices={"capabilities.legal": 70.0}),
              _model("gamma", "Gamma Three")]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal",
              [_index_page_model("beta", 70.0, {"knowledge": 71.0})],
              "/models/capabilities/legal", 26)

    out = server.aa_leaderboard(sort="capabilities.legal", top=5)
    assert out.index("Beta Two") < out.index("Alpha One")
    assert "Cap Legal" in out
    # honest coverage: how many variants carry a value, and where the sub-scores are
    assert "Cap Legal: 2 of 3 tracked variants have a value" in out
    assert "/models/capabilities/legal" in out
    assert "sub-scores for 1 of the 2 rows shown" in out
    # the unscored model is not listed as if it had a value
    assert "Gamma Three" not in out


def test_capability_index_aliases_resolve_to_the_same_ranking(monkeypatch, fake):
    models = [_model("alpha", "Alpha One", indices={"capabilities.legal": 60.0})]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal", [], "/models/capabilities/legal", 0)
    # the payload's own field name, AA's human label and the bare domain word all
    # reach the same ranking
    for alias in ("capabilities.legal", "Legal", "Legal Index", "legal"):
        assert server._metric_key(alias, "sort") == "capabilities.legal"
        assert "Cap Legal" in server.aa_leaderboard(sort=alias, top=3)
    for alias, key in (("Finance & Accounting", "capabilities.financeAndAccounting"),
                       ("financeAndAccounting", "capabilities.financeAndAccounting"),
                       ("Strategy & Ops", "capabilities.strategyAndOps"),
                       ("strategyAndOps", "capabilities.strategyAndOps"),
                       ("Healthcare & Medical", "capabilities.healthcareAndMedical"),
                       ("healthcareAndMedical", "capabilities.healthcareAndMedical"),
                       ("Engineering", "capabilities.engineering"),
                       ("engineering", "capabilities.engineering"),
                       ("Economics", "capabilities.economics"),
                       ("economics", "capabilities.economics")):
        assert server._metric_key(alias, "sort") == key


def test_benchmark_leaderboard_ranks_a_capability_index(monkeypatch, fake):
    models = [_model("alpha", "Alpha One", indices={"capabilities.legal": 60.0}),
              _model("beta", "Beta Two", indices={"capabilities.legal": 70.0})]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal",
              [_index_page_model("beta", 70.0, {"knowledge": 71.0})],
              "/models/capabilities/legal", 26)

    out = server.aa_benchmark_leaderboard(benchmark="capabilities.legal", top=5)
    assert out.index("Beta Two") < out.index("Alpha One")
    assert "Cap Legal" in out
    assert "/models/capabilities/legal + rich dataset" in out
    assert "sub-scores for 1 of the 2 rows shown" in out


def test_pareto_and_compare_reach_a_capability_index(monkeypatch, fake):
    models = [_model("alpha", "Alpha One", indices={"capabilities.legal": 60.0},
                     cost_per_task=1.0),
              _model("beta", "Beta Two", indices={"capabilities.legal": 70.0},
                     cost_per_task=2.0)]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal", [], "/models/capabilities/legal", 0)

    frontier = server.aa_pareto(score="capabilities.legal", top=5)
    assert "Legal Index vs $/task" in frontier
    compared = server.aa_compare(queries=["alpha", "beta"], metrics="capabilities.legal")
    assert "Legal Index" in compared and "70.0" in compared


def test_model_section_shows_capability_sub_scores(monkeypatch, fake):
    """``aa_model sections=indexes`` shows the six scores + the page's sub-scores."""
    base = _model("alpha", "Alpha One", intelligence=50.0,
                  indices={"capabilities.legal": 63.26,
                           "capabilities.economics": 65.6})
    monkeypatch.setattr(server, "_models", lambda refresh=False: [base])
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: {})
    monkeypatch.setattr(server, "_capability_page_subs",
                        lambda key, slug, refresh=False: (
                            ([("capabilities.legal.knowledge", 64.2)], True)
                            if key == "capabilities.legal" else ([], True)))

    out = server.aa_model(query="alpha", sections="indexes")
    assert "| Legal | 63.3 |" in out
    assert "Legal: Knowledge 64.2" in out
    # the index AA does not publish free is stated plainly, with no key talk
    assert "Coding Index, Agentic Index: AA publishes these composites only" in out
    assert "AA_API_KEY" not in out and "JSON API" not in out
    assert "no sub-scores for Economics" in out


def test_model_section_names_an_unreadable_capability_page(monkeypatch, fake):
    """An index page that could not be read is not reported as an absent model (L1)."""
    base = _model("alpha", "Alpha One", intelligence=50.0,
                  indices={"capabilities.legal": 63.26})
    monkeypatch.setattr(server, "_models", lambda refresh=False: [base])
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: {})
    monkeypatch.setattr(server, "_capability_page_subs",
                        lambda key, slug, refresh=False: ([], False))

    out = server.aa_model(query="alpha", sections="indexes")
    assert "| Legal | 63.3 |" in out
    assert "could not be read" in out
    assert "does not list this model" not in out


def test_paid_only_indexes_explain_themselves_without_a_key(monkeypatch, fake):
    """``sort=coding``/``sort=agentic``: honest text, no key talk, free alternatives."""
    for key, constituent in (("coding", "scicode"),
                             ("agentic", "terminalBench40")):
        with pytest.raises(ToolError) as exc:
            server.aa_leaderboard(sort=key, top=3)
        text = str(exc.value)
        assert "paid data API" in text
        assert "no public page carries a per-model value" in text
        assert constituent in text
        assert "AA_API_KEY" not in text and "JSON API" not in text and "env" not in text
        with pytest.raises(ToolError) as exc2:
            server.aa_benchmark_leaderboard(benchmark=key)
        assert "paid data API" in str(exc2.value)


def test_no_hint_for_a_paid_only_index_claims_a_leaderboard_path():
    """A hint must never propose a call that cannot work."""
    for key in ("coding", "agentic"):
        rank = catalog.RANKABLES[key]
        assert rank.surface == "none"
        assert not rank.how.startswith("aa_leaderboard sort="), rank.how
        tool, _, arg = rank.how.partition(" ")
        assert tool == "aa_benchmark_leaderboard"
        constituent = arg.partition("=")[2]
        assert catalog.benchmark(constituent) is not None
        assert catalog.benchmark(constituent).source_hint != "none"
        assert key in catalog.API_ONLY_INDEXES


def test_leaderboard_ranks_the_decision_index(monkeypatch, fake):
    models = [_model("alpha", "Alpha One"), _model("beta", "Beta Two")]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    page = [_model("beta", "Beta Two", indices={"decisionIndex": 79.0}),
            _model("alpha", "Alpha One", indices={"decisionIndex": 62.0})]
    _own_page(monkeypatch, "decisionIndex", page,
              "/evaluations/artificial-analysis-decision-index", 28)

    out = server.aa_leaderboard(sort="decisionIndex", top=3)
    assert out.index("Beta Two") < out.index("Alpha One")
    assert "Decision" in out
    assert "28 rows it publishes" in out


def test_leaderboard_ranks_the_openness_index_from_its_own_page(monkeypatch, fake):
    models = [_model("alpha", "Alpha One"), _model("beta", "Beta Two")]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    page = [_model("alpha", "Alpha One", indices={"openness": 88.9}),
            _model("beta", "Beta Two", indices={"openness": 40.0})]
    _own_page(monkeypatch, "openness", page,
              "/evaluations/artificial-analysis-openness-index", 326)

    out = server.aa_leaderboard(sort="openness", top=3)
    assert out.index("Alpha One") < out.index("Beta Two")
    assert "/evaluations/artificial-analysis-openness-index" in out


def test_rankable_coverage_reports_a_paid_only_index_and_a_page(monkeypatch, fake):
    monkeypatch.setattr(server, "_extra_score_models", lambda key, refresh=False: [])
    assert "paid data API" in server._rankable_coverage(
        catalog.RANKABLES["coding"], [], [])

    page = [_model("alpha", "Alpha One", indices={"decisionIndex": 79.0})]
    _own_page(monkeypatch, "decisionIndex", page,
              "/evaluations/artificial-analysis-decision-index", 28)
    coverage = server._rankable_coverage(catalog.RANKABLES["decisionIndex"], [], [])
    assert "28 rows are tracked models" in coverage


def test_agents_board_presents_the_coding_agent_index(monkeypatch):
    """The coding board's ``indexScore`` is the Coding Agent Index (0-100, agents)."""
    rows = [{"rank": 1, "agent": "Claude Code", "model": "Sonnet 5.5 (max)",
             "creator": "Anthropic", "score": 0.6835783373750831,
             "cost_per_task": 14.19}]
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: rows)

    out = server.aa_agents(board="coding_agents", top=3)
    assert "Coding Agent Index" in out
    assert "| 1 | Claude Code | Sonnet 5.5 (max) | Anthropic | 68.4 | $14.19 |" in out
    assert "agents, not models" in out
    # the other agent boards keep their own score rendering
    other = server.aa_agents(board="chatbots", top=3)
    assert "Coding Agent Index" not in other


def test_chatbot_board_renders_the_feature_score_not_a_percentage(monkeypatch):
    """``featuresScore`` is AA's absolute Feature Score out of 6, never a fraction.

    The raw ``/agents/chatbots`` payload carries the site's own rendered string
    (``{"value": 5.8, "displayValue": "5.80"}``), so 5.8 must print as "5.80" —
    the old percentage path printed "580.0%".
    """
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: [
        {"rank": 1, "agent": "SuperGrok Heavy", "name": "SuperGrok Heavy",
         "model": "Grok 4.7 Heavy", "creator": "SpaceXAI", "score": 5.8},
        {"rank": 4, "agent": "Perplexity Pro", "name": "Perplexity Pro",
         "model": "Claude Sonnet 5.5", "creator": "Perplexity", "score": 5.65},
    ])
    out = server.aa_agents(board="chatbots", top=2)
    assert "| Feature Score |" in out
    assert "| 5.80 |" in out and "| 5.65 |" in out
    assert "%" not in out                       # not a percentage any more
    assert "out of 6" in out


def test_agent_board_scores_keep_their_own_scale(monkeypatch):
    """One ``score`` field, three units: 0-100 index, percentage, out-of-6 score."""
    rows = [{"rank": 1, "agent": "A", "model": "M", "creator": "C", "score": 0.684}]
    monkeypatch.setattr(server, "_load", lambda name, fn, *a, **k: rows)
    coding = server.aa_agents(board="coding_agents", top=1)
    assert "| Coding Agent Index |" in coding and "| 68.4 |" in coding
    search = server.aa_agents(board="search_api", top=1)
    assert "| Score |" in search and "| 68.4% |" in search
    chatbot = server.aa_agents(board="chatbots", top=1)
    assert "| Feature Score |" in chatbot and "| 0.68 |" in chatbot


def test_coding_agent_index_label_resolves_to_a_real_board():
    """AA's own name for the index resolves, and its hint names a real board."""
    rank = catalog.rankable("Coding Agent Index")
    assert rank is not None
    _tool, _, arg = rank.how.partition(" ")
    assert arg.partition("=")[2] in server.loaders.AGENT_BOARDS


# --------------------------------------------------------------------------- #
# coverage is a property of the dataset, never of a filtered view
# --------------------------------------------------------------------------- #

def _capability_dataset(monkeypatch, fake):
    """5 scored models (2 of them deprecated) + 1 unscored, as the merged dataset."""
    models = [
        _model("alpha", "Alpha One", creator="LabA",
               indices={"capabilities.legal": 60.0}),
        _model("beta", "Beta Two", indices={"capabilities.legal": 70.0}),
        _model("gamma", "Gamma Three", indices={"capabilities.legal": 55.0}),
        _model("delta", "Delta Four", indices={"capabilities.legal": 40.0},
               deprecated=True),
        _model("epsilon", "Epsilon Five", indices={"capabilities.legal": 30.0},
               deprecated=True),
        _model("zeta", "Zeta Six"),
    ]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal", [],
              "/models/capabilities/legal", 26)
    return models


def test_capability_coverage_is_the_dataset_count_when_unfiltered(monkeypatch, fake):
    _capability_dataset(monkeypatch, fake)
    out = server.aa_leaderboard(sort="capabilities.legal", top=2)
    # 5 of the 6 variants carry a value; only 3 of them are active
    assert "Cap Legal: 5 of 6 tracked variants have a value (3 active)" in out
    assert "match your filters" not in out


def test_capability_coverage_survives_a_filter(monkeypatch, fake):
    _capability_dataset(monkeypatch, fake)
    out = server.aa_leaderboard(sort="capabilities.legal", name="Alpha", top=2)
    # the coverage line still describes the dataset …
    assert "Cap Legal: 5 of 6 tracked variants have a value (3 active)" in out
    # … and the filter's effect is a separate, clearly labelled match count
    assert "1 of 3 scored models match your filters" in out
    assert out.startswith("# 1 shown of 1 matching")


def test_capability_coverage_survives_a_filter_that_matches_nothing(
    monkeypatch, fake,
):
    _capability_dataset(monkeypatch, fake)
    out = server.aa_leaderboard(sort="capabilities.legal", name="zzz-nope", top=2)
    assert out.startswith("# no models match")
    assert "Cap Legal: 5 of 6 tracked variants have a value (3 active)" in out
    assert "match your filters" not in out       # nothing matched, so no count


def test_benchmark_leaderboard_coverage_survives_a_filter(monkeypatch, fake):
    models = _capability_dataset(monkeypatch, fake)
    unfiltered = server.aa_benchmark_leaderboard(benchmark="capabilities.legal", top=2)
    assert "Cap Legal: 5 of 6 tracked variants have a value" in unfiltered
    assert "2 of 5 scored (6 tracked)" in unfiltered

    filtered = server.aa_benchmark_leaderboard(benchmark="capabilities.legal",
                                               creator="LabA", top=2)
    # the coverage still describes the dataset; the filter is a match count
    assert "Cap Legal: 5 of 6 tracked variants have a value" in filtered
    assert "1 of 5 scored models match your filters" in filtered
    assert "1 shown of 1 matching (6 tracked)" in filtered
    assert models  # the dataset is unchanged by either call


def test_match_note_appears_only_when_a_filter_narrows(fake):
    """The post-filter count is a labelled match count — and only when it narrows."""
    narrowed = server.aa_leaderboard(creator="LabA", top=5)
    assert "1 shown of 1 matching (4 tracked)" in narrowed     # header: filtered view
    assert "1 of 4 scored models match your filters" in narrowed

    whole = server.aa_leaderboard(creator="Lab", top=5)        # matches every lab
    assert "match your filters" not in whole                   # nothing narrowed
    assert whole.startswith("# 4 shown of 4 matching (4 tracked)")


# --------------------------------------------------------------------------- #
# Round-2 regressions: name filter, estimate marker, frontier denominator, copy
# --------------------------------------------------------------------------- #

def test_leaderboard_name_with_no_tokens_matches_nothing(fake):
    """A name carrying no alphanumeric token can never match a model (M1).

    ``name="日本"`` used to normalise to an empty token list, silently disabling
    the filter: the call returned the whole leaderboard while the header still
    claimed ``name~日本``. It must now match nothing, like any other non-match.
    """
    out = server.aa_leaderboard(name="日本", top=5)
    assert out.startswith("# no models match")
    assert "| Model |" not in out          # not the whole dataset
    assert server.aa_leaderboard(name="zzzzzz", top=5).startswith("# no models match")


@pytest.mark.parametrize("name", ["日本", "-_-", "   ", "🎉🎉", "。", "!!!?"])
def test_leaderboard_name_with_no_token_is_never_a_wildcard(fake, name):
    """Punctuation/whitespace/emoji-only names are unmatchable, not "no filter" (M1)."""
    assert server.aa_leaderboard(name=name, top=5).startswith("# no models match")


def test_leaderboard_name_with_tokens_still_filters(fake):
    """The M1 guard must not break ordinary name filtering."""
    out = server.aa_leaderboard(name="Alpha", top=5)
    assert "Alpha One" in out and "Beta Two" not in out


def test_benchmark_leaderboard_marks_only_estimated_intelligence(monkeypatch):
    """The ``*`` marks an AA-estimated value, and only Intelligence carries one (M2).

    ``K2 Think V2``'s openness 88.9 is a real published value: it must not be
    starred because the model's *intelligence* is an AA estimate.
    """
    est = _model("est", "Estimated One", estimated=True, intelligence=40.0,
                 indices={"openness": 88.9})
    plain = _model("plain", "Plain Two", estimated=False, intelligence=50.0,
                   indices={"openness": 40.0})
    _patch_dual_source(monkeypatch, [est, plain], [est, plain])

    out = server.aa_benchmark_leaderboard(benchmark="openness", top=5)
    assert "88.9" in out
    assert "88.9*" not in out
    assert "AA-estimated" not in out        # no legend on a non-intelligence metric

    intel = server.aa_benchmark_leaderboard(benchmark="intelligence", top=5)
    assert "40.0*" in intel                 # the estimate marker is preserved
    assert "AA-estimated" in intel


def test_pareto_labels_a_filtered_denominator_as_matches(fake):
    """A filter narrows the frontier pool; the footnote must say so (M3)."""
    unfiltered = server.aa_pareto(score="intelligence", top=5)
    assert "models scored on both axes" in unfiltered
    assert "matching your filters" not in unfiltered
    filtered = server.aa_pareto(score="intelligence", creator="LabA", top=5)
    assert "matching your filters" in filtered


def test_leaderboard_copy_does_not_pin_a_stale_row_count(fake):
    """The TTFT note must not claim a "700-row" snapshot when the header says 703 (M4)."""
    out = server.aa_leaderboard(sort="ttft", top=3)
    assert "leaderboard snapshot" in out
    assert "700-row" not in out


def test_fields_all_drops_a_column_empty_for_every_row(fake):
    """``fields=all`` asks for everything renderable, not an all-``-`` column (L5)."""
    everything = server.aa_leaderboard(fields="all", top=3)
    assert "Precision" not in everything
    # an explicitly named empty column is still shown, so "no data" ≠ "wrong name"
    explicit = server.aa_leaderboard(fields="precision", top=3)
    assert "Precision" in explicit and "no data for: Precision" in explicit


def test_capability_footnote_names_an_unreadable_page(monkeypatch, fake):
    """An unreadable capability page is not reported as an absent model (L1)."""
    _capability_dataset(monkeypatch, fake)
    readable = server.aa_leaderboard(sort="capabilities.legal", top=2)
    assert "none of these is on that page's chart set" in readable
    # simulate the page failing to read this call (no index-page source recorded)
    monkeypatch.setattr(server, "_index_page_meta", lambda key: ("", 0, 0))
    unreadable = server.aa_leaderboard(sort="capabilities.legal", top=2)
    assert "could not be read" in unreadable
    assert "none of these is on that page's chart set" not in unreadable


def test_capability_coverage_is_qualified_without_the_rich_overlay(monkeypatch, fake):
    """Without the rich overlay the count is the coverage *in the data available*."""
    models = [_model("alpha", "Alpha One", indices={"capabilities.legal": 60.0})]
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, False))
    monkeypatch.setattr(server, "_lb_rows", lambda refresh=False: models)
    _own_page(monkeypatch, "capabilities.legal", [], "/models/capabilities/legal", 26)

    out = server.aa_leaderboard(sort="capabilities.legal", top=2)
    assert "in the data available" in out
    assert "the rich model-page overlay is not loaded" in out

    # with the rich overlay present the claim stays unqualified
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: (models, True))
    assert "in the data available" not in server.aa_leaderboard(
        sort="capabilities.legal", top=2)


# --------------------------------------------------------------------------- #
# board rows as their own namespace: TTS voices, STT hosts, search APIs
# --------------------------------------------------------------------------- #

def _board_test_entry(name, board, metrics, *, creator="Lab", kind="board"):
    """An ``_ArenaEntry`` shaped like ``server._board_entry``'s output."""
    return server._ArenaEntry(
        name=name, board=board, kind=kind, creator=creator,
        metrics=tuple(metrics), rank=None, appearances=None, price=None,
        price_unit=None, release_date=None, open_weights=None,
        ci_lower=None, ci_upper=None)


def test_compare_resolves_a_board_row_on_its_own_columns(fake, monkeypatch):
    """A TTS voice resolves by name and compares on the TTS board's own columns."""
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _board_test_entry("Eleven v4 Turbo", "tts", [
            ("ttsQualityElo", "TTS Quality Elo", 1146.5, "Elo"),
            ("ttsPronunciationPassRate", "TTS Pronunciation", 0.987, "%")],
            creator="ElevenLabs"),
        _board_test_entry("Sonic 3.6", "tts", [
            ("ttsQualityElo", "TTS Quality Elo", 1100.0, "Elo"),
            ("ttsPronunciationPassRate", "TTS Pronunciation", 0.951, "%")],
            creator="Cartesia"),
    ])
    out = server.aa_compare(queries=["Eleven v4 Turbo", "Sonic 3.6"],
                            metrics="ttsPronunciationPassRate,ttsQualityElo")
    assert "| TTS Quality Elo | 1147 | 1100 |" in out      # Elo rounds half-up
    assert "| TTS Pronunciation | 98.7% | 95.1% |" in out
    assert "board rows are their own namespace" in out
    assert "board: tts" in out


def test_compare_picks_the_board_that_carries_the_requested_metric(fake, monkeypatch):
    """A name on several boards: the one publishing the requested column wins."""
    def entry(board, kind, key, value, name):
        return _board_test_entry(name, board, [(key, key, value, "Elo")], kind=kind)

    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        entry("text_to_speech", "media", "elo", 1200.0, "Sonic 3.6"),
        entry("text_to_speech", "media", "elo", 1150.0, "Eleven v4 Turbo"),
        entry("tts", "board", "ttsQualityElo", 1100.0, "Sonic 3.6"),
        entry("tts", "board", "ttsQualityElo", 1146.5, "Eleven v4 Turbo"),
    ])
    out = server.aa_compare(queries=["Sonic 3.6", "Eleven v4 Turbo"],
                            metrics="ttsQualityElo")
    assert "board: tts" in out
    assert "1147" in out and "1100" in out
    # the media arena that also carries the name is offered as an alternative
    assert "text_to_speech" in out


def test_search_labels_a_board_row(fake, monkeypatch):
    """``aa_search`` finds a board row and marks it as a board, not an arena."""
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _board_test_entry("Eleven v4 Turbo", "tts",
                          [("ttsQualityElo", "TTS Quality Elo", 1146.5, "Elo")])])
    out = server.aa_search(query="Eleven v4 Turbo")
    assert "board match" in out and "aa:board" in out
    assert "tts (board)" in out
    assert "| TTS Quality Elo | 1147 |" in out


def test_pareto_explains_a_board_only_score_has_no_cost(fake, monkeypatch):
    """A board-only column has rows but no Intelligence-Index cost — say so."""
    board_row = _model("eleven-v4-turbo", "Eleven v4 Turbo",
                       evals={"ttsQualityElo": 1146.5})   # no cost_per_task
    monkeypatch.setattr(server, "_models_state",
                        lambda refresh=False, rich=True: ([*fake.values(), board_row], rich))
    monkeypatch.setattr(server, "_lb_rows",
                        lambda refresh=False: [*fake.values(), board_row])
    monkeypatch.setattr(server, "_board_models",
                        lambda refresh=False: {"tts": [board_row]})
    out = server.aa_pareto(score="ttsQualityElo", top=3)
    assert "no model has both" in out
    assert "publish no Intelligence-Index cost" in out
    assert "aa_compare" in out


def test_compare_lm_vs_board_row_is_explained(fake, monkeypatch):
    """A language model and a board row are refused with a clear explanation."""
    monkeypatch.setattr(server, "_arena_entries", lambda refresh=False: [
        _board_test_entry("Eleven v4 Turbo", "tts",
                          [("ttsQualityElo", "TTS Quality Elo", 1146.5, "Elo")])])
    with pytest.raises(ValueError) as exc:
        server._compare(["alpha", "Eleven v4 Turbo"])
    msg = str(exc.value)
    assert "either language models or arena-board models" in msg
    assert "board row" in msg and "tts" in msg


def test_compare_two_language_models_is_unchanged(fake):
    """The language-model comparison path is untouched by the board widening."""
    out = server.aa_compare(queries=["alpha", "beta"], metrics="intelligence")
    assert "| 60.0 | 50.0 |" in out
    assert "arena" not in out
    assert "board rows are their own namespace" not in out


# --------------------------------------------------------------------------- #
# fixed-context budget (the wire tool list is paid at every session start)
# --------------------------------------------------------------------------- #

# mcp 2.x sets the tool ``description`` to the *whole* docstring and derives
# ``inputSchema`` from the signature alone — an ``Args:`` block never becomes a
# per-parameter description, so every docstring byte is a wire byte. Measured
# 2026-10-16 after the trim; the before/after table is in
# docs/process/SHAPE_AB_TEST.md. Trim src/aa_mcp/server.py, never this test.
_TOOL_DESC_SCHEMA_TOK_CEILING = 3200   # description + inputSchema, all 12 tools
_TOOL_WIRE_TOK_CEILING = 3400          # the serialized tools/list result


def _wire_tools() -> list[dict]:
    """The 12 tools exactly as ``tools/list`` serializes them."""
    return [t.model_dump(by_alias=True, exclude_none=True)
            for t in asyncio.run(server.srv.list_tools())]


def test_tool_list_fixed_context_stays_within_budget():
    """The tool list must not creep back up: it is paid on every session start."""
    payload = _wire_tools()
    assert len(payload) == 12
    desc_schema = sum(
        len(t.get("description", ""))
        + len(json.dumps(t.get("inputSchema", {}), separators=(",", ":")))
        for t in payload
    )
    wire = len(json.dumps(payload, separators=(",", ":")))
    assert desc_schema / 4 < _TOOL_DESC_SCHEMA_TOK_CEILING, (
        f"tool description+schema is {desc_schema / 4:.0f} tok ({desc_schema} chars), "
        f"over the {_TOOL_DESC_SCHEMA_TOK_CEILING} tok budget — trim the docstrings "
        "in src/aa_mcp/server.py, not this test"
    )
    assert wire / 4 < _TOOL_WIRE_TOK_CEILING, (
        f"serialized tools/list is {wire / 4:.0f} tok ({wire} chars), over the "
        f"{_TOOL_WIRE_TOK_CEILING} tok budget — trim the docstrings in "
        "src/aa_mcp/server.py, not this test"
    )
