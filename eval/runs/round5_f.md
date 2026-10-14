# Round 5 — final acceptance check (`round5_f`)

Harness only: `.venv/bin/python eval/client.py …` (stdio MCP). No `curl`, no web search,
no `src/` reading. Every call below is a real harness invocation; token numbers are the
harness's own `chars/4` estimates from stderr.

**Totals.** 65 logged `call` invocations (plus 6 non-logged: `tools`, `schema`,
`resources`, `prompts`, `prompt compare_models`, 2 resource `read`s) ≈ **10,567 tok**
across all calls; discovery searches (`aa_benchmarks`) account for ~2,700 of those.
Median table call ≈ 120 tok / <1 s.

Method per Part A item: (1) resolve the name with `aa_benchmarks query=…`, (2) read the
`How to query` hint, (3) make that exact call. "Found via" = the search that resolved it.

---

## Part A — the user's 16 named items

| # | item | found via | how-to-query hint (from server) | call made | top result | flag |
|---|---|---|---|---|---|---|
| 1 | Artificial Analysis Intelligence Index | `aa_benchmarks query="intelligence index"` (row 14/15) | `aa_leaderboard sort=intelligence` | `aa_leaderboard {"sort":"intelligence","top":3}` | Claude Opus 5.5 (Max, Default Fallback) **57.6**; Claude Sonnet 5.5 (Max) 56.0; Claude Opus 5.5 (Xhigh) 56.0 | CLEAN |
| 2 | Speed | `aa_benchmarks query="speed"` (domain match) → *Speed (output tokens/s)* | `aa_leaderboard sort=tps` | `aa_leaderboard {"sort":"tps","top":3}` | Celeris-1 **1458.8** tok/s; Mercury 2.5 647.3; Gemini 3.5 Flash-Lite 425.0 | CLEAN (query "speed" resolves via domain, not literal text) |
| 3 | Cost per Task | `aa_benchmarks query="cost per task"` | `aa_pareto x=cost_per_task` | `aa_pareto {"x":"cost_per_task","top":3}` | K2 Horizon 375B A23B **$0.00**; GPT-6 Luna (High) $0.03; GPT-6 Luna (Xhigh) $0.04 | CLEAN — two valid paths (`aa_leaderboard sort=cost_per_task` also works: North Mini Code $0.00) |
| 4 | Artificial Analysis Cyber Index | `aa_benchmarks query="cyber"` | `aa_leaderboard sort=cyberIndex` | **hint call FAILED** → then `aa_benchmark_leaderboard {"benchmark":"cyberIndex","top":3}` | GPT-6 Sol (Daybreak Blue, max) **68.7**; Grok 4.7 (Xhigh) 56.4; MiMo-V2.6-Pro 56.1 | **FRICTION** — the published hint is wrong; error text is *"'AA Cyber Ind' has no values in the 700-row leaderboard — it is chart-set / model-page only. — rank it with aa_benchmark_leaderboard benchmark=<slug>"*. Needed a 2nd call. |
| 5 | AA-3D | `aa_benchmarks query="3d"` → *AA-3D Elo* + *AA-3D Breakdown* | `aa_benchmark_leaderboard benchmark=aa3dElo` | `aa_benchmark_leaderboard {"benchmark":"aa3dElo","top":3}` | Claude Sonnet 5.5 **1194**; Claude Opus 5.5 1190; GPT-6 Astra 1165 | **FRICTION** — the sibling row's hint `benchmark=aa3dBreakdown` **crashes** (`TypeError: float() argument must be a string or a real number, not 'dict'`), not an honest empty. Label form `benchmark="AA-3D Elo"` also works. |
| 6 | Provider Voice Arena Preference Elo | `aa_benchmarks query="provider voice"` → *Text-to-Speech Arena Elo* (alias hit) | `aa_media board=text_to_speech` | `aa_media {"board":"text_to_speech","top":3}` | Eleven v4 Turbo **1328**; Eleven v4 1326; Qwen-Audio-3.1-TTS-Plus 1297 | CLEAN — the user's phrasing is an alias of the TTS board (`aa://rankables` confirms alias `Provider Voice Arena Preference Elo`). |
| 7 | Artificial Analysis Speech to Speech Index | `aa_benchmarks query="speech to speech"` (alias hit) | `aa_media board=speech_to_speech` | `aa_media {"board":"speech_to_speech","top":3}` | Grok Voice 3.0 **STS 86.9**; GPT-Live-1 (Astra, medium) 83.2; Gemini 3.8 Live Extended Thinking (High) 82.6 | CLEAN — the name is an alias of the STS board; STS Index shown. |
| 8 | Terminal-Bench 4.0 | `aa_benchmarks query="terminal"` | `aa_benchmark_leaderboard benchmark=terminalBench40` | `aa_benchmark_leaderboard {"benchmark":"terminalBench40","top":3}` | Claude Sonnet 5.5 **63.6%**; GPT-6 Astra (Xhigh) 59.6%; Claude Opus 5.5 59.6% | CLEAN |
| 9 | Terminal-Bench-Science 0.1 | `aa_benchmarks query="terminal"` → *Terminal-Bench Science* | `aa_benchmark_leaderboard benchmark=terminalBenchScience` | `aa_benchmark_leaderboard {"benchmark":"terminalBenchScience","top":3}` | GPT-6 Astra (Max) **63.3%**; Claude Opus 5.5 (Xhigh) 61.9%; Claude Opus 5.5 (Max) 59.0% | CLEAN — the "0.1" version string lives only in the *Measures* column; the key/label don't carry it (querying "0.1" would not match). |
| 10 | FrontierCode 1.1 | `aa_benchmarks query="frontiercode"` | `aa_benchmark_leaderboard benchmark=frontierCode` | `aa_benchmark_leaderboard {"benchmark":"frontierCode","top":3}` | Claude Opus 5.5 (Max) **52.2%**; GPT-6.1 Sol (Max) 49.1%; Claude Fable 5.1 (Max) 49.0% | CLEAN (same "1.1 only in Measures" caveat) |
| 11 | ITBench-AA | `aa_benchmarks query="itbench"` → *ITBench-AA SRE* | `aa_benchmark_leaderboard benchmark=itbenchSre` | `aa_benchmark_leaderboard {"benchmark":"itbenchSre","top":3}` | GPT-5.6 Sol (Max) **56.2%**; Step 5 Preview 55.6%; Gemini 3.8 Flash (High) 52.5% | CLEAN |
| 12 | AA-Omniscience Index | `aa_benchmarks query="omniscience"` | `aa_leaderboard sort=omniscience` | `aa_leaderboard {"sort":"omniscience","top":3}` | Claude Opus 5.5 (Max) **46.4**; GPT-6 Astra (High) 43.7; Claude Fable 5.1 (Max) 43.5 | CLEAN |
| 13 | Openness Index | `aa_benchmarks query="openness"` (domain match) → *Artificial Analysis Openness Index* | `aa_leaderboard sort=openness` | `aa_leaderboard {"sort":"openness","top":3}` | Olmo 3 7B Think **88.9**; Olmo 3.1 32B Think 88.9; Apertus 70B Instruct 88.9 | CLEAN |
| 14 | Output Tokens per Intelligence Index Task | `aa_benchmarks query="output tokens"` | `aa_pareto x=out_tokens_per_task` | `aa_pareto {"x":"out_tokens_per_task","top":3}` | GPT-6 Luna (Low) **2k**; GPT-5.6 Terra (Non-reasoning) 3k; GPT-6 Luna (Non-reasoning) 4k | CLEAN — `aa_leaderboard sort=out_tokens_per_task` also works. |
| 15 | Intelligence Index vs Output Tokens per Index Task | `aa_benchmarks query="output tokens"` (same rankable as #14) | `aa_pareto x=out_tokens_per_task` | `aa_pareto {"x":"out_tokens_per_task","include_all":true}` | 13-point frontier; **knee ≈ GPT-6 Astra (Xhigh): 17k tok/task, Intel 52.4** | CLEAN — resolves to the *same* call as #14 (metric and its scatter view are one rankable). |
| 16 | Intelligence Index vs Cost to Run the AA Intelligence Index | `aa_benchmarks query="cost per task"` → *Cost to Run the Intelligence Index (whole suite)* | `aa_pareto x=index_total_cost` | `aa_pareto {"x":"index_total_cost","top":3}` | K2 Horizon $0.00; GPT-6 Luna (High) **$47.85**; Claude Haiku 5.5 (Medium) $56.36 | CLEAN — 17-point frontier, knee ≈ MiMo-V2.6-Pro $207 / Intel 46.3; footnote flags "$/index is model-page data (rich dataset), not a leaderboard column". |

**Empty / misleading tables:** none for items 1–3, 6–16. Two defects instead of empties:
item 4's hint call errors; item 5's sibling key `aa3dBreakdown` **raises an internal
`TypeError`** (also reproduced for `harveyLabBreakdown` — every "*…Breakdown*" chart-set
benchmark). Neither degrades to an honest empty row.

**Guessing needed:** only for item 4 (hint wrong → had to guess `aa_benchmark_leaderboard`
from the error text) and item 5 (avoid the crashing sibling key). Everything else was
reachable from the search hint alone.

---

## Part B — the user's comparison URLs

### 17. `mimo-v2-6-pro` vs `deepseek-v4-1-flash`

Calls: `aa_compare {"queries":["mimo-v2-6-pro","deepseek-v4-1-flash"],"metrics":"all","view":"diff"}`
(860 tok) and the same with `"view":"table"` (731 tok). Both slugs resolved exactly;
header: *"2 models · 56 metrics"*.

Winner per domain (server gives raw metrics, not domain verdicts — I aggregate; both models
are `active`, both have 1.0M context):

| domain | winner | evidence (MiMo → DeepSeek) |
|---|---|---|
| coding | **MiMo-V2.6-Pro** | FrontierCode 45.4 vs 44.0; SciCode 60.9 vs 51.9; Terminal-Bench 4.0 34.8 vs 26.8; MLCR-AA 18.3 vs 22.8 (DS) |
| science | **MiMo-V2.6-Pro** | CritPt 26.6 vs 14.3; GDP.pdf 19.2 vs 12.8; HLE 49.4 vs 39.2; Terminal-Bench Science 5.7 vs 9.0 (DS); MMMU-Pro — vs 77.0 (DS only) |
| agentic | **split, edge MiMo** | Terminal-Bench 4.0 34.8 vs 26.8, AA-AnalystAgent 37.5 vs 35.0 (MiMo); AutomationBench 58.6 vs 68.9, ITBench-AA SRE — vs 46.9 (DS) |
| security | **MiMo-V2.6-Pro** | Cyber Index 56.1 vs 40.8; CyberGym-E2E 78.6 vs 22.9; CWE-Bench 63.3 vs 68.3, DeepSec 26.2 vs 31.2 (DS) |
| cost | **MiMo-V2.6-Pro** | $0.13 vs $0.27 /task; $207 vs $477 per index run; in $0.43 vs $0.30, out $0.87 vs $1.20 |
| speed | **DeepSeek V4.1 Flash** | 180.2 vs 43.7 tok/s; TTFT 1.1 vs 4.1 s; E2E 14.9 vs 61.3 s; time/task 324.7 vs 1267.3 s |
| context | **tie** | both 1.0M tokens |

Overall Intelligence Index: MiMo 46.3 vs DeepSeek 39.5. **Verdict: MiMo-V2.6-Pro wins
intelligence/coding/science/security and cost; DeepSeek V4.1 Flash wins speed (≈4×).**
The prompt `compare_models` only emits *instructions* (steps 1–5), not a verdict — the
aggregation above is mine. **CLEAN**, with the note that no domain-verdict surface exists.

### 18. 4-model URL (`compare=mimo-v2-6-pro,deepseek-v4-1-flash,gpt-6-luna-xhigh,muse-wonder-full`)

Call: `aa_compare {"queries":[…4 slugs…],"metrics":"all","view":"diff"}` — 1,242 tok,
*"4 models · 57 metrics"*, deltas vs the first model. All four resolved
(`GPT-6 Luna (xhigh)`, `Muse Wonder Full (max)`).

**Missing metrics per model** (derived from the `-` cells; the footer's `missing:` line is
truncated to 4 items + `… (+29 more)`):

- **GPT-6 Luna (xhigh)** — missing every chart-set-only metric (not in AA's ~28-model chart
  set, closed weights): AA-3D Elo, AA-AnalystAgent, Analyst Pass@1/@k, CWE-Bench-AA,
  CWE Refusal, CyberGym-E2E-AA, CyberGym Refusal, DeepSecBench-AA, DeepSec Refusal,
  FrontierCode, Harvey LAB-AA, ITBench-AA SRE, MLCR Accuracy/Complete/Concise/AA,
  Terminal-Bench Science, Cap Medical, Artificial Analysis Cyber Index, Openness Index,
  Active/Total Parameters, Cache Write Price.
- **Muse Wonder Full (max)** — **no published pricing or speed at all**: Cost per Task,
  Cost to Run the Index, Input/Output/Cache prices, Time per Index Task, Speed, TTFT,
  TTFA, E2E Response Time — *plus* the same chart-set metrics above (AA-3D, CWE, CyberGym,
  DeepSec, FrontierCode, MLCR, MMMU-Pro, Terminal-Bench Science, ITBench, Cap Medical,
  Cyber Index, Openness, params). It *does* have Intelligence 55.8, Omniscience 30.1,
  tok/task 54k and 1.0M context.
- **MiMo-V2.6-Pro** — missing Harvey LAB-AA, ITBench-AA SRE, MMMU-Pro, Cache Write Price.
- **DeepSeek V4.1 Flash** — missing only AA-3D Elo and Cache Write Price.

Server wording for gaps: per-cell `-`, plus a footer `missing: <metric> (<model>)` list and
`— AA-3D Elo, … from AA's eval chart set (top ~28 models)`. **FRICTION**: the explicit
`missing:` line is truncated (`… (+29 more)`), so the full per-model gap map has to be read
out of the table by hand.

### 19. Pareto frontiers

All three site views via `aa_pareto` (with `include_all=true` for the full frontier):

- **Intelligence vs Cost per Index Task** — `aa_pareto {"x":"cost_per_task","include_all":true}`
  (423 tok): 16 non-dominated of 114; **knee ≈ MiMo-V2.6-Pro, $0.13/task, Intel 46.3
  (5× cost/score cliff)**. Frontier (cheapest→smartest): K2 Horizon 375B A23B $0.00/30.5 ·
  GPT-6 Luna (High) $0.03/32.9 · GPT-6 Luna (Xhigh) $0.04/34.6 · MiMo-V2.6-Flash $0.06/37.9 ·
  GPT-6 Luna (Max) $0.07/38.1 · Claude Haiku 5.5 (Xhigh) $0.12/41.2 · GPT-6.1 Sol (Low)
  $0.13/42.1 · **MiMo-V2.6-Pro $0.13/46.3** · GPT-6.1 Sol (Medium) $0.21/47.8 · (High) $0.32/50.2 ·
  (Xhigh) $0.39/51.0 · (Max) $0.72/51.8 · Claude Opus 5.5 (High) $1.82/53.6 · (Xhigh) $3.46/56.0 ·
  Claude Sonnet 5.5 (Max) $5.46/56.0 · Claude Opus 5.5 (Max) $5.98/57.6.
- **Intelligence vs Cost to Run the whole Index** — `aa_pareto {"x":"index_total_cost","include_all":true}`
  (480 tok): 17 points of 114; **knee ≈ MiMo-V2.6-Pro, $207, Intel 46.3**. Head: K2 Horizon $0.00 ·
  GPT-6 Luna (High) $47.85 · Claude Haiku 5.5 (Medium) $56.36 · … · Claude Opus 5.5 (Max) $8,708.
- **Intelligence vs Output Tokens per Index Task** — `aa_pareto {"x":"out_tokens_per_task","include_all":true}`
  (362 tok): 13 points of 126; **knee ≈ GPT-6 Astra (Xhigh), 17k tok/task, Intel 52.4**.
  Head: GPT-6 Luna (Low) 2k/21.5 · GPT-5.6 Terra (Low) 4k/27.5 · GPT-6.1 Sol (Low) 4k/42.1 ·
  GPT-6 Astra (Low) 4k/45.8 · … · Claude Opus 5.5 (Max) 119k/57.6.

**CLEAN.** The knee line, the `non-dominated of N` coverage, and the "rich dataset vs
leaderboard column" provenance note are all present and honest.

---

## Part C — the bar (item 20)

**Question the server cannot answer: "Compare Grok Voice 3.0 vs GPT-Live-1 (Astra, medium)
on the Artificial Analysis Speech-to-Speech Index."**

The data *is* published by AA — `aa_media {"board":"speech_to_speech","top":5}` returns
both with STS scores (86.9 / 83.2) — but there is **no comparison path**: the only
comparison tool cannot see arena/media models.

Calls tried:
1. `aa_media {"board":"speech_to_speech","top":5}` → rows present (Grok Voice 3.0, GPT-Live-1 …).
2. `aa_compare {"queries":["Grok Voice 3.0","GPT-Live-1 (Astra, medium)"],"metrics":"all"}`
   → **`Error executing tool aa_compare: no model matches 'Grok Voice 3.0' — closest slugs: none — use aa_search to resolve names to slugs`**.
3. `aa_search {"query":"voice"}` → **`# no models match 'voice' — try a shorter substring or aa_reference topic=fields`** (same for TTS: `aa_compare ["Eleven v4 Turbo","Eleven v4"]` → `no model matches 'Eleven v4 Turbo' — closest slugs: none`).

So the coverage wording is *"no model matches '<name>' — closest slugs: none"*: media/speech
models live outside the 700-row comparison universe and can only be listed, never compared.

Two runner-up gaps found while probing (both genuine "published data the comparison surface
can't reach"):

- **Unpublished-metric comparison** — `aa_compare {"queries":["gpt-6-astra","claude-opus-5-5"],"metrics":"knowledge cutoff"}`
  returns an **empty table** with honest wording: *"GPT-6 Astra (Max) has no published values
  for the requested metrics on AA; 0/1 requested metrics available"* (and the same for the
  other model). A valid alias ("Cutoff") that AA simply doesn't publish.
- **Breakdown benchmarks** — a comparison on *Harvey LAB-AA sub-scores by practice area*
  (`aa_benchmark_leaderboard benchmark=harveyLabBreakdown`, and likewise `aa3dBreakdown`)
  **crashes**: `aa_benchmark_leaderboard failed: TypeError: float() argument must be a
  string or a real number, not 'dict'` — no coverage wording, just a stack-trace message.

Unknown *names* are handled gracefully (e.g. `aa_compare metrics="MMLU"` → *"unknown metric
'MMLU' — closest: MMLU-Pro, MMMU-Pro, Global-MMLU-, Global-MMLU-Lite, MLCR-AA — aa_reference
topic=fields lists every accepted name"*), so those are naming issues, not coverage gaps.

---

## Per-item accounting (calls + harness tokens)

Includes the discovery search(es) for that item; some searches are shared across items
(e.g. `query="terminal"` serves #8/#9, `query="cost per task"` serves #3/#16).

| item | calls | harness tokens | item | calls | harness tokens |
|---|---|---|---|---|---|
| 1 | 2 | 587 | 11 | 2 | 171 |
| 2 | 2 | 371 | 12 | 2 | 357 |
| 3 | 3 | 506 | 13 | 2 | 192 |
| 4 | 4 | 561 | 14 | 3 | 462 |
| 5 | 4 | 385 | 15 | 2 | 519 |
| 6 | 3 | 340 | 16 | 3 | 912 |
| 7 | 4 | 614 | 17 | 3 | 1,591 |
| 8 | 2 | 315 | 18 | 1 | 1,242 |
| 9 | 2 | 326 | 19 | 6 | 1,824 |
| 10 | 2 | 190 | 20 | 12 | ~600 |

Calls include the failures (item 4's bad hint call, item 5's `aa3dBreakdown` crash) and the
Part-C probes; the 20 probes cost ~600 tok total, i.e. the error paths are cheap.

## Per-item verdicts

| item | verdict | reason |
|---|---|---|
| 1,2,3,6,7,8,9,10,11,12,13,14,15,16 | **CLEAN** | found from `aa_benchmarks` hint, call worked first try, top-3 returned |
| 4 | **FRICTION** | hint `aa_leaderboard sort=cyberIndex` is wrong for a chart-set index; needed a 2nd call (the error text gives the fix) |
| 5 | **FRICTION** | AA-3D Elo is fine, but the sibling `aa3dBreakdown` (same search result) raises an internal `TypeError` |
| 17 | **CLEAN** | 2 slugs resolved, 56 metrics with deltas; no domain-verdict surface (must aggregate manually) |
| 18 | **FRICTION** | 4-way diff fine, but the `missing:` footer is truncated (`… (+29 more)`) → full gap map only by hand |
| 19 | **CLEAN** | three axes, knee + coverage + provenance all present |
| 20 | **FRICTION** | media/speech models are uncomparable (`no model matches … closest slugs: none`); Breakdown benchmarks crash |

## Top 3 things I'd still change

1. **Fix the `How to query` hints for chart-set-only rankables.** Item 4's published hint
   (`aa_leaderboard sort=cyberIndex`) errors on the leaderboard; the hint generator should
   emit `aa_benchmark_leaderboard benchmark=cyberIndex` for anything whose coverage is
   "chart set", not "leaderboard". Same class of bug makes the search surface self-inconsistent.
2. **Stop the `TypeError` on "*…Breakdown*" benchmarks.** `aa3dBreakdown` and
   `harveyLabBreakdown` are advertised in search (coverage "no live values in current
   source") yet raise `float() argument must be … not 'dict'`. They should return an honest
   empty table + coverage note like `aa_compare` does, not an internal error.
3. **Extend comparison coverage to media/speech and un-truncate the missing list.** The
   user's own list includes the STS Index and Voice Arena; today `aa_compare` can't touch
   those models at all (`no model matches … closest slugs: none`), so a named comparison
   question fails even though the numbers exist. At minimum, `aa_compare` should accept
   arena board keys (or `aa_media` should expose a 2-model delta view), and the Part-B
   `missing:` footer should list every gap rather than `… (+29 more)`.
