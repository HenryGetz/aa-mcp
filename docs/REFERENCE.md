# aa-mcp reference text

Canonical text served by the `aa_reference` tool and the `aa://reference/*`
resources. Source: artificialanalysis.ai (live, scraped) and its published
methodology. Coverage counts measured 2026-10-16 and drift as AA adds or retires
models.

## overview

Live AI benchmark data from artificialanalysis.ai (AA). One keyless source: the site's Next.js RSC flight payloads (no API key, no quota).

Tool routing:

| Question | Tool |
|---|---|
| smartest / best / cheapest / fastest models now | `aa_leaderboard` |
| best value (intelligence per $/task), budget caps | `aa_leaderboard` `mode=value` (also `sort=value` / `sort=intel_per_cost` / `sort=intel/$`) |
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
| the six Capability Indexes (Finance & Accounting, Strategy & Ops, Legal, Healthcare & Medical, Engineering, Economics) — one model's score + sub-scores, or a cross-model ranking | `aa_model` (per model); `aa_benchmarks query=capabilities` prints the exact ranking call |
| the AA Coding Agent Index (agent x harness rows, not models) | `aa_agents board=coding_agents` |
| unsure of a model's exact name or slug (incl. media/speech) | `aa_search` (resolves language models and arena entries; when no model matches but the query names a benchmark/metric/board it answers with that thing's hint; always resolve names first) |
| the Decision-Models suite (When2Call, WildGuardTest, HLE-MultiChoice, AA-Omniscience-Decision — 28 scored models each) | `aa_benchmark_leaderboard benchmark=when2call` / `wildguardtest` / `hleMultichoice` / `omniscienceDecision` |
| the Multilingual Index and its 16 per-language scores | `aa_leaderboard sort=multilingual` (also `sort=multilingual.<lang>`) |
| the on-device / mobile benchmark set (7 evals incl. BFCL-500 / BFCL-Small) | `aa_benchmark_leaderboard benchmark=mobile.<eval>` (`aa_leaderboard sort=mobile.<eval>`) |
| the silent (no-audio) video arenas, or a media board's per-category sub-board | `aa_media board=text_to_video_silent` / `board=image_to_video_silent`; `aa_media board=<board> category=<slug>` |
| a benchmark's breakdown sub-scores (rankable ones too) | `aa_model sections=benchmarks`; `aa_leaderboard sort=<key>` (e.g. `openness.modelAvailability`, `omniscience.domain.law`) |
| the full speech boards (speech-to-text 36 rows, streaming 45, speech-to-speech 27) and their per-dataset WER / streaming latency / STS components | `aa_media board=speech_to_text` / `board=speech_to_text_streaming` / `board=speech_to_speech`; rank a column with `aa_leaderboard sort=sttWerIndex` / `sttStreamingTimeToFinal` / `stsBigBenchAudio` |
| TTS use-case sub-boards | `aa_media board=text_to_speech category=assistants` (also `knowledge-sharing`, `entertainment`, `customer-service`, `en-us`, `en-gb`) |
| the Search API Index and its BrowseComp / DeepSearchQA / latency / cost metrics | `aa_agents board=search_api`; `aa_leaderboard sort=searchQualityIndex` (also `searchBrowsecompAccuracy`, `searchAvgLatency`, `searchCostPerQuery`) |
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
included); `compact` selects the core rows for the default metric set, and with
`metrics=` it omits the Slug row and any all-null row (`compact=false` includes
them). The default metric set is a subset (13 rows); its footer says so and
points at `metrics=all` for every published row. `metrics=all` carries every
rankable row the models have — including the derived `Intel/$` (and `score/$` for the
other score axes), which the default view shows and `all` used to omit.

One metric never means two numbers, and a correction is never silent:

