# Round 3 — spot check (post-fix confirmation)

Agent: `EvalR3` · date 2026-10-14 · harness: `.venv/bin/python eval/client.py` only.
Token costs are the harness-reported `chars/4` estimates (printed to stderr for `call`,
recorded in `eval/runs/live.ndjson` for `read`).

---

## 1. LiveCodeBench leader + `mistral-large-4` rank

Calls:
- `aa_benchmarks '{"query":"livecodebench"}'` → 63 tok
- `aa_benchmark_leaderboard '{"benchmark":"livecodebench","top":10}'` → 237 tok
- `aa_benchmark_leaderboard '{"benchmark":"livecodebench","creator":"Mistral","top":20}'` → 351 tok
- `aa_benchmark_leaderboard '{"benchmark":"livecodebench","creator":"Mistral","top":40,"fields":"name,slug,livecodebench"}'` → 396 tok
- `aa_model '{"query":"mistral-large-4","sections":"indexes,benchmarks"}'` → 287 tok

**Leader: Gemini 3 Pro Preview (High)** — slug `gemini-3-pro`, **91.7 %**, Intel 28.0.
Runners-up: `gemini-3-flash-reasoning` 90.8 %, `deepseek-v3-2-speciale` 89.6 %,
`glm-4-7` 89.4 %, `gpt-5-2-medium` 89.4 %, `gpt-5-2` (Xhigh) 88.9 %.

**`mistral-large-4` (Mistral Large 4 Preview, Intel 38.4): not ranked — it carries no
LiveCodeBench score.** The model digest's Benchmarks section lists 15 evals and
LiveCodeBench is not among them; the Mistral-filtered leaderboard enumerates all
**28 of 28** scored Mistral variants and `mistral-large-4` is absent
(the newest Mistral Large with a score is `mistral-large-3` at 46.5 %).

**Subset vs full leaderboard: it is a subset, and the tool says so — labelled.**
- `aa_benchmark_leaderboard` header: `rich dataset — not a full leaderboard`.
- `aa_benchmarks` catalog for `livecodebench`: coverage = **"chart set only"**.
Header also reads `10 of 343 scored (700 tracked)`; 343 is the scored-row pool the
call drew from, not a public leaderboard size. Note the *omission* of an unscored
model is silent — only `aa_model` makes "no score for this model" explicit.

**Verdict: CLEAN** — leader + subset labelling are correct and the missing score is
consistent across tools (though an explicit "unscored on livecodebench" line would help).

---

## 2. Legal capability top 5 + `gemini-4-argon`

Calls:
- `aa_leaderboard '{"sort":"capabilities.legal","top":5}'` → 198 tok
- `aa_model '{"query":"gemini-4-argon","sections":"indexes,benchmarks"}'` → 282 tok
- `aa_leaderboard '{"name":"gemini-4-argon","fields":"name,capabilities.financeAndAccounting,capabilities.strategyAndOps,capabilities.legal,capabilities.healthcareAndMedical,capabilities.engineering,capabilities.economics,briefcaseElo"}'` → 100 tok

**Legal capability index, top 5** (header: `5 of 270 scored · Cap Legal, active only`):

| # | Model | Slug | Cap Legal | Intel | $/Task |
|---|---|---|---|---|---|
| 1 | Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | 63.3 | 57.6 | $5.98 |
| 2 | Claude Fable 5.1 (Xhigh, Default Fallback) | `claude-fable-5-1-xhigh` | 60.8 | 53.2 | $5.98 |
| 3 | Claude Opus 5.5 (Xhigh, Default Fallback) | `claude-opus-5-5-xhigh` | 60.8 | 56.0 | $3.46 |
| 4 | Claude Fable 5.1 (Max, Default Fallback) | `claude-fable-5-1` | 60.5 | 53.4 | $7.63 |
| 5 | Gemini 4 Argon (High) | `gemini-4-argon` | 60.0 | 52.6 | $1.99 |

(2nd/3rd are tied at 60.8.)

**`gemini-4-argon` capability indexes — 5 of 6 present, the 6th is null:**

| Capability index | Score |
|---|---|
| Finance & Accounting | 53.8 |
| Strategy & Ops | 56.2 |
| Legal | 60.0 |
| **Healthcare & Medical** | **null (not reported)** |
| Engineering | 55.2 |
| Economics | 60.4 |

The dedicated call labels this: `— no data for: Cap Medical (shown as -)`, and the
model digest prints the capability table with the row omitted. The reference explains
why: "Members of a capability index are null for models missing any constituent
evaluation." So Healthcare & Medical is **not labelled as missing in the raw table**;
it is labelled only by the `no data for:` footnote / absence. `claude-opus-5-5`, by
contrast, has all six (Medical 60.5).

