# Round 1 — evaluation by `EvalR1a`

Scope: questions 1–6 only (assigned). Every data point below came from
`eval/client.py` against a single MCP session; no curls, no web, no `src/` reading.
All data flags `aa:rsc` (scraped) and is dated 2026-10-14.

Legend for calls: `tool {args}` ✔ = succeeded, ✗ = errored.

---

## Q1 — Smartest model, cost per task, effort setting

**Answer:** **Claude Opus 5.5 (Max, Default Fallback)** — slug `claude-opus-5-5`
(Anthropic, released 2026-09-22).
- Intelligence (Index v4.3.2): **57.6** (rank 1 of 700).
- Cost per task (cache-aware, AA's blend): **$5.98/task** (input $3.60, cache-read
  $2.42, cache-write $1.07, output $2.38, of which reasoning $1.68).
- List price: **$4.00 / 1M input**, **$20.00 / 1M output**.
- Effort setting: **Max** (reasoning effort = max). Runner-up is the *Xhigh*
  variant `claude-opus-5-5-xhigh` at Intel 56.0 / $3.46.

**Calls (4, of which 3 to land the answer):**
1. ✔ `aa_leaderboard {"top":3,"sort":"intelligence"}`
2. ✗ `aa_model {"query":"claude-opus-5-5","sections":["specs","cost","speed"]}` → rejected: `sections` must be a string, not a list.
3. ✗ `aa_model {"query":"claude-opus-5-5","sections":"specs,cost"}` → `unknown section(s) specs — valid: identity, indexes, benchmarks, pricing, speed, cost, openness, modalities, all`.
4. ✔ `aa_model {"query":"claude-opus-5-5","sections":"identity,indexes,cost"}` → Intel 57.6, cost breakdown, `reasoning (max)`.

**First tool right?** Yes — `aa_leaderboard sort=intelligence` is exactly the routed
tool and it answered the whole question in one call. It also made the *effort*
question ambiguous, though (see friction).

**Friction:**
- **`aa_model.sections` schema is undiscoverable and rejects the natural form.**
  The tool listing shows only `params: query, refresh, sections` with no type or
  allowed values. I guessed a JSON list (natural for "sections"), got a pydantic
  error, then guessed `"specs"` (the word in the tool description: *"specs, indices,
  benchmarks…"*) and got another error. The valid names (`identity`, `pricing`,
  `cost`, …) are **not** the words used in the docstring. Output:
  `Tool 'aa_model' rejected arguments: ['sections'] / Input should be a valid string`.
  The server should document `sections` as a comma-separated string with the valid
  names inline (or accept a list).
- **The `Effort` field exists but is always null, so effort had to be inferred from
  the display name.** I asked for it explicitly:
  `aa_leaderboard {"name":"Claude Opus 5.5","fields":"model,slug,effort,reasoning,intelligence,cpt,ctx,license","top":6}`
  → returned only `Model | Slug | Reasoning | Intel | Cost | Ctx`. The `effort` and
  `license` columns were **silently dropped**; `reasoning` only says `yes`. The
  effort value `Max` lives only inside the model *name* string
  `"Claude Opus 5.5 (Max, Default Fallback)"`. The server should expose `effort`
  as a real field (and should not drop requested columns without saying so).
- **The `", Default Fallback"` suffix in the name is unexplained.** `aa://reference`
  never defines it; I had to ignore it. It reads as a routing detail leaking into a
  user-facing model name.

---

## Q2 — Cheapest model above Intelligence 40; fastest output

**Answer (two parts):**
- Cheapest model above Intel 40: **Claude Haiku 5.5 (Xhigh)** — slug
  `claude-haiku-5-5-xhigh` — **$0.12/task**, Intel **41.2**, 1.0M ctx. Next:
  `gpt-6-1-sol-low` ($0.13, Intel 42.1) and `mimo-v2-6-pro` ($0.13, Intel 46.3).
  If you weight cost/quality rather than literal cheapest, **MiMo-V2.6-Pro** at
  $0.13 / Intel 46.3 is the standout for a bulk pipeline.
