# Round 2 — answers (evaluator `EvalR2a`)

Harness: `eval/client.py` only. Data header stamp on most calls: **live AA scraped
data, 2026-10-14, ~31–35 min cache age**. All numbers below are copied verbatim from
tool output.

Shared preamble (not counted per-question): `tools`, `prompts`, and four resource
reads `read aa://reference/metrics`, `aa://sources`, `aa://benchmarks`,
`aa://reference/fields` (one bash invocation, 4 read calls). The `fields` dump is a
token sink (~1000 tok of near-duplicate aliases) — see Friction.

---

## Q1 — "what about opus max?"

**Resolution of the ambiguity.** The literal string is not a model. `aa_search
"opus max"` returned nothing, so I re-resolved on `opus` and read the top Opus row at
Max reasoning effort.

**Answer: Claude Opus 5.5 (Max, Default Fallback)** (slug `claude-opus-5-5`), Anthropic,
released 2026-09-22.

| Metric | Value |
|---|---|
| Intelligence | **57.6** |
| In / Out | **$4.00 / $20.00** per 1M |
| Cache read / write | $0.20 / $5.00 per 1M (95% cache discount) |
| $/task | $5.98 |
| tok/s | 95.2 |
| TTFT | 679.2 s (TTFA 679.2 s, E2E 684.5 s, "Reasoning 0.0s") |
| Context | 1.0M |

Caveats I could not resolve from the tool: (a) "opus max" also matches the older
`claude-opus-5` (intel 50.8), `claude-opus-4-8/4-7/4-6`; I took the newest and highest
Opus. (b) The 679.2 s TTFT is implausible as a literal first-token latency and
contradicts the 95.2 tok/s throughput; flag below.

**Calls (4 attempts, 1 failure):**
```
call aa_search '{"query":"opus max"}'        -> no models match 'opus max'
call aa_search '{"query":"opus"}'            -> 15 variants
call aa_model  '{"query":"claude-opus-5-5","sections":"identity,indexes,pricing,speed"}'  -> FAILED: unknown section(s) indices
call aa_model  '{"query":"claude-opus-5-5","sections":"identity,indexes,pricing,speed"}'
```
**Did the tool tell me everything?** Answer set yes after resolution, but the *name*
resolution was the tool's weak point (substring search misses parenthesised variants).

---

## Q2 — most recent release + intelligence

**Answer: Meta "Muse Wonder Full (Max)"** (slug `muse-wonder-full`), released
**2026-10-12**, intelligence **55.8**.

Tie note: a second Meta model, **Muse Wonder (Max)** (`muse-wonder`, intel 52.4), shares
the same release date 2026-10-12. The board only exposes day granularity, so I cannot
say which of the two shipped first; I report the higher-intelligence one as "the model"
and disclose the tie.

**Calls (1):**
```
call aa_leaderboard '{"sort":"released","top":8,"fields":"name,creator,released,intelligence,slug"}'
```
**Did the tool tell me everything?** No — date granularity only (no timestamp), and ties
are not broken/flaggable. Otherwise sufficient.

---

## Q3 — AA-Briefcase leader, margin, leaderboard status

**Leader: Claude Sonnet 5.5 (Max, Default Fallback)** (`claude-sonnet-5-5`), **1819 Elo**
(95% CI 1808–1832). Second: Claude Opus 5.5 (Max) at 1805 (CI 1793–1817).

**Margin: +14 Elo.** But the two CIs overlap → the lead is *not* statistically decisive.

**Full leaderboard or chart subset?** A **chart subset, not a full leaderboard.** Header
literal: `rich dataset (228/700 models) — not a full leaderboard`; `aa_benchmarks`
marks AA-Briefcase Elo coverage as `chart set only`.

**Calls (1):**
```
call aa_benchmark_leaderboard '{"benchmark":"aa-briefcase","top":5,"fields":"name,creator,briefcaseElo,ci"}'
```
**Did the tool tell me everything?** Yes — including the coverage caveat and CIs.

---

