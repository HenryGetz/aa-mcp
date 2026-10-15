#!/usr/bin/env python3
"""Exhaustive live sweep of every aa-mcp tool and every documented enum value.

Runs through the real stdio MCP server (same path an agent uses), so it catches
wiring/schema/lookup bugs that unit tests cannot see (e.g. a misnamed variable in
one branch of a tool). Requires network (or a warm cache).

    .venv/bin/python scripts/surface_sweep.py            # human summary
    .venv/bin/python scripts/surface_sweep.py --json     # machine output
    AA_MCP_CMD=/path/to/aa-mcp .venv/bin/python scripts/surface_sweep.py

Exit code 1 if any call fails unexpectedly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aa_mcp import catalog, loaders, reference

SECTIONS = ["identity", "indexes", "benchmarks", "pricing", "speed", "cost",
            "openness", "modalities", "specs", "all"]

MODEL_CANDIDATES = ["claude-opus-5-5", "gpt-6-luna", "step-5", "glm-4-5v"]


def cases() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []

    # --- leaderboard: modes, sorts, filters, fields -------------------------
    for mode in ("rank", "value", "frontier"):
        out.append(("aa_leaderboard", {"mode": mode, "top": 3}))
    for sort in ("intelligence", "cost_per_task", "tps", "ttft", "e2e", "context_tokens",
                 "price_in", "price_out", "params_b", "release_date", "omniscience",
                 "briefcaseElo", "capabilities.legal", "gpqa", "terminalBench40"):
        out.append(("aa_leaderboard", {"sort": sort, "top": 2}))
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
        # a chart key whose values only exist for deprecated models still explains itself
        ("aa_leaderboard", {"sort": "mmluPro", "top": 2}),
        ("aa_leaderboard", {"sort": "mmluPro", "top": 2, "include_deprecated": True}),
    ]
    out += [
        ("aa_leaderboard", {"top": 2, "creator": "anthropic"}),
        ("aa_leaderboard", {"top": 2, "name": "opus max"}),
        ("aa_leaderboard", {"top": 2, "open_weights": True}),
        ("aa_leaderboard", {"top": 2, "reasoning": False}),
        ("aa_leaderboard", {"top": 2, "min_intelligence": 40, "max_cost_per_task": 1.0}),
        ("aa_leaderboard", {"top": 2, "min_speed": 50, "max_ttft": 30, "min_context": 100000}),
        ("aa_leaderboard", {"top": 2, "released_after": "2026-09-01"}),
        ("aa_leaderboard", {"top": 2, "include_deprecated": True}),
        ("aa_leaderboard", {"top": 2, "fields": "license,effort,params_b,open_weights,capabilities.legal"}),
        ("aa_leaderboard", {"top": 2, "fields": "tps,ttft,ctx,params,released,creator"}),
    ]

    # --- model: sections x representative models ----------------------------
    for slug in MODEL_CANDIDATES:
        for section in SECTIONS:
            out.append(("aa_model", {"query": slug, "sections": section}))
    out.append(("aa_model", {"query": "claude opus 5.5"}))          # fuzzy
    out.append(("aa_model", {"query": "glm-4-5v"}))                 # legacy page

    # --- compare ------------------------------------------------------------
    cmp3 = ["claude-opus-5-5", "gpt-6-luna", "gemini-3-5-flash"]
    cmp8 = cmp3 + ["mimo-v2-6-pro", "kimi-k3", "glm-5-3", "step-5", "grok-4-7"]
    cmp12 = cmp8 + ["qwen3-8-max", "ling-3-1-flash", "deepseek-v4-1-flash", "gpt-6-astra"]
    out += [
        ("aa_compare", {"queries": ["claude-opus-5-5", "gpt-6-luna"]}),
        ("aa_compare", {"queries": ["claude-opus-5-5", "gpt-6-luna", "step-5"], "compact": False}),
        ("aa_compare", {"queries": ["claude-opus-5-5", "gpt-6-luna"],
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
        # documented error paths (listed in EXPECTED_FAILURES): never a broken table
        ("aa_compare", {"queries": ["Grok Voice 3.0", "claude-opus-5-5"]}),
        # YAML / JSON spec round-trip (the emitted `spec:` block is re-runnable)
        ("aa_compare", {"spec": "models: [claude-opus-5-5, gpt-6-luna, gemini-3-5-flash]\n"
                                "metrics: all\nview: diff\n"}),
        ("aa_compare", {"spec": "models:\n  - claude-opus-5-5\n  - gpt-6-luna\n"
                                "metrics: benchmarks\nfilters:\n  min_intelligence: 20\n"}),
        ("aa_compare", {"spec": '{"models": ["claude-opus-5-5", "gpt-6-luna"], '
                                '"metrics": "tps,ttft", "view": "diff"}'}),
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
    ]
    bench_keys = [b.key for b in catalog.BENCHMARKS.values()][:14]
    for key in bench_keys:
        out.append(("aa_benchmark_leaderboard", {"benchmark": key, "top": 2}))
    # Wave E: the hint audit — the call each ``how`` hint now points at succeeds
    out += [
        ("aa_benchmark_leaderboard", {"benchmark": "cyberIndex", "top": 2}),
        ("aa_pareto", {"x": "tps", "top": 2}),
        # container benchmarks return an honest one-liner, never a TypeError (E2)
        ("aa_benchmark_leaderboard", {"benchmark": "aa3dBreakdown"}),
        ("aa_benchmark_leaderboard", {"benchmark": "harveyLabBreakdown"}),
    ]

    # --- providers ----------------------------------------------------------
    out += [
        ("aa_providers", {"model": "claude-opus-5-5"}),
        ("aa_providers", {"model": "glm-5-3", "fields": "precision,cache_read,cache_write"}),
        ("aa_providers", {"host": "groq", "top": 3}),
        ("aa_providers", {"open_weights": True, "min_context": 200000, "top": 3}),
    ]
    for sort in ("cost_per_task", "price_in", "price_out", "cache_read", "tps", "ttft",
                 "intelligence", "context_tokens"):
        out.append(("aa_providers", {"model": "kimi-k3", "sort": sort, "top": 2}))

    # --- media: every board -------------------------------------------------
    boards = sorted(loaders.MEDIA_BOARDS) + ["speech_to_text", "speech_to_text_streaming",
                                             "speech_to_speech"]
    for board in boards:
        out.append(("aa_media", {"board": board, "top": 2}))
    out.append(("aa_media", {"board": "text-to-image", "top": 2}))   # hyphen form
    out.append(("aa_media", {"board": "text_to_image", "top": 2,
                             "fields": "name,elo,ci_lower,ci_upper,ci,price,release"}))

    # --- agents: every board ------------------------------------------------
    for board in sorted(loaders.AGENT_BOARDS):
        out.append(("aa_agents", {"board": board, "top": 2}))

    # --- search -------------------------------------------------------------
    for query in ("opus max", "kimi", "gemini 4 argon", "glm", "nonexistentmodel"):
        out.append(("aa_search", {"query": query, "top": 2}))
    out.append(("aa_search", {"creator": "meta", "open_weights": True, "top": 2}))
    # Wave E: arena/media models are searchable too (E3)
    out.append(("aa_search", {"query": "Grok Voice 3.0"}))

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
        "Coding Index is API-only (AA_API_KEY): no cross-model ranking on the "
        "scrape source — aa_benchmark_leaderboard raises an explanatory error",
    ("aa_benchmark_leaderboard", '{"benchmark": "agentic", "top": 2}'):
        "Agentic Index is API-only (AA_API_KEY): same as coding",
    ("aa_benchmark_leaderboard", '{"benchmark": "hleDiamond", "top": 2}'):
        "HLE Diamond has no values in the 700-row leaderboard, the eval chart "
        "set or the homepage panels — '+' reported as 'no data for benchmark'",
    ("aa_leaderboard", '{"sort": "mmluPro", "top": 2}'):
        "MMLU-Pro's only current values are on deprecated models; the default "
        "(active-only) view explains that include_deprecated=true ranks them",
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
    ("aa_benchmark_leaderboard", '{"benchmark": "aa3dBreakdown"}'):
        "AA-3D Breakdown is a container benchmark: AA publishes per-model sub-score "
        "maps, not a ranking column — an honest error naming the scalar sibling "
        "aa3dElo, never a TypeError (E2)",
    ("aa_benchmark_leaderboard", '{"benchmark": "harveyLabBreakdown"}'):
        "Harvey Breakdown is a container benchmark: same honest error naming "
        "harveyLab (E2)",
}


def _case_key(r: dict) -> tuple[str, str]:
    args = {k: v for k, v in r["args"].items() if v not in ("", None)}
    return (r["tool"], json.dumps(args, sort_keys=True))


def _result_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in (result.content or []))


async def run(extra_env: dict[str, str]) -> list[dict]:
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
        for tool, args in cases():
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

    results = asyncio.run(run(extra))
    failures = [r for r in results if r["error"]]
    expected = [r for r in failures if _case_key(r) in EXPECTED_FAILURES]
    unexpected = [r for r in failures if _case_key(r) not in EXPECTED_FAILURES]
    slow = sorted([r for r in results if r["ms"] >= a.slow_ms], key=lambda r: -r["ms"])

    if a.json:
        print(json.dumps({k: v for k, v in
                          {"results": results, "calls": len(results),
                           "failures": len(failures),
                           "unexpected_failures": len(unexpected),
                           "expected_failures": [
                               {"tool": r["tool"], "args": r["args"],
                                "why": EXPECTED_FAILURES[_case_key(r)]}
                               for r in expected]}.items()
                          if k != "results"} |
                         {"results": [{k: r[k] for k in r if k != "text"} for r in results]},
                         indent=1))
    else:
        tokens = sum(r['tokens_est'] for r in results)
        print(f"{len(results)} calls · {len(failures)} failures "
              f"({len(expected)} expected, {len(unexpected)} unexpected) · "
              f"≈{tokens} tokens total (avg {tokens // max(1, len(results))})")
        for r in expected:
            print(f"EXPECTED FAIL {r['tool']} {json.dumps(r['args'])[:80]}\n"
                  f"     why: {EXPECTED_FAILURES[_case_key(r)]}")
        for r in unexpected:
            print(f"FAIL {r['tool']} {json.dumps(r['args'])[:90]}\n     {r['text'][:220]}")
        for r in slow:
            print(f"SLOW {r['ms']}ms {r['tool']} {json.dumps(r['args'])[:70]}")
        if not unexpected:
            print("UNEXPECTED FAILURES: 0 — the run is clean"
                  + (f" ({len(expected)} documented expectation(s) above)" if expected else ""))
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
