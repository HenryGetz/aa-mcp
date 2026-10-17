---
name: aa-mcp
description: Work with or on the keyless artificialanalysis.ai MCP server in this repo — its aa_* tool surface, resources and prompts, the stdio eval harness, the pre-ship gates, and the data-model traps that produce wrong answers. Load when answering AI-model benchmark, pricing or speed questions through aa-mcp, or when changing this server.
---

# aa-mcp

A **keyless MCP server for [artificialanalysis.ai](https://artificialanalysis.ai)** (AA).
One data source: the site's Next.js **RSC flight payloads**, scraped and cached locally —
no API key, no quota, no backend selection. Every response header reads `aa:rsc`.
Pure Python, one runtime dependency (`mcp>=2.0.0`).

## Install & wire up

```bash
uvx --from git+https://github.com/HenryGetz/aa-mcp aa-mcp               # run, no install
uv tool install --from git+https://github.com/HenryGetz/aa-mcp aa-mcp   # -> ~/.local/bin/aa-mcp
uv sync && uv run aa-mcp                                               # local checkout, stdio
```

omp registration lives in `~/.omp/agent/mcp.json` (project: `.omp/mcp.json`):

```json
{"mcpServers": {"aa": {"type": "stdio", "command": "/home/wavy/.local/bin/aa-mcp",
                       "timeout": 180000, "enabled": true}}}
```

## Surface

Twelve tools. The inventory is **live, not this list**:

```bash
.venv/bin/python eval/client.py tools      # names, one-liners, params
.venv/bin/python eval/client.py schema     # full input schemas
```

`aa_leaderboard` · `aa_model` · `aa_pareto` · `aa_compare` · `aa_benchmarks` ·
`aa_benchmark_leaderboard` · `aa_providers` · `aa_media` · `aa_agents` · `aa_search` ·
`aa_reference` · `aa_raw`.

Resources: `aa://reference/<topic>` (one per `reference.TOPICS` entry, e.g.
`aa://reference/indexes`, `aa://reference/pricing`), `aa://benchmarks`, `aa://rankables`
(+ `aa://rankables.yaml`), `aa://comparisons/spec`, `aa://sources`.
Prompts: `best_model_for_task`, `compare_models`.

## Driving it while developing

`eval/client.py` is a thin stdio MCP client that spawns the server exactly as a real
client does:

```bash
.venv/bin/python eval/client.py tools                     # inventory + params
.venv/bin/python eval/client.py schema                    # full input schemas
.venv/bin/python eval/client.py call aa_model '{"query":"gpt-6-luna"}'
.venv/bin/python eval/client.py read aa://reference/indexes
.venv/bin/python eval/client.py resources
.venv/bin/python eval/client.py prompts
.venv/bin/python eval/client.py bench                     # token panel -> eval/runs/live.ndjson
AA_MCP_CMD=/path/to/aa-mcp .venv/bin/python eval/client.py tools   # test an installed build
```

`scripts/surface_sweep.py` is the **live end-to-end guard**: every tool × every
documented enum, through the real server (~220 calls, needs network or a warm cache,
exit 1 on an unexpected failure). Unit tests cannot see wiring bugs; the sweep can.

## Gates before shipping

```bash
AA_OFFLINE=1 uv run pytest -q                        # offline, fixture-backed
uvx ruff check .                                     # lint (CI runs this)
uv run python scripts/gen_reference_md.py --check    # docs/REFERENCE.md == reference.py
.venv/bin/python scripts/surface_sweep.py            # live surface sweep
```

CI additionally asserts `import aa_mcp.server` writes nothing to stdout, and runs
`eval/client.py tools` over stdio.

## Data-model gotchas that bite

- **Tests never touch the network.** They run `AA_OFFLINE=1` against saved payloads in
  `tests/fixtures/*.rsc`. Add a fixture, not a live call.
- **Coverage ≠ match count.** Headers state `shown / matching / tracked`, and the
  `Coverage` column is computed live from the source chain (703-row leaderboard → rich
  overlay → eval chart set / homepage panel). A filter narrows *matching*, never
  *tracked* — say which you mean.
- **Chart sets are a subset.** Eval chart sets / homepage panels carry only ~5–32
  models. `aa_benchmark_leaderboard` on such a benchmark is a subset ranking;
  `aa_leaderboard sort=<key>` joins the chart set by slug and states the real coverage.
- **Board rows are their own namespace.** A TTS voice, an STT host or a search API is
  **not a language model** — those rows publish no Intelligence-Index cost or speed, so
  `aa_pareto score=<board key>` reports that no frontier can be drawn. `aa_search` tags
  them `aa:arena`; `aa_compare` keeps them within one board.
- **One metric = one number.** `fields=` / `metrics=` / `sort=` aliases resolve to a
  single canonical column (`cost` → `cost_per_task`); identity columns always resolve.
  `fields=all` is bounded by the response cap.
- **Two caches, two ages.** Leaderboard and chart sets: 1 h (`AA_CACHE_TTL`). The **rich
  overlay** (capability indexes, whole-suite cost, first-party speed medians) is a
  separate file with a **6 h** TTL (`AA_RICH_TTL`) and its own header age label
  (`overlay 12m ago`) — two numbers can disagree on age alone.
- **Env knobs:** `AA_OFFLINE=1` (cache only), `AA_CACHE_DIR` (`~/.cache/aa-mcp`),
  `AA_CACHE_TTL` (3600), `AA_RICH_TTL` (21600), `AA_MAX_BYTES` (48 MB decode cap),
  `AA_HTTP_TIMEOUT` / `AA_HTTP_DEADLINE`, `AA_BASE_URL`, `AA_LOG_LEVEL`.
  `AA_API_KEY` / `AA_SOURCE` are **dead** — warned about once, then ignored.

## Non-negotiables

- **Never invent or recompute an AA value.** `cost_per_task` is already cache-aware
  (cache read + write + input + reasoning + answer, weighted per eval) — do **not**
  derive it from $/1M rates. `*` after a score = AA estimate; `-` = no data, never zero.
- **Label coverage honestly** — name the surface and the subset behind a number.
- **Never offer an API key as a way to get data.** There is no key path; the server is
  keyless by design and the keyed backend was removed.
- **AA publishes no model-level Coding Index or Agentic Index** (paid data API only).
  Say so, and point at the free constituents ranked by `aa_benchmark_leaderboard`:
  SciCode, Terminal-Bench 4.0, LiveCodeBench, FrontierCode, τ²-Bench / τ³-Banking,
  AutomationBench.
- **Never hardcode chunk or build-id URLs** — AA redeploys often. On a Cloudflare
  challenge or a changed payload, the error names the cache path to overwrite: render
  the URL in a browser, save the HTML there, retry.

## Where the evidence lives

- `eval/runs/round*.md`, `eval/runs/live.ndjson` — agent call logs, token costs, friction.
- `eval/reports/fidelity.md`, `audit_quality.md`, `adversarial.md` — parser fidelity,
  prioritized code review, 44 hostile-usage attacks.
- `docs/process/*` — the audit waves and the coverage / keyless verifications.
- `docs/REFERENCE.md` is **generated** from `src/aa_mcp/reference.py` (the source of
  truth); never edit the markdown alone — regenerate and `--check`.
- `src/aa_mcp/`: `server.py` (tools, resources, prompts, `main()`), `fetch.py`
  (HTTP + cache), `flight.py` (RSC decode), `loaders.py` (parse), `catalog.py`
  (benchmark catalog), `normalize.py` (model records), `select.py` (filter/search),
  `render.py` (markdown), `reference.py` (served reference text).
