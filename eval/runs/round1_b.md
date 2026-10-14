# Round 1 — evaluation by `EvalR1b`

Scope: questions **7–12** only (assigned). Every data point below came from
`eval/client.py` against a single MCP session; no curls, no web, no `src/` reading.
All data flags `aa:rsc` (scraped) and is dated 2026-10-14.

Legend for calls: ✔ = succeeded, ✗ = errored.

---

## Q7 — Text-to-image leader + cost per 1000 images

**Answer:** **GPT Image 2.5 Sunburst (max)** — OpenAI, released 2026-09-08 — leads
AA's `text_to_image` human-preference arena at **Elo 1217** (12,743 appearances),
cost **$210.72 per 1,000 images**. Full top 5:

| Rank | Model | Creator | Elo | $/1k imgs |
|---|---|---|---|---|
| 1 | GPT Image 2.5 Sunburst (max) | OpenAI | 1217 | $210.72 |
| 2 | GPT Image 2.5 Flare (max) | OpenAI | 1209 | $210.72 |
| 3 | GPT Image 2 (high) | OpenAI | 1188 | $211.00 |
| 4 | Nano Banana 2.1 | Google | 1173 | $33.60 |
| 5 | Grok Imagine Image 2.0 | SpaceXAI | 1167 | $60.00 |

Note the shape of the answer: the Elo leader (GPT Image 2.5, $210.72/1k) is ~6× more
expensive than Nano Banana 2.1 at Elo 1173 ($33.60/1k). The arena ranks by preference
Elo, not value.

**Calls (2):**
1. ✗ `aa_media {"board":"image","top":5}` → `unknown media board 'image' — valid: image_editing, image_to_video, music_instrumental, music_with_vocals, text_to_image, text_to_speech, …`
2. ✔ `aa_media {"board":"text_to_image","top":5}` → answered everything.

**First tool right?** Right *tool*, wrong *board slug*. `aa_media` is the correct
route; `image` is the obvious human word for the board and is rejected.

**Friction — the reference and the tool disagree on how to spell every board.**
`aa_reference {"topic":"media"}` describes the boards with **hyphens**
(`text-to-image`, `image-editing`, `text-to-speech`, `speech-to-text`), but
`aa_media` only accepts **underscores** (`text_to_image`, `image_editing`,
`text_to_speech`, `speech_to_text`). So the one place that documents the boards gives
you a name the tool rejects. The tool-list line is even vaguer — `board: image, video,
speech, music (Elo + 95% CI)`, where `image` isn't a valid board at all. My natural
first guess `image` errored; only the (good) error message recovered it. Server should
make the reference and the tool use the same spelling (or accept both).

**Friction — CI promised, not delivered.** `aa://reference/metrics` and the
`aa_media` docstring both advertise "Elo + 95% CI", but the table has no CI column,
so "who leads" cannot be stated with the confidence interval the docs imply. I had
to treat Elo 1217 vs 1209 (a 8-point gap) as meaningful without the ±CI.

