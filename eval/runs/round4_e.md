# Round 4 — comparison-parity evaluation

Agent: `EvalR4` · date 2026-10-14 · harness: `.venv/bin/python eval/client.py` only
(no curl, no web search, no `src/` reads). Token costs are the harness-reported
`chars/4` estimates (stderr for `call`, `eval/runs/live.ndjson` for `read`/`call`).
Every number below is pasted from a harness reply.

## Call / token ledger

| Item | Calls | Tokens |
|---|---:|---:|
| 1 pairwise parity | 3 | 887 |
| 2 multi-model parity | 9 | 2,666 |
| 3 Pareto lines | 5 | 1,516 |
| 4 domain search | 8 | 1,077 |
| 5 spec round-trip | 11 | 4,103 |
| 6 the bar | 13 | 1,608 |
| **direct total** | **49** | **11,857** |

Shared setup (counted once, used by 1/2/5): `read aa://comparisons/spec` 149 ·
`read aa://reference/metrics` 1,214 · `read aa://benchmarks` 4,541 → **5,904 tok**.
Plus `tools`/`schema` inventory (~0.4k/2k, not logged by the harness). Grand total
≈ **18–20k harness tokens for 49+ calls**.

---

## 1. Comparison-page parity (pairwise) — `mimo-v2-6-pro` vs `deepseek-v4-1-flash`

Calls:
- `aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash"],"metrics":"all","view":"diff"}'` → 621 tok
- `aa_model '{"query":"deepseek-v4-1-flash","sections":"benchmarks"}'` → 187 tok
- `aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash"],"metrics":"livecodebench"}'` → 79 tok

`metrics=all` returned **43 metrics** (`2 models · 43 metrics`, header
`aa:rsc + rich dataset`, cache 23m). The full matrix is in the run log; the domain
roll-up:

| Domain | MiMo-V2.6-Pro | DeepSeek V4.1 Flash | Winner |
|---|---|---|---|
| **Coding** | FrontierCode 45.4%, SciCode 60.9%, Terminal-Bench 4.0 34.8% | FrontierCode 44.0%, SciCode 51.9%, Terminal-Bench 4.0 26.8% | **MiMo** (3/3) |
| **Science** | SciCode 60.9, CritPt 26.6, HLE 49.4, GDP.pdf 19.2 | SciCode 51.9, CritPt 14.3, HLE 39.2, GDP.pdf 12.8, T-B Science 9.0, MMMU-Pro 77.0 | **MiMo** (4/6; DS wins only the 2 MiMo does not have/leads weakly) |
| **Agentic / tool-use** | AnalystAgent 37.5, AutomationBench 58.6, T-B 4.0 34.8 | AnalystAgent 35.0, AutomationBench 68.9, T-B 4.0 26.8, ITBench-AA SRE 46.9 | **split** — MiMo on analyst+terminal, DS on automation+SRE |
| **Cost** | $0.13/task, $207/index, out $0.87, cache $0.0036 | $0.27/task, $477/index, out $1.20, cache $0.0060, in $0.30 | **MiMo** (DS cheaper only on input price) |
| **Speed** | 43.7 tok/s, TTFT 4.1s, TTFA 49.8s, E2E 61.3s, 1267.3s/index-task | 180.2 tok/s, TTFT 1.1s, TTFA 12.2s, E2E 14.9s, 324.7s/index-task | **DeepSeek** (every axis) |
| **Context** | 1.0M | 1.0M | **tie** |
| Intelligence Index | 46.3 | 39.5 | MiMo |
| Knowledge / hallucination | Omniscience 8.4, Omni Acc 34.8, Non-Halluc 59.4 | Omniscience −5.3, Omni Acc 46.4, **Halluc 96.5%** | MiMo (DS answers more but hallucinates 96.5%) |
| Capability indexes | Econ 53.2, Eng 46.9, Fin 46.1, Med 41.8, Legal 44.8, Strat 47.8 | Econ 44.4, Eng 39.3, Fin 45.0, Med 40.6, Legal 41.3, Strat 51.7 | MiMo (5/6) |
| **Security / cyber** | Cyber Index 56.1, CWE-Bench 63.3% | Cyber Index 40.8, **CWE-Bench 68.3%** | split (see item 6; not in `metrics=all`) |

**Adversarial notes.**
- **Silently missing cells.** MiMo-V2.6-Pro shows `-` for `Harvey LAB-AA`,
  `ITBench-AA SRE`, `MMMU-Pro`; DeepSeek shows `-` for nothing. The table never says
  *why* those three are blank — no per-row "no data" marker in `aa_compare`.