- Fastest output generation: **Celeris-1** (`celeris-1`, Celeris) — **1549.2 tok/s**,
  then Mercury 2.5 (`mercury-2-5`, 761.8 tok/s), Gemini 3.5 Flash-Lite
  (`gemini-3-5-flash-lite`, 407.6 tok/s). Note the speed leaders are low-intelligence
  models (Celeris-1 Intel 6.3); among models ≥ Intel 40, **Claude Haiku 5.5 (Max)**
  (`claude-haiku-5-5`) leads at **237.3 tok/s** (Intel 43.4, $0.21/task), then Muse
  Spark 1.3 (Xhigh) 213.1 tok/s, Ling 3.1 Flash 209.0.

**Calls (3):**
1. ✔ `aa_leaderboard {"top":5,"sort":"cost","min_intelligence":40}` → `# 5/700 models · Cost, active only, intel>=40`.
2. ✔ `aa_leaderboard {"top":5,"sort":"speed"}` → header `tok/s` confirms speed = tok/s.
3. ✔ `aa_leaderboard {"top":5,"sort":"speed","min_intelligence":40}` → the ≥40 speed ranking.

**First tool right?** Yes — `aa_leaderboard` is the routed tool and both filters
(`sort`, `min_intelligence`) worked first try.

**Friction:**
- **"Cheapest" is under-specified and the tool gives no help.** For a *bulk*
  pipeline the relevant metric is $/task, but a user could mean $/M input. There is
  no `sort=input`-style option here (and on `aa_providers` `sort=input` is silently
  ignored — see Q4), so the meaning of "cheapest" can't be switched. Minor, but a
  `sort=price_in` would remove the guess.
- **`min_intelligence` silently excludes rows without a measured Intelligence score.**
  The output does disclose it (`— 10 rows skipped: no measured intelligence (AA has
  intelligence for 690/700 variants)`), which is the right behavior — noting it as
  *good* friction-handling rather than a defect.
- **The two halves of the question want different sort keys in one tool**, and the
  tool does not hint that `sort=tps` (not `sort=speed`) is the canonical key — the
  `sort=speed` alias worked, but `aa://reference` says "bulk generation →
  `sort=tps`", i.e. two names for the same thing with no alias list.

---

## Q3 — Claude Opus 5.5 vs GPT-6 Astra

Ambiguity: both names have 5 effort variants. Compared the headline (Max) variants
`claude-opus-5-5` vs `gpt-6-astra`.

**Answer:**

| Metric | Claude Opus 5.5 (Max) | GPT-6 Astra (Max) |
|---|---|---|
| Intelligence | **57.6** | 52.7 |
| $/task (cache-aware) | $5.98 | **$3.26** |
| Input / 1M | **$4.00** | $10.00 |
| Output / 1M | **$20.00** | $50.00 |
| Output speed | **94.8 tok/s** | 61.3 tok/s |
| TTFT (long-prompt median) | 650.1 s | **284.2 s** |
| Context window | 1.0M | 1.0M |

**Better value: GPT-6 Astra (Max).** Intel per $/task = 57.6/5.98 = **9.6** for
Opus 5.5 vs 52.7/3.26 = **16.2** for Astra — Astra buys ~68% more intelligence per
dollar and is ~35% faster to first token. Opus 5.5 is the smarter model (and wins on
list $/1M rates), but not the better value.

**Calls (5):**
1. ✔ `aa_search {"query":"GPT-6 Astra"}` → `gpt-6-astra` etc.
2. ✔ `aa_search {"query":"Claude Opus 5.5"}` → `claude-opus-5-5` etc.
3. ✔ `aa_compare {"queries":["claude-opus-5-5","gpt-6-astra"]}` → default rows (no context window).
4. ✔ `aa_compare {"queries":["claude-opus-5-5","gpt-6-astra"],"metrics":"intelligence,cost,speed,context"}` → same rows + `Ctx`.
5. ✔ `aa_leaderboard {"mode":"value","top":8}` → confirmed value = Intel per $/task (for the value framing).

