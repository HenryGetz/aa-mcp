# aa-mcp reference text

Canonical text served by the `aa_reference` tool and the `aa://reference/*`
resources. Source: artificialanalysis.ai (live, scraped) and its published
methodology + public OpenAPI schema. Coverage counts measured 2026-10-14.

## overview

Live AI benchmark data from artificialanalysis.ai (AA). Two backends, same records:

- `aa:rsc` (default, no key): the site's Next.js RSC flight payloads.
- `aa:api` (requires `AA_API_KEY`): AA's JSON API `/api/v2/language/models/free`.
  Adds the six Capability Indexes plus Coding/Agentic Indexes; 100 req/24 h free tier.

Tool routing:

| Question | Tool |
|---|---|
| smartest / best / cheapest / fastest models now | `aa_leaderboard` |
| best value (intelligence per $/task), budget caps | `aa_leaderboard` `mode=value` |
| Pareto frontier / trade-offs: Intelligence Index vs. Cost per Index Task (default), vs. Output Tokens per Task (`x=out_tokens_per_task`), vs. Cost to Run the AA Intelligence Index (`x=index_total_cost`); also context, params, TTFT, price | `aa_pareto` (`x=`, `score=`) — `aa_leaderboard mode=frontier` is the same code path |
| anything about ONE model (specs, scores, price, license, context, cutoff) | `aa_model` |
| model A vs B (up to 12 models, any benchmark, any metric, reproducible spec) | `aa_compare` (`metrics=all`, `view=diff`, `spec=` YAML) |
| media/speech model A vs B (image/video/voice/music arenas) | `aa_compare` (arena names resolve; pass a board key such as `text_to_speech` to pin an ambiguous name) |
| which things can be ranked, and which one fits a task domain | `aa_benchmarks` (`query=`, `domain=`, `tag=`) — every row shows the exact tool call in `How to query` |
| who leads benchmark X / a model's score on X | `aa_benchmark_leaderboard` |
| which provider serves a model, at what price, precision, TTFT | `aa_providers` |
| provider landscape across models | `aa_providers` (no `model`, use `host`) |
| image / video / TTS / music leaderboards | `aa_media` |
| speech-to-text / realtime voice | `aa_media` (`speech_to_text`, `speech_to_text_streaming`, `speech_to_speech`) |
| AA coding agents / chatbots / search API boards | `aa_agents` |
| unsure of a model's exact name or slug (incl. media/speech) | `aa_search` (resolves language models and arena entries; always resolve names first) |
| definitions, field names, provenance | `aa_reference` |
| raw JSON for anything not covered | `aa_raw` (token-expensive, last resort) |

The three site trade-off views are one code path: `aa_pareto` = Intelligence Index
vs. Cost per Index Task; `aa_pareto x=out_tokens_per_task` = Intelligence Index vs.
Output Tokens per Task; `aa_pareto x=index_total_cost` = Intelligence Index vs. Cost
to Run the AA Intelligence Index (whole suite). `score=` takes any rankable, and
`aa_benchmarks domain=<name>` finds the ones that fit a task.

`aa_benchmarks query=<word>` expands a single word that names a task domain (e.g.
`security`) to that whole domain and flags it `(domain match)` in the header; a
multi-word query stays a tokenised AND search. `aa_compare` fills every metric AA
publishes — including chart-set / homepage-panel scores (the cyber boards, AA-3D,
…), stating the source in the footer — and footers the gaps (a per-model
`missing on requested metrics: <model> <n>` count, plus the per-metric detail
while the gap is small, or "<model> has no published pricing or speed on AA"). The echoed `spec:` reproduces the effective call (view/metrics/compact
included); `compact` selects the core rows for the default metric set and is a
documented no-op when `metrics=` is given.

Trust these, do not re-derive:

- **Cost per task is already cache-aware** (cache read + cache write + input +
  reasoning + answer tokens, weighted by eval). Never recompute it from $/1M rates.
  Use `aa_model` pricing for raw list rates, `cost_per_task` for comparisons.
- **TTFT ≠ throughput.** A model can stream fast (tok/s) yet feel slow (TTFT).
  Snappy UI → `sort=ttft`; bulk generation → `sort=tps`.
- **Reasoning-effort variants are separate rows** (`claude-opus-5-5`,
  `claude-opus-5-5-high`, `-xhigh`). Compare like for like and name the effort.
- `*` after an intelligence score = AA estimate, not measured. `-` = no data
  (never zero).
- **Quantization matters** for open-weights models; the `Precision` column (FP8,
  INT4, BF16, …) comes from the provider endpoint slug.
- **AA does not track** MathVista, DocVQA or BFCL (Berkeley function calling). For
  vision use the `mmmuPro` benchmark plus modality flags; for tool use use the
  `FnCall`/`JSON` endpoint flags. If asked for an untracked benchmark, say AA has no
  data — do not invent scores.
