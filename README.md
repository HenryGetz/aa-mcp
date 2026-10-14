# aa-mcp

[![ci](https://github.com/HenryGetz/aa-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/HenryGetz/aa-mcp/actions/workflows/ci.yml)

MCP server for [artificialanalysis.ai](https://artificialanalysis.ai) — live AI model
benchmarks, pricing, speed, context/parameter specs, provider endpoints and the
image/video/speech/music arenas — shaped for agents that pay per token.

No API key needed. Two interchangeable data backends, same records out:

| | `aa:rsc` (default) | `aa:api` (optional) |
|---|---|---|
| source | the site's Next.js RSC payloads | `GET /api/v2/language/models/free` |
| needs | nothing | `AA_API_KEY` (free tier is enough) |
| adds | ~50 metrics per model incl. 17 cross-model benchmarks, pricing, speed, per-model cost-per-task breakdown, provider endpoints, media boards | six Capability Indexes + Coding/Agentic indexes (not in the scrape) |
| quota | none | 100 req/24 h → cached 6 h by default |

If a key is present the API is tried first and the server falls back to scraping on
401/403 rather than failing. Every response header shows which backend answered.

## Install

One line, no clone (uv fetches and runs it for you):

```bash
uvx --from git+https://github.com/HenryGetz/aa-mcp aa-mcp
```

Or install the `aa-mcp` executable once:

```bash
uv tool install --from git+https://github.com/HenryGetz/aa-mcp aa-mcp   # -> ~/.local/bin/aa-mcp
```

Local checkout / development:

```bash
git clone <this repo> && cd aa-mcp
uv sync                      # creates .venv with the mcp SDK
uv run aa-mcp                # serve on stdio
```

Register with an MCP client (omp, Claude Code, Codex, …):

```json
{
  "mcpServers": {
    "aa": {
      "type": "stdio",
      "command": "/home/USER/.local/bin/aa-mcp",
      "timeout": 120000
    }
  }
}
```

## Tools

| tool | answers |
|---|---|
| `aa_leaderboard` | smartest / best / cheapest / fastest models, best value (`mode=value`), Pareto frontier (`mode=frontier`, delegates to `aa_pareto`), budget and capability filters |
| `aa_model` | everything AA knows about one model: indices, benchmark scores, pricing incl. cache, speed, cost-per-task breakdown, license, modalities, cutoff |
| `aa_pareto` | the trade-off frontier for any score vs any x-axis (cost per task, whole-index cost, output tokens, time, context, params, TTFT, in/out price) with the knee — no per-benchmark tool needed |
| `aa_compare` | 2-12 models side by side on the metrics you care about (`metrics=all`/`benchmarks`/list, `view=diff` for deltas, `spec=` for a reproducible YAML/JSON round-trip) |
| `aa_benchmarks` | the search index over everything rankable (benchmarks, indexes, derived metrics, arenas): what it measures, its unit, live coverage and the exact `How to query` call; filter with `query=`/`domain=`/`tag=` |
| `aa_benchmark_leaderboard` | who leads a given benchmark (full leaderboard when AA publishes one, otherwise AA's chart set — stated in the header; lower-is-better metrics rank lowest-first) |
| `aa_providers` | which provider serves a model, at what price, quantization, TTFT and feature support; or the whole provider × model board |
| `aa_media` | text-to-image, image-editing, text-to-video, image-to-video, video-editing, TTS, music, speech-to-text, realtime voice (`speech_to_speech` == `realtime_voice`) |
| `aa_agents` | AA's coding-agent, chatbot and search-API leaderboards |
| `aa_search` | resolve a fuzzy model name to real names + slugs (use it before guessing) |
| `aa_reference` | metric definitions, index composition, field names, provenance |
| `aa_raw` | raw JSON escape hatch for anything the tables do not cover |

Resources (15): `aa://reference/metrics` (full definitions), one per topic
(`overview`, `indexes`, `benchmarks`, `pricing`, `speed`, `providers`, `media`,
`fields`, `sources`), `aa://benchmarks` (registry JSON), `aa://rankables` and
`aa://rankables.yaml` (every rankable thing, for building your own queries),
`aa://comparisons/spec` (a `aa_compare spec=` template) and `aa://sources`.
Prompts: `best_model_for_task`, `compare_models`.

### Comparing models

Everything AA's own comparison pages do, without the pages:

```bash
# same models as artificialanalysis.ai/models/comparisons?compare=a,b,c,d
aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"]}'

# every benchmark AA has for those models, with deltas vs the best
aa_compare '{"queries":[...],"metrics":"all","view":"diff"}'

# reproducible / reusable comparison (YAML or JSON); the output echoes the spec back
aa_compare '{"spec":"models: [mimo-v2-6-pro, kimi-k3]\nmetrics: [intelligence, cost_per_task, gpqa, terminalBench40]\nview: diff"}'
```

Trade-off questions always have one call:

```bash
aa_pareto '{}'                             # Intelligence vs $/task frontier + knee
aa_pareto '{"x":"index_total_cost"}'       # vs cost of the whole index run
aa_pareto '{"x":"out_tokens_per_task"}'    # vs verbosity
aa_pareto '{"score":"cyberIndex","x":"cost_per_task"}'
```

Finding the right benchmark for a domain, without knowing its name:

```bash
aa_benchmarks '{"domain":"security"}'   # -> CWE-Bench, CyberGym, Cyber Index, …
aa_benchmarks '{"query":"speech"}'      # -> STT/TTS/STS boards + the exact call to make
```

### Token discipline

- Tables, not JSON — rounded values, one header line, no argument echo.
- Default 10-15 rows; every table tool accepts `top` and `fields`.
- Long-form documentation lives in resources/reference, so it never costs context
  unless the agent asks for it.
- `aa_raw` warns when used.

Measured live (12-call panel, one call per tool): **≈3.3k tokens total, ≈277 per
call**, e.g. a 5-row leaderboard is ~180 tokens, a full model digest ~470, a media
board ~160, the `aa_benchmarks` search index ~235, `aa_reference topic=overview`
~915 (the one call that is deliberately long-form).

Example — `aa_leaderboard {"mode":"value","top":5}` (verbatim):

```text
# 5 of 109 scored by value (700 tracked) · value = Intel per $/task, active only · stale: 23m ago · aa:rsc
| Model | Slug | Creator | Intel | $/Task | tok/s | TTFT | Ctx | Intel/$ |
|---|---|---|---|---|---|---|---|---|
| GPT-6 Luna (Low) | gpt-6-luna-low | OpenAI | 21.5 | $0.0045 | 121.9 | 2.6s | 1.0M | 4766.0 |
| GPT-6 Luna (Medium) | gpt-6-luna-medium | OpenAI | 29.9 | $0.02 | - | - | 1.0M | 1712.3 |
| GPT-6 Luna (Non-reasoning) | gpt-6-luna-non-reasoning | OpenAI | 18.5 | $0.01 | 112.3 | 0.9s | 1.0M | 1627.8 |
| Granite 4.2 3B | granite-4-2-3b | IBM | 9.1 | $0.0060 | 215.4 | 0.5s | 131k | 1513.0 |
| Claude Haiku 5.5 (Low) | claude-haiku-5-5-low | Anthropic | 29.5 | $0.02 | 170.0 | 9.2s | 1.0M | 1204.1 |
— 514 rows skipped: no measured cost per task (AA has cost per task for 186/700 variants)
```

## Coverage and limits

Covered: 700 model variants × ~50 leaderboard metrics **merged with** a 700 × 94
dataset (capability indexes, AA-Briefcase/GDPval Elo, AIME, LiveCodeBench, GDP.pdf,
AutomationBench, Harvey LAB, MLCR, cost breakdowns, per-eval costs, licenses, effort
labels); per-model digests with prompt-type speed breakdowns; 1,201 provider endpoints
across 64 hosts with prices, quantization, latency and feature flags; 9 media arenas
plus speech-to-text / streaming / realtime voice; AA's coding-agent, chatbot and
search-API boards; a 95-entry rankable index (67 cross-model benchmarks plus
indexes, derived cost/speed metrics and arenas) with descriptions, units, live
coverage and the exact tool call for each.

Deliberately out of scope (and the server says so instead of guessing):

- Benchmarks AA does not track (MathVista, DocVQA, BFCL) — no data exists.
- Cross-model *signature* leaderboards for benchmarks AA only exposes as a chart
  subset: the tool labels these `not a full leaderboard` and reports real coverage.
- Coding/Agentic indexes need the JSON API (`AA_API_KEY`).
- Performance-over-time history and raw per-provider measurements are Commercial-tier
  API features; not implemented.
- Image/video/music *model detail* pages (per-family specs beyond arena rows) and
  hardware/inference-stack pages are not exposed.

## Environment

| variable | default | meaning |
|---|---|---|
| `AA_API_KEY` | unset | AA JSON API key; enables the `aa:api` backend |
| `AA_SOURCE` | `auto` | `auto` \| `api` \| `rsc` — backend selection |
| `AA_CACHE_DIR` | `~/.cache/aa-mcp` | payload cache |
| `AA_CACHE_TTL` | `3600` | scrape cache TTL (seconds) |
| `AA_API_TTL` | `21600` | API cache TTL (seconds) |
| `AA_RICH_TTL` | `21600` | rich-dataset (model-page overlay) cache TTL |
| `AA_MAX_BYTES` | `50331648` | decoded-body cap (gzip-bomb guard) |
| `AA_HTTP_TIMEOUT` | `30` | per-attempt HTTP timeout (seconds) |
| `AA_HTTP_DEADLINE` | `45` | total budget for one fetch (seconds) |
| `AA_OFFLINE` | unset | `1` — serve from cache only, never touch the network |
| `AA_BASE_URL` | `https://artificialanalysis.ai` | override host (tests/mirrors) |
| `AA_LOG_LEVEL` | `WARNING` | stderr log level |

## Behaviour worth knowing

- **Freshness is labelled.** Payloads are cached for an hour; the header shows the
  age and says `stale` when a network failure forced a cached copy. Pass
  `refresh=true` for freshly released models.
- **Coverage is labelled.** AA scores a benchmark on a subset of models; tables state
  how many of the 700 tracked variants carry a value, and warn when a filter dropped
  rows that simply have no measurement.
- **Cost per task is cache-aware** and must not be recomputed from $/1M rates; raw
  rates are separate fields.
- Effort variants (`-low` … `-xhigh`) are separate rows — always name the effort.
- **Replies are bounded and cells are neutralized.** Scraped text is sanitized
  (markdown metacharacters escaped, 120 chars per cell) and any reply is capped at
  200 kB, so one hostile page cannot blow up your context; oversized tables say how
  many rows were kept.
- **Hostile arguments are rejected up front**, not passed to a fetch or a cache
  path: control characters / lone surrogates, over-long strings (>256 chars, 2000
  for `fields`) and non-finite numbers (`NaN`/`Infinity`) return a `ValueError`
  naming the argument, and error text never echoes more than 60 chars of your input.
- AA does not track MathVista, DocVQA or BFCL; the server says so instead of inventing.

## Troubleshooting

- **Cloudflare / bot challenge** (403/503 or a tiny body): the error names the exact
  cache path. Render the URL in a browser, save the HTML there, re-run — or set
  `AA_OFFLINE=1` to keep working from the last good capture.
- **Site structure change**: the error says which array was missing; the parsers live
  in `src/aa_mcp/loaders.py` (`flight.py` finds the arrays).
- **AA redeploys often** — never hardcode chunk or build-id URLs; the client always
  re-parses freshly fetched payloads.
- **Cache size**: payloads are stored verbatim (a rich model page is ~3 MB, so the
  cache settles around 50-120 MB). Clear it with
  `python -c "from aa_mcp.fetch import clear_cache; print(clear_cache())"` — worst
  case the next call refetches.

## Development

```bash
uv run pytest -q                 # offline: fixtures in tests/fixtures (real payloads)
uvx ruff check .                 # lint (CI runs this)
.venv/bin/python eval/client.py tools
.venv/bin/python eval/client.py call aa_leaderboard '{"top":5}'
.venv/bin/python eval/client.py bench                 # per-call chars/tokens report
.venv/bin/python scripts/surface_sweep.py             # every tool × every documented enum, live
.venv/bin/python scripts/gen_reference_md.py --check  # docs/REFERENCE.md in sync
```

`scripts/surface_sweep.py` is the end-to-end guard: it drives the real stdio server
through ~220 calls covering every tool, board, sort key, axis, section, topic and raw
kind, and fails if anything errors unexpectedly (it is how the speech-board `NameError`
was caught).

`docs/REFERENCE.md` is generated from `src/aa_mcp/reference.py`
(`scripts/gen_reference_md.py`); `docs/INTERFACES.md` documents the internal data
model. `eval/` holds the evaluation harness and every audit report: the independent
field-by-field parser audit (`eval/reports/fidelity.md`), the code review
(`eval/reports/audit_quality.md`), the adversarial attack report
(`eval/reports/adversarial.md`) and five rounds of agent usage reports
(`eval/runs/round*.md`).