- **Silently missing benchmarks.** `metrics=all` claims "every rankable key any of
  these models has", yet neither model has `LiveCodeBench` (explicit
  `metrics=livecodebench` → `| LiveCodeBench | - | - |`) and the chart-set security
  boards are absent entirely. **AA Coding Index / Agentic Index are missing for both**
  (API-only — see item 2/6).
- **Source is labelled** (`aa:rsc + rich dataset`) and the reply ends with a
  reproducible spec block. That part is clean.

**Verdict: CLEAN** on values/source/labelling; **FRICTION** on unlabelled blank cells
(3 rows for MiMo) and the silent omission of chart-set/security metrics.

---

## 2. Comparison-page parity (multi-model) — the user's own URL

Calls:
- `aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"],"metrics":"all","view":"diff"}'` → 910 tok
- `aa_benchmarks '{"query":"security"}'` → 83 · `aa_benchmarks '{"query":"cyber"}'` → 353 · `aa_benchmarks '{"domain":"security"}'` → 399
- `aa_benchmark_leaderboard '{"benchmark":"cyberIndex","top":20,...}'` → 291 · `...benchmark=cweBench...` → 296 · `top:5` variants → 126 + 131
- `aa_leaderboard '{"sort":"coding","top":5}'` → 77 (error)

`metrics=all` → `4 models · 44 metrics`. Deltas are vs MiMo (first model). Key rows:

| Metric | MiMo-V2.6-Pro | DeepSeek V4.1 Flash | GPT-6 Luna (xhigh) | Muse Wonder Full (max) |
|---|---|---|---|---|
| Intelligence Index | 46.3 | 39.5 (−6.9) | 34.6 (−11.8) | **55.8 (+9.5)** |
| SciCode | 60.9% | 51.9% (−9.0) | 51.7% (−9.1) | **62.6% (+1.7)** |
| FrontierCode | **45.4%** | 44.0% (−1.4) | - | - |
| Terminal-Bench 4.0 | 34.8% | 26.8% (−8.1) | 8.1% (−26.8) | **57.1% (+22.2)** |
| AutomationBench | 58.6% | 68.9% (+10.3) | 47.8% (−10.8) | **71.3% (+12.7)** |
| AA-Briefcase Elo | 1516 | 1422 (−94) | 1237 (−279) | **1729 (+213)** |
| Cost per Task | $0.13 | $0.27 (+0.1) | **$0.04 (−0.1)** | - |
| Cost to run Index | $207 | $477 (+270) | **$66.81 (−140)** | - |
| Speed (tok/s) | 43.7 | **180.2 (+136.5)** | 122.2 (+78.5) | - |
| TTFT | 4.1s | **1.1s (−3.0)** | 40.0s (+36.0) | - |
| Context Window | 1.0M | 1.0M | 1.0M | 1.0M |

**Best coding.** On the only coding benchmark scored for all four, SciCode, **Muse
Wonder Full (62.6%)** wins (MiMo 60.9 > DeepSeek 51.9 > Luna 51.7). On FrontierCode
only two are scored (MiMo 45.4 > DeepSeek 44.0). The **AA Coding Index is not
available cross-model** — `aa_leaderboard sort=coding` fails:

> `'Coding': AA exposes this index per model only on the scrape source (model pages) and through the JSON API (AA_API_KEY) — there is no cross-model ranking to sort by.`

**Best security / cyber.** Neither the Cyber Index nor CWE-Bench appears in
`metrics=all`; pulled from the chart-set leaderboards (`20 of 20 scored`, header
`AA chart set — not a full leaderboard`):