## Q4 — MathVista for current frontier models

**Answer: AA has no MathVista data.** The catalog has no such benchmark (closest:
`math500`), and `aa_reference` states outright that AA does not track MathVista. I
cannot give frontier scores without inventing them, so I don't. (The nearest tracked
math/vision proxies are MATH-500, AIME 2025, and — for reasoning-with-images — MMMU-Pro,
none of which is MathVista.)

**Calls (2):**
```
call aa_benchmarks '{"query":"mathvista"}'  -> "no benchmark matches 'mathvista' — closest: math500, agentic"
call aa_reference '{}'                       -> "...AA does not track MathVista, DocVQA or BFCL..."
```
**Did the tool tell me everything?** Yes, and it told me the *honest* thing (no data)
rather than a plausible-looking number.

---

## Q5 — daily cost of 5M in + 1M out on three best-value frontier models

**Resolution of the ambiguity.** "Frontier" → `mode=frontier` (AA's Intel-vs-$/task
Pareto set); "best-value" → highest Intel per $/task (`cost_per_task`, which AA states
is already cache-aware). I excluded the $0.00 unpriced outlier K2 Horizon 375B A23B
(cost $0.00 with no cache data → 5M/1M cost is $0/undefined and its "$0" is
indistinguishable from missing data). I take the three Pareto points with the best
Intel/$.

**Assumption (stated):** raw list rates, 1M = 10^6 tokens, **no caching** (worst case),
5M input + 1M output per day.

| Model | intel | In $/1M | Out $/1M | input/day | output/day | **$/day** |
|---|---|---|---|---|---|---|
| GPT-6 Luna (High) | 32.9 | $0.10 | $0.50 | 5×0.10 = $0.50 | 1×0.50 = $0.50 | **$1.00** |
| GPT-6 Luna (Xhigh) | 34.6 | $0.10 | $0.50 | $0.50 | $0.50 | **$1.00** |
| MiMo-V2.6-Flash | 37.9 | $0.14 | $0.28 | 5×0.14 = $0.70 | 1×0.28 = $0.28 | **$0.98** |

If instead "best value" is read as `mode=value` top-3, the set becomes GPT-6 Luna
(High), GPT-6 Luna (Xhigh), Claude Haiku 5.5 (Medium) — the third also lands at $1.00/day
($0.10/$0.50). I chose the frontier definition because the reference maps "Pareto
frontier" → `mode=frontier`.

**Calls (2; one failed probe):**
```
call aa_leaderboard '{"sort":"value","min_intelligence":30,...}'  -> FAILED: unknown sort 'value'
call aa_leaderboard '{"mode":"frontier","top":12,"fields":"name,creator,intelligence,in,out,cost,slug"}'
```
**Did the tool tell me everything?** Mostly — but the correct knob is `mode=value`/`mode=frontier`
and the tool's own `sort` validator rejects `value`; I only found the right option by
reading `aa_reference`. See Friction.

---

## Q6 — providers serving Kimi K3, price, best TTFT

**Resolution.** `kimi k3` resolves to two rows: **Kimi K3 (Max)** (`kimi-k3`, intel 43.6)
and **Kimi K3 (Low)** (`kimi-k3-low`, intel 30.1). I treat the canonical `kimi-k3`
(Max) as "Kimi K3" and report Low separately.

**Kimi K3 (Max) — 15 endpoints** (In/Out, TTFT, tok/s, $/task):