**First tool right?** No — I picked `aa_search` first (correct, names were variant-
ambiguous), but **`aa_compare`'s default metric set omitted the context window**,
which the question explicitly asks for, forcing a second compare call with `metrics`.

**Friction:**
- **`aa_compare` default output omits context window** even though "context window"
  is a standard comparison axis. A user comparing two models for a spec decision
  gets Intel/price/speed but has to know to pass `metrics=…` for `Ctx`.
- **No direct "value" metric in `aa_compare`.** The question literally asks "which is
  better value"; `aa_leaderboard mode=value` exists but only ranks the global
  leaderboard, and `aa_compare` deliberately drops `Intel/$`. I had to compute
  9.6 vs 16.2 by hand. A `value`/`intel_per_dollar` row in `aa_compare` would
  make this a one-call answer.
- **No guidance on which effort variant to use when a bare model name is given.**
  `aa_compare {"queries":["claude-opus-5-5"]}` silently resolves to Max, but the
  column header it *prints* says `Claude Opus 5.5 (max with fallback)` while the
  leaderboard prints `(Max, Default Fallback)` — two different renderings of the
  same variant across tools (see contradictory-numbers/consistency note below).
- **TTFT = 650 s for Opus 5.5** is a huge, credibility-tugging number. It is the
  long-prompt median, but the question ("snappiest") and this comparison invite the
  reader to think it is per-request latency. The `aa_compare` table gives no unit
  note; only `aa_leaderboard` appended `— TTFT is AA's long-prompt median`.

---

## Q4 — Cheapest API provider for DeepSeek V4.1 Flash + quantization

**Answer:** Model slug `deepseek-v4-1-flash` = **DeepSeek V4.1 Flash (Max)**,
Intel 39.5, $0.27/task at DeepSeek's own endpoint. 15 provider endpoints.

- **Cheapest provider: LithosAI** — **$0.15 / 1M input, $0.60 / 1M output**,
  **$0.16/task**, 503.4 tok/s. (Cheapest on every blended measure.)
- Caveat: **DeepInfra is cheapest on *input* rate alone** ($0.14/1M in, $0.42/1M
  out) but lands at $0.44/task; **GMI** is $0.18 in. So "cheapest" flips with the
  metric: LithosAI on $/task and mixed traffic, DeepInfra on pure-input-heavy
  traffic. LithosAI also resells the same model as four separately-priced endpoints
  (base `$0.15`, `FAST $0.25`, `ULTRA $0.35`, `ULTRA CHAT $0.35`).
- **Quantization: not reported.** AA exposes no precision for any of the 15
  DeepSeek V4.1 Flash endpoints — the `Precision` column is empty for every row
  (confirmed via `aa_raw` → `{"host":"LithosAI","precision":null}`). So the honest
  answer is **"AA has no quantization data for this model"**, not "FP8/BF16".

**Calls (9):**
1. ✔ `aa_search {"query":"DeepSeek V4.1 Flash"}` → `deepseek-v4-1-flash`.
2. ✔ `aa_providers {"model":"deepseek-v4-1-flash","sort":"cost"}` → 15 rows, no precision column.
3. ✗ `aa_providers {"model":"deepseek-v4-1-flash","fields":"host,model,precision,context,in,out,costPerTask,ttft,tokensPerSecond"}` → `unknown field 'tokensPerSecond' — closest: … DeepSecBench, contexttokens`.
4. ✔ `aa_providers {…,"fields":"host,model,precision,ctx,in,out,cpt,tps,ttft"}` → still no Precision column.
5. ✔ `aa_providers {"model":"deepseek-v4-1-flash","fields":"host,precision"}` → only `Host` column.
6. ✔ `aa_providers {"model":"mimo-v2-6-pro","fields":"host,precision"}` → control: `GMI (BF16) | bf16`.
7. ✗ `aa_providers {"model":"deepseek-v4-1-flash","fields":"host,quantization"}` → `unknown field 'quantization'`.
8. ✔ `aa_providers {"model":"deepseek-v4-1-flash","sort":"input","fields":"host,in,out,cpt"}` → returned cost-sorted order (sort ignored).
9. ✔ `aa_raw {"kind":"providers","query":"deepseek-v4-1-flash","fields":"host,precision"}` → `"precision": null`.

