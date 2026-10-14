# Round 2 — evaluation by `EvalR2b`

Scope: questions **7–12** only (assigned). Every number below came from
`eval/client.py` (MCP stdio) — no curl, no web search, no reading `src/`.
All data rides the `aa:rsc` (scraped) backend, snapshot age ~30 min, dated 2026-10-14.

Legend: ✔ = succeeded, ✗ = errored. All model prices are USD per 1M tokens unless
stated; model prices/costs are **model-level** (leaderboard/model page), not
endpoint-level, unless stated.

Setup calls (not attributed to any question), all `✔` unless noted — 13 total:
`tools`, `prompts`, `read aa://reference/metrics`, `read aa://sources`,
`read aa://benchmarks`, `read aa://reference/fields`,
`aa_reference routing` (✗ unknown topic), `read aa://reference/overview` (✗ unknown
resource), `read aa://reference/media` (✗), `read aa://reference/indexes` (✗),
`aa_reference media`, `aa_reference overview`, `aa_reference providers`.

**Q7–Q12 data calls: 7 + 1 + 5 + 3 + 1 + 4 = 21** (plus the 13 setup calls above).

---

## Q7 — Top 3 `video_editing` vs top 3 `text_to_video`: best pick for editing fan footage

**Answer: `video-editing` #1 — Gemini Omni Flash 1.1 (Google), Elo 1170, $9.64/min.**
It is the best pick *on AA's own preference data*: it tops the arena that actually
measures human preference on **edits of existing footage**, and its Elo (1170) beats
the top of the text-to-video board (Wan 3.0, 1134) while being **cheaper per minute**
than Wan 3.0 ($12.00) and ~4× cheaper than the #3 editor (Dreamina Seedance 2.5,
$40.82).

| Board (arena size) | Rank | Model | Creator | Elo | 95% CI | $/min | Appearances |
|---|---|---|---|---|---|---|---|
| **video-editing** (11) | 1 | Gemini Omni Flash 1.1 | Google | **1170** | 1149–1191 | **$9.64** | 2,012 |
| video-editing | 2 | Wan 3.0 | Alibaba | 1156 | 1138–1174 | $12.00 | 2,896 |
| video-editing | 3 | Dreamina Seedance 2.5 | ByteDance Seed | 1146 | 1125–1167 | $40.82 | 2,050 |
| **text-to-video** (32) | 1 | Wan 3.0 | Alibaba | 1134 | 1115–1153 | $12.00 | 3,718 |
| text-to-video | 2 | MiniMax H3 (768p) | MiniMax | 1121 | 1102–1140 | $4.80 | 3,637 |
| text-to-video | 3 | MiniMax H3 Max (host Fal) | Fal | 1117 | 1099–1135 | $4.80 | 5,564 |