- The dual-sourced speed/latency metrics (`tps`, `ttft`, `ttfa`, `e2e`) resolve to
  the **first-party model page** in `aa_compare` whatever alias you type, with a
  footnote naming the leaderboard snapshot value when the two differ by >2%
  (`— TTFT: model page 661.2s vs leaderboard snapshot 679.2s for <model> (using the
  model page)`). See topic `speed`.
- A query that is not the exact slug/name says how it resolved (`— matched
  'opus max' → claude-opus-5-5 (exact slug for that name)`), and a bare family slug
  says which reasoning-effort variant it is plus its siblings (`— matched the Max
  variant of gpt-6-luna; siblings: gpt-6-luna-xhigh, -high, -medium, -low,
  -non-reasoning`).
- Ranked tables order rows that *display* the same value by a named secondary key
  and say so: `— 2 models tie at $0.13/task; ordered by intelligence (46.3 vs
  42.1)`.
- A task word AA publishes no benchmark for is answered with its closest measures:
  `AA does not measure classification; closest AA measures are IFBench …`
  (`aa_search`, `aa_benchmarks`).
- A cost or price that renders `$0.00` is explained (`— $0.00 = measured under
  $0.005/task …`) instead of standing as a bare zero that wins every "cheapest"
  ranking.
- Identity fields always resolve in `fields=` (topic `fields`), and a list-valued
  `metrics=`/`fields=` renders what resolves plus one footnote for the rest.

`aa_leaderboard sort=<key>` is the uniform ranking path: it ranks any key with
per-model values on any surface it can reach — the 703-row leaderboard, the rich
overlay, or an eval chart set / homepage panel (joined by slug) — so a
chart/panel-backed index (the AA Cyber Index, its refusal-rate and
mitigation-status companions, the cyber boards, AA-3D, MMLU-Pro, …) ranks exactly
like `intelligence`, with `mode=value`/`mode=frontier`/`fields=` too. The header
states the real coverage (`n of m scored`, `703 tracked`) and the source, and the
footnote names the surface joined; a key AA has no cross-model values for returns
an explanatory error, never a bare failure.

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
- **AA does not track** MathVista or DocVQA. **BFCL** (Berkeley function calling) is
  published only through the on-device/mobile set (`mobile.bfcl_500`,
  `mobile.bfcl_small`) — there is no server-grade BFCL leaderboard. For vision use the
  `mmmuPro` benchmark plus modality flags; for tool use use the `τ²-Bench` /
  `τ³-Banking` benchmarks and the `FnCall`/`JSON` endpoint flags. If asked for an
  untracked benchmark, say AA has no data — do not invent scores.
- **Speech/arena board rows are their own namespace.** A TTS voice or an ASR host is
  not a language model: those rows publish no Intelligence-Index cost or speed, so
  `aa_pareto score=<board key>` reports that no frontier can be drawn and names the
  board's row count. `aa_search` resolves board entries (tagged `aa:arena` with their
  board) and `aa_compare` compares board rows within one board, accepting both the
  board's own columns and the board sub-metrics (e.g. `metrics=stsOverallElo`); its
  footer says the rows are not language models.
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
- **Openness Index** — availability, transparency, licensing (0-100); a full
  326-model array on `/evaluations/artificial-analysis-openness-index`.
- **Decision Index** — AA's decision-quality composite; its own eval page
  (`/evaluations/artificial-analysis-decision-index`) carries a 28-row `indexScore`
  array that also holds the four Decision-Models scores (see topic `benchmarks`).
- **Multilingual Index** — average over 16 languages (`ar, bn, de, en, es, fr, hi,
  id, it, ja, ko, pt, sw, yo, zh, my`) for 13 chart-selected models on
  `/models/multilingual` (`multilingual.average` plus `multilingual.<lang>`); the
  same page carries the 13-row `globalMmluLite` split. AA's OpenAPI calls it
  `artificial_analysis_multilingual_index`.
- **Cyber Index** — safety composite, with refusal-rate and mitigation-status
  companions (eval page / homepage panel).