| Host | In $/M | Out $/M | TTFT | tok/s | $/Task |
|---|---|---|---|---|---|
| Makora | $1.53 | $12.75 | 1.1s | 39.3 | $1.18 |
| LithosAI | $2.40 | $12.00 | 0.8s | 177.8 | $1.69 |
| Databricks | $3.00 | $15.00 | 1.0s | 101.2 | $1.85 |
| Amazon Bedrock | $3.00 | $15.00 | 1.6s | 126.6 | $1.87 |
| Inco | $3.00 | $15.00 | 1.5s | 85.2 | $1.88 |
| DigitalOcean | $3.00 | $15.00 | 1.1s | 52.2 | $1.90 |
| Fireworks | $3.00 | $15.00 | 1.0s | 110.9 | $1.91 |
| Kimi | $3.00 | $15.00 | 3.2s | 44.3 | $2.00 |
| Together AI | $2.70 | $13.50 | 1.0s | 59.4 | $2.16 |
| Baseten | $3.00 | $15.00 | 0.8s | 119.9 | $2.42 |
| Fireworks (FAST) | $4.50 | $22.50 | 1.0s | 111.2 | $2.72 |
| LithosAI (FAST) | $4.00 | $20.00 | 0.8s | 192.0 | $2.81 |
| Modal | $3.00 | $15.00 | 1.4s | 85.1 | $3.48 |
| Inco (FAST) | $6.00 | $30.00 | 1.7s | 347.1 | $3.77 |
| LithosAI (ULTRA CHAT) | $5.60 | $28.00 | 0.7s | 402.2 | $3.93 |

- **Cheapest:** Makora — $1.53/$12.75 per 1M.
- **Best TTFT:** LithosAI (ULTRA CHAT) — **0.7 s** (then four tied around 0.8 s).
- **Kimi K3 (Low)** is served by 5 hosts (Databricks, DigitalOcean, Kimi, Baseten,
  Nebius), all $3.00/$15.00; best TTFT ≈ 1.1 s (DigitalOcean/Nebius).

**Calls (5):**
```
call aa_search   '{"query":"kimi k3"}'
call aa_providers '{"model":"kimi-k3"}'                                  # cost order
call aa_providers '{"model":"kimi-k3","fields":"host,in,out,ttft","sort":"ttft"}'
call aa_providers '{"model":"kimi-k3","fields":"host,in,out,ttft,tok/s,cost_per_task"}'
call aa_providers '{"model":"kimi-k3-low","fields":"host,in,out,ttft"}'
```
**Did the tool tell me everything?** Prices/TTFT yes, but the *set of endpoints changes
with the sort key* (see Friction) — so "which providers serve it" is not a stable
answer from this tool.

---

## Q7 — video-editing top 3 vs text-to-video top 3 (editing fan footage)

**video_editing** (11 models): 1 Gemini Omni Flash 1.1 (Google, **1170** Elo, $9.64/min),
2 Wan 3.0 (Alibaba, 1156, $12.00/min), 3 Dreamina Seedance 2.5 (ByteDance Seed, 1146,
$40.82/min).
**text_to_video** (32 models): 1 Wan 3.0 (1134, $12.00/min), 2 MiniMax H3 768p (1121,
$4.80/min), 3 MiniMax H3 Max (1117, $4.80/min).

**Best pick for editing fan footage: Gemini Omni Flash 1.1.** Basis: the
`video_editing` board is the human-preference arena for *editing*; the text-to-video Elo
measures generation quality, not edit fidelity. Gemini Omni Flash 1.1 leads the editing
board (+36 over the best text-to-video model) and is cheaper than the editing #2/#3
($9.64 vs $12.00 / $40.82 per minute). Wan 3.0 is the only model strong on both boards.

**Calls (2):**
```
call aa_media '{"board":"video","top":10}'          # actually returned text_to_video
call aa_media '{"board":"video_editing","top":10}'
```
**Did the tool tell me everything?** Yes for Elo/appearances/price. Note `board=video`
silently resolved to `text_to_video` (see Friction).

---

## Q8 — coding-agent leaderboard leader

**Leader: "Claude Code" powered by Claude Sonnet 5.5 (max)** — score **68.4%**, **$14.19
per task**. Runner-up: Muse Code / Muse Wonder Full (max), 68.0%, no $/task listed.
Board size: 15/39 rows shown (`coding_agents`).

**Calls (1):**
```
call aa_agents '{}'
```
**Did the tool tell me everything?** Yes — agent, model, creator, score, $/task.

---