Basis / caveats (see Friction G — these are *my* inferences, not printed by the tool):
the editing board is 11 models vs 32 for text-to-video; the two arenas are separate
human-preference Elo scales, so the cross-board gap (1170 vs 1134 = 36 pts) is **not
a validated head-to-head** — the tool states no cross-arena comparability. The 95% CIs
narrowly overlap (editing #1 low 1149 vs t2v #1 high 1153), so "the editor wins" is
directionally supported, not statistically airtight. If budget dominates, the
text-to-video #2/#3 MiniMax H3 entries ($4.80/min) are ~2× cheaper than the editing
leader, but they are generative models, not editing-specialised.

**Calls (7):**
1. ✗ `aa_media {"board":"video-editing","top":5,"fields":"elo,ci,ci_lower,ci_upper"}`
   → table returned **without any Model column** (see Friction A).
2. ✗ `aa_media {"board":"text-to-video","top":5,"fields":"elo,ci,ci_lower,ci_upper"}` → same.
3. ✔ `aa_media {"board":"video-editing","top":5}` → names returned.
4. ✗ `aa_media {"board":"video-editing","top":5,"fields":"model,slug,elo"}` →
   `unknown field 'slug' — valid: appearances, ci, ci_lower, ci_upper, creator, elo, model, name, open_weights, price, price_unit, rank, release, release_date, url`.
5. ✔ `aa_media {"board":"text-to-video","top":3}` → names returned.
6. ✔ `aa_media {"board":"video-editing","fields":"model,creator,elo,ci_lower,ci_upper,price,price_unit,appearances"}` → all 11 rows w/ CI.
7. ✔ `aa_media {"board":"text-to-video","top":3,"fields":"rank,model,creator,elo,ci_lower,ci_upper,price,appearances"}` → CI for t2v top 3.

**First tool right?** Yes (`aa_media` is the right route) — but 3 of 7 calls were
burned on the `fields` trap and the missing `slug` field. Correct route is 2 calls.

---

## Q8 — Coding-agent leaderboard leader, its model, cost per task

**Answer: Claude Code, powered by Sonnet 5.5 (max effort) (Anthropic) — 68.4%,
$14.19/task.** Board `coding_agents`; 39 rows total, top 15 shown.

| Rank | Agent | Model | Creator | Score | $/Task |
|---|---|---|---|---|---|
| 1 | **Claude Code** | **Sonnet 5.5 (max)** | Anthropic | **68.4%** | **$14.19** |
| 2 | Muse Code | Muse Wonder Full (max) | Meta | 68.0% | - |
| 3 | Claude Code | Opus 5.5 (max) | Anthropic | 66.0% | $13.04 |

The lead is 0.4 pp over #2 (Muse Code / Muse Wonder Full) — within noise, and #2 has
no cost data. #3 is the same agent (Claude Code) on the heavier Opus 5.5 (max) at a
*lower* score (66.0%) for $13.04, i.e. the top row is the costlier-of-the-two Claude
Code entries.

**Calls (1):** ✔ `aa_agents {}` — defaulted to `coding_agents` and answered in one call.

**First tool right?** Yes, entirely. The only missing field is a stated metric for
"Score" (see Friction H).

---

## Q9 — Best intelligence-per-dollar model above Intel 30: cheapest provider + that endpoint's context window

**Answer: GPT-6 Luna (High) — `gpt-6-luna-high` (OpenAI), Intel 32.9, $0.03/task,
Intel/$ = 1134.2.** It is served by exactly **2 endpoints, both at the identical list
price ($0.10 in / $0.50 out / $0.01 cache-read)** — so **no provider is strictly
cheapest; OpenAI and Microsoft Azure tie**. On speed Azure is the better endpoint
(172.1 vs 128.2 tok/s; TTFT 18.5 s vs 19.1 s). **The endpoint's context window is not
exposed** by the provider view (both rows show `-`); the model-level context is
**1.0M** (leaderboard and model page agree).

Value top 5 (Intel ≥ 30, `mode=value`, Intel/$ = Intel per $/task):

| Model | Slug | Intel | $/Task | tok/s | TTFT | Ctx | Intel/$ |
|---|---|---|---|---|---|---|---|
| **GPT-6 Luna (High)** | `gpt-6-luna-high` | 32.9 | $0.03 | 128.2 | 19.1s | 1.0M | **1134.2** |
| GPT-6 Luna (Xhigh) | `gpt-6-luna-xhigh` | 34.6 | $0.04 | 122.2 | 40.0s | 1.0M | 819.2 |
| Claude Haiku 5.5 (Medium) | `claude-haiku-5-5-medium` | 34.5 | $0.05 | 145.2 | 12.2s | 1.0M | 732.8 |
| MiMo-V2.6-Flash | `mimo-v2-6-flash` | 37.9 | $0.06 | 53.8 | 3.2s | 1.0M | 607.4 |
| GPT-6 Luna (Max) | `gpt-6-luna` | 38.1 | $0.07 | 128.4 | 102.2s | 1.0M | 562.1 |

Provider endpoints for the winner:

| Host | In $/M | Out $/M | CacheRd $/M | Ctx | TTFT | Precision | tok/s |
|---|---|---|---|---|---|---|---|
| OpenAI | $0.10 | $0.50 | $0.01 | - | 19.1s | - | 128.2 |
| Microsoft Azure | $0.10 | $0.50 | $0.01 | - | 18.5s | - | 172.1 |

`aa_model` confirms model-level: 1.0M ctx, In $0.10, Out $0.50, Cache read $0.01,
Cache write $0.12, cache discount 90%, $/task $0.03.

**Calls (5):**
1. ✔ `aa_leaderboard {"mode":"value","min_intelligence":30,"top":5}` → winner + Intel/$.
2. ✔ `aa_providers {"model":"gpt-6-luna-high"}` → 2 endpoints (no ctx column by default).
3. ✔ `aa_providers {"model":"gpt-6-luna-high","fields":"host,model,in,out,context,cacheread,ttft"}`
   → `— no data for: Model, Ctx (shown as -)`.
4. ✔ `aa_providers {"model":"gpt-6-luna-high","top":20,"fields":"host,in,out,cacheread,ctx,ttft,precision,tps"}`
   → confirms exactly 2 endpoints; still `-` ctx / precision.
5. ✔ `aa_model {"query":"gpt-6-luna-high"}` → model-level 1.0M ctx (to fill the gap in call 4).

**First tool right?** Yes. Calls 3 and 4 were redundant (call 3 already proved ctx is
absent). Minimum route: calls 1 + 4 (+5 to answer the ctx half).

**Ambiguity resolved:** "which provider is cheapest" has **no unique answer** here —
the two hosts are price-identical, so the honest answer is a tie; I did not invent a
tiebreak. The second half ("what context window does that endpoint offer") is **not
answerable at endpoint level** from any tool; I substituted the model-level 1.0M and
flagged it (Friction C).

---

## Q10 — ≥400k-context models: cheapest cache-read

**Answer: MiMo-V2.6-Flash — `mimo-v2-6-flash` (Xiaomi), cache-read $0.0028/1M, Ctx
1.0M, Intel 37.9.** For cache-heavy re-ingestion it is ~1.3× cheaper than the next
option on cache reads, and ~3.6× cheaper than the whole $0.01 tier.

Cheapest cache-read among ≥400k-context models (`sort=cacheread`, ascending):

| Intel | Model | Slug | Ctx | CacheRd $/M |
|---|---|---|---|---|
| 37.9 | **MiMo-V2.6-Flash** | `mimo-v2-6-flash` | 1.0M | **$0.0028** |
| 46.3 | MiMo-V2.6-Pro | `mimo-v2-6-pro` | 1.0M | $0.0036 |
| 24.7 | DeepSeek V4.1 Flash (Non-reasoning) | `deepseek-v4-1-flash-non-reasoning` | 1.0M | $0.0060 |
| 39.5 | DeepSeek V4.1 Flash (Max) | `deepseek-v4-1-flash` | 1.0M | $0.0060 |
| 34.6 | GPT-6 Luna (Xhigh) | `gpt-6-luna-xhigh` | 1.0M | $0.01 |
| 37.8 | Claude Haiku 5.5 (High) | `claude-haiku-5-5-high` | 1.0M | $0.01 |
| 43.4 | Claude Haiku 5.5 (Max) | `claude-haiku-5-5` | 1.0M | $0.01 |

**How many models support ≥400k?** **Not determinable** from the tool — the header's
leading number is *rows displayed*, not match count (Friction B), and every ≥400k row
shown actually reports `Ctx = 1.0M`. So "which models support ≥400k" can only be
answered as "the cheapest tier of a long list I can't size."

**Calls (3):**
1. ✗ `aa_leaderboard {"min_context":400000,"sort":"cache_read","top":5,"fields":"intel,name,slug,ctx,cacheRd"}`
   → `unknown field 'cacheRd' — closest: cacheread, cache_read, cache-read, CacheRd $/M, cachewrite`.
2. ✔ `aa_leaderboard {"min_context":400000,"sort":"cacheread","top":8,"fields":"intel,name,slug,ctx,cacheread"}` → answer.
3. ✔ `aa_leaderboard {"min_context":400000,"sort":"cacheread","top":20,"fields":"intel,name,slug,ctx,cacheread"}` → extended list (tests header count semantics).

**First tool right?** Yes; `aa_leaderboard` with `min_context` + `sort=cacheread` is
exactly the right route. Call 3 was a deliberate probe of the count ambiguity, not a
data need.

---

## Q11 — Intelligence Index vs AA-Briefcase; is Briefcase in the index?

**Answer:** The **Intelligence Index v4.3.2** is a **0–100 composite of 10
evaluations**: AA-Briefcase v1.1, GDPval-AA v2.1, AutomationBench-AA (partial),
Terminal-Bench 4.0, SciCode, AA-LCR v1.1, AA-Omniscience, HLE, GDP.pdf, CritPt.
**AA-Briefcase (Elo)** is itself *one* long-horizon knowledge-work benchmark
(private set, reported as Elo, *chart set only — not a full public leaderboard*).
**Yes — AA-Briefcase is included in the Intelligence Index**, as a constituent
evaluation; `aa_benchmarks` marks it `Index = yes`, tags `intelligence-index`.
So the relationship is *component → composite*, not two rival headline scores:
Briefcase Elo is a raw pairwise-preference arena, the Index is a normalised 0–100
weighted composite that consumes Briefcase v1.1 alongside nine other evals.

**Calls (2 incl. shared setup):**
1. ✔ `read aa://reference/metrics` (setup) → the "indexes" section defines both.
2. ✔ `aa_benchmarks {"query":"briefcase","verbose":true}` → confirms Index=yes, chart set only, v1.1.

**First tool right?** Yes — the reference resource answers it directly; the benchmark
call was confirmation only. The only thing the tool does **not** give is the
**weight** Briefcase carries in the composite (Friction G).

---

## Q12 — Pick one: (a) smartest overall, (b) best value above Intel 45, (c) fastest above Intel 45

**Answer:**

| Pick | Model | Slug | Intel | $/Task | tok/s | TTFT | Ctx |
|---|---|---|---|---|---|---|---|
| **(a) smartest overall** | Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | **57.6** | $5.98 | 95.2 | 679.2s | 1.0M |
| **(b) best value > Intel 45** | MiMo-V2.6-Pro | `mimo-v2-6-pro` | 46.3 | **$0.13** | 43.7 | 4.1s | 1.0M |
| **(c) fastest > Intel 45** | Muse Spark 1.3 (Xhigh) | `muse-spark-1-3-xhigh` | 45.1 | $1.37 | **213.1** | 29.4s | 1.0M |

Notes: (a) is not the cheapest way to 57.6 (its Xhigh fallback variant
`claude-opus-5-5-xhigh` also hits Intel 56.0 at $3.46). (b) value = Intel per $/task
= **347.7** ($0.13/task for Intel 46.3), ~1.6× the next option (GPT-6.1 Sol Medium,
$0.21, Intel/$ 223.6). (c) wins on **median output throughput**; if "fastest" is
instead read as *snappiest* (lowest TTFT), the answer changes to **Qwen3.8 Max (0902)**
(`qwen3-8-max`, Intel 45.4, **TTFT 3.0s**, 42.4 tok/s, $5.41/task, 984k ctx) — see
ambiguity note below.

**Calls (4):**
1. ✔ `aa_leaderboard {"top":3}` → (a).
2. ✔ `aa_leaderboard {"mode":"value","min_intelligence":45,"top":5}` → (b).
3. ✔ `aa_leaderboard {"min_intelligence":45,"sort":"tps","top":5}` → (c) by throughput.
4. ✔ `aa_leaderboard {"min_intelligence":45,"sort":"ttft","top":4}` → (c) by latency, to disambiguate.

**Ambiguity resolved:** "fastest" is undefined. AA's own routing note says
*"snappy UI → `sort=ttft`; bulk generation → `sort=tps`."* I defaulted to **tok/s**
(throughput) as the literal reading of "fastest" and confirmed the alternative with
call 4 so the reader can pick either — the tool itself gives no single "fastest"
ranking. Also note call 3's footer: *"TTFT is AA's long-prompt median"*, so the TTFT
column is a specific prompt class, not a universal latency.

---

## Friction

Blunt, with the offending lines pasted.

### A. `aa_media` `fields` silently drops model identity (worst issue)
Asking for Elo *and* its CI removed the Model column entirely, with no error:

```
# 5/11 video_editing · human-preference Elo (ask fields=ci_lower,ci_upper,ci for the 95% CI) · 0s ago · aa:rsc
| Elo | 95% CI | CI low | CI high |
|---|---|---|---|
| 1170 | 1149–1191 | 1149 | 1191 |
```

A named-model leaderboard answered a "who leads" question with **unnamed numbers**. The
tool prints the *default* fields when `fields` is omitted (Model/Creator/Elo/…) but,
when `fields` is given, replaces the whole set with exactly what you asked for —
including dropping `model`. There is no "you forgot `model`" warning and no `slug`
field at all (`unknown field 'slug'`). Cost: 3 wasted calls on Q7. A leaderboard
tool should always emit the entity identity (or refuse to drop it).

### B. `aa_leaderboard` header count = rows shown, not matches — filters are unsizable
```
# 8/700 models · CacheRd $/M, active only, ctx>=400000 · 33m ago
...
# 20/700 models · CacheRd $/M, active only, ctx>=400000 · 34m ago
```
Same filter, numerator follows `top`. So `N/700` cannot be read as "N models match
`min_context=400000`" — Q10's "how many models support ≥400k" is **unanswerable**.
(The 700 denominator also never moves with active/deprecated filters, so it's just the
variant total, not the eligible set.) Contrast `aa_media`, where `11/11` *is* a true
total for the board — the two tools reuse the `x/y` idiom with different meanings.

### C. Endpoint context window missing where the model-level one exists
`aa_providers` on the Q9 winner and the model head disagree:
```
— no data for: Ctx, Precision (shown as -)
| Host | In $/M | Out $/M | CacheRd $/M | Ctx | TTFT | Precision | tok/s |
| OpenAI | $0.10 | $0.50 | $0.01 | - | 19.1s | - | 128.2 |
| Microsoft Azure | $0.10 | $0.50 | $0.01 | - | 18.5s | - | 172.1 |
```
while `aa_leaderboard` prints `Ctx 1.0M` and `aa_model` prints `1.0M ctx` for the same
slug. The question explicitly asked *"what context window does **that endpoint**
offer"* — the tool cannot answer it, and a missing value is rendered identically to a
field name the caller typed wrong, so I could not distinguish "no data" from "wrong
field" without opening `aa_model`. Model-level `1.0M` is a **substitution**, not the
endpoint's guarantee.

### D. "Cheapest provider" tie with no tiebreak
```
| Host | In $/M | Out $/M | CacheRd $/M | ...
| OpenAI | $0.10 | $0.50 | $0.01 |
| Microsoft Azure | $0.10 | $0.50 | $0.01 |
```
Both endpoints of the Q9 model are byte-identical on price and `$0.03/task`. The
ranking idiom (`by cost_per_task`) implies a winner that does not exist. Nothing in
the output says "tie"; I had to infer it. Ranking surfaces should mark equal ranks.

### E. TTFT column is misleadingly combined with tok/s
From the Q12(a) query:
```
| Claude Opus 5.5 (Max, Default Fallback) | claude-opus-5-5 | Anthropic | 57.6 | $5.98 | 95.2 | 679.2s | 1.0M |
```
A model shown at **95.2 tok/s** with a **679.2 s "TTFT"** (11+ min) in the same row is
not interpretable as "time to first token" for a 95 tok/s streamer — `aa://reference`
itself distinguishes TTFT from **TTFA (time to first answer token)**. The leaderboard's
`TTFT` column appears to behave like TTFA for high-effort reasoning variants (call 4's
footer: *"TTFT is AA's long-prompt median"*), so sorting `fastest` by `ttft` yields
figures that contradict the docs' own TTFT definition. I sidestepped it by using
`tps`, but a naive user would read 679 s as a broken number.

### F. Wrong surface for reference text: resources vs the tool
The docs advertise `aa://reference/<topic>` resources, but the obvious `read` form is
rejected for most topics while the `aa_reference` tool works:
```
Resource 'aa://reference/indexes' failed: 'Unknown resource: aa://reference/indexes'
Resource 'aa://reference/overview' failed: 'Unknown resource: aa://reference/overview'
Resource 'aa://reference/media' failed: 'Unknown resource: aa://reference/media'
```
Only `aa://reference/metrics` (a merged blob) and `/fields`, `/sources`, `/benchmarks`
exist as resources; `indexes`, `pricing`, `speed`, `providers`, `media`, `overview`
are tool-only. Four wasted setup calls. `aa_reference {"topic":"routing"}` also errored
(`unknown topic 'routing' — topics: overview, indexes, …`) — the tool listed no
`routing` topic while its own description fields call the overview text "tool routing".

### G. Oversized / low-signal output
- `read aa://reference/fields` dumps ~200 lines of **alphabetised field-name
  variants**, many visibly truncated with no way to know the full name:
  ```
  AA Cyber Ind
  AutomationBe
  Global-MMLU-
  Terminal-Ben
  Harvey LAB-A
  MLCR Accurac
  ```
  (e.g. `AA Cyber Ind` vs `AA Cyber Index` both listed; `AutomationBe` is a clipped
  `AutomationBench`). This is a list of every accepted spelling, not a usable schema —
  it needs grouping (field → tool → example) or it just burns context.
- `aa://benchmarks` (the mid-size catalog) is a raw JSON array; readable but a whole
  screen for what `aa_benchmarks {"query":…}` answers in 2 rows.

### H. Things I had to infer rather than read
- **Cross-arena comparability (Q7):** nothing states whether `video_editing` and
  `text_to_video` Elo share a scale. I inferred they do **not**, and that the 36-pt
  gap is therefore weak evidence.
- **"Score" unit in `aa_agents` (Q8):** the column is header-less-typed `68.4%`;
  nothing says whether that's pass rate, win rate, or a composite. I reported the raw
  percentage.
- **Q9 tiebreak (D)** and **Q10 eligible-model count (B)** — inferred/absent, above.
- **Briefcase weight in the Index (Q11):** the reference lists Briefcase v1.1 as one
  of 10 constituents but never gives weights, so "how much does Briefcase move the
  Index" cannot be answered.
- **Q12 "fastest" (see note):** undefined; resolved by AA's routing guidance + a
  confirmation call, not by any "fastest" field.

### I. Silent filter drops (the good kind, for contrast)
Worth noting because the *opposite* also happened cleanly: `aa_leaderboard` **errors**
on unknown `fields` (`unknown field 'cacheRd' — closest: cacheread, cache_read,
cache-read, CacheRd $/M, cachewrite`) and `aa_media` **errors** on unknown `fields`
(`unknown field 'slug' — valid: appearances, ci, ci_lower, …`), and value mode
**discloses** its skip: `— 10 rows skipped: no measured intelligence (AA has
intelligence for 690/700 variants)`. So the codebase has a good erroring convention —
`aa_media`'s silent `model` drop (A) is the outlier, not the norm.

---

### Per-question summary

| Q | First tool right? | Calls | Tool self-sufficient? | Main friction |
|---|---|---|---|---|
| 7 | yes (route) | 7 (2 needed) | partially | `fields` drops Model (A); no cross-arena note (H) |
| 8 | yes | 1 | yes | untyped "Score" (H) |
| 9 | yes | 5 (2 needed) | no | endpoint ctx missing (C); price tie (D) |
| 10 | yes | 3 (2 needed) | partially | filter match count unknown (B) |
| 11 | yes | 2 (1 needed) | yes | no Index weights (H) |
| 12 | yes | 4 | yes | "fastest" undefined (E, H) |