- **Capability Indexes** (six, all free) — Finance & Accounting, Strategy & Ops,
  Legal, Healthcare & Medical, Engineering, Economics. Each is a weighted composite
  with published sub-scores drawn from `knowledge`, `reasoning`, `longContext`,
  `agenticKnowledgeWork`, `agenticToolUse`, `agenticTerminalUse` and
  `nonHallucination` (the exact set differs per index). Every model page carries the
  six values under `capabilities.<name>`; each index also has a public cross-model
  page at `/models/capabilities/<index>` (index = `finance-and-accounting`,
  `strategy-and-ops`, `legal`, `healthcare-and-medical`, `engineering`, `economics`)
  with `weightedIndex`/`headlineValue` for a curated subset — 26 models each, 20 for
  Healthcare & Medical. Full coverage comes from the rich model-page array:
  ≈222/222/222/82/221/229 of the 703 variants (measured 2026-10-16; AA drifts). A
  member is null for a model missing any constituent evaluation.
- **AA Speech-to-Speech Index** (`sts`, 0-100) — a speech index over the STS arena's
  `overall` slice (19 scored), with components `stsBigBenchAudio`, `stsTauVoice`,
  `stsArenaScore` and `stsTaskSuccess`; the same arena also ranks `stsOverallElo` /
  `stsAgenticElo` / `stsNonAgenticElo` and `stsTaskCompletionRate`.
- **AA Coding Agent Index** (agent-level, not model-level) — 41 agent x harness rows
  on `/agents/coding-agents`, `indexScore` as a 0-1 fraction (x100 for display).
- **AA-Briefcase Elo** — long-horizon knowledge-work benchmark, reported as Elo
  (95% CI via `fields=ci_lower,ci_upper,ci`; private set; not a full public leaderboard).