**First tool right?** Mostly — `aa_providers` is the routed tool. But I needed
`aa_search` first (correct per routing) and then **six** probes to establish that
"no precision" is a data gap rather than a wrong field name.

**Friction (Q4 is the worst offender):**
- **Requested columns are dropped silently when all values are null.** Asking for
  `precision` returns a table with *no* Precision column, no warning, no
  `-` placeholders. I could not tell "AA has no data" from "your field name is
  wrong" from "this tool ignores that field". Only the control call (`mimo-v2-6-pro`
  → `GMI (BF16) | bf16`) proved the field name was right and the data was missing.
  The server should render the column with `-` and/or print `— no precision data
  for N/N endpoints`. This directly caused the extra calls.
- **`sort=input` is silently ignored** — the output came back in identical
  $/task order (`LithosAI, Parasail, Novita, DeepSeek, …`, not
  `DeepInfra $0.14, LithosAI $0.15, GMI $0.18`). Unknown sort keys should error with
  the valid list (the tool *does* validate `fields`, so the inconsistency is jarring).
- **The valid speed field name is `tps`; the tool description calls it "speed"** and
  the error message for `tokensPerSecond` did *not* suggest `tps` either (it
  suggested unrelated benchmark names). A user guessing `speed`/`tokensPerSecond`/
  `tokps` will flail inches from the answer.
- **"Cheapest" is ambiguous and the tool offers no side-by-side.** The cheapest
  provider on $/task (LithosAI) differs from the cheapest on input rate
  (DeepInfra); nothing in `aa_providers` ranks by a chosen price component, so the
  answer depends on a metric the caller cannot select.
- **Host naming embeds the tier**: `LithosAI`, `LithosAI (FAST)`, `LithosAI (ULTRA)`,
  `LithosAI (ULTRA CHAT)` look like four different providers in the Host column but
  are one reseller with four endpoint pricing tiers. Easy to miscount "providers".

---

## Q5 — Snappiest models (lowest TTFT) without falling below Intelligence 45

**Answer:** **GPT-6 Astra (Low)** — `gpt-6-astra-low` — **TTFT 2.5 s**, Intel 45.8,
1.0M ctx, $0.82/task, 52.3 tok/s. Runners-up (all Intel ≥ 45):
- `qwen3-8-max` (Qwen3.8 Max 0902) — 3.0 s, Intel 45.4
- `claude-fable-5-1-low` (Claude Fable 5.1 Low) — 3.1 s, Intel 46.8
- `mimo-v2-6-pro` (MiMo-V2.6-Pro) — 4.0 s, Intel 46.3, only $0.13/task
- `gpt-6-astra-medium` — 6.3 s, Intel 49.6
- `gpt-6-1-sol-medium` — 7.6 s, Intel 47.8

For a streaming chat UI the practical picks are the top three (all Intel ≥ 45 and
TTFT ≤ 3.1 s: `gpt-6-astra-low`, `qwen3-8-max`, `claude-fable-5-1-low`);
if intelligence matters more, `gpt-6-astra-medium` (Intel 49.6 / 6.3 s) is the best
quality-per-latency step up. Best cheap-and-snappy: `mimo-v2-6-pro`
(Intel 46.3 / 4.0 s / $0.13 per task).

**Calls (1):**
1. ✔ `aa_leaderboard {"top":6,"sort":"ttft","min_intelligence":45}`

**First tool right?** Yes — one call, correct tool, correct sort key. Best-executed
question of the six.