**`gemini-4-argon` AA-Briefcase Elo = 1488** (private set, 95 % CI not requested).

**Verdict: CLEAN** — ranking and scores are consistent across the three calls; the
null 6th capability is honestly flagged, not fabricated.

---

## 3. "opus max" + BFCL + MathVista

Calls:
- `aa_search '{"query":"opus max"}'` → 21 tok → **`no models match 'opus max'`**
- `aa_search '{"query":"opus"}'` → 349 tok → resolves
- `aa_benchmarks '{"query":"bfcl"}'` → 24 tok (error) → `no benchmark matches 'bfcl' — closest: briefcaseElo, ifbench`
- `aa_benchmark_leaderboard '{"benchmark":"bfcl","top":3}'` → 43 tok (error) → `unknown benchmark 'bfcl' … closest: briefcaseElo, ifbench`
- `aa_benchmarks '{"query":"mathvista"}'` → 24 tok (error) → `no benchmark matches 'mathvista' — closest: math500, agentic`
- `aa_benchmarks '{"query":"function"}'` → 33 tok (error) → closest `AutomationBench, coding, scicode, ifbench, agentic`

**"opus max" resolves to `claude-opus-5-5` = Claude Opus 5.5 (Max, Default Fallback)**,
Intel 57.6, $5.98/task. The literal two-word phrase does **not** match
(`aa_search` does contiguous substring matching), so the resolution required the
broader `query:"opus"` (15 of 20 rows). Highest-intel Opus variant = `claude-opus-5-5`.

**BFCL: AA does not track it.** No `bfcl` benchmark exists on the server (not in the
67-entry catalog, not in the accepted field list) — so there is **no BFCL score for any
frontier model**; the request is refused with `unknown benchmark 'bfcl'` (closest slugs
`briefcaseElo`, `ifbench`). **MathVista: not tracked either** (closest `math500`,
`agentic`). Function-calling coverage is only `tau2` / `tauBanking` / `ifbench` /
`when2call`.

**Verdict: FRICTION** — the tool correctly refuses unknown benchmarks, but a two-token
non-contiguous name ("opus max") silently returns nothing instead of tokenising/match
-all.

---

## 4. `kimi-k3` endpoints

Calls:
- `aa_search '{"query":"kimi-k3"}'` → 66 tok → `kimi-k3` (Kimi K3 (Max), Intel 43.6, $2.00) + `kimi-k3-low`
- `read aa://reference/providers` → 120 tok
- `aa_providers '{"model":"kimi-k3"}'` → 269 tok (15 of 18)
- `aa_providers '{"model":"kimi-k3","top":18}'` → 313 tok
- `aa_providers '{"model":"kimi-k3","top":18,"fields":"host,precision,ttft,context_tokens"}'` → 204 tok
- `aa_providers '{"model":"gpt-oss-120b","top":6,"fields":"host,precision,ttft"}'` → 92 tok
- `aa_providers '{"fields":"host,model,precision","top":20,"sort":"price_in"}'` → 264 tok
- `aa_providers '{"host":"Modular","fields":"model,host,precision","top":6}'` → 113 tok
- (`fields:"…quantization…"` rejected → 52 tok error: `unknown field 'quantization' — closest: AutomationBe, AutomationBench, …`)

**Endpoints: 18** (`# 18 of 18 endpoints · Kimi K3 (Max) (aa.kimi-k3)`).

**Cheapest: Makora, `$1.18` per task** (in $1.53/M, out $12.75/M). Runner-up LithosAI
`$1.69`. Note the "cheapest" answer is metric-dependent: LithosAI has the lowest output
price ($12.00/M vs Makora $12.75/M), Makora has the lowest input price ($1.53/M) and is
cheapest on AA's own $/task. Most expensive: Nebius $9.22/task.

**Best TTFT: LithosAI (ULTRA CHAT) — `0.7s`** (vs LithosAI / LithosAI FAST / Baseten
0.8s, LithosAI ULTRA 0.8s; worst = Kimi first-party 3.2s). The TTFT winner is one of the
more expensive endpoints ($3.93/task).

**Quantization: none reported.** Every one of the 18 endpoints shows `-` in the
Precision column, and the response footnotes it: `— no data for: Precision (shown as -)`.
I confirmed this is not a kimi-k3 gap: `gpt-oss-120b` (6 endpoints), the Modular
NVFP4-tagged models, and the 1,201-row global board (`sort=price_in`, 20 rows) all show
`-` too. The server is *labelled* here (column plus `no data for:` footnote) but the
`precision` field — advertised in the tool description and in
`aa_reference topic=providers` — is **uniformly empty in practice**.

