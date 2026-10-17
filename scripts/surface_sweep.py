#!/usr/bin/env python3
"""Exhaustive live sweep of every aa-mcp tool and every documented enum value.

Runs through the real stdio MCP server (same path an agent uses), so it catches
wiring/schema/lookup bugs that unit tests cannot see (e.g. a misnamed variable in
one branch of a tool). Requires network (or a warm cache).

    .venv/bin/python scripts/surface_sweep.py            # human summary
    .venv/bin/python scripts/surface_sweep.py --json     # machine output
    AA_MCP_CMD=/path/to/aa-mcp .venv/bin/python scripts/surface_sweep.py

The model panel every model-shaped case uses is **derived from the live data at
run time** (top two active models by Intelligence Index, the best active
open-weights model, the cheapest active model, and one model AA marks deprecated)
and printed with the counts, so a failure is reproducible and a hardcoded slug
cannot go stale as AA rolls a generation over. The one shape the live site may
simply stop offering — a legacy model page (``currentModel``, no embedded chart
set) — is reported as ``SKIP`` with the reason instead of failing the run.

Exit code 1 if any call fails unexpectedly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import sys
import time
from typing import NamedTuple

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aa_mcp import catalog, loaders, reference

SECTIONS = ["identity", "indexes", "benchmarks", "pricing", "speed", "cost",
            "openness", "modalities", "specs", "all"]


class Panel(NamedTuple):
    """The live model panel the model-shaped cases are built from.

    AA deprecates and drops models continuously (2026-10-16: ``glm-4-5v`` and
    ``gpt-5-2`` went deprecated under a hardcoded panel and the whole happy path
    went red), so every active slug here is read from the data layer the tools
    read, once per run, and printed with the counts.
    """

    leaders: tuple[str, ...]     # top 2 active models by Intelligence Index
    open_weights: str            # best-scoring active open-weights model
    cheap: str                   # cheapest active model by $/task
    ranked: tuple[str, ...]      # 12 active slugs for the 3/8/12-model compares
    top_name: str                # display name of ``leaders[0]`` (name -> slug)
    deprecated: str              # best-scoring model AA marks deprecated ("" if none)
    legacy_page: bool            # /models/<deprecated> still carries ``currentModel``
    deprecated_active: bool      # ...and the deprecated slug is a live leaderboard row

    @property
    def models(self) -> tuple[str, ...]:
        """The active slugs the per-section ``aa_model`` sweep walks."""
        return tuple(s for s in (*self.leaders, self.open_weights, self.cheap) if s)

    @property
    def fuzzy(self) -> str:
        """A human-style query for the name -> slug path (drop the variant suffix)."""
        return re.sub(r"\s*\(.*?\)\s*$", "", self.top_name) or self.top_name

    @property
    def summary(self) -> str:
        return (f"panel: leaders={'+'.join(self.leaders)} "
                f"open_weights={self.open_weights} cheap={self.cheap} "
                f"ranked={len(self.ranked)} "
                f"deprecated={self.deprecated or 'none'} "
                f"(active={'yes' if self.deprecated_active else 'no'}, "
                f"legacy_page={'yes' if self.legacy_page else 'no'})")


def _deprecated_slug(refresh: bool = False) -> str:
    """The best-scoring model AA marks deprecated.

    The leaderboard's metrics array carries only active rows (every row has a
    ``deprecated`` key and every one is false today); the deprecated ones live in
    the chart-shaped rich dataset, which is also where the chart-backed rankings
    read them from.
    """
    try:
        rows = loaders.rich_dataset(refresh=refresh)
    except Exception as exc:  # a live-source hiccup must not stop the sweep
        print(f"panel: no deprecated slug ({type(exc).__name__}: {exc})",
              file=sys.stderr)
        return ""
    deprecated = [m for m in rows if m.deprecated and m.intelligence is not None]
    return max(deprecated, key=lambda m: (m.intelligence, m.slug)).slug if deprecated else ""


def _legacy_page(slug: str) -> bool:
    """Whether ``/models/<slug>`` still carries the legacy ``currentModel`` object."""
    if not slug:
        return False
    try:
        path = loaders.SOURCE_URLS["model"].format(slug=slug)
        got = loaders.fetch.get(loaders.url(path), f"model_{slug}")
    except Exception:  # a page AA no longer serves is "no legacy page", not a crash
        return False
    return loaders.parse_legacy_model(got.text) is not None


def live_panel(refresh: bool = False) -> Panel:
    """Derive the model panel from the live data layer (once per run)."""
    rows = loaders.leaderboard(refresh=refresh)
    scored = sorted((m for m in rows if m.intelligence is not None),
                    key=lambda m: (-m.intelligence, m.slug))
    leaders = tuple(m.slug for m in scored[:2])
    open_weights = next((m.slug for m in scored if m.is_open_weights), "")
    cheap = min((m for m in rows if m.cost_per_task is not None),
                key=lambda m: (m.cost_per_task, m.slug)).slug
    # the open-weights and cheap leaders ride in front of the by-intelligence order
    # so the 8- and 12-model compares span labs, not one lab's variants.
    ranked = tuple(dict.fromkeys(
        s for s in (*leaders, open_weights, cheap, *(m.slug for m in scored)) if s))[:12]
    deprecated = _deprecated_slug(refresh)
    return Panel(leaders, open_weights, cheap, ranked,
                 scored[0].name if scored else "", deprecated, _legacy_page(deprecated),
                 deprecated in {m.slug for m in rows})


def skippable(panel: Panel) -> dict[tuple[str, str], str]:
    """Cases reported as ``SKIP`` + a note instead of failing the run.

    The legacy model page is the one shape the live site may simply stop serving
    (AA's current pages embed a chart set); when it is gone — or when nothing can
    reach it — the coverage is unavailable rather than broken, and the note says
    which.
    """
    if not panel.deprecated or panel.deprecated_active:
        return {}
    why = (
        f"{panel.deprecated} is deprecated and aa_model resolves names against the "
        "active leaderboard rows only, so no tool reaches its page"
        if panel.legacy_page else
        f"/models/{panel.deprecated} carries no legacy currentModel object (the page "
        "has a chart set), so there is no legacy page to parse"
    )
    return {("aa_model", json.dumps({"query": panel.deprecated})): why}


def cases(panel: Panel) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []

    # --- leaderboard: modes, sorts, filters, fields -------------------------
    for mode in ("rank", "value", "frontier"):
        out.append(("aa_leaderboard", {"mode": mode, "top": 3}))
    for sort in ("intelligence", "cost_per_task", "tps", "ttft", "e2e", "context_tokens",
                 "price_in", "price_out", "params_b", "release_date", "omniscience",
                 "briefcaseElo", "gpqa", "terminalBench40"):
        out.append(("aa_leaderboard", {"sort": sort, "top": 2}))
    # keyless capability indexes: all six canonical keys, plus a human-label alias
    for sort in ("capabilities.legal", "capabilities.engineering", "capabilities.economics",
                 "capabilities.financeAndAccounting", "capabilities.strategyAndOps",
                 "capabilities.healthcareAndMedical", "Legal Index"):
        out.append(("aa_leaderboard", {"sort": sort, "top": 2}))
    out += [
        ("aa_benchmark_leaderboard", {"benchmark": "capabilities.legal", "top": 2}),
        ("aa_leaderboard", {"sort": "openness", "top": 2}),
        ("aa_leaderboard", {"sort": "decisionIndex", "top": 2}),
        # decision-family rankable carried by the rich dataset / chart set
        ("aa_leaderboard", {"sort": "when2call", "top": 2}),
    ]
    # paid-data-API-only composites: every call must explain the gap and point at
    # the free constituents (see EXPECTED_FAILURES + CONTENT_CHECKS)
    out += [
        ("aa_leaderboard", {"sort": "coding"}),
        ("aa_leaderboard", {"sort": "agentic"}),
        ("aa_benchmark_leaderboard", {"benchmark": "agentic"}),
    ]
    # Wave F: every chart/panel-backed key ranks through the default leaderboard
    for sort in ("cyberIndex", "cyberRefusalRate", "cyberMitigationStatus",
                 "cweBench", "deepsecBench", "cybergymE2e", "cweBenchRefusalRate",
                 "aa3dElo", "harveyLab", "globalMmluLiteScore", "math500",
                 "frontierCode", "enterpriseOpsGym", "gdpPdfAllPass", "mlcrOverall",
                 "analystAgentPassAt1", "mlcrAccuracy"):
        out.append(("aa_leaderboard", {"sort": sort, "top": 2}))
    out += [
        # F2: the companion metrics are usable as fields and modes, like intelligence
        ("aa_leaderboard", {"sort": "cyberIndex", "mode": "frontier", "top": 3}),
        ("aa_leaderboard", {"sort": "cyberIndex", "mode": "value", "top": 3}),
        ("aa_leaderboard", {"sort": "cyberIndex", "top": 3,
                            "fields": "cyberIndex,cyberRefusalRate,cyberMitigationStatus"}),
        # the deprecated path, exercised deliberately: AA publishes MMLU-Pro only
        # for deprecated models, so the default call explains itself and names the
        # include_deprecated twin, which then ranks those rows — never the active
        # panel as if it were deprecated.
        ("aa_leaderboard", {"sort": "mmluPro", "top": 2}),
        ("aa_leaderboard", {"sort": "mmluPro", "top": 2, "include_deprecated": True}),
    ]
    out += [
        ("aa_leaderboard", {"top": 2, "creator": "anthropic"}),
        ("aa_leaderboard", {"top": 2, "name": "opus max"}),
        # a name with no alphanumeric token matches nothing, never "everything"
        ("aa_leaderboard", {"top": 2, "name": "-_-"}),
        ("aa_leaderboard", {"top": 2, "open_weights": True}),
        ("aa_leaderboard", {"top": 2, "reasoning": False}),
        ("aa_leaderboard", {"top": 2, "min_intelligence": 40, "max_cost_per_task": 1.0}),
        ("aa_leaderboard", {"top": 2, "min_speed": 50, "max_ttft": 30, "min_context": 100000}),
        ("aa_leaderboard", {"top": 2, "released_after": "2026-09-01"}),
        ("aa_leaderboard", {"top": 2, "include_deprecated": True}),
        ("aa_leaderboard", {"top": 2, "fields": "license,effort,params_b,open_weights,capabilities.legal"}),
        ("aa_leaderboard", {"top": 2, "fields": "tps,ttft,ctx,params,released,creator"}),
        # Wave G: argument vocabulary — value sort tokens, wildcard fields,
        # the column a provider table is sorted by, and closest-match errors
        ("aa_leaderboard", {"sort": "intel_per_cost", "top": 3}),
        ("aa_leaderboard", {"sort": "intel/$", "top": 2}),
        ("aa_leaderboard", {"fields": "all", "top": 2}),
        # Wave G: identity fields always resolve, and an unknown list entry is
        # ignored with a footnote instead of aborting the call
        ("aa_leaderboard", {"top": 3, "fields": "model,slug,creator,tps"}),
        ("aa_leaderboard", {"top": 3, "fields": "tps,ttft,not_a_field"}),
        # Wave G: a displayed tie is ordered by a named secondary key and footnoted
        ("aa_leaderboard", {"sort": "cost_per_task", "min_intelligence": 40, "top": 6}),
        ("aa_leaderboard", {"sort": "nonsense_sort", "top": 2}),   # expected fail
    ]

    # --- model: sections x the live panel (leaders / open-weights / cheapest) ---
    for slug in panel.models:
        for section in SECTIONS:
            out.append(("aa_model", {"query": slug, "sections": section}))
    out.append(("aa_model", {"query": panel.fuzzy}))                # name -> slug
    if panel.deprecated:
        # the legacy page (``currentModel``, no embedded chart set); SKIPped with a
        # note when the live site no longer serves that shape — see ``skippable``.
        out.append(("aa_model", {"query": panel.deprecated}))
        # the deprecated path, deliberately: a deprecated slug is not a live resolver
        # hit, and asking for it by name (even with include_deprecated=true) explains
        # itself rather than ranking a ghost as if it were active.
        out.append(("aa_search", {"query": panel.deprecated, "top": 3}))
        out.append(("aa_leaderboard", {"name": panel.deprecated,
                                       "include_deprecated": True, "top": 2}))

    # --- compare ------------------------------------------------------------
    cmp3 = list(panel.ranked[:3])
    cmp8 = list(panel.ranked[:8])
    cmp12 = list(panel.ranked[:12])
    out += [
        ("aa_compare", {"queries": cmp3[:2]}),
        ("aa_compare", {"queries": cmp3, "compact": False}),
        ("aa_compare", {"queries": cmp3[:2],
                        "metrics": "intelligence,cost_per_task,tps,ttft,context_tokens"}),
        ("aa_compare", {"queries": cmp3, "metrics": "all"}),
        ("aa_compare", {"queries": cmp3, "metrics": "all", "view": "diff"}),
        ("aa_compare", {"queries": cmp8, "metrics": "all"}),
        ("aa_compare", {"queries": cmp8, "metrics": "all", "view": "diff"}),
        ("aa_compare", {"queries": cmp12, "metrics": "all"}),
        ("aa_compare", {"queries": cmp12, "metrics": "all", "view": "diff"}),
        ("aa_compare", {"queries": cmp3, "metrics": "benchmarks"}),
        ("aa_compare", {"queries": cmp3,
                        "metrics": "intelligence,cost_per_task,cyberIndex,gpqa,tps"}),
        # Wave E: arena-board models resolve and compare (E3)
        ("aa_compare", {"queries": ["Grok Voice 3.0", "GPT-Live-1 (Astra, medium)"]}),
        ("aa_compare", {"queries": ["speech_to_speech", "Grok Voice 3.0",
                                    "GPT-Live-1 (Astra, medium)"]}),
        ("aa_compare", {"queries": ["text_to_image", "GPT Image 2.5 Sunburst (max)",
                                    "GPT Image 2.5 Flare (max)"], "metrics": "all"}),
        # F1: a metric the board does not publish falls back to the native metric(s)
        ("aa_compare", {"queries": ["Grok Voice 3.0", "GPT-Live-1 (Astra, medium)"],
                        "metrics": "elo,ci,price,release"}),
        # the Elo/CI/price path on a media board (ambiguous names -> shared board)
        ("aa_compare", {"queries": ["GPT Image 2.5 Sunburst (max)", "Nano Banana 2.1"]}),
        ("aa_compare", {"queries": ["GPT Image 2.5 Sunburst (max)", "Nano Banana 2.1"],
                        "metrics": "elo,ci,price,release"}),
        # Wave E: the user's 4-model URL exercises the scaled missing-metric footer (E4)
        ("aa_compare", {"queries": ["mimo-v2-6-pro", "deepseek-v4-1-flash",
                                    "gpt-6-luna-xhigh", "muse-wonder-full"],
                        "metrics": "all", "view": "diff"}),
        # Wave G: compact=false adds the Slug row (compact=true omits it)
        ("aa_compare", {"queries": ["mimo-v2-6-pro", "deepseek-v4-1-flash",
                                    "gpt-6-luna-xhigh", "muse-wonder-full"],
                        "metrics": "all", "compact": False}),
        ("aa_compare", {"queries": ["mimo-v2-6-pro", "deepseek-v4-1-flash",
                                    "gpt-6-luna-xhigh", "muse-wonder-full"]}),
        # Wave G: one metric never means two numbers — the ttft alias, the key and
        # metrics=all all resolve to the same (model-page) value
        ("aa_compare", {"queries": list(panel.leaders),
                        "metrics": "ttft,time_to_first_token,tps"}),
        ("aa_compare", {"queries": list(panel.leaders), "metrics": "ttft",
                        "compact": False}),
        ("aa_compare", {"queries": list(panel.leaders), "metrics": "tps",
                        "compact": False}),
        # Wave G: a bare family slug says which effort variant it is
        ("aa_compare", {"queries": list(reversed(panel.leaders)),
                        "metrics": "intelligence"}),
        # Wave G: an unknown metric name in a list must not abort the whole call
        ("aa_compare", {"queries": [panel.leaders[0], panel.open_weights],
                        "metrics": ["livecodebench", "frontierCode", "terminalBench40",
                                    "lcr", "swe-bench-verified"]}),
        # Wave G: score/$ is a derived ratio, and metrics=all carries it
        ("aa_compare", {"queries": [panel.leaders[0], panel.open_weights],
                        "metrics": "intel/$,coding/$", "compact": False}),
        # documented error paths (listed in EXPECTED_FAILURES): never a broken table
        ("aa_compare", {"queries": ["Grok Voice 3.0", "claude-opus-5-5"]}),
        # YAML / JSON spec round-trip (the emitted `spec:` block is re-runnable)
        ("aa_compare", {"spec": f"models: [{', '.join(cmp3)}]\n"
                                "metrics: all\nview: diff\n"}),
        ("aa_compare", {"spec": f"models:\n  - {cmp3[0]}\n  - {cmp3[1]}\n"
                                "metrics: benchmarks\nfilters:\n  min_intelligence: 20\n"}),
        ("aa_compare", {"spec": json.dumps({"models": cmp3[:2], "metrics": "tps,ttft",
                                            "view": "diff"})}),
    ]

    # --- pareto: every x axis, several scores -------------------------------
    for x in ("cost_per_task", "index_total_cost", "out_tokens_per_task",
              "time_per_task", "context_tokens", "params_b", "ttft",
              "price_in", "price_out"):
        out.append(("aa_pareto", {"x": x, "top": 3}))
    for score in ("intelligence", "cyberIndex", "terminalBench40", "gpqa",
                  "openness", "capabilities.legal", "tps"):
        out.append(("aa_pareto", {"score": score, "top": 2}))
    out += [
        ("aa_pareto", {}),
        ("aa_pareto", {"x": "index_total_cost", "include_all": True}),
        ("aa_pareto", {"x": "out_tokens_per_task", "creator": "openai", "top": 2}),
        ("aa_pareto", {"x": "cost_per_task", "open_weights": True, "top": 2}),
        ("aa_pareto", {"x": "cost_per_task", "include_deprecated": True, "top": 2}),
        ("aa_pareto", {"x": "cost_per_task", "min_intelligence": 40,
                       "min_context": 200000, "top": 2}),
        ("aa_pareto", {"x": "Cost to Run the Intelligence Index", "top": 2}),
        # a filter narrows the frontier pool; the footnote labels that as matches
        ("aa_pareto", {"score": "capabilities.legal", "creator": "OpenAI", "top": 3}),
        # a board-only column has rows but no Intelligence-Index cost: explained,
        # never a made-up cost
        ("aa_pareto", {"score": "ttsQualityElo", "top": 2}),
    ]

    # --- boards as their own namespace: TTS voices, STT hosts, search APIs -----
    out += [
        ("aa_compare", {"queries": ["Eleven v4 Turbo", "Sonic 3.6"],
                        "metrics": "ttsPronunciationPassRate,ttsQualityElo"}),
        ("aa_compare", {"queries": ["Scribe v2", "MAI-Transcribe-2"],
                        "metrics": "sttEarnings22Wer"}),
        ("aa_compare", {"queries": ["Perplexity Search", "Octen Search"],
                        "metrics": "searchQualityIndex,searchCostPerQuery"}),
        ("aa_search", {"query": "Eleven v4 Turbo"}),
        # a language model and a board row are refused with an explanation
        ("aa_compare", {"queries": ["claude-opus-5-5", "Eleven v4 Turbo"]}),
    ]

    # --- benchmarks: the rankable search index ------------------------------
    for domain in ("coding", "math", "science", "security", "agentic", "tool-use",
                   "long-context", "knowledge", "reasoning", "safety", "multimodal",
                   "speech", "media", "music", "video", "legal", "medical", "cost",
                   "speed", "openness"):
        out.append(("aa_benchmarks", {"domain": domain}))
    for tag in ("index", "cost", "speed", "agentic", "cyber", "coding", "speech"):
        out.append(("aa_benchmarks", {"tag": tag}))
    for query in ("speech", "cyber", "long context",
                  "Provider Voice Arena Preference Elo",
                  "Artificial Analysis Speech to Speech Index", "AA-3D",
                  "Terminal-Bench 4.0", "cost",
                  "Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index"):
        out.append(("aa_benchmarks", {"query": query}))
    out.append(("aa_benchmarks", {"domain": "security", "verbose": True}))
    out.append(("aa_benchmarks", {"query": "speech", "verbose": True}))
    # documented error paths (listed in EXPECTED_FAILURES): never a bare table
    out.append(("aa_pareto", {"x": "nonsense", "top": 2}))
    out.append(("aa_benchmarks", {"domain": "nonsense"}))
    out.append(("aa_benchmarks", {"query": "zzzqqq"}))
    out.append(("aa_compare", {"queries": ["claude-opus-5-5"], "metrics": "all"}))
    out.append(("aa_compare", {"queries": ["claude-opus-5-5", "gpt-6-luna"],
                               "view": "sparkline"}))

    # --- benchmarks ---------------------------------------------------------
    out += [
        ("aa_benchmarks", {}),
        ("aa_benchmarks", {"query": "gpqa"}),
        ("aa_benchmarks", {"query": "gpqa", "verbose": True}),
        ("aa_benchmarks", {"query": "BFCL"}),
        # Wave G: a task word AA does not measure answers instead of dead-ending
        ("aa_benchmarks", {"query": "classif"}),
        ("aa_benchmarks", {"query": "tool calling"}),
    ]
    bench_keys = [b.key for b in catalog.BENCHMARKS.values()][:14]
    for key in bench_keys:
        out.append(("aa_benchmark_leaderboard", {"benchmark": key, "top": 2}))
    # Wave E: the hint audit — the call each ``how`` hint now points at succeeds
    out += [
        ("aa_benchmark_leaderboard", {"benchmark": "cyberIndex", "top": 2}),
        # the estimate marker belongs to the displayed metric: Openness is real
        ("aa_benchmark_leaderboard", {"benchmark": "openness", "top": 2}),
        ("aa_pareto", {"x": "tps", "top": 2}),
        # container benchmarks return an honest one-liner, never a TypeError (E2)
        ("aa_benchmark_leaderboard", {"benchmark": "aa3dBreakdown"}),
        ("aa_benchmark_leaderboard", {"benchmark": "harveyLabBreakdown"}),
    ]

    # --- providers ----------------------------------------------------------
    out += [
        ("aa_providers", {"model": panel.leaders[0]}),
        ("aa_providers", {"model": panel.open_weights,
                          "fields": "precision,cache_read,cache_write"}),
        ("aa_providers", {"host": "groq", "top": 3}),
        ("aa_providers", {"open_weights": True, "min_context": 200000, "top": 3}),
    ]
    for sort in ("cost_per_task", "price_in", "price_out", "cache_read", "tps", "ttft",
                 "intelligence", "context_tokens"):
        out.append(("aa_providers", {"model": panel.leaders[0], "sort": sort, "top": 2}))
    out += [
        # the sorted-by column must be visible, and fields=all must work
        ("aa_providers", {"model": panel.leaders[0], "sort": "ttft", "fields": "all",
                          "top": 3}),
        # Wave G: identity fields resolve from the endpoint record (never blank)
        ("aa_providers", {"model": panel.open_weights, "top": 3,
                          "fields": "model,slug,host,creator,price_in"}),
        # Wave G: a model AA lists no endpoints for is explained, not errored
        ("aa_providers", {"model": "muse-wonder-full", "fields": "model,price_in"}),
        ("aa_providers", {"model": "kimi-k3", "sort": "nope", "top": 2}),  # expected fail
    ]

    # --- media: every board -------------------------------------------------
    boards = sorted(loaders.MEDIA_BOARDS) + ["speech_to_text", "speech_to_text_streaming",
                                             "speech_to_speech"]
    for board in boards:
        out.append(("aa_media", {"board": board, "top": 2}))
    out.append(("aa_media", {"board": "text-to-image", "top": 2}))   # hyphen form
    out.append(("aa_media", {"board": "text_to_image", "top": 2,
                             "fields": "name,elo,ci_lower,ci_upper,ci,price,release"}))
    # Wave G: a media field the board does not have is ignored, not fatal
    out.append(("aa_media", {"board": "text_to_image", "top": 2,
                             "fields": "elo,nonsense"}))
    # per-category sub-boards: an image category and a TTS language, plus the two
    # argument errors (unknown slug, and a speech panel that has no split)
    out.append(("aa_media", {"board": "text_to_image", "category": "marketing-and-advertising",
                             "top": 2}))
    out.append(("aa_media", {"board": "text_to_speech_controlled", "category": "ja",
                             "top": 2}))
    out.append(("aa_media", {"board": "text_to_image", "category": "nope", "top": 2}))
    out.append(("aa_media", {"board": "speech_to_text", "category": "ja", "top": 2}))

    # --- agents: every board ------------------------------------------------
    for board in sorted(loaders.AGENT_BOARDS):
        out.append(("aa_agents", {"board": board, "top": 2}))

    # --- search -------------------------------------------------------------
    for query in ("opus max", "kimi", "gemini 4 argon", "glm", "nonexistentmodel"):
        out.append(("aa_search", {"query": query, "top": 2}))
    out.append(("aa_search", {"creator": "meta", "open_weights": True, "top": 2}))
    # Wave E: arena/media models are searchable too (E3)
    out.append(("aa_search", {"query": "Grok Voice 3.0"}))
    # arena matches use the same all-token rule as the language-model path:
    # a genuine AND match ("grok voice") vs a labelled partial ("gpt 6 luna high")
    out.append(("aa_search", {"query": "grok voice"}))
    out.append(("aa_search", {"query": "gpt 6 luna high"}))
    # a strong language-model answer gets one arena hint line, not a fuzzy table
    out.append(("aa_search", {"query": "claude opus 5.5"}))
    # a query naming a rankable thing answers with its hint instead of dead-ending
    out.append(("aa_search", {"query": "gpqa"}))
    out.append(("aa_search", {"query": "terminal-bench 4.0"}))
    # Wave G: a task word AA does not measure answers with its closest measures
    out.append(("aa_search", {"query": "best model for classification"}))
    out.append(("aa_search", {"query": "summarization"}))

    # --- reference: every topic --------------------------------------------
    for topic in sorted(reference.TOPICS):
        out.append(("aa_reference", {"topic": topic}))

    # --- raw: every kind ----------------------------------------------------
    for kind in ("leaderboard", "model", "providers", "providers_board", "media",
                 "agents", "home", "eval", "catalog"):
        out.append(("aa_raw", {"kind": kind, "top": 1, "query": "claude-opus-5-5"
                               if kind in ("model", "providers", "eval") else ""}))
    # the eval happy path (kind=eval rejects a *model* slug, see EXPECTED_FAILURES)
    out.append(("aa_raw", {"kind": "eval", "top": 1, "query": "gpqa-diamond"}))
    # F4: the sitemap-union makes a card-omitted eval page (the Cyber Index) valid
    out.append(("aa_raw", {"kind": "eval", "top": 1,
                           "query": "artificial-analysis-cyber-index"}))
    return out


#: failures this sweep EXPECTS on a live scrape source (documented, not regressions).
#: Anything not listed here is a real failure and fails the run.
EXPECTED_FAILURES: dict[tuple[str, str], str] = {
    ("aa_benchmark_leaderboard", '{"benchmark": "coding", "top": 2}'):
        "AA publishes no model-level Coding Index on any public page (it exists "
        "only behind AA's paid data API), so there is no cross-model ranking to "
        "give — aa_benchmark_leaderboard raises an explanatory error pointing at "
        "the constituent benchmarks (SciCode, Terminal-Bench 4.0, LiveCodeBench, "
        "FrontierCode)",
    ("aa_benchmark_leaderboard", '{"benchmark": "agentic", "top": 2}'):
        "AA publishes no model-level Agentic Index on any public page; same "
        "explanatory error as coding",
    ("aa_benchmark_leaderboard", '{"benchmark": "agentic"}'):
        "AA publishes no model-level Agentic Index on any public page (no top given); "
        "same explanatory error as coding",
    ("aa_leaderboard", '{"sort": "coding"}'):
        "AA publishes no model-level Coding Index on any public page (paid data API "
        "only) — the error names the free constituents to rank instead "
        "(scicode, livecodebench, frontierCode, terminalBench40)",
    ("aa_leaderboard", '{"sort": "agentic"}'):
        "AA publishes no model-level Agentic Index on any public page (paid data API "
        "only) — the error names the free constituents to rank instead "
        "(terminalBench40, tau2, tauBanking, automationBenchPartialScore)",
    ("aa_benchmark_leaderboard", '{"benchmark": "hleDiamond", "top": 2}'):
        "HLE Diamond has no values in the leaderboard, the eval chart "
        "set or the homepage panels — '+' reported as 'no data for benchmark'",
    ("aa_leaderboard", '{"sort": "mmluPro", "top": 2}'):
        "MMLU-Pro's only current values are on deprecated models; the default "
        "(active-only) view explains that include_deprecated=true ranks them",
    ("aa_leaderboard", '{"sort": "nonsense_sort", "top": 2}'):
        "an unknown sort token lists the closest accepted metric names instead of "
        "dead-ending (argument vocabulary, round 6)",
    ("aa_providers", '{"model": "kimi-k3", "sort": "nope", "top": 2}'):
        "an unknown provider sort lists the closest accepted sort keys and the "
        "alias list",
    ("aa_raw", '{"kind": "eval", "query": "claude-opus-5-5", "top": 1}'):
        "aa_raw kind=eval validates the slug: a model slug is rejected with "
        "'kind=eval expects an evaluation slug (e.g. gpqa-diamond)' instead of "
        "fetching /evaluations/<model-slug> and 404ing",
    ("aa_pareto", '{"top": 2, "x": "nonsense"}'):
        "aa_pareto rejects an unknown x axis with the valid list "
        "(cost_per_task, index_total_cost, out_tokens_per_task, time_per_task, "
        "context_tokens, params_b, ttft, price_in, price_out)",
    ("aa_benchmarks", '{"domain": "nonsense"}'):
        "aa_benchmarks rejects an unknown domain with the valid domain list from "
        "catalog.DOMAINS",
    ("aa_benchmarks", '{"query": "zzzqqq"}'):
        "aa_benchmarks answers a zero-hit search with the closest labels instead of "
        "an empty table",
    ("aa_compare", '{"metrics": "all", "queries": ["claude-opus-5-5"]}'):
        "aa_compare needs 2-12 models; one model is rejected with the accepted range",
    ("aa_compare", '{"queries": ["claude-opus-5-5", "gpt-6-luna"], "view": "sparkline"}'):
        "aa_compare rejects an unknown view with the valid list (table, diff)",
    ("aa_compare", '{"queries": ["Grok Voice 3.0", "claude-opus-5-5"]}'):
        "mixing a language model and an arena-board entry is refused with an "
        "explanation instead of a broken table (E3)",
    ("aa_compare", '{"queries": ["claude-opus-5-5", "Eleven v4 Turbo"]}'):
        "mixing a language model and a board row (a TTS voice) is refused with the "
        "same explanation, naming the board it belongs to (round-2 follow-up)",
    ("aa_media", '{"board": "text_to_image", "category": "nope", "top": 2}'):
        "an unknown category lists the board's published slugs instead of silently "
        "ranking the overall board (round-2 follow-up)",
    ("aa_media", '{"board": "speech_to_text", "category": "ja", "top": 2}'):
        "the homepage speech panels publish no category split — category= is refused "
        "with the reason, never ignored",
    ("aa_benchmark_leaderboard", '{"benchmark": "aa3dBreakdown"}'):
        "AA-3D Breakdown is a container benchmark: AA publishes per-model sub-score "
        "maps, not a ranking column — an honest error naming a rankable sub-score "
        "(aa3dTurnsP50) and the model-page breakdown path, never a TypeError (E2)",
    ("aa_benchmark_leaderboard", '{"benchmark": "harveyLabBreakdown"}'):
        "Harvey Breakdown is a container benchmark: same honest error naming "
        "harveyCriteriaPass (E2)",
}


#: Reply-text contract for the paid-data-API-only composites.  Every such call must
#: explain the gap in free terms and must never point at a key, an env var or the
#: removed JSON API.  ``(must_contain_all, must_not_contain_any)``, case-insensitive;
#: a violation is reported like an unexpected failure.
_CONTENT_CHECKS: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {
    key: (("paid data api", "constituent"),
          ("aa_api_key", "api key", "json api", "env"))
    for key in (
        ("aa_leaderboard", '{"sort": "coding"}'),
        ("aa_leaderboard", '{"sort": "agentic"}'),
        ("aa_benchmark_leaderboard", '{"benchmark": "coding", "top": 2}'),
        ("aa_benchmark_leaderboard", '{"benchmark": "agentic", "top": 2}'),
        ("aa_benchmark_leaderboard", '{"benchmark": "agentic"}'),
    )
}
_CONTENT_CHECKS.update({
    # a name with no alphanumeric token matches nothing, never the whole dataset
    ("aa_leaderboard", '{"name": "-_-", "top": 2}'):
        (("no models match",), ("| model |",)),
    # a filtered frontier labels its denominator as the filtered pool
    ("aa_pareto", '{"creator": "OpenAI", "score": "capabilities.legal", "top": 3}'):
        (("matching your filters",), ()),
    # the `*` estimate marker belongs to the Intelligence Index, not to Openness
    ("aa_benchmark_leaderboard", '{"benchmark": "openness", "top": 2}'):
        (("openness",), ("aa-estimated",)),
    # fields=all asks for everything renderable — not an all-"-" column
    ("aa_leaderboard", '{"fields": "all", "top": 2}'):
        (("intel",), ("precision",)),
    # a category call surfaces the slug it ranked
    ("aa_media", '{"board": "text_to_image", "category": "marketing-and-advertising", "top": 2}'):
        (("category=marketing-and-advertising",), ()),
    # the container-benchmark error names a call that ranks something
    ("aa_benchmark_leaderboard", '{"benchmark": "aa3dBreakdown"}'):
        (("container benchmark", "aa3dturnsp50"), ("typeerror",)),
    # the chatbot board's Feature Score is an absolute score out of 6, not a percentage
    ("aa_agents", '{"board": "chatbots", "top": 2}'):
        (("feature score", "out of 6"), ("%",)),
    # board rows resolve by name and compare on the board's own columns
    ("aa_compare", '{"metrics": "ttsPronunciationPassRate,ttsQualityElo", "queries": ["Eleven v4 Turbo", "Sonic 3.6"]}'):
        (("board rows are their own namespace", "tts quality elo"), ()),
    ("aa_compare", '{"metrics": "sttEarnings22Wer", "queries": ["Scribe v2", "MAI-Transcribe-2"]}'):
        (("board rows are their own namespace", "earnings22"), ()),
    ("aa_search", '{"query": "Eleven v4 Turbo"}'):
        (("tts",), ()),
})


def _case_key(r: dict) -> tuple[str, str]:
    args = {k: v for k, v in r["args"].items() if v not in ("", None)}
    return (r["tool"], json.dumps(args, sort_keys=True))


def _result_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in (result.content or []))


def _content_violations(results: list[dict]) -> list[str]:
    """Cases whose reply text breaks the paid-only content contract."""
    by_key = {_case_key(r): r for r in results}
    out: list[str] = []
    for key, (need, forbid) in _CONTENT_CHECKS.items():
        label = f"{key[0]} {key[1]}"
        r = by_key.get(key)
        if r is None:
            out.append(f"{label}: case did not run")
            continue
        low = r["text"].lower()
        missing = [s for s in need if s not in low]
        present = [s for s in forbid if s in low]
        if missing or present:
            out.append(f"{label}: missing={missing} forbidden={present}")
    return out


async def run(extra_env: dict[str, str], panel: Panel) -> list[dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.update(extra_env)
    override = env.get("AA_MCP_CMD")
    if override:
        params = StdioServerParameters(command=override, args=[], env=env)
    else:
        exe = REPO / ".venv" / "bin" / "aa-mcp"
        params = (StdioServerParameters(command=str(exe), args=[], env=env) if exe.exists()
                  else StdioServerParameters(command=str(REPO / ".venv" / "bin" / "python"),
                                             args=["-m", "aa_mcp.server"], env=env))

    results: list[dict] = []
    async with stdio_client(params) as (read, write), \
            ClientSession(read, write) as session:
        await session.initialize()
        for tool, args in cases(panel):
            t0 = time.time()
            try:
                res = await session.call_tool(tool, args)
                text = _result_text(res)
                err = bool(res.is_error)
            except Exception as exc:
                text, err = f"EXCEPTION {type(exc).__name__}: {exc}", True
            results.append({"tool": tool, "args": args, "error": err,
                            "ms": round((time.time() - t0) * 1000),
                            "chars": len(text),
                            "tokens_est": (len(text) + 3) // 4,
                            "first": text.splitlines()[0][:110] if text else "",
                            "text": text})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--env", action="append", default=[], metavar="K=V")
    ap.add_argument("--slow-ms", type=int, default=1500)
    a = ap.parse_args()
    extra = dict(kv.split("=", 1) for kv in a.env)

    panel = live_panel()
    results = asyncio.run(run(extra, panel))
    skips = skippable(panel)
    failures = [r for r in results if r["error"]]
    expected = [r for r in failures if _case_key(r) in EXPECTED_FAILURES]
    skipped = [r for r in failures if _case_key(r) in skips]
    unexpected = [r for r in failures
                  if _case_key(r) not in EXPECTED_FAILURES and _case_key(r) not in skips]
    violations = _content_violations(results)
    slow = sorted([r for r in results if r["ms"] >= a.slow_ms], key=lambda r: -r["ms"])

    if a.json:
        print(json.dumps({k: v for k, v in
                          {"panel": dict(panel._asdict()), "calls": len(results),
                           "failures": len(failures),
                           "unexpected_failures": len(unexpected),
                           "content_violations": violations,
                           "skipped": [{"tool": r["tool"], "args": r["args"],
                                        "why": skips[_case_key(r)]}
                                       for r in skipped],
                           "expected_failures": [
                               {"tool": r["tool"], "args": r["args"],
                                "why": EXPECTED_FAILURES[_case_key(r)]}
                               for r in expected]}.items()
                          if k != "results"} |
                         {"results": [{k: r[k] for k in r if k != "text"} for r in results]},
                         indent=1))
    else:
        tokens = sum(r['tokens_est'] for r in results)
        print(f"PANEL {panel.summary}")
        print(f"{len(results)} calls · {len(failures)} failures "
              f"({len(expected)} expected, {len(skipped)} skipped, "
              f"{len(unexpected)} unexpected) · "
              f"≈{tokens} tokens total (avg {tokens // max(1, len(results))})")
        for r in expected:
            print(f"EXPECTED FAIL {r['tool']} {json.dumps(r['args'])[:80]}\n"
                  f"     why: {EXPECTED_FAILURES[_case_key(r)]}")
        for r in unexpected:
            print(f"FAIL {r['tool']} {json.dumps(r['args'])[:90]}\n     {r['text'][:220]}")
        for r in skipped:
            print(f"SKIP {r['tool']} {json.dumps(r['args'])[:90]}\n"
                  f"     why: {skips[_case_key(r)]}")
        for v in violations:
            print(f"CONTENT CONTRACT VIOLATION {v}")
        for r in slow:
            print(f"SLOW {r['ms']}ms {r['tool']} {json.dumps(r['args'])[:70]}")
        if not unexpected and not violations:
            print("UNEXPECTED FAILURES: 0 — the run is clean"
                  + (f" ({len(expected)} documented expectation(s) above)" if expected else "")
                  + (f" ({len(skipped)} shape(s) unavailable — SKIP notes above)"
                     if skipped else ""))
    return 1 if unexpected or violations else 0


if __name__ == "__main__":
    sys.exit(main())
