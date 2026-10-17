# Shape A/B test: the same 10 questions through MCP, skill+CLI, and pure skill

Actively-used head-to-head for "should this be a **skill**, an **MCP server**, or
something else?" — the companion to `SHAPE_COSTS.md`, which measured what each shape
costs *before* a question is asked. This file measures what each shape costs
*per answer*, and whether it gets the answer right.

Measured on this machine (linux 6.8.0-142-generic) on **2026-10-16** against the live
site. Token convention: **`bytes ÷ 4`** (the same `math.ceil(len/4)` the MCP harness
`eval/client.py` prints as `chars ≈ tok`).

Shapes under test:

| | shape | what runs |
|---|---|---|
| **A** | MCP server (this repo) | `.venv/bin/python eval/client.py call <tool> '<json>'` — 12 tools, disk cache in `~/.cache/aa-mcp` |
| **B** | skill + bundled CLI (the zip) | `artificial-analysis-skill.zip` → `/tmp/shape-b`, driven by `scripts/aa.py` |
| **C** | pure skill (markdown only) | the agent writes its own scraper against `artificialanalysis.ai` each time |

---

## 0. How each shape was actually run (reproduce exactly)

**A** — as shipped, warm cache after the first call:

```console
$ cd /home/wavy/ai/aa-mcp && .venv/bin/python eval/client.py call aa_leaderboard '{"sort":"intelligence","top":5}'
```

**B, as shipped** — extracted to `/tmp` only (the repo zip is untouched), run with the
deps the zip's own `SKILL.md` names (`pandas`) plus the ones its fallbacks actually
need (`lxml`, `tabulate`):

```console
$ unzip -q /home/wavy/ai/aa-mcp/artificial-analysis-skill.zip -d /tmp/shape-b
$ cd /tmp/shape-b/artificial-analysis-skill
$ uv run --with pandas --with lxml --with tabulate -- python scripts/aa.py leaderboard --top 5
Model array not found in leaderboard payload — site changed.        # ← every data command
```

`uv run --with …` was used instead of a scratch venv because the zip ships no
`requirements.txt`; `uv` resolves and caches the three deps once, then each run costs
~0.2 s of overhead. Everything below labelled "B (repaired)" was run as:

```console
$ cd /tmp/shape-b && uv run --with pandas --with lxml --with tabulate -- python run_patched.py <cmd>
```

where `/tmp/shape-b/run_patched.py` is a 35-line wrapper that imports the bundled
`scripts/aa.py`, replaces **one** function, and dispatches. The replacement is the
minimal repair for the payload drift described in §2:

```python
# bundled:  scan only '"models|data|rows|items":[' arrays, test dicts[0] for the key
# repaired: scan every '[{' array, keep the one whose dicts carry the key
def find_array(payload, required_key):
    for m in re.finditer(r"\[\{", payload):
        try: arr, _ = json.JSONDecoder().raw_decode(payload[m.start():])
        except json.JSONDecodeError: continue
        if arr and isinstance(arr[0], dict) and required_key in arr[0]:
            return [x for x in arr if isinstance(x, dict)]
```

**C** — scrapers written by hand in `/tmp/shape-c/`, one per question, against the
live site (`curl` + RSC `self.__next_f.push([1,"…"])` decode, and `-H 'RSC: 1'` on the
homepage when probing for a source). The scripts are counted as tokens of *code the
agent had to write*.

---

## 1. The fixed cost before any question (recap of `SHAPE_COSTS.md`)

| shape | available-but-unused | paid when used |
|---|---:|---:|
| **A** MCP | **3,196 tok** (12 tool defs on the wire, after the docstring trim in §8; was 5,346) | + result text per call |
| **B** skill+CLI | **≤40 tok** in omp (compressed blurb) | +1,801 (zip `SKILL.md`) +240 (`--help`) + stdout |
| **C** pure skill | **≤40 tok** | + markdown body (≥1,774 tok) + **all the code the agent writes** + stdout |