AA does not publish model-level **Coding Index** or **Agentic Index** values on any
public page — no route, payload key or sitemap entry exists for them (they are
exposed only through AA's paid data API), so this server does not provide them. The
free substitutes are the constituent benchmarks: SciCode, Terminal-Bench 4.0,
LiveCodeBench, FrontierCode, tau2-Bench / tau3-Banking and AutomationBench, which
`aa_benchmark_leaderboard` ranks. Use those for a coding/agentic comparison.

## benchmarks

Per-benchmark scores held by aa-mcp (label · unit · coverage in the 703 tracked
variants on 2026-10-16 · what it tests):

Leaderboard-wide (full cross-model ranking available):
- GPQA Diamond · % · 617 · 198 graduate-level science questions (PhD experts ~65%).
- Humanity's Last Exam (HLE) · % · 665 · 2,500 expert-written frontier questions.
- SciCode · % · 232 · 288 scientist-curated coding subproblems, 16 disciplines.
- Terminal-Bench 2.1 · % · 242 · 89 agentic terminal tasks.
- Terminal-Bench 4.0 · % · 221 · newer, harder agentic terminal suite.
- Terminal-Bench Hard · % · 432 · hardest subset of the terminal suite.
- τ²-Bench · % · 440 · tool-use agent benchmark (telecom/retail).
- τ³-Banking · % · 209 · fintech support: unstructured KB + multi-step tool calls.
- AA-LCR · % · 576 · long-context reasoning over 10k-100k-token documents.
- IFBench · % · 450 · instruction following on 58 verifiable constraints.
- CritPt · % · 580 · 71 composite research-level physics challenges.
- MMMU-Pro · % · 288 · multimodal academic reasoning, 30 disciplines.
- GDPval-AA (normalized) · % · 295 · real-world occupational tasks, 44 occupations.
- AA-AnalystAgent · % · 49 · spreadsheet/document analysis tasks.
- APEX-Agents-AA · % · 33 · long-horizon cross-application agent tasks.
- ITBench-AA (SRE) · % · 45 · Kubernetes incident root-cause analysis.
- AA-Omniscience · index · 577 · see `indexes`.

Chart-set / homepage-panel (AA exposes these for a curated model list, typically
5-32 models per eval page — a subset, not a full leaderboard; `aa_leaderboard
sort=<key>` joins them by slug and the header/footnote state the real coverage):
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
- Global-MMLU-Lite · % · 17 (union of its 5-row eval page and the 13-row
  `/models/multilingual` page) · multilingual knowledge; also split per language.
- MMLU-Pro, Math-500 · % · knowledge and math suites (only ~1 active model each —
  the rest are deprecated).

Decision Models (AA's `/evaluations/{aa-omniscience-decision,hle-multichoice,when2call,wildguardtest}`
— each a **28-row** array whose four pages share one 28-row score blob with five
keys, so every model ranks on all four):
- When2Call · % · 28 · does the model call a tool when it should?
- WildGuardTest · % · 28 · safety, average F1 over the WildGuardTest suite.
- HLE-MultiChoice · % · 28 · HLE multiple-choice subset (`hleMultichoice`).
- AA-Omniscience-Decision · % · 28 · decision-mode factual recall
  (`omniscienceDecision`); `omniscienceDecisionNonHallucination` is its
  hallucination counterpart.

Multilingual (AA's OpenAPI `artificial_analysis_multilingual_index`):
- Artificial Analysis Multilingual Index · % · 13 · average over 16 languages
  (`multilingual`); per-language keys `multilingual.ar|bn|de|en|es|fr|hi|id|it|ja|ko|pt|sw|yo|zh|my`
  on `/models/multilingual`.

On-device / mobile set (`/hardware-inference-stack/mobile-phones`, **90 rows x 7
evals** — the same evaluations run on-device with quantised weights and bounded
context; this is where AA publishes **BFCL**, so "AA does not track BFCL" is
wrong):
- `mobile.gpqa` 57 · `mobile.ifbench` 55 · `mobile.ifstruct` 11 · `mobile.math_500`
  57 · `mobile.omniscience` 58 · `mobile.bfcl_500` 17 · `mobile.bfcl_small` 57 ·
  all % of the 90 on-device rows.
- Security boards (homepage, top 20): AA Cyber Index (`cyberIndex`) with its
  companions Cyber Refusal (`cyberRefusalRate`, lower is better) and Cyber
  Mitigation (`cyberMitigationStatus`, standard/unmitigated), plus CWE-Bench-AA,
  DeepSecBench-AA and CyberGym-E2E-AA (each with its own refusal-rate key).

Speech / voice / search (chart-set; the three speech boards serve the **full**
published board, not the homepage panel):
- Speech-to-text (`/speech-to-text/non-streaming`, board `speech_to_text`, 36 rows):
  `sttWerIndex` 36, `sttWordErrorRate` 11, `sttEarnings22Wer` / `sttVoxpopuliWer` /
  `sttAgenttalkWer` 36 each (all %, lower is better).
- Streaming speech-to-text (`/speech-to-text/streaming`, board
  `speech_to_text_streaming`, 45 rows): `sttStreamingWerIndex`,
  `sttStreamingEarnings22Wer`, `sttStreamingAgenttalkWer` (45 each, lower is
  better), `sttStreamingTimeToFirstPartial` / `sttStreamingTimeToFinal` (s, lower is
  better).
- Speech-to-speech (`/speech-to-speech/arena`, board `speech_to_speech`, the
  `overall` slice — 27 rows; the page's 80 rows are overall + agentic + non-agentic):
  `sts` index 19, `stsOverallElo` 27, `stsAgenticElo` 27, `stsNonAgenticElo` 26,
  `stsTaskCompletionRate` 27, `stsBigBenchAudio` / `stsTauVoice` / `stsArenaScore` /
  `stsTaskSuccess` 19 each.
- TTS (`/text-to-speech/models`, chart-set slug `tts`): `ttsQualityElo` 97,
  `ttsCharactersPerSecond` 79 (chars/s), `ttsGenerationTime` 79 (s, lower is
  better), and the pronunciation suite `ttsPronunciationPassRate` /
  `ttsTermPronunciation` / `ttsTextNormalization` / `ttsSequenceFidelity` /
  `ttsContextualDisambiguation` (30 each). Use-case sub-boards:
  `aa_media board=text_to_speech category=<assistants|knowledge-sharing|entertainment|customer-service>`,
  plus the language boards `en-us` / `en-gb`.
- Search API (`/agents/search-api`, chart-set slug `search-api`; `aa_agents
  board=search_api`): `searchQualityIndex`, `searchBrowsecompAccuracy`,
  `searchDeepsearchqaF1`, `searchOmniscienceAccuracy`, `searchQualityLift` (26 each),
  `searchCostPerTask` 26, `searchQueriesPerTask` 25 (index),
  `searchAvgLatency` 26 (s, lower is better), `searchCostPerQuery` 25 (USD/query,
  lower is better).

Breakdown sub-scores (AA ships these on its chart sets; `aa_model
sections=benchmarks` renders them, and the multi-model ones are rankable
sub-metrics via `aa_leaderboard sort=<key>`):
- AA-Briefcase: `briefcaseRubricPassRate`, `briefcaseAnalyticalQualityElo`,
  `briefcasePresentationElo`.
- Harvey LAB: `harveyCriteriaPass`, `harveyGatedAllPass`; GDP.pdf:
  `gdpPdfMacroPassRate`; AutomationBench: `automationBenchStrictScore`,
  `automationBenchCompletion`.
- Turn / efficiency: `gdpvalAvgTurns`, `itbenchAvgTurnsPerTask`,
  `enterpriseOpsGymAvgTurns`, `aa3dTurnsP50`, `medianCanonicalAnswerOutputSpeed`.
- Openness components (9): `openness.modelAvailability`, `openness.modelTransparency`,
  `openness.transparencyPreTrainingData`, `openness.transparencyPostTrainingData`,
  `openness.transparencyMethodology`, `openness.dataPretrainAccess`,
  `openness.dataPretrainLicense`, `openness.dataPosttrainAccess`,
  `openness.dataPosttrainLicense`.
- Omniscience domains (6): `omniscience.domain.<business|health|humanitiesAndSocialSciences|law|scienceAndEngineering|softwareEngineering>`;
  SWE languages (14): `omniscience.language.<c|r|go|php|dart|html|java|rust|julia|swift|kotlin|python|javascript|typescript>`.
- Terminal-Bench-Science domains (5): `terminalBenchScience.domain.<life-sciences|physical-sciences|mathematical-sciences|engineering-sciences|earth-sciences>`.
- EnterpriseOps-Gym domains (8): `enterpriseOpsGym.domain.<csm|hr|itsm|email|calendar|teams|drive|hybrid>`.

Index membership (v4.3.2) is marked per benchmark in `aa_benchmarks`. The
`Coverage` column is computed live from the source chain the ranking tools use
(703-row leaderboard → rich overlay → eval chart set / homepage panel), so a
benchmark AA fetches live is never labelled "not fetched" — and
`aa_leaderboard sort=<key>` ranks that same chain, stating the real coverage
(`n of m scored`, `703 tracked`) and the surface it joined.

A task word AA publishes no benchmark for is never a dead end. `aa_benchmarks
query=<word>` and `aa_search` answer with the closest AA measures — "AA does not
measure <task>; closest AA measures are …" — for classification, summarization,
translation, retrieval/RAG, SQL/data analysis, tool calling, moderation and OCR
(e.g. classification → IFBench / MMLU-Pro, tool calling → τ²-Bench / τ³-Banking plus
the provider FnCall/JSON flags). Never invent a score for a task AA does not measure.

## pricing

USD per 1M tokens: input, output, cache-read (cache hit) and cache-write. `cacheHit
discount` = cache-read discount vs full input price. Blended prices are AA's fixed
input:output:cached ratios (0:3:1, 7:2:1, …).

`cost_per_task` = AA's measured cost to complete one average Intelligence Index task,
cache-aware (~195 of 703 variants have it, measured 2026-10-16; unscored/deprecated
models do not).
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

AA publishes `tok/s`, `TTFT`, `TTFA` and `E2E` on **two** surfaces: the 703-row
leaderboard snapshot (`medianOutputTokensPerSecond`, `medianTimeToFirstTokenSeconds`,
…) and the first-party model page (`timescaleData.medianOutputSpeed` /
`medianTimeToFirstChunk`, `timeToFirstAnswerToken.total`, `endToEndResponseTime.total`).
They are genuinely different measurements (for claude-opus-5-5 the leaderboard
snapshot TTFT is 679.2 s, the model-page long-prompt median 661.2 s).
`aa_compare` always reports the **model page** value — the same number whichever
alias you type (`ttft` or `time_to_first_token`) — and adds one footnote naming both
numbers when they differ by more than 2%. `aa_leaderboard`/`aa_pareto` report the
leaderboard snapshot and say so in their footer. `aa_model` shows the model page and
breaks TTFT out by prompt type (short/medium/long/100k).

## providers

Per model x provider endpoint: host, precision/quantization tag (from the endpoint
slug — shown only when AA's payload discloses it, which is rare), $/1M
input/output/cache-read, cache discount, cache-hit rate, cost per task,
tok/s, TTFT, E2E, function-calling and JSON-mode support, and context window (the
model-level value when the endpoint does not report one).
The provider board holds 1,222 endpoints across ~455 models and 64 hosts (measured
2026-10-16) with pricing, performance and feature flags, but without precision tags
or per-endpoint cost per task — use the per-model view for those. The table always
shows the column it is sorted by (`sort=ttft` appends a TTFT column).
Identity names always resolve in `fields=` (`model`/`name`, `slug`, `host`,
`creator`) — they are never blank and never reported as "no data". A model AA
lists no API endpoints for is explained, not errored: `— AA lists no API providers
for <model>; it has no published pricing or endpoint measurements (see aa_model for
what AA does publish)`.

## media

Human-preference arenas (Elo + appearance counts; the 95% confidence interval is
available on request with `fields=ci_lower,ci_upper,ci`, not shown by default):
text-to-image,
image-editing, text-to-video, image-to-video, video-editing, text-to-speech
(provider-voice and controlled-voice), music (instrumental, with-vocals). The two
video pages ship **two** arenas each — the audio-capable board and a **silent**
board (`text_to_video_silent` 31 rows, `image_to_video_silent` 82 rows — larger
than the audio-capable I2V 23), so `aa_media board=text_to_video_silent` /
`board=image_to_video_silent` rank those. Most boards also ship per-category
sub-boards: pass `aa_media category=<slug>` to rank one (`text_to_image` 19,
`image_editing` 17, `text_to_video` 20, `video_editing` 5,
`text_to_speech_controlled` 11, and the TTS use-case boards `assistants` 90,
`knowledge-sharing` 97, `entertainment` 90, `customer-service` 92 alongside
`en-us` 96 / `en-gb` 83 on `text_to_speech`); omit it for the overall board. Prices are
$/1k images, $/min and $/1M characters respectively. Speech boards serve the **full** published boards (not the homepage panels):
speech-to-text (`board=speech_to_text`, 36 rows; word error rate, lower is better),
streaming speech-to-text (`board=speech_to_text_streaming`, 45 rows; WER + time to
first partial / final transcript), speech-to-speech realtime voice
(`board=speech_to_speech`, 27 rows — the arena's `overall` slice; STS Index 0-100,
higher is better); each column is separately rankable (`sttWerIndex`,
`sttStreamingTimeToFinal`, `stsBigBenchAudio`, …).
`aa_agents` covers AA's coding-agent, chatbot and search-API boards. Speech board
keys are `speech_to_text`, `speech_to_text_streaming` and `speech_to_speech`
(also accepted as `realtime_voice` / "real-time voice").
`aa_search` and `aa_compare` resolve these media/speech models too: compare two arena entries (pass a board key such as `text_to_speech` as a `queries` entry, or prefix a name with `text_to_speech: `, to pin an ambiguous name) — a footer names the board and warns that scores from different boards are not comparable.

## fields

Field aliases accepted by every `fields=`/`metrics=`/`sort=` parameter (canonical
name first); `fields=all` (or `*`) selects every column the surface has (bounded
by the response cap): intelligence (intel), estimated, coding, agentic, omniscience,
omniscience_accuracy, omniscience_non_hallucination, openness, capabilities.<name>,
cost_per_task (alias cost; shown as $/Task), index_total_cost (whole-suite index cost,
`aa_pareto x=index_total_cost`), price_in, price_out, cache_read,
cache_write, cache_hit_discount, blended_*, tps, ttft, ttfa, e2e, reasoning_time,
out_tokens_per_task, time_per_task (AA-published seconds per index task),
context_tokens (ctx), params_b, active_params_b, release_date,
knowledge_cutoff, license, weights_url, is_open_weights (open), is_reasoning,
effort, deprecated, size_class, modalities_in, modalities_out, creator, slug, name
plus every benchmark key listed in `benchmarks` (e.g. gpqa, hle, mmmuPro,
briefcaseElo, terminalBench40, cyberIndex, cyberRefusalRate, cyberMitigationStatus,
when2call, wildguardtest, hleMultichoice, omniscienceDecision, multilingual,
mobile.bfcl_500, briefcaseRubricPassRate, openness.modelAvailability, sttWerIndex,
sttStreamingTimeToFinal, sts, stsBigBenchAudio, ttsQualityElo,
ttsCharactersPerSecond, searchQualityIndex, searchBrowsecompAccuracy,
searchCostPerQuery). Chart-set
sub-keys resolve too: `multilingual.<lang>` (16 languages: ar, bn, de, en, es, fr,
hi, id, it, ja, ko, pt, sw, yo, zh, my), `mobile.<eval>` (gpqa, ifbench, ifstruct,
math_500, omniscience, bfcl_500, bfcl_small), `omniscience.domain.<name>`,
`omniscience.language.<lang>`, `terminalBenchScience.domain.<name>`,
`enterpriseOpsGym.domain.<name>` and `openness.<component>`. Media arenas also
accept `ci_lower`, `ci_upper`
and `ci` (the 95% confidence interval).

Identity names resolve in every `fields=` list whatever the surface calls the
column: `model`/`name` → the Model column, `slug`, `host`, `creator`, and
`benchmark` (aa_benchmark_leaderboard). They are never blank and never reported as
"no data". A list-valued `fields=`/`metrics=` request renders everything that
resolves and footnotes the rest (`— unknown, ignored: <name> (closest: …)`) instead
of aborting the call; single-purpose arguments (`sort=`, `benchmark=`, `board=`,
`domain=`) still fail with the accepted values.

A `score/$` form asks for the derived score-per-$/task ratio instead of the plain
score: `intel/$` (the default axis, same as `value`), `coding/$`, `agentic/$`. It is
computed here (`score ÷ cost_per_task`) — AA publishes no such column — and
`aa_compare metrics=all` includes `Intel/$` and the same ratio for the other score
axes the models carry.

## sources

- Site: https://artificialanalysis.ai — `/leaderboards/models` (all variants),
  `/models/<slug>` (rich record + chart set), `/models/<slug>/providers`,
  `/leaderboards/providers`, `/evaluations/<slug>` (incl. the Decision-Models pages
  `aa-omniscience-decision`, `hle-multichoice`, `when2call`, `wildguardtest`),
  `/evaluations` (catalog),
  `/sitemap.xml` (the eval catalog is the union of the `/evaluations` cards and the
  sitemap `/evaluations/*` paths, so every published eval page is discoverable),
  media/agent leaderboards (video pages carry both the audio-capable and the silent
  arena, plus per-category sub-boards), the dedicated speech pages
  (`/speech-to-text/non-streaming`, `/speech-to-text/streaming`,
  `/speech-to-speech/arena`) and `/text-to-speech/models` (TTS quality/throughput
  plus the pronunciation suite), homepage (speech + security panels as fallback),
  `/models/multilingual` (Multilingual Index + 16 per-language scores),
  `/hardware-inference-stack/mobile-phones` (the 90-row on-device benchmark set
  incl. BFCL-500/BFCL-Small),
  `/models/capabilities/<index>` (the six Capability Indexes), `/agents/coding-agents`
  (the AA Coding Agent Index).
- Surfaces, what each carries and how fresh it is (TTL, then default seconds):
  - leaderboard (`aa_leaderboard`, `aa_pareto`) — 703 variants x
    ~50 columns: index, prices, speed, per-benchmark scores [1 h, `AA_CACHE_TTL`].
  - rich overlay (`aa_compare`, `aa_pareto`, `aa_model`) — 703 x ~94: capability
    indexes, AA-Briefcase Elo, whole-suite cost and per-evaluation costs/times,
    and the first-party model-page speed/latency medians [6 h, `AA_RICH_TTL`]. It
    is a separate cache file, so it can be hours older than the leaderboard age
    the header prints: two numbers can disagree on age alone. The header labels
    it separately — `aa:rsc + rich dataset (overlay 12m ago, seed <slug>)`.
  - eval chart sets + homepage panels (`aa_benchmark_leaderboard`, speech and
    security panels) — the top ~20-30 models per evaluation [1 h]; the
    Decision-Models pages (28 rows each), the Multilingual Index
    (`/models/multilingual`, 13 rows x 16 languages + average), the on-device set
    (`/hardware-inference-stack/mobile-phones`, 90 rows x 7 evals) and the
    speech/TTS/search chart sets (`stt` 36, `stt_streaming` 45, `sts` 27,
    `tts` 97, `search-api` 26) ride this same chart-set path — the speech boards
    prefer the dedicated page over the homepage panel (`loaders.SPEECH_BOARDS`).
  - provider board (`aa_providers` board view) — 1,222 endpoints x 64 hosts [1 h].
  - model providers (`aa_providers model=<slug>`) — per-endpoint pricing,
    performance and feature flags [1 h].
  - media arenas (`aa_media`) — Elo and appearance counts per arena [1 h]; the
    video pages' silent boards (`text_to_video_silent`, `image_to_video_silent`)
    and every board's per-category sub-boards (`category=`) come from the same
    payload.
  - agents boards (`aa_agents`) — coding-agent, chatbot and search-API tables [1 h];
    the Search API's BrowseComp / DeepSearchQA / latency / $-per-query columns are
    also rankable (`searchQualityIndex`, `searchBrowsecompAccuracy`, …).
  - eval catalog (`aa_benchmarks` index) — `/evaluations` cards + sitemap paths [1 h].
  - capability index pages (`/models/capabilities/<index>`) — the curated
    26-row (20 for Healthcare & Medical) cross-model subset per index; the full
    per-model values ride the rich overlay's `capabilities.<name>` [1 h].
- Transport: `RSC: 1` request header returns the Next.js flight payload (JSON-ish,
  ~1.2 MB gzip-transfer for the leaderboard). AA redeploys often; never hardcode
  chunk or build-id URLs.
- Cache: `~/.cache/aa-mcp` (`AA_CACHE_DIR`), TTL `AA_CACHE_TTL` (default 3600 s),
  rich overlay TTL `AA_RICH_TTL` (default
  21600 s). `AA_OFFLINE=1` serves cache only.
- Recovery: if the site answers with a Cloudflare challenge or the payload structure
  changed, the error states the cache path to overwrite — render the URL in a browser
  and save the HTML there, then retry. Offline/stale data is labelled in the header.