## Q9 — best Intel-per-$ above Intelligence 30: cheapest provider + endpoint context

**Best-value model (mode=value, intel≥30): GPT-6 Luna (High)** (`gpt-6-luna-high`),
intel 32.9, $0.10/$0.50 per 1M, $0.03/task. (The $0.00 K2 Horizon 375B A23B, intel 30.5,
is silently omitted from the value ranking — see Friction.)

**Cheapest provider:** a tie — **OpenAI and Microsoft Azure**, both $0.10 in / $0.50 out
/ $0.01 cache-read per 1M. Only those two endpoints exist (per the tool).

**Endpoint context window: NOT AVAILABLE.** Both endpoints report Ctx as `-`
(`no data for: Ctx (shown as -)`). The model-level page/leaderboard gives 1.0M, but the
*endpoint* context the question asks for is missing.

**Calls (3; 1 failed):**
```
call aa_leaderboard '{"mode":"value","min_intelligence":30,...}'
call aa_providers   '{"model":"gpt-6-luna-high","sort":"price_in",...}'  -> FAILED: unknown sort 'price_in'
call aa_providers   '{"model":"gpt-6-luna-high","fields":"host,in,out,cache_read,ctx,ttft"}'
```
**Did the tool tell me everything?** No — the headline endpoint attribute requested
(context window) is blank.

---

## Q10 — ≥400k context models; cheapest cache-read

**109 models** have context ≥ 400k (returned in full at `top=150` with cost sort;
`top<109` truncates, so 109 is the true count).

**Cheapest cache-read:**
- **Model level:** MiMo-V2.6-Flash (Xiaomi) — **$0.0028**/1M.
- **Endpoint level (cheapest serving that model):** **Makora** — **$0.0020**/1M
  (In $0.13 / Out $0.28).
- Runner-ups: MiMo-V2.6-Pro $0.0036/1M, DeepSeek V4.1 Flash $0.0060/1M.
- Caveat: several ≥400k models have **no** cache-read data (`-`): K2 Horizon 375B A23B,
  Muse Wonder Full (Max), Quasar 438B, most Amazon Nova 2.0 variants, etc., so "cheapest"
  is only among models that report a cache-read price.

**Calls (6; 2 failed probes):**
```
call aa_providers   '{"min_context":400000,"sort":"cache_read",...}'      -> FAILED: unknown sort 'cache_read'
call aa_leaderboard '{"min_context":400000,"sort":"cost_per_task","top":5,...}'
call aa_providers   '{"min_context":400000,"fields":"model,host,ctx,ttft","top":5}'   # Model column "-"
call aa_leaderboard '{"min_context":400000,"top":60,"fields":"name,creator,ctx,cache-read,cost,slug"}'
call aa_leaderboard '{"min_context":400000,"sort":"cost_per_task","top":150,"fields":...}'
call aa_providers   '{"model":"mimo-v2-6-flash","fields":"host,in,out,cache_read,ctx"}'
```
**Did the tool tell me everything?** No. There is no cache-read sort, so I had to page
109 rows and eyeball the minimum; and the provider listing across models blanks the
Model column, so the provider→model join had to be inferred.

---

## Q11 — Intelligence Index vs AA-Briefcase; is AA-Briefcase in the index?

**Difference.** The **Intelligence Index v4.3.2** is a 0–100 composite of 10 evaluations
(AA-Briefcase v1.1, GDPval-AA v2.1, AutomationBench-AA, Terminal-Bench 4.0, SciCode,
AA-LCR v1.1, AA-Omniscience, HLE, GDP.pdf, CritPt). **AA-Briefcase** is *one* long-horizon
knowledge-work benchmark inside it, reported as **Elo** with 95% CIs; it is a private set,
**not a full public leaderboard** ("chart set only").

**Is AA-Briefcase included in the index? Yes.** `aa_benchmarks` marks AA-Briefcase Elo
`Index = yes` (`index_member: true` in the raw taxonomy). Note the Elo number itself is
not fed in as Elo — the index consumes AA-Briefcase v1.1 via its normalized contribution.