The decisive asymmetry is not the fixed cost — it is that **B and C pay a
per-question *code* cost that A does not**, and that cost is not in the token
column of any table until you measure it (§4).

---

## 2. Shape B is broken as shipped: 0 of 10 questions answerable

This is the single biggest empirical result and it is not a subtle one. Every B
command that reads the leaderboard dies on the first fetch:

```console
$ cd /tmp/shape-b/artificial-analysis-skill
$ uv run --with pandas -- python scripts/aa.py leaderboard --top 5   # and search, model,
Model array not found in leaderboard payload — site changed.         #   compare, evals, providers, json
```

Cause, verified against the fetched payload (`/tmp/aa_cache/leaderboard.html`, 1.90 MB):

* The page now embeds a `"models":[{"slug","name","releaseSlug"}, …]` array of **704
  index rows with no metrics at all**. The bundled `find_array()` matches that key
  first, tests only `dicts[0]` for `intelligenceIndex`, finds nothing, and hard-exits.
* The real metrics live in a **differently-named** array — `"initialModels":[{…273
  records…}]` — which the regex `"(?:models|data|rows|items)":\s*\[\{` never matches
  (`initialModels` has no quote before `models`).
* Result: `grep -c '"intelligenceIndex"' payload` = 274, yet the bundled parser sees
  **zero**.

`media` fails one layer later, on dependencies the zip's `SKILL.md` does not
mention:

```console
$ uv run --with pandas -- python scripts/aa.py media text-to-image
ImportError: `Import lxml` failed.        # pandas.read_html needs lxml
$ uv run --with pandas --with lxml -- python scripts/aa.py media text-to-image
ImportError: `Import tabulate` failed.    # the markdown fallback needs tabulate
```

So **B as shipped answers 0/10** and burns ~0.3–7 s and ~500 tok of tracebacks doing
it. `fields` (pure static text) is the only command that works. This is a one-line
site-drift break — but it is the shape's characteristic failure mode, and it is
silent: the CLI tells you the site changed, and a client that trusted the skill's
`description` would have no way to answer at all.

Everything in §3 for B is therefore measured on the **repaired** build. Where B
still cannot answer, that is a *capability* gap, not drift.

---

## 3. Per-question results

Legend — `✓` correct and complete · `~` partial/qualified · `✗` could not answer.
Tokens for A are the harness's own `chars ≈ tok`; for B/C they are `wc -c ÷ 4`.
Wall time for A includes ~4 s of `python` + stdio server start-up per call (a harness
artifact — a real MCP client holds one long-lived server, so the *tool* time the
harness prints, 30 ms–19 s, is the honest number); for B/C wall time is the process.

### Q1 — Smartest model now + its cost/task and context window

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_leaderboard {"sort":"intelligence","top":5}` | 4.7 s | 195 | ✓ `Claude Opus 5.5 (Max) 57.6 · $5.98 · 1.0M` |
| B (shipped) | `leaderboard --top 5` | 4.2 s | 16 | ✗ site-changed exit |
| B (repaired) | `leaderboard --top 3 --fields intelligence,cost_per_task,context` | 0.34 s | 75 | ✓ same top 3, same numbers |
| C | 1 hand-written scraper (`c_q1.py`, 1,143 B) | 1.2 s | 286 code | ✓ after 2 fixes |

### Q2 — Best value above Intelligence 45 + the knee

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_leaderboard {min_intelligence:45, sort:value}` + `aa_pareto {min_intelligence:45}` | 9.7 s | 442 | ✓ `MiMo-V2.6-Pro 46.3 @ $0.13`; knee called out |
| B (repaired) | `leaderboard --min-intel 45 --value` **and** `--frontier` | 0.63 s | 274 | ✓ same answer, but **two** commands |
| B (repaired, combined) | `leaderboard --min-intel 45 --value --frontier` | 0.25 s | 105 | ✗ **crash** `KeyError: '_value'` |

