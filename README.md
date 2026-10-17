# aa-mcp

[![ci](https://github.com/HenryGetz/aa-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/HenryGetz/aa-mcp/actions/workflows/ci.yml)

MCP server for [artificialanalysis.ai](https://artificialanalysis.ai) — live AI model
benchmarks, pricing, speed, context/parameter specs, provider endpoints and the
image/video/speech/music arenas. Every benchmark and index AA publishes is covered —
the leaderboard suite, the Decision Models, the Multilingual Index, the on-device
benchmark set and the eval-chart breakdowns — shaped for agents that pay per token.

No API key needed. One keyless data source: the site's Next.js RSC flight payloads,
scraped and cached locally — no quota, no backend selection, no fallback logic.
Every response header shows `aa:rsc`.

| | `aa:rsc` |
|---|---|
| source | the site's Next.js RSC flight payloads |
| needs | nothing |
| carries | ~50 metrics per model incl. 17 cross-model benchmarks, pricing, speed, per-model cost-per-task breakdown, provider endpoints, media boards (incl. the silent video arenas), the full speech/voice boards, the six Capability Indexes, the Decision-Models suite, the Multilingual Index, the on-device/mobile benchmark set and the Search-API metrics |
| quota | none |

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

### Skills and MCP install

The JSON above installs the **MCP server** (callable tools, exposed as
`mcp__aa_<tool>`). A **skill** is a different thing — markdown instructions an agent
reads on demand via `skill://<name>`, installed by copying a directory (or
`npx skills add …`) into a skills root such as `~/.agents/skills/` or
`<repo>/.agents/skills/`; it adds no tools, and omp only notices it after a restart.
This repo ships one at [`skills/aa-mcp/SKILL.md`](skills/aa-mcp/SKILL.md).

Full commands, paths and troubleshooting for both: [`docs/SKILLS.md`](docs/SKILLS.md).

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
| `aa_media` | text-to-image, image-editing, text-to-video, image-to-video (each with its silent/no-audio variant — `text_to_video_silent`, `image_to_video_silent`), video-editing, TTS, music, speech-to-text, realtime voice (`speech_to_speech` == `realtime_voice`); `category=` ranks one of a board's per-category sub-boards |
| `aa_agents` | AA's coding-agent, chatbot and search-API leaderboards (the Search API's BrowseComp / DeepSearchQA / latency / $-per-query metrics are rankable too) |
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
# 5 of 114 scored by value (703 tracked) · value = Intel per $/task, active only · 34m ago · aa:rsc
| Model | Slug | Creator | Intel | $/Task | tok/s | TTFT | Ctx | Intel/$ |
|---|---|---|---|---|---|---|---|---|
| GPT-6 Luna (Low) | gpt-6-luna-low | OpenAI | 21.5 | $0.0045 | 117.9 | 2.2s | 1.0M | 4766.0 |
| GPT-6 Luna (Medium) | gpt-6-luna-medium | OpenAI | 29.9 | $0.02 | - | - | 1.0M | 1712.3 |
| GPT-6 Luna (Non-reasoning) | gpt-6-luna-non-reasoning | OpenAI | 18.5 | $0.01 | 113.0 | 0.9s | 1.0M | 1627.8 |
| Granite 4.2 3B | granite-4-2-3b | IBM | 9.1 | $0.0060 | 219.0 | 0.5s | 131k | 1512.5 |
| Claude Haiku 5.5 (Low) | claude-haiku-5-5-low | Anthropic | 29.5 | $0.02 | 186.5 | 6.3s | 1.0M | 1204.1 |
— 508 rows skipped: no measured cost per task (AA has cost per task for 195/703 variants)
```

## Coverage and limits

Covered: 703 model variants × ~50 leaderboard metrics **merged with** a 703 × 94
dataset (capability indexes, AA-Briefcase/GDPval Elo, AIME, LiveCodeBench, GDP.pdf,
AutomationBench, Harvey LAB, MLCR, cost breakdowns, per-eval costs, licenses, effort
labels); per-model digests with prompt-type speed breakdowns; 1,222 provider endpoints
across 64 hosts with prices, quantization, latency and feature flags; 11 media arenas
(the nine image/video/TTS/music boards plus the two silent video boards) each with
per-category sub-boards; the full speech boards (speech-to-text **36** rows, streaming
**45**, speech-to-speech **27** — plus the agentic/non-agentic slices as their own
rankables) with per-dataset WER, streaming latency, STS components and the TTS
pronunciation/throughput suite; AA's coding-agent, chatbot and search-API boards, with
the Search API's BrowseComp / DeepSearchQA / latency / $-per-query metrics; the
Decision-Models suite, the Multilingual Index (16 languages), the on-device/mobile
benchmark set (7 evals incl. BFCL-500/BFCL-Small) and the eval-chart breakdown
sub-scores; a 223-entry rankable index (136 benchmarks plus indexes, derived metrics,
arenas and views) with descriptions, units, live coverage and the exact tool call for
each.

Counts were measured live on 2026-10-16 and drift as AA adds or retires models.

Deliberately out of scope (and the server says so instead of guessing):

- Benchmarks AA does not track (MathVista, DocVQA) — no data exists. BFCL is tracked
  only on the on-device/mobile set (`mobile.bfcl_500`, `mobile.bfcl_small`), not as a
  server-grade leaderboard.
- Cross-model *signature* leaderboards for benchmarks AA only exposes as a chart
  subset: the tool labels these `not a full leaderboard` and reports real coverage.
- Model-level **Coding Index** and **Agentic Index**: AA publishes these only through
  its paid data API (no public page, route or payload key exists), so the server does
  not provide them — use the constituent benchmarks (SciCode, Terminal-Bench 4.0,
  LiveCodeBench, FrontierCode, τ²-Bench/τ³-Banking, AutomationBench).
- Performance-over-time history and raw per-provider measurements are Commercial-tier
  API features; not implemented.
- Surfaces AA publishes no cross-model ranking for: **HLE Diamond** (model pages only)
  and **MicroEvals** (11,228 user-voted prompt responses, not an AA-run benchmark).
- Image/video/music *model detail* pages (per-family specs beyond arena rows) and the
  laptops/workstations and datacenter hardware pages are not exposed (the mobile
  on-device benchmark set **is** — see below).

## Indexes

Free, keyless and scraped like everything else:

| index | what it is | where it comes from |
|---|---|---|
| Intelligence Index v4.3.2 | composite of 10 evaluations | leaderboard (703 variants) |
| AA-Omniscience | factual recall minus hallucination | leaderboard |
| **six Capability Indexes** — Finance & Accounting, Strategy & Ops, Legal, Healthcare & Medical, Engineering, Economics | weighted composites with published sub-scores (`knowledge`, `reasoning`, `longContext`, `agenticKnowledgeWork`, `agenticToolUse`, `agenticTerminalUse`, `nonHallucination` — the set differs per index) | model pages (`capabilities.<name>`; full coverage ≈222/222/222/82/221/229 of the 703 variants, measured 2026-10-16) plus a curated 26-row (20 for Healthcare & Medical) cross-model page per index |
| Openness Index | availability, transparency, licensing (0-100) | 326-model array on the openness eval page |
| Decision Index / Cyber Index | decision quality / safety composite | eval pages, homepage panels |
| Multilingual Index | average over 16 languages (also per-language) | `/models/multilingual`, 13 chart-selected models |
| AA Coding Agent Index | coding-agent composite (agent × harness, **not** models) | the coding-agents board, 41 rows |

Not available: the **model-level Coding Index and Agentic Index**. AA publishes them
only through its paid data API — no public page, route, chunk string or payload key
exists — so this server does not provide them. The free substitutes are the
constituent benchmarks (SciCode, Terminal-Bench 4.0, LiveCodeBench, FrontierCode,
τ²-Bench/τ³-Banking, AutomationBench), which `aa_benchmark_leaderboard` ranks.

## Benchmark suites

Beyond the classic leaderboard benchmarks, the server reads every published
benchmark AA ships on its own eval pages and chart sets (counts measured
2026-10-16):

- **Decision Models** — `aa_benchmark_leaderboard benchmark=when2call`,
  `wildguardtest`, `hleMultichoice`, `omniscienceDecision` (and
  `omniscienceDecisionNonHallucination`). AA's four Decision-Models eval pages each
  publish a **28-row** array; the four pages share one 28-row score blob with five
  keys (`when2callAccuracy`, `wildguardtestAverageF1`, `hleTextMcqAccuracy`,
  `omniscienceAccuracy`, `omniscienceNonHallucinationRate`), so each model can be
  ranked on all four. Rows include `decisionModel` entries that are not in the
  703-row leaderboard.
- **Multilingual Index** — `aa_leaderboard sort=multilingual` ranks the average;
  `sort=multilingual.<lang>` ranks one of the **16** languages (`ar, bn, de, en, es,
  fr, hi, id, it, ja, ko, pt, sw, yo, zh, my`) on `/models/multilingual` (13
  chart-selected models). The same page carries `globalMmluLite`, which unions with
  the `/evaluations/global-mmlu-lite` page to 17 scored models.
- **On-device / mobile benchmark set** — `aa_benchmark_leaderboard
  benchmark=mobile.<eval>` (`aa_leaderboard sort=mobile.<eval>`) over the **90 rows
  × 7 evals** on `/hardware-inference-stack/mobile-phones`: `mobile.gpqa` (57
  scored), `mobile.ifbench` (55), `mobile.ifstruct` (11), `mobile.math_500` (57),
  `mobile.omniscience` (58), `mobile.bfcl_500` (17) and `mobile.bfcl_small` (57).
  This is where AA publishes **BFCL** — the old "AA does not track BFCL" claim was
  wrong.
- **Silent video arenas** — `aa_media board=text_to_video_silent` (**31** rows) and
  `board=image_to_video_silent` (**82** rows). These are separate boards from the
  audio-capable `text_to_video` (28) / `image_to_video` (23); the silent I2V board is
  the largest of the four.
- **Media category sub-boards** — `aa_media board=<board> category=<slug>` ranks one
  of a board's per-category subsets (e.g. `text_to_image` ships 19, `image_editing`
  17, `text_to_video` 20, `video_editing` 5, `text_to_speech_controlled` 11). Omit
  `category=` for the overall board.
- **Breakdown sub-scores** — `aa_model sections=benchmarks` renders the per-eval
  breakdowns AA publishes on its chart sets (AA-Briefcase rubric pass rate /
  analytical-quality / presentation Elo, Harvey criteria pass, GDP.pdf macro pass,
  AutomationBench strict/completion, GDPval/ITBench/EnterpriseOps average turns,
  AA-3D median turns). The multi-model ones are also rankable sub-metrics:
  the 9 Openness components (`openness.*`), the 6 Omniscience domains
  (`omniscience.domain.*`) and 14 SWE languages (`omniscience.language.*`), the 5
  Terminal-Bench-Science domains and 8 EnterpriseOps-Gym domains.
- **Speech, voice & search** (all rankable through `aa_leaderboard sort=<key>` /
  `aa_benchmark_leaderboard benchmark=<key>`, counts measured 2026-10-16):
  - **Speech-to-text** — `aa_media board=speech_to_text` serves the full
    `/speech-to-text/non-streaming` board (**36** rows, was the 15-row homepage
    panel). Metrics: `sttWerIndex` (36), `sttWordErrorRate` (11),
    `sttEarnings22Wer`, `sttVoxpopuliWer`, `sttAgenttalkWer` (36 each; lower is
    better).
  - **Streaming speech-to-text** — `board=speech_to_text_streaming`, the full
    `/speech-to-text/streaming` board (**45** rows): `sttStreamingWerIndex`,
    `sttStreamingEarnings22Wer`, `sttStreamingAgenttalkWer` (45 each, lower is
    better) plus `sttStreamingTimeToFirstPartial` and `sttStreamingTimeToFinal`
    (seconds, lower is better).
  - **Speech-to-speech** — `board=speech_to_speech` serves the arena's `overall`
    slice (**27** rows; the page's 80 rows are the overall + agentic + non-agentic
    slices). Metrics: `sts` index (19), `stsOverallElo`/`stsAgenticElo`/
    `stsNonAgenticElo` (27/27/26), `stsTaskCompletionRate` (27),
    `stsBigBenchAudio`/`stsTauVoice`/`stsArenaScore`/`stsTaskSuccess` (19 each).
  - **TTS** — `aa_media board=text_to_speech category=<use-case>` ranks AA's
    use-case sub-boards (`assistants` 90, `knowledge-sharing` 97, `entertainment`
    90, `customer-service` 92; inline language boards `en-us` 96, `en-gb` 83).
    Metrics: `ttsQualityElo` (97), `ttsCharactersPerSecond` (79, chars/s),
    `ttsGenerationTime` (79 s, lower is better), and the pronunciation suite
    `ttsPronunciationPassRate` / `ttsTermPronunciation` / `ttsTextNormalization` /
    `ttsSequenceFidelity` / `ttsContextualDisambiguation` (30 each).
  - **Search API** — `aa_agents board=search_api` plus the rankable
    `searchQualityIndex`, `searchBrowsecompAccuracy`, `searchDeepsearchqaF1`,
    `searchOmniscienceAccuracy`, `searchAvgLatency` (s, lower is better),
    `searchCostPerQuery` (USD/query, lower is better), `searchCostPerTask`,
    `searchQueriesPerTask` and `searchQualityLift` (26 scored each, 25 for the
    cost/queries columns).

## Environment

| variable | default | meaning |
|---|---|---|
| `AA_CACHE_DIR` | `~/.cache/aa-mcp` | payload cache |
| `AA_CACHE_TTL` | `3600` | scrape cache TTL (seconds) |
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
  how many of the 703 tracked variants carry a value, and warn when a filter dropped
  rows that simply have no measurement.
- **Cost per task is cache-aware** and must not be recomputed from $/1M rates; raw
  rates are separate fields.
- Effort variants (`-low` … `-xhigh`) are separate rows — always name the effort.
- **Replies are bounded and cells are neutralized.** Scraped text is sanitized
  (markdown metacharacters escaped, 120 chars per cell) and any reply is capped at
  200 kB, so one hostile page cannot blow up your context; oversized tables say how
  many rows were kept.
- **Speech/arena board rows are their own namespace.** A TTS voice or an ASR host
  is not a language model: those rows publish no Intelligence-Index cost or speed,
  so `aa_pareto score=<board key>` reports that no frontier can be drawn and names
  the board's row count. `aa_search` resolves board entries (tagged `aa:arena` with
  their board) and `aa_compare` compares board rows within one board — the board's
  own columns and its sub-metrics (`metrics=stsOverallElo`) both work, and the
  footer says the rows are not language models.
- **Hostile arguments are rejected up front**, not passed to a fetch or a cache
  path: control characters / lone surrogates, over-long strings (>256 chars, 2000
  for `fields`) and non-finite numbers (`NaN`/`Infinity`) return a `ValueError`
  naming the argument, and error text never echoes more than 60 chars of your input.
- AA does not track MathVista or DocVQA; BFCL is tracked only on the on-device/mobile
  set (`mobile.bfcl_500`, `mobile.bfcl_small`). The server says so instead of inventing.

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