**Context window: `1.0M`, and it is MODEL-LEVEL, not per-endpoint** — the response
states this explicitly: `— context is model-level, not per-endpoint`. Same 1.0M on all
18 rows.

**Verdict: FRICTION** — endpoint/pricing/TTFT data is good and the context scoping is
labelled correctly, but the advertised per-endpoint quantization/precision tag is empty
for every endpoint on the server.

---

## 5. Consistency: `claude-opus-5-5` across three tools

Calls (the only way to get `aa_compare` to run is with ≥2 models — see below):
- `aa_leaderboard '{"name":"claude-opus-5-5","fields":"name,slug,intelligence,cost_per_task,tps,ttft,context_tokens,cache_read"}'` → 195 tok
- `aa_model '{"query":"claude-opus-5-5","sections":"indexes,pricing,speed"}'` → 333 tok
- `aa_compare '{"queries":["claude-opus-5-5","claude-opus-5-5-xhigh"],"metrics":"intelligence,cost_per_task,tps,ttft,context_tokens,cache_read"}'` → 98 tok
- (single-model `aa_compare` rejected first → 17 tok: `aa_compare takes 2-6 models; got 1`)

| Metric | `aa_leaderboard` | `aa_model` | `aa_compare` | Δ |
|---|---|---|---|---|
| Intelligence | 57.6 | 57.6 | 57.6 | none |
| $/task | $5.98 | $5.98 | $5.98 | none |
| tok/s | 95.2 | 95.2 | 95.2 | none |
| TTFT | 679.2 s | 679.2 s | 679.2 s | none |
| Context | 1.0 M | 1.0 M | 1.0 M | none |
| Cache-read $/M | $0.20 | $0.20 | $0.20 | none |

**No value differs beyond rounding — every one of the six metrics is identical across
all three tools.** The three sources are also mutually annotated: `aa_leaderboard`
header says `Intel, active only`; `aa_model` notes `speed from the model page
(first-party measurement); aa_leaderboard reports the leaderboard snapshot and may
differ slightly`; `aa_compare` notes `TTFT is AA's long-prompt median`. The only number
that *looks* different is the TTFT breakdown inside `aa_model` — `TTFT by prompt: medium
455.9s · long 679.2s · 100k 769.4s` — and 679.2s (the long-prompt median, also the
compare/leaderboard figure) is the one all three headline tables report. So there is
nothing to arbitrate; if a future round *did* show drift I would trust `aa_model`
(first-party measurement, with per-prompt-type breakdown) over the leaderboard snapshot.

**Verdict: CLEAN** — perfect agreement; the only irritant is that `aa_compare` refuses a
single model, forcing a filler column.

---

## 6. Token cost per call + total

Harness-reported costs (chars/4); `tools`/`schema`/`resources`/`prompts` are **not
logged or printed** by the harness, so their cost is unmeasured (~2 full `schema` dumps
and 1 `tools` inventory were run and are excluded below).