| Board | MiMo | DeepSeek | GPT-6 Luna xhigh | Muse |
|---|---|---|---|---|
| AA Cyber Index | **56.1** | 40.8 | not listed | not listed |
| CWE-Bench-AA | 63.3% | **68.3% (tied #1)** | not listed | not listed |

So **only 2 of the 4 requested models have any security score** — Luna-xhigh and
Muse are absent from both boards. The two that do score disagree by board: **MiMo
wins the Cyber Index, DeepSeek wins CWE-Bench.**

**Cheapest per task.** **GPT-6 Luna (xhigh) $0.04** < MiMo $0.13 < DeepSeek $0.27.
**Muse Wonder Full has no `Cost per Task` (`-`)** — its cost is unknown, so it cannot
compete on cost at all (see item 6).

**Cost-sensitive agentic coding pick.** Numbers (agentic = Terminal-Bench 4.0 /
AutomationBench; coding = SciCode / FrontierCode):

| Model | $/task | T-B 4.0 | AutomationBench | SciCode | FrontierCode | Intel |
|---|---|---|---|---|---|---|
| MiMo-V2.6-Pro | $0.13 | 34.8 | 58.6 | 60.9 | 45.4 | 46.3 |
| DeepSeek V4.1 Flash | $0.27 | 26.8 | 68.9 | 51.9 | 44.0 | 39.5 |
| GPT-6 Luna (xhigh) | $0.04 | 8.1 | 47.8 | 51.7 | - | 34.6 |
| Muse Wonder Full | - (unknown) | 57.1 | 71.3 | 62.6 | - | 55.8 |

**Pick: MiMo-V2.6-Pro.** It is the only model that is simultaneously cheap
($0.13/task, ~½ DeepSeek), competent agentic (T-B 4.0 34.8 vs Luna 8.1) and strong
coding (SciCode 60.9, FrontierCode 45.4). GPT-6 Luna xhigh is cheaper ($0.04) but its
agentic score (8.1) is disqualifying; Muse is best on agentic/coding but has no cost
data to judge "cost-sensitive"; DeepSeek costs 2× MiMo for *lower* agentic-coding
scores (only AutomationBench is higher).

**Verdict: CLEAN** on the matrix itself; **FRICTION** on (a) two of four models
having zero security coverage with no in-table marker, (b) Muse's entire
cost/speed column blank with no explanation, (c) Coding/Agentic Index unavailable
without `AA_API_KEY`.

---

## 3. Pareto lines

Calls (all `aa_pareto`, 5 total, 1,516 tok incl. 2 catalog probes):
- `aa_pareto '{"score":"intelligence","x":"cost_per_task","top":20}'` → 423
- `aa_pareto '{"score":"intelligence","x":"index_total_cost","top":20}'` → 480
- `aa_pareto '{"score":"intelligence","x":"out_tokens_per_task","top":20}'` → 362
- `aa_benchmarks '{"query":"output tokens"}'` → 157 · `'{"query":"cost to run"}'` → 94

**(a) Intelligence vs Cost-per-task** — `16 frontier points` of 114 scored, knee:

> `— knee ≈ MiMo-V2.6-Pro: $/task $0.13, Intel 46.3 (5× cost/score cliff)`

Frontier (cost ascending): K2 Horizon 30.5/$0 → GPT-6 Luna High 32.9/$0.03 →
Luna Xhigh 34.6/$0.04 → MiMo-Flash 37.9/$0.06 → Luna Max 38.1/$0.07 →
Claude Haiku 5.5 Xhigh 41.2/$0.12 → GPT-6.1 Sol Low 42.1/$0.13 →
**MiMo-V2.6-Pro 46.3/$0.13** → … → Claude Opus 5.5 Max 57.6/$5.98.

**(b) Intelligence vs cost to run the whole Intelligence Index** — `17 frontier
points`, knee:

> `— knee ≈ MiMo-V2.6-Pro: $/index $207, Intel 46.3 (5× cost/score cliff)`
> `— $/index is model-page data (rich dataset), not a leaderboard column`

**(c) Intelligence vs output tokens per task** — `13 frontier points`, knee:

> `— knee ≈ GPT-6 Astra (Xhigh): tok/task 17k, Intel 52.4 (5× cost/score cliff)`

Frontier: GPT-6 Luna Low 21.5/2k → … → GPT-6 Astra Xhigh 52.4/17k →
Muse Wonder Full 55.8/54k → Claude Opus 5.5 Max 57.6/119k.

**Are the knees the same?** (a) and (b) both land on **MiMo-V2.6-Pro**; (c) lands on
**GPT-6 Astra (Xhigh)**.

- (a) vs (b) — same model: both axes are *dollar* axes driven by the same token
  counts × the same price list, so the cheapest model that still clears the 5×
  cost/score cliff (MiMo) dominates both.
- (c) — different model: the token axis measures *verbosity*, not price, so the lean
  low/medium-effort frontier models (GPT-6 Astra at 17k tok/task, Intel 52.4) push
  the knee off MiMo and onto a much more capable model.

**Verdict: CLEAN** — three frontiers, three explicit knees, honest `$/index is
model-page data` caveat and per-axis units.

---

## 4. Domain search

Calls (8 total, 1,077 tok): `aa_benchmarks` for `speech`(233)/`voice`(151)/
`legal`(155)/`3D`(112), then rankings.

**(a) Security / cyber** — `aa_benchmarks '{"query":"cyber"}'` → `7 of 95`:
CWE-Bench-AA, CWE Refusal, CyberGym-E2E-AA, CyberGym Refusal, DeepSecBench-AA,
DeepSec Refusal, **AA Cyber Index** (`aa_leaderboard sort=cyberIndex` /
`aa_benchmark_leaderboard benchmark=cyberIndex`).
*Friction:* `query:"security"` returns only `1 of 95` (DeepSecBench) while
`query:"cyber"` returns 7 — the plain word "security" under-recalls.

**(b) Speech / voice** — `aa_benchmarks '{"query":"speech"}'` → `5 of 95`, all arenas:
Speech-to-Speech, Speech-to-Text, Streaming Speech-to-Text, Text-to-Speech, Controlled
Voice (`aa_media board=…`). `query:"voice"` → 3 (STS, TTS, Controlled Voice).

**(c) Legal** — `aa_benchmarks '{"query":"legal"}'` → `3 of 95`: Harvey LAB-AA
(`aa_benchmark_leaderboard benchmark=harveyLab`), Harvey Breakdown, **Cap Legal**
(`aa_leaderboard sort=capabilities.legal`).

**(d) 3D** — `aa_benchmarks '{"query":"3D"}'` → `2 of 95`: AA-3D Elo
(`aa_benchmark_leaderboard benchmark=aa3dElo`), AA-3D Breakdown.

**Ran the ranking for legal + speech (+ 3D as a probe):**

`aa_leaderboard '{"sort":"capabilities.legal","top":3}'` → 145 tok
(`3 of 270 scored · Cap Legal, active only`):

| # | Model | Slug | Cap Legal |
|---|---|---|---|
| 1 | Claude Opus 5.5 (Max) | `claude-opus-5-5` | 63.3 |
| 2 | Claude Fable 5.1 (Xhigh) | `claude-fable-5-1-xhigh` | 60.8 |
| 3 | Claude Opus 5.5 (Xhigh) | `claude-opus-5-5-xhigh` | 60.8 |

`aa_benchmark_leaderboard '{"benchmark":"harveyLab","top":3}'` → 103 tok
(`3 of 27 scored · Harvey LAB-AA · rich dataset — not a full leaderboard`):

| # | Model | Harvey LAB-AA |
|---|---|---|
| 1 | Muse Wonder Full (Max) | 13.1% |
| 2 | Muse Wonder (Max) | 10.0% |
| 3 | Grok 4.7 (Xhigh) | 9.4% |

`aa_media '{"board":"speech_to_speech","top":3}'` → 70 tok (`3 of 15 rows · STS index`):

| # | Model | Host | STS |
|---|---|---|---|
| 1 | Grok Voice 3.0 | SpaceXAI | 86.9 |
| 2 | GPT-Live-1 (Astra, medium) | OpenAI | 83.2 |
| 3 | Gemini 3.8 Live Extended Thinking (High) | Google | 82.6 |

`aa_benchmark_leaderboard '{"benchmark":"aa3dElo","top":3}'` → 108 tok
(`3 of 21 scored · AA-3D Elo · AA chart set — not a full leaderboard`):
Claude Sonnet 5.5 (Max) 1194, Claude Opus 5.5 (Max) 1190, GPT-6 Astra (Max) 1165.

**Adversarial note.** `aa_benchmarks` labels AA-3D Elo as **"chart set only (not
fetched)"**, but `aa_benchmark_leaderboard benchmark=aa3dElo` fetched it live
(`0s ago`, `3 of 21 scored`). The catalog's "not fetched" wording contradicts the
leaderboard tool actually fetching it.