`--value --frontier` together is a genuine pre-existing bug (the `frontier` branch
runs and never sets `_value`, which the render path then reads) — and it is the
exact combination the zip's own `SKILL.md` answering pattern recommends.

### Q3 — `mimo-v2-6-pro` vs `deepseek-v4-1-flash` on cyber + coding, with deltas

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_compare {queries:[…], metrics:[cyberIndex,scicode,terminalBench40,livecodebench]}` | 5.6 s | 245 | ✓ cyber 56.1/40.8, SciCode 60.9/51.9, TB4.0 34.8/26.8, **and says LiveCodeBench is missing on both** |
| B (repaired) | `compare … --fields coding,scicode,terminalbenchV21,terminalbenchHard` | 0.44 s | 48 | ~ SciCode only; `Coding` row **blank**; TB rows blank (B is on Terminal-Bench **v2.1**, AA now publishes **4.0**) |

### Q4 — AA Cyber Index leader + second place

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_benchmarks {query:cyber}` → `aa_leaderboard {"sort":"cyberIndex","top":3}` | 15.9 s | 567 | ✓ `GPT-6 Sol (Daybreak Blue) 68.7`, then `Grok 4.7 56.4` |
| B (shipped) | — | — | — | ✗ |
| B (repaired) | `evals --metric cyber` | 0.30 s | 77 | ✗ `Unknown metric 'cyber'` — the CLI has **no Cyber Index at all** |
| C | 1 scraper (`c_q4.py`, 1,039 B) against `/evaluations/artificial-analysis-cyber-index` | 1.0 s | 260 code | ✓ same two values, first try |

### Q5 — Top 3 on the Legal capability index + the leader's sub-scores

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_leaderboard {"sort":"capabilities.legal","top":3}` + `aa_model {query:claude-opus-5-5}` | 19.5 s | 1,418 | ✓ `63.3 / 60.8 / 60.8` + all 6 legal sub-scores (Agentic knowledge work 66.7 · Agentic tool use 77.3 · Knowledge 64.2 · Long context 55.4 · Non-hallucination 55.0 · Reasoning 61.4) |
| B (repaired) | `leaderboard --sort legal` | 0.24 s | 185 | ✗ `invalid choice: 'legal'` — no capability indexes in the CLI |

### Q6 — Cheapest provider for `kimi-k3` + best TTFT

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_providers {model:kimi-k3}` + `{fields:host,ttft,cost_per_task}` | 9.6 s | 465 | ✓ cheapest `Makora $1.18`; best TTFT `LithosAI (ULTRA CHAT) 0.7 s` |
| B (repaired) | `providers kimi-k3` | 0.87 s | 450 | ✓ same cheapest; richer table (cache-read %, E2E, 17 rows) — B is **better** here |

### Q7 — text-to-image leader + cost per 1k images

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_media {"board":"text-to-image","top":5}` | 5.2 s | 160 | ✓ `GPT Image 2.5 Sunburst 1220 · $210.72/1k` |
| B (repaired) | `media text-to-image` (needs `lxml`+`tabulate`) | 1.7 s | 808 | ✓ same leader; includes 95 % CI — but the CI column renders mangled (`1220±1095% interval 1210 to 1230`) |

### Q8 — What the on-device set publishes + who leads its BFCL-500

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_benchmarks {query:"on-device"}` → `aa_benchmark_leaderboard {benchmark:"mobile.bfcl_500"}` | 10.7 s | 502 | ✓ names all 7 on-device evals **and** states `17 scored · AA chart set — not a full leaderboard`; leader `LFM2.5-8B-A1B (Q4_K_M) 42.7 %` |
| B (repaired) | `evals --metric bfcl` | 0.24 s | 77 | ✗ `Unknown metric 'bfcl'` — B's own `SKILL.md` says AA does not track BFCL, yet AA **does** publish an on-device BFCL-500 set |