| # | Call (args abbreviated) | tok | err |
|---|---|---|---|
| 1 | `read aa://reference/indexes` | 276 | – |
| 2 | `read aa://reference/fields` | 440 | – |
| 3 | `read aa://reference/providers` | 120 | – |
| 4 | `aa_benchmarks {"query":"livecodebench"}` | 63 | |
| 5 | `aa_search {"query":"mistral-large-4"}` | 60 | |
| 6 | `aa_benchmark_leaderboard {"benchmark":"livecodebench","top":10}` | 237 | |
| 7 | `aa_benchmark_leaderboard {"benchmark":"livecodebench","creator":"Mistral","top":20}` | 351 | |
| 8 | `aa_model {"query":"mistral-large-4","sections":"benchmarks,indices,…"}` | 43 | ✗ |
| 9 | `aa_model {"query":"mistral-large-4","sections":"indexes,benchmarks"}` | 287 | |
| 10 | `aa_benchmark_leaderboard {…,"creator":"Mistral","top":40,"fields":"…"}` | 396 | |
| 11 | `aa_leaderboard {"sort":"capabilities.legal","top":5}` | 198 | |
| 12 | `aa_search {"query":"gemini-4-argon"}` | 59 | |
| 13 | `aa_model {"query":"gemini-4-argon","sections":"indexes,benchmarks"}` | 282 | |
| 14 | `aa_leaderboard {"name":"gemini-4-argon","fields":"…capabilities…"}` | 100 | |
| 15 | `aa_search {"query":"opus max"}` | 21 | |
| 16 | `aa_benchmarks {"query":"bfcl"}` | 24 | ✗ |
| 17 | `aa_benchmarks {"query":"mathvista"}` | 24 | ✗ |
| 18 | `aa_benchmark_leaderboard {"benchmark":"bfcl","top":3}` | 43 | ✗ |
| 19 | `aa_search {"query":"opus"}` | 349 | |
| 20 | `aa_benchmarks {"query":"function"}` | 33 | ✗ |
| 21 | `aa_providers {"model":"kimi-k3"}` | 269 | |
| 22 | `aa_search {"query":"kimi-k3"}` | 66 | |
| 23 | `aa_providers {"model":"kimi-k3","top":18}` | 313 | |
| 24 | `aa_providers {"model":"kimi-k3",…,"fields":"…quantization…"}` | 52 | ✗ |
| 25 | `aa_providers {"model":"kimi-k3","top":18,"fields":"host,precision,ttft,context_tokens"}` | 204 | |
| 26 | `aa_providers {"model":"gpt-oss-120b","top":6,"fields":"host,precision,ttft"}` | 92 | |
| 27 | `aa_providers {"fields":"host,model,precision","top":20,"sort":"price_in"}` | 264 | |
| 28 | `aa_providers {"host":"Modular","fields":"model,host,precision","top":6}` | 113 | |
| 29 | `aa_model {"query":"claude-opus-5-5","sections":"indexes,pricing,speed"}` | 333 | |
| 30 | `aa_compare {"queries":["claude-opus-5-5"]}` | 17 | ✗ |
| 31 | `aa_leaderboard {"name":"claude-opus-5-5","fields":"…"}` | 195 | |
| 32 | `aa_compare {"queries":["claude-opus-5-5","claude-opus-5-5-xhigh"],"metrics":"…"}` | 98 | |

**Logged calls: 32 · total ≈ 5 422 tok (21 637 chars).**
Plus 3 unlogged metadata commands (`tools`, `schema` ×2) the harness does not meter.
Errors cost ~213 tok combined (7 failed calls), i.e. cheap.

**Worst value for the question it answered: call #10**
(`aa_benchmark_leaderboard … creator=Mistral, top=40`, **396 tok**). It answered only
the *negative* "`mistral-large-4` is not in the Mistral LiveCodeBench set" — already
established by call #9 (`aa_model`, which listed no LiveCodeBench row) and strongly
implied by call #7 (`20 of 28 scored`, no Large-4). Runner-up: call #19
(`aa_search "opus"`, **349 tok**) returned a 15-row leaderboard to answer a one-line
name resolution whose answer was the first row.

---

## Verdict summary

| # | Item | Verdict |
|---|---|---|
| 1 | LiveCodeBench leader / mistral-large-4 rank / subset labelling | **CLEAN** |
| 2 | Legal top 5 / gemini-4-argon six capabilities + Briefcase Elo | **CLEAN** |
| 3 | Resolve "opus max" / BFCL / MathVista | **FRICTION** |
| 4 | kimi-k3 endpoints / cheapest / TTFT / quantization / context scope | **FRICTION** |
| 5 | claude-opus-5-5 across leaderboard/model/compare | **CLEAN** |

## What I would still change in the server

1. **`aa_providers` precision field is dead weight.** `precision` is accepted, rendered
   as a column and documented in the tool description + `aa_reference topic=providers`,
   yet it is empty for 100 % of the 1,201 endpoints I sampled (kimi-k3 ×18, gpt-oss-120b,
   Modular NVFP4 models, global board). Either populate it from the endpoint slug or drop
   the column and state plainly that quantization is not tracked.
2. **`aa_search` should tokenise non-contiguous names.** `"opus max"` → no match even
   though `Claude Opus 5.5 (Max, Default Fallback)` exists; only `"opus"` works. Split
   the query on whitespace and AND the tokens (or fall back to fuzzy on a miss).
3. **`aa_compare` should accept 1 model** (or explicitly redirect to `aa_model`);
   "2-6" forces a filler column to read one model's row.
4. **Benchmark leaderboard should say "no score for this model" instead of silently
   omitting it.** A name filter on `aa_benchmark_leaderboard` (like `aa_leaderboard`'s
   `name=`) would let a user ask "where does X rank?" and get "unscored" rather than a
   truncated list.
5. **Reconcile the coverage labels.** `aa_benchmarks` says `livecodebench` is
   "chart set only" while `aa_benchmark_leaderboard` reports `343 scored`; state the
   actual scored-model count and the provenance in one place so the two can be trusted
   together.
6. **Benchmark-gap note.** BFCL and MathVista are simply absent; a one-line "not
   tracked by AA" in `aa_benchmarks` output (rather than only a closest-match list)
   would make "does AA track X?" self-evident.