**Verdict: CLEAN** — every domain resolved to a concrete, runnable call and the top-3
rankings are labelled with source + coverage. **FRICTION:** `query:"security"`
under-recalls (1 vs 7), and the "not fetched" catalog label for AA-3D is wrong.

---

## 5. Spec round-trip

Calls (11 total, 4,103 tok): 1 spec run + 1 echoed-spec re-run + 4 diagnostic
`compact` probes + 4 extra spec runs, all `aa_compare`.

Spec run (485 tok):
`aa_compare '{"spec":"models:\n  - mimo-v2-6-pro\n  - muse-wonder-full\nmetrics: all\nview: table\ncompact: true\n"}'`
→ echoed spec **dropped `view: table` and `compact: true`** (both are defaults) and
returned the same 41-metric table. Re-running the echoed spec (`485 tok`) reproduced
byte-identical output (`1939 chars` both runs).

Non-default spec run (522 tok) — echoes are preserved verbatim:

```yaml
models:
  - mimo-v2-6-pro
  - muse-wonder-full
  - deepseek-v4-1-flash
metrics: benchmarks
view: diff
compact: false
```

**The spec text (echoed verbatim by the server):**

```yaml
models:
  - mimo-v2-6-pro
  - muse-wonder-full
  - deepseek-v4-1-flash
metrics: benchmarks
view: diff
compact: false
```