### Q9 — A question whose data is absent on AA (MathVista / no published pricing)

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_benchmarks {query:mathvista}` | 4.4 s | 45 | ✓ `# AA does not track mathvista` + points at MMMU-Pro |
| A | `aa_model {query:muse-wonder-full}` | 29.7 s | 820 | ✓ every absent field is `-`, and the Coding/Agentic Index absence is explained inline |
| B (repaired) | `evals --metric mathvista` | 0.24 s | 78 | ~ `Unknown metric 'mathvista'` (honest, but it is a parser error, not a coverage statement) |
| B (repaired) | `model muse-wonder-full` | 3.5 s | 205 | ✓ prints `—` / `?` for absent price and release |

### Q10 — A judgment answer ("which should I pick for cost-sensitive agentic coding, and why")

| shape | commands | wall | tok | verdict |
|---|---|---:|---:|---|
| A | `aa_pareto {score:terminalBench40, min_intelligence:40}` | 6.5 s | 251 | ✓ frontier + explicit **knee** (`GPT-6.1 Sol (Max)`, 5× cost/score cliff) + `Terminal-Bench 4.0/$` column |
| B (repaired) | `leaderboard --min-intel 40 --frontier` | 0.27 s | 140 | ~ intel-vs-cost frontier only; no per-benchmark axis, so the *agentic-coding* part is not answerable from the data |

---

## 4. Totals