**Friction — unexplained price unit/field.** Price is rendered as the pre-formatted
string `$210.72/1k imgs`. There is no `fields` value to ask for the underlying
per-image price, no note whether it is list price or a blended price, and no coverage
note (unlike `aa_benchmark_leaderboard`, this tool did not say "chart set only / N
models"). GPT-6's own top row ($210.72) vs the GPT Image 2 row ($211.00) is a
$0.28/1k difference with no explanatory field.

---

## Q8 — What SciCode measures + best models

**Answer:** SciCode is **288 scientist-curated coding subproblems drawn from 80 lab
problems across 16 scientific disciplines**, scored as **%**. Catalog row:
`SciCode | scicode | % | 229/700 | SciCode: 288 scientist-curated coding subproblems
from 80 lab problems.` Current leaders:

| Model | Slug | SciCode | Intel | $/Task |
|---|---|---|---|---|
| Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | 66.9% | 57.6 | $5.98 |
| Claude Opus 5.5 (Xhigh, Default Fallback) | `claude-opus-5-5-xhigh` | 65.0% | 56.0 | $3.46 |
| Claude Fable 5.1 (Max, Default Fallback) | `claude-fable-5-1` | 63.1% | 53.4 | $7.63 |
| Muse Wonder Full (Max) | `muse-wonder-full` | 62.6% | 55.8 | - |
| Gemini 4 Argon (High) | `gemini-4-argon` | 61.8% | 52.6 | $1.99 |

Coverage is 229/700 models scored.

**Calls (2):**
1. ✔ `aa_benchmarks {"query":"scicode"}` → slug `scicode`, what it measures.
2. ✔ `aa_benchmark_leaderboard {"benchmark":"scicode","top":5}` → ranking.

**First tool right?** Yes. The one-two of `aa_benchmarks` (to resolve/confirm slug +
definition) then `aa_benchmark_leaderboard` is exactly the intended route and cost
only 2 clean calls. No friction on this one except a minor definition inconsistency
(below).

**Friction — two different descriptions of SciCode.** The catalog tool says
"288 scientist-curated coding subproblems from 80 lab problems"; `aa://reference`
(benchmarks) says "288 scientist-curated coding subproblems, **16 disciplines**".
Neither is wrong, but a user asking "what does it measure" gets a different answer
depending on which surface they hit; the catalog row omits the 16-discipline scope
that is arguably the most useful part of "what it measures".

---

## Q9 — Legal / healthcare-and-medical capability index leaders

**Answer (partial — see friction):** I could **not** produce a ranked leader for
either index from the tools. Both `Cap Legal` and `Cap Medical` are catalogued as
`api only` and the leaderboard cannot rank or even display them. The best evidence I
could obtain was by opening individual model pages:

| Model | Legal | Healthcare & Medical | (source) |
|---|---|---|---|
| Claude Opus 5.5 (Max) | **63.3** | **60.5** | `aa_model` indexes |
| Claude Fable 5.1 (Max) | 60.5 | 58.0 | `aa_model` indexes |
| GPT-6 Astra (Max) | 58.5 | 51.7 | `aa_model` indexes |
| Claude Sonnet 5.5 (Max) | 56.4 | 58.1 | `aa_model` indexes |

So among the frontier pages I could retrieve, **Claude Opus 5.5 (Max, Fallback)**
leads both indexes (Legal 63.3, Medical 60.5) — **but this is not a verified
leaderboard leader**: the two most plausible rival families (Gemini 4 Argon and the
open-weight/Llama-class entries) *crashed the model tool* (see friction), and there is
no enumerable list of which of the 700 models carry capability scores.

**Calls (many — this is the failure case; ~14):**
1. ✔ `aa_reference {"topic":"indexes"}` → "six Capability Indexes … **API-only
   (require AA_API_KEY)** … Members … are null for models missing any constituent
   evaluation."
2. ✔ `aa_leaderboard {"sort":"cap-legal","fields":"name,cap-legal","top":5}` → header
   says `Cap Legal, active only`, but rows are 5 unrelated low-intel models, **no
   score column**.
3. ✔ `aa_leaderboard {"sort":"cap-medical","fields":"name,cap-medical","top":5}` →
   **byte-identical row set** to call 2. Silent no-op.
4. ✔ `aa_model {"query":"claude-opus-5-5","sections":"indexes"}` → capability table
   present (Legal 63.3, Medical 60.5).
5. ✔ `aa_model {"query":"gpt-6-astra","sections":"indexes"}` → Legal 58.5, Medical 51.7.
6. ✔ `aa_model {"query":"claude-sonnet-5-5","sections":"indexes"}` → Legal 56.4, Med 58.1.
7. ✔ `aa_model {"query":"claude-fable-5-1","sections":"indexes"}` → Legal 60.5, Med 58.0.
8. ✗ `aa_model {"query":"gemini-4-argon","sections":"indexes"}` → **unhandled
   AttributeError crash** (see below). Retried → same crash.
9. ✗ `aa_model {"query":"muse-wonder-full","sections":"indexes"}` → same crash.
10. ✗ `aa_model {"query":"muse-wonder","sections":"indexes"}` → same crash.
11. ✗ `aa_model {"query":"qwen3-5-omni-plus","sections":"indexes"}` → same crash.
12. ✔ `aa_leaderboard {"fields":"name,creator,Cap Legal,Cap Medical","min_intelligence":45,"top":8}`
    → **both requested columns silently dropped**; header reverts to `Intel`.
13. ✔ `aa_benchmarks {"query":"legal"}` / `{"query":"health"}` → both rows say
    `index | api only`.
14. ✗ `aa_raw {"kind":"model","query":"gemini-4-argon"}` → same AttributeError crash.

**First tool right?** No. My first instinct (`aa_leaderboard sort=cap-legal`) was the
natural route and it *accepted* the argument while returning meaningless output — the
worst possible failure mode.

**Friction — `sort` silently accepts a capability field and returns garbage.**
`aa_leaderboard {"sort":"cap-legal"}` does **not** error, does **not** warn, and does
**not** sort by anything related to legal. It returns the same 5 rows for legal and
for medical (JT-35B-Flash, Qwen3.5 Omni Plus, Nova 2.0 Omni (Medium), …) with **no
value column**. A filtering/ranking param that is accepted-but-ignored is worse than
one that errors. The server should either (a) rank by the field, (b) print the field,
or (c) hard-error `"cap-legal: coverage is API-only; not available on the scrape
source"`. Compare `aa_benchmark_leaderboard`, which at least prints
`chart set only — not a full leaderboard`; `aa_leaderboard` prints nothing.

**Friction — requested columns are silently dropped.** `fields:"…,Cap Legal,Cap Medical"`
returns a 2-column table (`Model | Creator`). Unknown `fields` names vanish with no
warning, so the caller cannot distinguish "no data" from "you typed the field name
wrong". (Same class of bug hit Q12 with `AA-Briefcase Elo`.)

**Friction — `aa_model` hard-crashes on a whole class of models.** For `gemini-4-argon`,
`muse-wonder-full`, `muse-wonder`, `qwen3-5-omni-plus` the tool raises an **unhandled**
`AttributeError: 'str' object has no attribute 'get'` in `normalize.py` (surfaced as
`UnexpectedToolError: Error executing tool aa_model`), instead of a clean "could not
parse model page for slug X" message. This makes the *only* surface that exposes
capability scores unusable for exactly the rival models I needed to rank. Note
`gemini-4-argon` works fine through `aa_benchmark_leaderboard` (Q8 row 5), so the
crash is specific to the model-page chart parser.

**Friction — no enumeration route.** Even with model pages working, there is no tool
to list the ~N models that carry capability scores, so "which model leads" is
unanswerable without brute-forcing every slug. `aa_benchmark_leaderboard` would be
the natural place, but capability indexes have no `benchmark` slug (catalog shows
`Cap Legal | - | index | api only` — **slug is literally null**).

---

## Q10 — Cached-input cost + cache discount: Opus 5.5 vs GPT-6 Astra

**Answer:**

| | Claude Opus 5.5 (Max) | GPT-6 Astra (Max) |
|---|---|---|
| Input $/1M | $4.00 | $10.00 |
| Output $/1M | $20.00 | $50.00 |
| **Cache read $/1M** | **$0.20** | **$1.00** |
| Cache write $/1M | $5.00 | $12.50 |
| **Cache discount** | **95%** | **90%** |

Both are first-party list prices on their max-effort variants. Cached input is 10×
cheaper on Opus ($0.20) than on Astra ($1.00) in absolute terms; the percentage
discount is 95% vs 90%. Slugs: `claude-opus-5-5`, `gpt-6-astra`.

**Calls (5):**
1. ✗ `aa_compare {"queries":"claude-opus-5-5,gpt-6-astra","metrics":"…"}`
   → `queries — Input should be a valid list`.
2. ✔ `aa_compare {"queries":["claude-opus-5-5","gpt-6-astra"],"metrics":"In $/M,Out $/M,CacheRd $/M,CacheWr $/M,Cache disc."}`
   → prices correct, but **`Cache disc.` = `-` for both**.
3. ✔ same call with `metrics":"cache-hit-discount"` → `Cache disc. | - | -`.
4. ✔ `aa_model {"query":"claude-opus-5-5","sections":"pricing"}` → `Cache discount | 95%`.
5. ✔ `aa_model {"query":"gpt-6-astra","sections":"pricing"}` → `Cache discount | 90%`.

**First tool right?** Yes in spirit (`aa_compare` is the natural side-by-side tool),
but it is **missing the field the question is about** and forced two extra model-page
calls.

**Friction — contradictory/missing number between two tools.** The exact metric this
question asks for (`Cache disc.`) is a *recognised* `aa_compare` metric (it accepts
the name, prints the row) yet renders `-` for both models, while `aa_model` prints
`95%` / `90%` for the same field. Two tools, same data source, different answers —
and the wrong one is silent. The server should populate `Cache disc.` in `aa_compare`
from the same source `aa_model` uses, or omit the row.

**Friction — `queries` type.** Documented only as `queries`; must be a JSON **array**,
not the comma-joined string the sibling `metrics` param requires. Mixed types across
two adjacent params of the same call is a coin-flip error.

**Friction — naming inconsistency across tools.** `aa_compare` labels the model
`Claude Opus 5.5 (max with fallback)`; `aa_search`/`aa_leaderboard` label it
`Claude Opus 5.5 (Max, Default Fallback)`. Same row, two names — makes it hard to
match output back to slugs.

---

## Q11 — Which models use Terminal-Bench 4.0, and who leads

**Answer:** Terminal-Bench 4.0 is scored on **218/700** tracked variants; it is the
newer/harder agentic terminal suite (the older `terminalbench-2-1` has wider coverage,
241/700). Leader: **Claude Sonnet 5.5 (Max, Default Fallback)** — `claude-sonnet-5-5`
— at **63.6%**. Top 5:

| Model | Slug | Terminal-Bench 4.0 | Intel | $/Task |
|---|---|---|---|---|
| Claude Sonnet 5.5 (Max, Default Fallback) | `claude-sonnet-5-5` | **63.6%** | 56.0 | $5.46 |
| GPT-6 Astra (Xhigh) | `gpt-6-astra-xhigh` | 59.6% | 52.4 | $2.31 |
| Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | 59.6% | 57.6 | $5.98 |
| Claude Opus 5.5 (Xhigh, Default Fallback) | `claude-opus-5-5-xhigh` | 59.6% | 56.0 | $3.46 |
| GPT-6 Astra (Max) | `gpt-6-astra` | 59.1% | 52.7 | $3.26 |

**Calls (2):**
1. ✔ `aa_benchmarks {"query":"terminal"}` → returned all four terminal bench slugs,
   incl. `terminalbench-4-0`.
2. ✔ `aa_benchmark_leaderboard {"benchmark":"terminalbench-4-0","top":5}` → leader + notes.

**First tool right?** Yes — same 2-call pattern as Q8. Clean.

**Friction — three-way tie with no tiebreak shown.** Ranks 2–4 are all `59.6%`
(GPT-6 Astra Xhigh, Opus Max, Opus Xhigh) but the tool prints them as a strict 2/3/4
order without stating the tiebreak (likely raw float precision below the shown 1 dp).
The "who leads" answer is safe (63.6% is a clear lead), but a user comparing the
chasers cannot reproduce the order from the displayed numbers.

**Friction — no query-tool for "does model X use benchmark Y".** The question as
posed ("which models use TB 4.0") is only answerable as "218/700 do" via the
leaderboard header; there is no per-model "evaluations covered" listing short of
opening each model page. Not fatal, but the coverage count lives in a footnote, not a
field.

---

## Q12 — AA-Briefcase Elo for the top 5

**Answer:** AA-Briefcase Elo (private chart set, **32 models**, not a full
leaderboard). Top 5:

| Rank | Model | Slug | AA-Briefcase Elo | Intel |
|---|---|---|---|---|
| 1 | Claude Sonnet 5.5 (Max, Default Fallback) | `claude-sonnet-5-5` | **1819** | 56.0 |
| 2 | Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | **1805** | 57.6 |
| 3 | Claude Opus 5.5 (Xhigh, Default Fallback) | `claude-opus-5-5-xhigh` | **1766** | 56.0 |
| 4 | Claude Sonnet 5.5 (Xhigh, Default Fallback) | `claude-sonnet-5-5-xhigh` | **1752** | 51.9 |
| 5 | Muse Wonder Full (Max) | `muse-wonder-full` | **1729** | 55.8 |

Note the Elo leader (Sonnet 5.5 Max) is *not* the Intel leader (Opus 5.5 Max), and
the Elo ranking puts the Anthropic family 1–4.

**Calls (this one took 9, all avoidable after the fact):**
1. ✗ `aa_leaderboard {"sort":"aa-briefcase-elo","fields":["name","aa-briefcase-elo"],"top":5}`
   → `fields — Input should be a valid string`.
2. ✔ `aa_leaderboard {"sort":"aa-briefcase-elo","fields":"name,aa-briefcase-elo,creator","top":6}`
   → **Elo value and sort both ignored**; returns 6 models in Intel order, 2 columns.
3. ✗ `aa_leaderboard {"sort":"briefcase","top":6}` → `unknown sort 'briefcase' — closest: briefcaseElo, aa-briefcase, AA-Briefcase, aa_briefcase_elo, briefcaseBreakdown`.
4. ✔ `aa_leaderboard {"sort":"aa_briefcase_elo","fields":"name,creator,aa_briefcase_elo","top":6}` → header now `AA-Briefcase`, but again **no Elo column, ordering is the cap-legal garbage set**.
5. ✔ `aa_leaderboard {"sort":"briefcaseElo","fields":"name,creator,briefcaseElo","top":6}` → identical to 4.
6. ✔ `aa_benchmarks {"query":"briefcase"}` → slug `aa-briefcase`, unit Elo.
7. ✔ `aa_benchmark_leaderboard {"benchmark":"aa-briefcase","top":5}` → **the answer**.
8. ✗ `aa_model {"query":"claude-opus-5-5","sections":"briefcase"}` → `unknown section(s) briefcase — valid: identity, indexes, benchmarks, pricing, speed, cost, openness, modalities, all`.
9. ✗ `aa_agents {"top":5}` → **unhandled AttributeError crash** (`'str' object has no attribute 'get'` in `loaders.parse_agents`).
10. ✔ `aa_leaderboard {"fields":"name,creator,AA-Briefcase Elo","top":5}` → Elo column **silently dropped**.

**First tool right?** No. `aa_leaderboard sort=…` is the natural guess for "Elo
ranking" and it silently lies three different ways; the correct tool is
`aa_benchmark_leaderboard` with the `aa-briefcase` slug.

**Friction — three sorts accepted, zero effect.** `aa-briefcase-elo`,
`aa_briefcase_elo`, and `briefcaseElo` are all **accepted** by `aa_leaderboard`
(no error) yet none sorts by Elo: each returns the same set in the same non-Elo order
as the `cap-legal` call in Q9 (JT-35B-Flash first). Worse, `sort:"aa-briefcase-elo"`
and `sort:"aa_briefcase_elo"` produce *different headers* (`AA-Briefcase` vs
`AA-Briefcase` with different rows) — the param has effects on the label but not the
ordering. `sort:"briefcase"` errors with a helpful "closest" list; the hyphen/underscore
forms should have done the same (or worked).

**Friction — requested Elo column silently dropped.** Steps 2/4/10 all asked for an
Elo field in `fields`; no Elo column ever appeared. Because `fields` unknown names
are dropped without a note, `aa_leaderboard` **cannot be trusted to answer a value
question at all** — the user cannot tell "field unavailable" from "typo".

**Friction — Cliff-promised CI absent.** `aa://reference/metrics` says AA-Briefcase
Elo is "reported as Elo with **95% CI**"; `aa_benchmark_leaderboard` prints bare Elo
with no CI, so 1819 vs 1805 cannot be called a real gap from the tool output.

**Friction — `aa_agents` crashes outright** (separate from this question's route, but
I tried it while hunting for the Briefcase board): `aa_agents {"top":5}` raises
`AttributeError: 'str' object has no attribute 'get'` in `loaders.py:712 _agent_row`
(`creator.get("name")`). The whole AA agent-leaderboard family is unreachable.

---

## Cross-cutting friction (ranked, blunt)

1. **Silent no-op params on `aa_leaderboard` (worst).** `sort=<any capability or Elo
   alias>` is *accepted* and ignored; `fields=<unknown>` is *accepted* and dropped.
   The tool never says "I didn't do that." It returned the same garbage row set for
   `cap-legal`, `cap-medical`, `capLegal`, `_cap_legal`, `aa-briefcase-elo`,
   `aa_briefcase_elo`, `briefcaseElo`. Fix: hard-error, or apply, or print a warning
   line. This single behaviour cost Q9 and Q12 the most calls and made wrong answers
   *look* authoritative.
2. **`aa_model` hard-crashes (unhandled `AttributeError`) on a large model class.**
   Reproduced on `gemini-4-argon`, `muse-wonder-full`, `muse-wonder`,
   `qwen3-5-omni-plus` (and via `aa_raw kind=model`). Raw traceback leaked to the
   caller instead of a clean error. This is the *only* surface exposing capability
   indexes, so it also breaks Q9.
3. **`aa_agents` hard-crashes** for every board (`loaders._agent_row` assumes
   `creator` is a dict; it's a str). Tool is 100% unusable.
4. **Contradictory field: `Cache disc.` = `-` in `aa_compare` vs `95%/90%` in
   `aa_model`.** Same metric, two answers; the question literally asked for it (Q10).
5. **Missing CI everywhere it is documented.** Metrics/reference promise 95% CI for
   media Elo and AA-Briefcase Elo; neither tool prints it (Q7, Q12).
6. **Param type zoo.** `aa_leaderboard.fields` = comma string; `aa_compare.queries` =
   list; `aa_compare.metrics` = comma string; `aa_model.sections` = comma string of
   *undocumented* names. I hit a pydantic rejection in Q10 (`queries`) and Q12
   (`fields`) purely from guessing the wrong adjacent type.
7. **Inconsistent model display names across tools** (`Claude Opus 5.5 (max with
   fallback)` vs `(Max, Default Fallback)`), and no tool prints the slug for every
   row by default (`aa_media`, `aa_compare` omit it) — you must re-resolve.
8. **Board/section vocabulary lives in error messages, and where documented it is
   spelled wrong.** Valid `aa_media` boards only appear in the error text; the
   `media` reference topic describes them with hyphens while the tool demands
   underscores (Q7). Valid `aa_model` sections only appear in the error text — the
   `indexes` topic never mentions that `aa_model sections=` takes
   `identity|indexes|benchmarks|pricing|speed|cost|openness|modalities|all`. Calling
   a non-existent topic (`aa_reference {"topic":"routing"}`) does at least return the
   valid topic list (`overview, indexes, benchmarks, pricing, speed, providers, media,
   fields, sources, all`). The `fields` topic is useful but is a flat 300+ alias dump
   with no grouping, so it does not obviously answer "which name do I pass to
   `sort=`".
9. **Capability indexes are catalogued as `api only` but the tool accepts them as
   filters/sorts** — the mismatch is what generates the silent no-op in (1). If
   `AA_API_KEY` is unset, `sort=cap-legal` should say so, not fake an answer.

---

## Summary table (calls per question)

| Q | Answer landed | Calls | Wrong turns | First tool right? |
|---|---|---|---|---|
| 7 | Yes | 2 | 1 (board slug) | right tool, wrong slug |
| 8 | Yes | 2 | 0 | yes |
| 9 | **Partial** (no verifiable leader) | ~14 | many | no (silent no-op sort) |
| 10 | Yes | 5 | 1 (queries type) + 2 forced by `aa_compare` gap | yes-ish |
| 11 | Yes | 2 | 0 | yes |
| 12 | Yes | 10 (9 probed + 1 correct route) | many | no (silent no-op sort) |