**Calls (1):**
```
call aa_benchmarks '{"query":"briefcase","verbose":true}'
```
**Did the tool tell me everything?** Yes (via `aa://reference/metrics` + this call).

---

## Q12 — three picks

| Option | Pick | Model / creator | Intel | Key number | Price |
|---|---|---|---|---|---|
| (a) smartest overall | `claude-opus-5-5` | Claude Opus 5.5 (Max, Default Fallback) · Anthropic | **57.6** | top of the Intel board | $4.00/$20.00 per 1M, $5.98/task |
| (b) best value > Intel 45 | `mimo-v2-6-pro` | MiMo-V2.6-Pro · Xiaomi | 46.3 | **$0.13/task** (best Intel/$) | $0.43/$0.87 per 1M |
| (c) fastest > Intel 45 | `muse-spark-1-3-xhigh` | Muse Spark 1.3 (Xhigh) · Meta | 45.1 | **213.1 tok/s** (TTFT 29.4 s) | $1.37/task |

Note: (a) is *also* the Q1 model. (c) is fastest by throughput; it is also the lowest
TTFT among Intel≥45 rows shown, so the two speed readings agree here.

**Calls (3):**
```
call aa_leaderboard '{"sort":"intelligence","top":5,...}'
call aa_leaderboard '{"mode":"value","min_intelligence":45,"top":6,...}'
call aa_leaderboard '{"sort":"tps","min_intelligence":45,"top":6,"fields":"...tok/s,ttft..."}'
```
**Did the tool tell me everything?** Yes for all three, once the `mode=value` knob was
known.

---

## Call log (per question)

| Q | Calls | Failures |
|---|---|---|
| preamble | `tools`; `prompts`; `read` metrics/sources/benchmarks/fields | 0 |
| 1 | aa_search ×2; aa_model ×2 | 1 (bad `sections` value) |
| 2 | aa_leaderboard ×1 | 0 |
| 3 | aa_benchmark_leaderboard ×1 | 0 |
| 4 | aa_benchmarks ×1; aa_reference ×1 | 0 |
| 5 | aa_leaderboard ×2 (value probe, frontier) | 1 (unknown sort `value`) |
| 6 | aa_search ×1; aa_providers ×4 | 0 |
| 7 | aa_media ×2 | 0 |
| 8 | aa_agents ×1 | 0 |
| 9 | aa_leaderboard ×1; aa_providers ×2 | 1 (unknown sort `price_in`) |
| 10 | aa_providers ×3; aa_leaderboard ×3 | 1 (unknown sort `cache_read`) |
| 11 | aa_benchmarks ×1 | 0 |
| 12 | aa_leaderboard ×3 | 0 |
| **total** | **31 data calls + 6 preamble** | **4 failed** |

---

## Friction (blunt)

**1. Wrong/underspecified tool choice & knobs that the tool hides.**
- `aa_search "opus max"` → `no models match 'opus max' — try a shorter substring`. The
  variant names are `Claude Opus 5 (Max)`, so the two-word query the *user* uses fails;
  I had to guess a shorter substring.
- The routing text says best value/Pareto → `mode=value`/`mode=frontier`, but the `sort`
  validator advertises no such value and rejects it:
  `unknown sort 'value' — closest: gdpval, hle, tau2, slug, name`. Nothing in the
  leaderboard's own param help mentions `mode`; I only learned it from `aa_reference`.
- **Provider `sort` is self-contradictory** — its own error text lists a name it then
  rejects:
  ```
  unknown sort 'price_in' — expected one of cost_per_task, price_in, price_out, tps, ttft, intelligence, context_tokens
  ```
  `price_in` is in the "expected" list *and* was the value I passed, yet it errored.
- There is no `cache_read` sort on providers: `unknown sort 'cache_read' — expected one
  of cost_per_task, price_in, ...`. Q10's core query (cheapest cache-read) is therefore
  unanswerable by sort and requires scanning.