**Friction:**
- **The TTFT caveat is essential and nearly hidden.** The tool appended
  `— TTFT is AA's long-prompt median; use aa_model for the per-prompt-type
  breakdown (short/medium/long/100k)`. A chat UI is *short*-prompt, where the
  ranking can differ, but the leaderboard can only sort on long-prompt TTFT and the
  short-prompt breakdown is only in `aa_model` (one call per model, so no ranking).
  There is no way to rank the cohort by short-prompt TTFT in one call — arguably the
  single most useful thing for this question. This deserves either a `ttft_prompt=short`
  option or an explicit "leaderboard only ranks long-prompt TTFT" in the tool output.
- TTFT here is in **seconds** but the thread's other tables don't label units; only
  the appended note clarifies. Mixed-unit risk if a caller skims.

---

## Q6 — Open-weights model that beats a proprietary mid-tier on GPQA Diamond

**Answer:** **Kimi K3 (Max)** — slug `kimi-k3` (Kimi) — **open-weights**,
**GPQA Diamond 93.5%**, beating proprietary **GPT-5.5 (High)** (`gpt-5-5-high`,
93.2%) and **GPT-6 Astra (Low)** (`gpt-6-astra-low`, 93.1%).
- **License:** `Kimi K3 License`
- **Context window:** **1.0M** tokens (identity: 2800B params, 104B active,
  text+image→text, reasoning (max)).

Alternative if a bigger headline is wanted: **Qwen3.8 2.4T A95B**
(`qwen3-8-2-4t-a95b`) also scores 93.5% and is open-weights, **262k ctx**, but its
license is not exposed and its `aa_model` digest crashes (below), so Kimi K3 is the
answer I can fully support.

**Calls (7):**
1. ✔ `aa_benchmark_leaderboard {"benchmark":"gpqa-diamond","top":15}`
2. ✔ `aa_benchmark_leaderboard {"benchmark":"gpqa-diamond","open_weights":true,"top":10}`
3. ✔ `aa_benchmark_leaderboard {"benchmark":"gpqa-diamond","top":40,"fields":"model,slug,creator,gpqa,openweights,intelligence,cost"}` → found the 93.5/93.2 proprietary-vs-open crossing.
4. ✗ `aa_model {"query":"qwen3-8-2-4t-a95b","sections":"identity"}` → **crash**, raw Python traceback.
5. ✔ `aa_model {"query":"kimi-k3","sections":"identity"}` → license + ctx.
6. ✔ `aa_leaderboard {"name":"Qwen3.8 2.4T A95B","fields":"model,slug,creator,license,ctx,openweights,intelligence,gpqa"}` → ctx 262k, no license column.
7. ✗ `aa_model {"query":"qwen3-8-2-4t-a95b","sections":"identity"}` (retry) → **same crash**.

**First tool right?** Yes for the benchmark (`aa_benchmark_leaderboard`,
`open_weights=true`), but the *second half* (license + context) routed to `aa_model`,
which is where the server broke.

**Friction:**
- **`aa_model` hard-crashes on `qwen3-8-2-4t-a95b` with an unhandled traceback.**
  Both attempts returned:
  ```
  File "/home/wavy/ai/aa-mcp/src/aa_mcp/loaders.py", line 438, in model
      chart = parse_chart(got.text)
  File "/home/wavy/ai/aa-mcp/src/aa_mcp/normalize.py", line 341, in from_chart
      slug = rec.get("slug") or ""
  AttributeError: 'str' object has no attribute 'get'
  ...
  UnexpectedToolError: Error executing tool aa_model
  ```
  The user-facing output is `Error executing tool aa_model` (8 tokens) after a wall
  of server source paths. This is a parser that assumes `chart` records are dicts;
  when the payload has bare strings it dies instead of skipping them. It should
  either handle the shape or return a clean "no chart data for this model" and still
  emit identity/pricing. As-is, **any question about Qwen3.8 2.4T's license or
  benchmarks is unanswerable through `aa_model`**, and the caller sees internal file
  paths rather than a recovery hint.