| | **A — MCP** | **B — skill+CLI (shipped)** | **B — repaired** | **C — pure skill** |
|---|---:|---:|---:|---:|
| questions answerable | **10 / 10** | **0 / 10** | 7 / 10 (4 clean, 3 partial) | 2 / 2 attempted |
| unanswerable | 0 | 10 | **3** (Q4 Cyber, Q5 Legal, Q8 on-device BFCL) | 0 of the 2 tried |
| calls | 16 | ~10 (all failing) | 12 | 2 scrapers |
| wall clock | 121.3 s (36.4 s of it tool time) | ~12 s (all errors) | 8.7 s | 2.2 s |
| answer tokens | **5,110** | ~500 (tracebacks) | 2,262 | 546 **of code** + output |
| **code the agent had to write** | **0 bytes** | 0 (but the CLI *is* 39,101 B of someone's code) | 0 | **2,182 B** for 2 questions |
| correctness (5+ values spot-checked vs a raw payload) | 10/10 | — | 4/4 checked | 2/2 |
| iterations/retries | 2 (Q4 key discovery, Q5 section name) | — | 1 patch + 2 split commands | 3 (2 silent-wrongness fixes) |

Spot-checks were done by fetching and parsing the raw payload independently of the
tool that produced the answer: Q1/Q2 from the leaderboard RSC array + HTML table
(`MiMo-V2.6-Pro` = `46.324…`), Q4 from the cyber-index eval page (`68.7`, `56.4`),
Q6 from `/models/kimi-k3/providers` (`Makora`, `$1.53`, `$12.75`), Q7 from
`/image/leaderboard/text-to-image` (`1220`, `210.72`), Q8 from
`/hardware-inference-stack/mobile-phones` (`LFM2.5-8B-A1B`, `42.7`).

---

## 5. Structural differences observed in practice

**Determinism.** A is byte-stable per input and footnotes its tie-breaks
(`— 2 models tie at 56.0; ordered by intelligence`). B has a *silently
non-deterministic* path: `leaderboard --sort coding` sorts on `codingIndex`, which
AA does not publish free (`grep -c '"codingIndex"' payload` = **0**), and the sort
puts nulls **first** (`key=(key(m) is None, key(m) or 0), reverse=True`) — so B
answers "best coding model" with `JT-35B-Flash (18.7*)`. A refuses the same
question honestly: *"AA publishes these composites only through its paid data API…
the free constituents are rankable."* This is the failure the repo exists to prevent,
and B ships it.

**Caching.** A: two disk caches (`AA_CACHE_TTL` 1 h, `AA_RICH_TTL` 6 h) shared by all
12 tools — visible in the run, where Q3 (1.0 s), Q5 (0.4 s) and Q10 (0.1 s) were tool
time once warm. B: one 1 h file cache in `/tmp/aa_cache`, also reused (repeat runs
0.24–0.4 s). C: **no cache** — each of my scrapers re-downloaded 1.9 MB / 1.0 MB of
HTML; a pure-skill agent pays that every question unless it writes caching too.

**Coverage honesty.** A states `shown / matching / tracked` and names the surface on
every header (`3 of 20 scored (273 tracked) · AA Cyber Ind … + chart set + homepage
panel`; `17 scored · AA chart set — not a full leaderboard`). B prints
`268 models (of 273 tracked)` but never says a benchmark is a *subset*, and its
`--sort coding` case shows what that omission costs. C: honesty is whatever the agent
remembers to write — my Q1 scraper silently returned `$/task=None` until I noticed.

**Error quality.** A's errors are domain-aware and enumerating: `unknown section(s)
capabilities — valid: identity, indexes, benchmarks, …`; `no model matches 'legal' —
closest slugs: none — use aa_search to resolve names to slugs`. B's are either
argparse usage dumps (`invalid choice: 'legal'`) or bare `Unknown metric`. Both beat
C, where the only error is a Python traceback you wrote yourself.

**Does the agent write code?** A: never — the 12 schemas are the contract. B: never,
but only because someone else wrote 39 KB of parser that must be kept in sync with
the site (and today is not). C: **always** — ~1.1 KB per question, and each new
surface (leaderboard RSC, eval-page RSC, providers HTML, media HTML, on-device page)
is a fresh scraper. For the 10 questions here that is ~5–10 KB of one-off code, none
of it tested, none of it shared.

**Cache reuse between questions.** A and B reuse a warm cache; C does not. In my run
A's per-question *tool* time collapsed from 3.9 s (cold discovery) to 0.1–1.0 s once
the cache was warm.

---

## 6. Where a shape cannot answer a question the other can

* **A answers, B cannot (even repaired):** Q4 AA Cyber Index, Q5 Legal capability
  index + sub-scores, Q8 on-device BFCL-500. B's CLI simply has no Cyber Index, no
  capability indexes, and no on-device set — they postdate the zip.
* **A answers, B answers wrongly:** Q3 (`Coding` row blank where A names the
  constituents and the missing metric) and the `--sort coding` case in §5.
* **A answers, B as-shipped cannot:** all 10.
* **B beats A:** Q6 only — the `providers` table carries cache-read $/1M and E2E
  latency that A's default view omits (A reaches them with `fields=`), and Q7's CI
  column. Nothing else.
* **C answers both questions it was given** (Q1, Q4) *after* the agent wrote the
  scraper — so C is not structurally incapable; it is structurally *expensive and
  unverifiable*, and the two bugs I hit (`costPerTask` absent from RSC; `name` vs
  `shortName` join mismatch) both produced plausible-but-wrong output rather than an
  error.

---

## 7. Recommendation

**Keep the MCP server as the data layer; keep a skill for conventions; do not ship
the zip's `aa.py`.** Concretely, for *this* capability:

* **MCP wins whenever the question needs AA's data.** It was the only shape that
  answered 10/10, it never made the agent write code, and its coverage labels are
  part of the response contract rather than advice the model may skip. Its cost is
  3,196 tok/session (after the §8 trim; 5,346 before) and 5,110 tok for all ten
  answers.
* **The skill shape wins for *conventions and reach*:** ≤40 tok to sit unused, one
  `cp -r` to install, editable in a minute, and the only shape that works in a client
  with no tool support. It should carry the routing table, the "never recompute
  `cost_per_task`" rule, the "AA publishes no free Coding/Agentic Index" caveat, and
  the not-tracked list — not a parser.
* **The skill+CLI shape is the worst of both here:** it pays the skill's fixed cost,
  it still needs a human to keep a 39 KB scraper in sync with AA's RSC layout (it is
  *already* broken — 0/10), and even repaired it is missing three of the ten
  surfaces. Its only defensible use is a client that can shell out but cannot speak
  MCP — and that gap is closed better by a thin CLI over the *existing* tool
  functions than by a second parser.
* **Pure skill is not viable for data questions.** ~0.5 KB of code per question, no
  cache, no coverage labels, and both of my two scrapers first produced
  confidently-wrong numbers. It is viable only as the *conventions* layer of the
  hybrid.

**Two sentences:** For this capability the MCP server is the right shape for data
(10/10 answerable, 5,110 tok, zero agent-written code) and a markdown skill is the
right shape for conventions and for tool-less clients (≤40 tok to sit unused), while
the bundled-CLI skill is dominated on both axes — it is broken as shipped (0/10) and
even repaired cannot reach the Cyber, Legal-capability or on-device surfaces.
Ship the hybrid that already exists in this repo (MCP + `skills/aa-mcp/SKILL.md`),
point the skill at a thin CLI over the same tool functions for shell-only clients,
and retire the zip's parallel parser rather than repairing it.

---

## 8. Post-trim: the MCP tool list at 3,196 tok (was 5,346)

The one cost the A/B run left standing was shape A's fixed context: **5,346 tok of
tool definitions at every session start, 64 % of it docstrings (13,648 B) and 30 %
schemas (6,349 B)**. It is now **3,196 tok — a 40.2 % cut**, with no change to any
tool's behaviour, signature, defaults or output text.

### 8.1 What was actually paying for those bytes

`mcp` 2.3 builds the tool like this
(`mcp/server/mcpserver/tools/base.py:85`):

```python
func_doc = description or fn.__doc__ or ""
```

— the **whole docstring** becomes the wire `description`, while `inputSchema` is
derived from the signature alone. An `Args:` block is therefore **never** turned
into per-parameter descriptions; it is just prose appended to the tool description.
Verified on the live payload: every `inputSchema.properties.<param>` has `type`,
`default` and `title` but **no `description`**, and `aa_leaderboard`'s wire
description (1,742 B) was byte-for-byte its docstring including the `Args:` block.

So the fix is not "write terser parameter docs" — it is **delete the `Args:` blocks
and fold only the routing-critical vocabulary into 3–6 lines of prose**. The
parameter *names* already reach the model through the schema; the parameter *essays*
were paid for and thrown away.

### 8.2 Before / after, per tool (wire bytes, exactly as `tools/list` serializes)

| tool | desc after | schema | **wire after** | wire before | cut |
|---|---:|---:|---:|---:|---:|
| `aa_leaderboard` | 465 | 1,377 | **1,941** | 3,503 | 45 % |
| `aa_pareto` | 488 | 823 | **1,407** | 2,552 | 45 % |
| `aa_benchmark_leaderboard` | 499 | 726 | **1,342** | 1,771 | 24 % |
| `aa_providers` | 554 | 663 | **1,309** | 2,054 | 36 % |
| `aa_media` | 591 | 511 | **1,191** | 1,866 | 36 % |
| `aa_compare` | 535 | 496 | **1,117** | 3,504 | 68 % |
| `aa_benchmarks` | 489 | 291 | **886** | 1,467 | 40 % |
| `aa_search` | 387 | 390 | **863** | 1,483 | 42 % |
| `aa_raw` | 351 | 399 | **842** | 1,030 | 18 % |
| `aa_model` | 393 | 302 | **775** | 1,047 | 26 % |
| `aa_agents` | 277 | 244 | **607** | 564 | **−8 %** |
| `aa_reference` | 265 | 127 | **490** | 531 | 8 % |
| **TOTAL** | **5,294** | **6,349** | **12,770 B per tool = 12,783 B = 3,196 tok serialized** | 21,372 / 21,385 B = 5,346 tok | **40.2 %** |

(The serialized `tools/list` array is 13 bytes larger than the sum of its tools —
`[`, the separating `,`s and `]`. 12,783 B = 3,196 tok is what the client actually
receives; the per-tool column is what the docstrings and schemas cost.)

Description + schema alone: **11,643 B = 2,911 tok** (from 19,997 B = 4,999 tok,
41.8 % cut). The remaining 6,349 B of schema is structural — parameter names, types,
defaults and pydantic's auto-generated `title` per property — and is untouchable
without changing signatures.

`aa_agents` is the one tool that grew (−8 %): it gained the "an agent row is not a
language model" honesty cue, which is worth more than 43 bytes.

### 8.3 What was cut, and what was kept

**Cut:** every `Args:` block (the whole point — it never reaches the model); worked
examples that duplicate `aa_reference` topics; the parameter inventory restated in
prose (`creator=, name=, min_intelligence=, …` — the schema already lists them);
repeated restatements of one rule across several tools; the long enumeration of
`domain=` values and the "one metric never means two numbers" paragraph on
`aa_compare` (the tool's own footnote says it).

**Kept, deliberately** — every routing cue the earlier evaluation rounds proved
necessary, now in prose: what each tool answers; `aa_search` before guessing names
(`aa_leaderboard`, `aa_model`, `aa_search`); `metrics="all"` / `view="diff"` on
`aa_compare`; `mode=value` and "same as aa_pareto" for trade-offs; `domain=`/`query=`
on `aa_benchmarks`; `fields=` for exact columns; `refresh=true`; provider `sort=`,
`model=`, `host=`; media `board=`/`category=`; and the honesty cues — coverage
labels ("The header labels coverage and ties"), "not a full leaderboard", "a board
entry is not a language model … not cross-comparable", and `aa_reference`'s
"keyless — there is no API-key path".

**One cue was corrected rather than cut:** the first draft of `aa_leaderboard` said
"`*` = AA estimate", but `aa_leaderboard` does **not** render that marker — only
`aa_benchmark_leaderboard` (`*` + footnote, `include_estimates=false`) and `aa_model`
(`Intel*`) do. The claim was removed from `aa_leaderboard` rather than left to
mislead. Likewise `aa_raw` now says `fields=` is "ignored for kind=model", which is
what `_raw` does (`_project` is applied to every kind except `model`).

**Borderline cuts, named rather than hidden** (each recoverable from a reply or a
neighbouring tool, so I judged none load-bearing enough to spend the bytes):
`aa_leaderboard`'s "use `aa_reference topic=fields` for all names" (the topic list in
`aa_reference` still advertises `fields`); `aa_media`'s "hyphens/spaces/case are
ignored" (the error text names the published boards); `aa_media`'s "not available on
homepage speech panels"; and `aa_compare`'s "one metric never means two numbers"
(its own reply footnote carries it). If a future eval round shows an agent fumbling
one of these, it is a one-line add — the budget test has ~280 tok of headroom.

### 8.4 Budget test

`tests/test_server.py::test_tool_list_fixed_context_stays_within_budget` serializes
the registered list exactly as the wire does and pins two ceilings, with the measured
number in the assertion message:

```python
_TOOL_DESC_SCHEMA_TOK_CEILING = 3200   # description + inputSchema, all 12 tools
_TOOL_WIRE_TOK_CEILING = 3400          # the serialized tools/list result

payload = [t.model_dump(by_alias=True, exclude_none=True)
           for t in asyncio.run(server.srv.list_tools())]
desc_schema = sum(len(t["description"]) + len(json.dumps(t["inputSchema"],
                  separators=(",", ":"))) for t in payload)
wire = len(json.dumps(payload, separators=(",", ":")))
assert desc_schema / 4 < 3200   # measured 2,911
assert wire / 4 < 3400          # measured 3,196
```

### 8.5 Routing did not regress: 8/8

Eight realistic phrasings, routed **from the trimmed `eval/client.py tools` listing
alone**, then executed:

| # | phrasing | tool + arguments | answered |
|---|---|---|---|
| 1 | "cheapest model above Intelligence 50" | `aa_leaderboard {mode:"value", min_intelligence:50, top:4}` | ✓ Intel/$ ranking + "153 rows skipped: no measured cost" footnote |
| 2 | "where does the intelligence-vs-cost curve stop being worth it" | `aa_pareto {top:6}` | ✓ 16 frontier points + `knee ≈ MiMo-V2.6-Pro … 5× cost/score cliff` |
| 3 | "compare three models on every benchmark" | `aa_compare {queries:[…3…], metrics:"all"}` | ✓ 102 metrics × 3 models |
| 4 | "which provider serves `kimi-k3` cheapest / fastest" | `aa_providers {model:"kimi-k3", sort:"cost_per_task"}` + `{sort:"ttft"}` | ✓ Makora $1.18; LithosAI (ULTRA CHAT) 0.7 s |
| 5 | "who leads GPQA Diamond" | `aa_benchmark_leaderboard {benchmark:"gpqa", top:3}` | ✓ GPT-6 Astra 96.3 % + source label (`leaderboard`) |
| 6 | "find the benchmark for a security task" | `aa_benchmarks {domain:"security"}` | ✓ 10 rankables, each with its `How to query` call |
| 7 | "is this number AA-estimated" | `aa_benchmark_leaderboard {benchmark:"intelligence", creator:"china mobile"}` | ✓ `27.3*` / `18.7*` + the `*` footnote |
| 8 | "raw JSON for an odd field" | `aa_raw {kind:"model", query:"claude-opus-5-5"}` | ✓ `weights_url`, `knowledge_cutoff`, `size_class` |

Q7 is the one that took a second attempt: `aa_leaderboard {fields:"intelligence"}`
returned `18.7` with **no** `*` (the marker is not rendered there), which is how the
inaccurate cue in §8.3 was found and removed.

### 8.6 Gates

* `uvx ruff check .` — **All checks passed!**
* `AA_OFFLINE=1 uv run pytest -q` — **751 tests collected, 0 failures** (rc=0;
  `pyproject.toml` already sets `addopts = "-q"`, so a second `-q` suppresses the
  summary line — the run's rc is the signal).
* `.venv/bin/python scripts/surface_sweep.py` — **315 calls · 36 failures
  (21 expected, 15 unexpected) · ≈99,707 tokens total**. The 21 expected failures
  are the sweep's documented error cases and all fired correctly. The 15 unexpected
  ones are **live-catalog drift in the sweep's own hardcoded names, not the trim**:

  * `aa_model {"query": "glm-4-5v"}` ×11 — AA's catalog no longer carries
    `glm-4-5v` (the sweep's own comment calls it "legacy page"); the error is
    `no model matches 'glm-4-5v' — closest slugs: none`.
  * `aa_compare {"queries": ["claude-opus-5-5", "gpt-5-2"], …}` ×4 — AA's image
    arena now carries a row that fuzzy-matches `gpt-5-2`, so the query resolves to
    a *board* row (`GPT Image 2.5 Flare (max)` on `image_editing`) and
    `aa_compare` correctly refuses to mix it with a language model. `aa_search
    {"query":"gpt-5-2"}` shows both the language-model match and
    "6 board/arena matches".

  **Proof the trim is not the cause:** `ast.dump` of the new
  `src/aa_mcp/server.py` with every docstring stripped is **identical** to
  `git show HEAD:src/aa_mcp/server.py` — the executable code is unchanged, so no
  tool's resolution or output can differ. Fixing the sweep (its stale
  `MODEL_CANDIDATES` / `gpt-5-2` cases) is a separate change outside this task's
  file scope, so it is reported rather than patched.

No file outside `src/aa_mcp/server.py` (docstrings only), `tests/test_server.py`
(the budget test) and this report was touched by this task.