- Freshness: scraped payloads are cached (default 1 h, `AA_CACHE_TTL`); the header
  line shows age and flags `stale`. Pass `refresh=true` for "released today" or
  suspicious data. Cite as "live data from artificialanalysis.ai, <date>".

## indexes

Scraped records (the majority of models):
- **Intelligence Index v4.3.2** (0-100) — composite of 10 evaluations: AA-Briefcase
  v1.1, GDPval-AA v2.1, AutomationBench-AA (partial score), Terminal-Bench 4.0,
  SciCode, AA-LCR v1.1, AA-Omniscience, HLE, GDP.pdf, CritPt. Major versions are not
  comparable; patch versions are not reflected in the reported version.
- **AA-Omniscience** — factual recall minus hallucination across economically
  relevant domains. Range roughly -70..+70 (can be negative). `AA-Omniscience
  Accuracy` and `Hallucination Rate` break it out.
- **Openness Index** (model pages) — availability, transparency, licensing (0-100).
- **AA-Briefcase Elo** — long-horizon knowledge-work benchmark, reported as Elo
  (95% CI via `fields=ci_lower,ci_upper,ci`; private set; not a full public leaderboard).

API-only (require `AA_API_KEY`): **Coding Index**, **Agentic Index**, and the six
Capability Indexes — Finance & Accounting, Strategy & Ops, Legal, Healthcare &
Medical, Engineering, Economics. Members of a capability index are null for models
missing any constituent evaluation.

## benchmarks

Per-benchmark scores held by aa-mcp (label · unit · coverage in the 700 tracked
variants on 2026-10-14 · what it tests):

Leaderboard-wide (full cross-model ranking available):
- GPQA Diamond · % · 616 · 198 graduate-level science questions (PhD experts ~65%).
- Humanity's Last Exam (HLE) · % · 662 · 2,500 expert-written frontier questions.
- SciCode · % · 229 · 288 scientist-curated coding subproblems, 16 disciplines.
- Terminal-Bench 2.1 · % · 241 · 89 agentic terminal tasks.
- Terminal-Bench 4.0 · % · 218 · newer, harder agentic terminal suite.
- Terminal-Bench Hard · % · 432 · hardest subset of the terminal suite.
- τ²-Bench · % · 440 · tool-use agent benchmark (telecom/retail).
- τ³-Banking · % · 209 · fintech support: unstructured KB + multi-step tool calls.
- AA-LCR · % · 573 · long-context reasoning over 10k-100k-token documents.
- IFBench · % · 450 · instruction following on 58 verifiable constraints.
- CritPt · % · 577 · 71 composite research-level physics challenges.
- MMMU-Pro · % · 287 · multimodal academic reasoning, 30 disciplines.
- GDPval-AA (normalized) · % · 291 · real-world occupational tasks, 44 occupations.
- AA-AnalystAgent · % · 47 · spreadsheet/document analysis tasks.
- APEX-Agents-AA · % · 33 · long-horizon cross-application agent tasks.
- ITBench-AA (SRE) · % · 45 · Kubernetes incident root-cause analysis.
- AA-Omniscience · index · 574 · see `indexes`.

Chart-set only (AA exposes these for a curated model list, typically 5-32 models per
eval page — not a full leaderboard; the tool states this):
- LiveCodeBench · % · competitive programming, contamination-free.
- AIME 2025 · % · 30 olympiad math problems.
- HLE Multichoice · % · HLE multiple-choice subset.
- Terminal-Bench-Science · % · science-focused agentic terminal tasks.
- FrontierCode · % · frontier software-engineering tasks.
- MLCR-AA · % · medical long-context multi-document reasoning.
- Harvey LAB-AA · % · 120 real legal work tasks, 24 practice areas.
- AutomationBench-AA · % · agentic SaaS workflows without guardrail violations.
- EnterpriseOps-Gym-AA · % · ServiceNow enterprise stateful workflows.
- GDP.pdf · % · all-pass rate on PDF document tasks.
- GDPval-AA raw Elo · Elo · pairwise preference Elo.
- AA-Briefcase · Elo · see `indexes`.
- AA-3D · Elo · three-dimensional reasoning/design tasks.
- Global-MMLU-Lite, MMLU-Pro, Math-500, When2Call, WildGuardTest · % · knowledge,
  math, tool-calling and safety suites.
- Security boards (homepage, top 20): AA Cyber Index, CWE-Bench-AA,
  DeepSecBench-AA, CyberGym-E2E-AA.

Index membership (v4.3.2) is marked per benchmark in `aa_benchmarks`. The
`Coverage` column is computed live from the source chain the ranking tools use
(700-row leaderboard → rich overlay → eval chart set / homepage panel), so a
benchmark AA fetches live is never labelled "not fetched".

## pricing