- **`license` is another silently-dropped column.** `fields=…,license,…` for the
  Qwen row returned no License column (null → dropped), so I could not tell whether
  the model is unlicensed in AA's data or misnamed. This is the same defect as Q4's
  `precision`: no `-` placeholder, no note.
- **"Proprietary mid-tier" is undefined.** Nothing in the tool corpus defines
  "mid-tier"; I had to choose a reference proprietary model myself (GPT-5.5 High,
  a previous-gen high-effort model, Intel 37). The server should either offer a
  tier/segment field or state the convention. The identification of the *open-weights*
  set was easy (`Open: yes/no` column exists and works), so only the "mid-tier"
  half was guesswork.
- **No license in the benchmark leaderboard.** The GPQA table gives `Open yes/no`
  but not the license or context window; answering `open-weights + license + context`
  always needs a second hop to `aa_model` (which crashed). A `fields=license,ctx`
  on the leaderboard does accept `ctx` but not usable `license`.

---

## Cross-cutting observations

- **Silent column drop is the #1 friction pattern.** `precision` (Q4), `license`
  (Q1, Q6), and `effort` (Q1) were all accepted as fields but returned **no column
  at all** when their values were null. I burned 5+ calls distinguishing "no data"
  from "wrong field". Fix: always render requested columns, use `-` for null, and
  print a one-line "no <field> data for this selection".
- **Validation inconsistency.** `fields` are strictly validated (good: the error
  lists near-miss names), but `sort` is *not* validated (`sort=input` on
  `aa_providers` silently degraded to cost order). Same tool, opposite philosophies.
- **Field-name vocabulary is a maze.** The canonical names are neither the words in
  the tool descriptions (`speed` → `tps`, `costPerTask` → `cpt`, `context` → `ctx`)
  nor suggested by the errors (`tokensPerSecond` error suggested `DeepSecBench`).
  `aa://reference` topic=fields lists every legal name, but nothing tells you to
  read it, and it contains ~300 aliases.
- **`aa_model` is fragile.** It is the routed tool for "anything about ONE model",
  yet it (a) rejects the natural `sections` list form, (b) rejects the docstring's own
  section words (`specs`), and (c) crashes outright on at least one indexed model
  (`qwen3-8-2-4t-a95b`). Two of my six questions needed it and it lost calls in both.
- **No `value`/`Intel-per-$` metric in `aa_compare`** though the routing table
  advertises "best value" as a first-class use case — it lives only in
  `aa_leaderboard mode=value`, which can't compare two arbitrary models.
- **Minor numeric drift between calls for the same metric.** Claude Haiku 5.5 (Max)
  read `237.0 tok/s` in the cost-sorted table and `237.3 tok/s` in the speed-sorted
  table, both `aa:rsc` and within the same session/cache window. Small, but a
  caller reconciling two tables (e.g. Q2's two halves) will see the same cell disagree.
- **Variant handling is repetitive but workable.** Every model has 5 effort variants
  and the question names carry them (`(Max, Default Fallback)` vs `(max with
  fallback)` across tools). The server should document that a bare slug = top
  effort, and should use one consistent display string per variant.

### Tool-choice scorecard (first tool I picked)

| Q | First tool | Right on first try? | Calls to answer |
|---|---|---|---|
| 1 | `aa_leaderboard` | Yes (answer) / no (`aa_model` sections) | 4 |
| 2 | `aa_leaderboard` | Yes | 3 |
| 3 | `aa_search` → `aa_compare` | Name resolution yes; `aa_compare` needed 2nd call for `Ctx` | 5 |
| 4 | `aa_search` → `aa_providers` | Partly; 6 probes to prove "no precision" | 9 |
| 5 | `aa_leaderboard` | Yes | 1 |
| 6 | `aa_benchmark_leaderboard` | Yes; `aa_model` crashed | 7 |