Re-running that exact echoed spec gave `2087 chars` both times;
`diff <(tail -n +2 runA) <(tail -n +2 runB)` → **IDENTICAL_BODIES** (only the cache-age
line, e.g. `29m ago` vs `0s ago`, differs). **Round-trip confirmed.**

**Adversarial note (FRICTION).** `compact` is documented (`aa://comparisons/spec`:
"table view only: the core rows instead of the full default set"; schema default
`true`) but its behaviour is confusing and the spec echo is lossy for defaults:
- `view=table, compact=true` (no metrics) → 8 rows; `compact=false` → 13 rows (adds
  Cache disc./Released/Params/Open weights/Effort) — so `compact` *does* work for the
  default set;
- but with `metrics=all` or an explicit metric list, `compact` is silently ignored
  (41 rows either way, `1939 chars` identical), and the echoed spec drops it.
An agent cannot tell from the echo whether `compact` was honoured.

**Verdict: CLEAN** — spec echoes are faithfully re-runnable and tables are identical.
**FRICTION:** the echoed spec omits default-valued keys (`view`/`compact`), and
`compact` is a silent no-op whenever `metrics` is supplied.

---

## 6. The bar — is there an unanswerable comparison question?

Calls (13 total, 1,608 tok).

### Found: YES — a genuinely unanswerable cost/speed comparison (Muse Wonder Full)

**Exact question:** *"Compare MiMo-V2.6-Pro and Muse Wonder Full on cost per task,
output speed, time-to-first-token and cost to run the whole Intelligence Index."*

`aa_compare '{"queries":["mimo-v2-6-pro","muse-wonder-full"],"metrics":"cost_per_task,tps,ttft,index_total_cost"}'` → 146 tok:

```
# 2 models · 4 metrics · 33m ago · aa:rsc + rich dataset
| Metric | MiMo-V2.6-Pro | Muse Wonder Full (max) |
|---|---|---|
| Cost per Task | $0.13 | - |
| Speed (output tokens/s) | 43.7 | - |
| Time to First Token | 4.1s | - |
| Cost to Run the Intelligence Index (whole suite) | $207 | - |
— metrics: cost_per_task,tps,ttft,index_total_cost
```

Every Muse cell is `-` and **`aa_compare` gives no coverage wording at all** — the
only footnotes are the metric line and the TTFT caveat. The reason is only visible
from other tools:

- `aa_model '{"query":"muse-wonder-full"}'` → `## Pricing` `no pricing recorded`;
  `## Speed` all `-` (`tok/s - TTFT - TTFA - E2E -`).
- `aa_leaderboard '{"name":"muse-wonder-full","fields":"...price_in,price_out,cost_per_task,tps,ttft..."}'` → `— no data for: In $/M, Out $/M, Cost, tok/s, TTFT (shown as -)`.
- `aa_providers '{"model":"muse-wonder-full"}'` → error: `no JSON array of dicts containing keys ['host','jsonMode','model','pricing'] in payload`.

So **AA publishes no pricing and no measured speed for Muse Wonder Full** → the
question is unanswerable *with the data AA publishes*, and the comparison tool does
not say so.

### Also found: a tool-level blind spot — published security data that `aa_compare` cannot see

**Exact question:** *"Compare MiMo-V2.6-Pro and DeepSeek V4.1 Flash on the AA Cyber
Index and CWE-Bench-AA."*

`aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash"],"metrics":"cyberIndex,cweBench,cybergymE2e,deepsecBench"}'` → 120 tok:

```
# 2 models · 4 metrics · 35m ago · aa:rsc + rich dataset
| Metric | MiMo-V2.6-Pro | DeepSeek V4.1 Flash (max) |
|---|---|---|
| Artificial Analysis Cyber Index | - | - |
| CWE-Bench-AA | - | - |
| CyberGym-E2E-AA | - | - |
| DeepSecBench-AA | - | - |
```

But the data **does exist and is published** — the same models, same session:

```
# 20 of 20 scored (700 tracked) · AA Cyber Index · AA chart set — not a full leaderboard
| MiMo-V2.6-Pro | mimo-v2-6-pro | 56.1 |
| DeepSeek V4.1 Flash (Max) | deepseek-v4-1-flash | 40.8 |

# 20 of 20 scored (700 tracked) · CWE-Bench-AA · AA chart set — not a full leaderboard
| DeepSeek V4.1 Flash (Max) | deepseek-v4-1-flash | 68.3% |
| MiMo-V2.6-Pro | mimo-v2-6-pro | 63.3% |
```

So through the comparison tool the question is unanswerable, even though AA publishes
both scores; the compare tool silently dashes them (chart-set metrics live outside
the rich dataset `aa_compare` reads). `metrics=all` omits them too.

### Closest call & the server's own coverage wording

The nearest thing to a *truly* impossible question is the Muse cost/speed one above.
For everything else, the server has explicit coverage/limit wording:

- `aa_compare`: **no coverage wording** — only `— metrics: …`, `— TTFT is AA's
  long-prompt median`, `— metrics=all: every rankable key any of these models has`.
- `aa_benchmark_leaderboard`: `AA chart set — not a full leaderboard` and
  `rich dataset — not a full leaderboard`.
- `aa_leaderboard` (per-row gaps): `— no data for: In $/M, Out $/M, Cost, tok/s,
  TTFT (shown as -)`.
- `aa_benchmarks` catalog column: `model page only (not in the rich dataset)`,
  `chart set only (not fetched)`, `rich dataset (27/700)`.
- `aa_leaderboard sort=cyberIndex` → error: `'AA Cyber Ind' has no values in the
  700-row leaderboard — it is chart-set / model-page only. — rank it with
  aa_benchmark_leaderboard benchmark=<slug>, or read one model with aa_model <slug>.`
- `aa_leaderboard sort=coding` → error: `'Coding': AA exposes this index per model
  only on the scrape source (model pages) and through the JSON API (AA_API_KEY) —
  there is no cross-model ranking to sort by.`
- `aa_model`: `— Coding Index, Agentic Index need AA_API_KEY (JSON API); unavailable
  on the scrape source`.

**Answer to the bar:** *Yes* — a cost/speed comparison against Muse Wonder Full is
unanswerable with AA's published data, and *a security comparison via `aa_compare` is
unanswerable even though the data is published*. Both stem from the same root cause:
**`aa_compare` emits `-` with no coverage note, whereas `aa_leaderboard` /
`aa_benchmark_leaderboard` explain every gap.** For the user's stated bar, `aa_compare`
is the one tool that does not meet it.

**Verdict: FRICTION** — the data model is honest everywhere *except* the flagship
comparison tool, which is exactly where the user's bar lives.

---

## Closing — what I would still change

1. **`aa_compare` should carry coverage wording.** Append a `— no data for: <model>:
   <metrics>` / `— <metric> is chart-set (use aa_benchmark_leaderboard)` footnote
   whenever a requested metric is `-` for a model. Today only `aa_leaderboard` does
   this; the comparison tool (the user's bar) is silent.
2. **`aa_compare` should reach chart-set metrics** (Cyber Index, CWE-Bench,
   CyberGym, DeepSec, LiveCodeBench, AA-3D) or explicitly say "not comparable here —
   use `aa_benchmark_leaderboard`". Currently `metrics=all` silently drops them, so
   an agent comparing security postures sees a wall of dashes and no pointer.
3. **Label blank cells in `aa_compare`.** Three MiMo rows (`Harvey LAB-AA`,
   `ITBench-AA SRE`, `MMMU-Pro`) are `-` with no marker; a `(no data)` tag or a
   footer would remove the ambiguity.
4. **Fix the `aa_benchmarks` "not fetched" label** for AA-3D Elo — the leaderboard
   tool fetches it live (`3 of 21 scored`, `0s ago`); "not fetched" is wrong.
5. **Improve `aa_benchmarks` recall for `security`** — `query:"security"` returns
   1 of 8 security rankables; `query:"cyber"`/`domain:"security"` return 7–8.
6. **`compact` semantics.** Make it a no-op-with-warning (or honoured) when `metrics`
   is given, and include it in the echoed spec so the round-trip is lossless.
7. **Coding/Agentic Index gap.** They are the two indexes a coding comparison most
   wants, yet they need `AA_API_KEY` and have no cross-model ranking. Surface them
   per-model in `aa_model` where possible, or state clearly at `aa_compare` time.