**2. Misleading / contradictory numbers.**
- Opus 5.5 (Max) reports `TTFT 679.2s` alongside `tok/s 95.2` and `Reasoning 0.0s`.
  A 679-second time-to-first-token is not credible as literal TTFT and directly
  contradicts 95 tok/s; `TTFA` is identical, so the field is likely reasoning-inclusive
  but is labelled plain TTFT. I reported it and flagged it; a naive agent would quote
  "opus max has 679s latency" as fact.
- Elo "lead" with overlapping CIs (Q3, Q6 media): the board says leader 1819 vs 1805 but
  the 95% CIs overlap (1808–1832 vs 1793–1817). The tool never flags that a 14-point
  margin is inside the noise.

**3. Missing data indistinguishable from a wrong field name.**
- Endpoint context window is blank exactly where the question needs it:
  ```
  # 2 endpoints · GPT-6 Luna (High) (aa.gpt-6-luna-high), by cost_per_task
  — no data for: Ctx (shown as -)
  | Host | In $/M | Out $/M | CacheRd $/M | Ctx | TTFT |
  | OpenAI | $0.10 | $0.50 | $0.01 | - | 19.1s |
  ```
  I could not tell whether `Ctx` was "no such field", "field named `context_tokens`",
  or genuinely missing — the header says "no data", so I treated it as missing.
- Same `-` for cache-read on many ≥400k models (Q10), which makes "cheapest cache-read"
  a claim over a *subset* only.

**4. Silent filter drops / unstable membership.**
- Asking for the same resource with different sorts returned **different endpoint sets**
  for Kimi K3 — both "15 endpoints", different membership:
  - cost-per-task sort included `Amazon Bedrock`, `Kimi`, `Inco (FAST)`;
  - TTFT sort replaced them with `LithosAI (ULTRA)`, `Nebius`, `Parasail`.
  So "which providers serve Kimi K3" has no single answer; a row silently appears or
  disappears depending on `sort`.
- Cross-model provider listing **blanks the model identity**:
  ```
  # 5/547 endpoints · cheapest 5 across all hosts, by cost_per_task
  — no data for: Model (shown as -)
  | Model | Host | Ctx | TTFT |
  | - | Google | 1.0M | 17.3s |
  ```
  Q10's "which providers serve the cheapest-cache-read model" required an inferred join.
- The free model `K2 Horizon 375B A23B` (cost `$0.00`) is present in the cost list and in
  `mode=frontier`, but **absent from `mode=value`** — an unpriced/free model silently
  drops out of the value ranking (or is dropped because `$0.00` is indistinguishable from
  no data).
- `aa_media board=video` silently returns the `text_to_video` board instead of erroring
  on an unknown board.

**5. Oversized output.**
- `read aa://reference/fields` dumps ~1000 tokens of near-duplicate alias spellings
  (`AA-Briefcase Elo` / `AA-Briefcase-Elo` / `AA-Briefcase_Elo` / `briefcaseElo` / …),
  and `read aa://benchmarks` embeds the full raw taxonomy. To answer a count question I
  pulled `min_context=400000 top=150` → 9 KB / 2260 tok in one shot.
- `aa_leaderboard` headers show `N/700 models` but never the *number of matches*; with a
  `top` cap you cannot tell "there are N matching" from "showing N of many". I had to
  infer the true 109 by requesting more than the count.

**6. Things I had to infer rather than read.**
- That "opus max" = `claude-opus-5-5` (newest Opus at Max effort).
- That "frontier" → `mode=frontier` and "value" → Intel per `cost_per_task` (from
  `aa_reference`, not from the tool's own parameter docs).
- The three-model set for Q5, and that the $0.00 model should be excluded.
- "fastest" in Q12 = `sort=tps` (throughput) vs `sort=ttft`; the tool offers both without
  disambiguating, and Q12c's answer happens to satisfy both.
- The provider→model join in the cross-model `aa_providers` listing (Model column `-`).
- That `mode=value`'s omission of `K2 Horizon` is intentional rather than a bug.