USD per 1M tokens: input, output, cache-read (cache hit) and cache-write. `cacheHit
discount` = cache-read discount vs full input price. Blended prices are AA's fixed
input:output:cached ratios (0:3:1, 7:2:1, …).

`cost_per_task` = AA's measured cost to complete one average Intelligence Index task,
cache-aware (186 of 700 variants have it; unscored/deprecated models do not).
Model pages add a full breakdown (input / cache-read / cache-write / reasoning /
answer) plus per-evaluation weighted cost and output tokens per task.

## speed

Measured by AA on the provider in `performanceDataSource` (usually first-party API):
- `tok/s` — median output speed; what matters for bulk generation and coding.
- `TTFT` — median time to first token; what users feel as snappiness.
- `TTFA` — time to first *answer* token (TTFT + reasoning).
- `E2E` — median end-to-end response time for a 500-token answer.
- Reasoning time, output tokens per task (reasoning vs answer) and p05/p95,
  q25/q75 variance bands come with model pages: a model can be inconsistent even
  when its median looks good.

## providers

Per model x provider endpoint: host, precision/quantization tag (from the endpoint
slug — shown only when AA's payload discloses it, which is rare), $/1M
input/output/cache-read, cache discount, cache-hit rate, cost per task,
tok/s, TTFT, E2E, function-calling and JSON-mode support, and context window (the
model-level value when the endpoint does not report one).
The provider board holds 1,201 endpoints across ~453 models and 64 hosts (measured
2026-10-14) with pricing, performance and feature flags, but without precision tags
or per-endpoint cost per task — use the per-model view for those.

## media

Human-preference arenas (Elo + appearance counts; the 95% confidence interval is
available on request with `fields=ci_lower,ci_upper,ci`, not shown by default):
text-to-image,
image-editing, text-to-video, image-to-video, video-editing, text-to-speech
(provider-voice and controlled-voice), music (instrumental, with-vocals). Prices are
$/1k images, $/min and $/1M characters respectively. Speech boards: speech-to-text
(word error rate, lower is better), streaming speech-to-text (WER + time to final
transcript), speech-to-speech realtime voice (STS Index, 0-100, higher is better).
`aa_agents` covers AA's coding-agent, chatbot and search-API boards. Speech board
keys are `speech_to_text`, `speech_to_text_streaming` and `speech_to_speech`
(also accepted as `realtime_voice` / "real-time voice").
`aa_search` and `aa_compare` resolve these media/speech models too: compare two arena entries (pass a board key such as `text_to_speech` as a `queries` entry, or prefix a name with `text_to_speech: `, to pin an ambiguous name) — a footer names the board and warns that scores from different boards are not comparable.

## fields

Field aliases accepted by every `fields=`/`metrics=`/`sort=` parameter (canonical
name first): intelligence (intel), estimated, coding, agentic, omniscience,
omniscience_accuracy, omniscience_non_hallucination, openness, capabilities.<name>,
cost_per_task (alias cost; shown as $/Task), index_total_cost (whole-suite index cost,
`aa_pareto x=index_total_cost`), price_in, price_out, cache_read,
cache_write, cache_hit_discount, blended_*, tps, ttft, ttfa, e2e, reasoning_time,
out_tokens_per_task, time_per_task (mean per-eval time per index task),
context_tokens (ctx), params_b, active_params_b, release_date,
knowledge_cutoff, license, weights_url, is_open_weights (open), is_reasoning,
effort, deprecated, size_class, modalities_in, modalities_out, creator, slug, name
plus every benchmark key listed in `benchmarks` (e.g. gpqa, hle, mmmuPro,
briefcaseElo, terminalBench40). Media arenas also accept `ci_lower`, `ci_upper`
and `ci` (the 95% confidence interval).

## sources

- Site: https://artificialanalysis.ai — `/leaderboards/models` (all variants),
  `/models/<slug>` (rich record + chart set), `/models/<slug>/providers`,
  `/leaderboards/providers`, `/evaluations/<slug>`, `/evaluations` (catalog),
  media/agent leaderboards, homepage (speech + security panels).
- Transport: `RSC: 1` request header returns the Next.js flight payload (JSON-ish,
  ~1.2 MB gzip-transfer for the leaderboard). AA redeploys often; never hardcode
  chunk or build-id URLs.
- JSON API: https://artificialanalysis.ai/api/v2 (`x-api-key`), public schema at
  `/api/v2/openapi`. Free tier covers `language/models/free` + free media endpoints.
- Cache: `~/.cache/aa-mcp` (`AA_CACHE_DIR`), TTL `AA_CACHE_TTL` (default 3600 s),
  API TTL `AA_API_TTL` (default 21600 s). `AA_OFFLINE=1` serves cache only.
- Recovery: if the site answers with a Cloudflare challenge or the payload structure
  changed, the error states the cache path to overwrite — render the URL in a browser
  and save the HTML there, then retry. Offline/stale data is labelled in the header.
