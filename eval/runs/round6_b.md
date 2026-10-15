# Round 6 — native MCP test — agent `EvalR6b`

Date: 2026-10-15 · repo `/home/wavy/ai/aa-mcp`

## Step 1 — the native-tool finding (primary result) — LITERAL

**I do NOT see any `aa_*` MCP tools in my own tool list.**

My complete tool list, verbatim as exposed to me:

`read`, `bash`, `edit`, `eval`, `glob`, `grep`, `task`, `wait`, `web_search`, `write`

plus the `xd://` virtual devices: `xd://ast_edit`, `xd://debug`, `xd://report_issue`.

No `aa_leaderboard`, `aa_model`, `aa_compare`, `aa_pareto`, `aa_search`, `aa_benchmarks`,
`aa_benchmark_leaderboard`, `aa_providers`, `aa_media`, `aa_agents`, `aa_reference`,
`aa_raw` — none of them. No MCP-sourced tool of any server appears.

Corroborating evidence (read-only):

- `~/.omp/agent/mcp.json` **does** register the server and it **is enabled**:
  ```json
  "aa": { "type": "stdio", "command": "/home/wavy/.local/bin/aa-mcp",
          "timeout": 180000, "enabled": true }
  ```
  (all other servers in that file — excel, windows-excel, win-ghidra-mcp, charlotte,
  adeu, turnkeys-audio-inspector — are `"enabled": false`, and none of *their* tools show
  up either.)
- `/home/wavy/.local/bin/aa-mcp` exists and the stdio harness drives it fine (see below).

**Conclusion:** the registration in `~/.omp/agent/mcp.json` is **not reaching the
subagent's native tool list**. `aa-mcp` is therefore *not* usable as a native MCP server
from inside a subagent in this round — this is exactly the "not present" branch of the
protocol (step 3). The server itself is healthy (every harness call below succeeded), so
the gap is on the omp→subagent MCP-exposure side, not on aa-mcp's side.

## Path used

Per protocol step 3: since the native tools are absent, **all answers below were obtained
through the stdio harness**:

```
.venv/bin/python eval/client.py call <tool> '<json>'
```

No curl, no web search, no source-code reading was used to answer the questions.

Call log note: the harness appends one record per call to `eval/runs/live.ndjson`
(`tool`, `args`, `ms`, `chars`, `tokens_est`, `is_error`) and prints
`[harness] <chars> chars ≈ <tok> tok · <ms>ms · error=<bool>` to stderr. The
chars/tok numbers below are those printed values (tokens ≈ chars/4).

---

## B1 — find a security benchmark via search, then top 3 models

**First tool picked: `aa_benchmarks` — the right one.** It is literally described as
"Search everything rankable: benchmarks, indexes, derived metrics, arenas", so no guessing
was needed to route here.

### Call 1
```
aa_benchmarks {"query":"security"}
```
- Result: 1877 chars ≈ 470 tok, 6543 ms, no error.
- Returned `10 of 101 rankables · query=security (domain match)`. The security-relevant
  rankables include CWE-Bench-AA (cyber vulnerability benchmark), CWE Refusal,
  Cyber Mitigation, Cyber Refusal, CyberGym-E2E-AA, CyberGym Refusal, DeepSecBench-AA,
  DeepSec Refusal, WildGuardTest, and the AA Cyber Index.
- The row itself told me the key to use next: `aa_leaderboard sort=cweBench` /
  `aa_benchmark_leaderboard benchmark=…`.

**Which is "the right one":** `CWE-Bench-AA` — the one described as the
"cyber vulnerability benchmark". (WildGuardTest is safety/guardrail, not security
engineering; the Refusal/Mitigation rows are companions, not the capability benchmark.)

### Call 2
```
aa_benchmark_leaderboard {"benchmark":"CWE-Bench-AA","top":3}
```
- Result: 409 chars ≈ 103 tok, 492 ms, no error.

**Top 3 models on CWE-Bench-AA:**

| # | Model | Slug | Creator | CWE-Bench-AA | Intel |
|---|-------|------|---------|--------------|-------|
| 1 | Grok 4.7 (Xhigh) | `grok-4-7` | SpaceXAI | 68.3% | 46.4 |
| 2 | DeepSeek V4.1 Flash (Max) | `deepseek-v4-1-flash` | DeepSeek | 68.3% | 39.5 |
| 3 | GPT-6 Sol (Daybreak Blue, max) | `gpt-6-sol-daybreak-blue` | OpenAI | 64.7% | – |

Header honesty: "3 of 20 scored (700 tracked) · CWE-Bench-AA · AA chart set — not a full
leaderboard". (1–2 are a tie on the metric; Grok 4.7 has the higher Intelligence.)

**Calls: 2 · answer cost ≈ 573 tok (470 + 103). First tool right: yes.**

---

## B2 — top 5 on the Legal capability index, and how I found the metric

**First tool picked: `aa_benchmarks` — the right one** (same search surface as B1).

### Call 1
```
aa_benchmarks {"query":"legal"}
```
- Result: 636 chars ≈ 159 tok, 1231 ms, no error.
- Returned `3 of 101 rankables · query=legal`. It named the index explicitly:
  `Cap Legal | index | index | rich dataset (218/700) | aa_leaderboard sort=capabilities.legal`
  — "AA capability index: legal (0-100)". This is **how I found the metric**: a
  `query=legal` search on `aa_benchmarks`, which handed back the exact sort key
  `capabilities.legal` in its "How to query" column.

### Call 2
```
aa_leaderboard {"sort":"capabilities.legal","top":5}
```
- Result: 789 chars ≈ 198 tok, 627 ms, no error.

**Top 5 models on Cap Legal:**

| # | Model | Slug | Creator | Cap Legal | Intel |
|---|-------|------|---------|-----------|-------|
| 1 | Claude Opus 5.5 (Max, Default Fallback) | `claude-opus-5-5` | Anthropic | 63.3 | 57.6 |
| 2 | Claude Fable 5.1 (Xhigh, Default Fallback) | `claude-fable-5-1-xhigh` | Anthropic | 60.8 | 53.2 |
| 3 | Claude Opus 5.5 (Xhigh, Default Fallback) | `claude-opus-5-5-xhigh` | Anthropic | 60.8 | 56.0 |
| 4 | Claude Fable 5.1 (Max, Default Fallback) | `claude-fable-5-1` | Anthropic | 60.5 | 53.4 |
| 5 | Gemini 4 Argon (High) | `gemini-4-argon` | Google | 60.0 | 52.6 |

Header: "5 of 131 scored (700 tracked) · Cap Legal, active only".

**Calls: 2 · answer cost ≈ 357 tok (159 + 198). First tool right: yes.**

---

## B3 — four models on every metric AA publishes

Query string decoded: `mimo-v2-6-pro, deepseek-v4-1-flash, gpt-6-luna-xhigh, muse-wonder-full`.

**First tool picked: `aa_compare` — the right one.** Its description is "Side-by-side
comparison of 2-12 models on any benchmark … every rankable metric". I read its schema
(see friction #2) to learn that `metrics` defaults to `""` (a small "default set") and that
`metrics:"all"` selects "every rankable key any of these models has". So I made two calls:
one to see the default, one for `all`.

### Call 1 (default metrics — exploratory)
```
aa_compare {"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"],"compact":false}
```
- Result: 1062 chars ≈ 266 tok, 667 ms, no error.
- Header: "4 models · **13 metrics**". Missing line: "MiMo-V2.6-Pro 4, DeepSeek V4.1
  Flash (max) 4, GPT-6 Luna (xhigh) 4, Muse Wonder Full (max) 11".
- The footer says "metrics: default (default set)" — i.e. 13 is *not* "every metric".

### Call 2 (the answer)
```
aa_compare {"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"],"metrics":"all","compact":false}
```
- Result: **3939 chars ≈ 985 tok**, 1306 ms, no error.
- Header: "4 models · **58 metrics** · aa:rsc + rich dataset".

**Number of metric rows: 58** (with `metrics:"all"`; the default set is only 13).

**Missing-data summary (verbatim footer line):**
> `missing on requested metrics: MiMo-V2.6-Pro 4, DeepSeek V4.1 Flash (max) 2, GPT-6 Luna (xhigh) 24, Muse Wonder Full (max) 35`

i.e. of the 58 requested rows: MiMo missing 4, DeepSeek missing 2, GPT-6 Luna missing 24,
Muse Wonder Full missing 35. The tool also footnotes *where* the sparse rows come from:
"AA-3D Elo, Analyst Pass@1, Analyst Pass@k, CWE Refusal, CyberGym Refusal, DeepSec Refusal,
MLCR Accuracy, MLCR Complete … (+1 more) from AA's eval chart set (top ~28 models)";
"CWE-Bench-AA, Cyber Index, CyberGym-E2E-AA, DeepSecBench-AA from AA's eval chart set /
homepage panel (top ~22 models)"; "Cyber Refusal from AA's homepage panel (top ~20 models)".
So the big Muse/GPT-6 gaps are the narrow chart-set/panel rows, not core metrics.

Sample of the 58 rows (4-model columns; `-` = not published for that model):
Intelligence 46.3 / 39.5 / 34.6 / 55.8; AA-Briefcase Elo 1516 / 1422 / 1237 / 1729;
GDPval-AA 59.2% / 55.0% / 43.2% / 67.9%; Terminal-Bench 4.0 34.8% / 26.8% / 8.1% / 57.1%;
CWE-Bench-AA 63.3% / 68.3% / – / –; Cap Legal 44.8 / 41.3 / 37.2 / 54.7;
AA-Omniscience Index 8.4 / −5.3 / −1.8 / 30.1; Cost per Task $0.13 / $0.27 / $0.04 / –.

**Token cost of the answer: ≈ 985 tok (3939 chars) for the one `metrics:"all"` call**;
+266 tok for the default-set probe = 1251 tok for the B3 exploration+answer.
**Calls: 2. First tool right: yes** (the only mis-step was the default `metrics` value —
see friction #3).

---

## Token-cost table

`tokens ≈ ceil(chars/4)`, values as printed by the harness.

| # | Question | Call (tool + args) | chars | tok | ms | err |
|---|----------|--------------------|------:|----:|---:|-----|
| 0 | setup | `tools` (enumerate the 12 aa tools) | 1,870 | 468 | – | – |
| 0 | setup | `schema` (full JSON schemas, all tools) | 22,366 | 5,592 | – | – |
| B1 | security bench | `aa_benchmarks {"query":"security"}` | 1,877 | 470 | 6543 | no |
| B1 | top 3 | `aa_benchmark_leaderboard {"benchmark":"CWE-Bench-AA","top":3}` | 409 | 103 | 492 | no |
| B2 | legal metric | `aa_benchmarks {"query":"legal"}` | 636 | 159 | 1231 | no |
| B2 | top 5 | `aa_leaderboard {"sort":"capabilities.legal","top":5}` | 789 | 198 | 627 | no |
| B3 | probe | `aa_compare {…,"compact":false}` (default metrics) | 1,062 | 266 | 667 | no |
| B3 | answer | `aa_compare {…,"metrics":"all","compact":false}` | 3,939 | 985 | 1306 | no |

**Answer-only cost** (the calls that actually produced the requested answers, no setup,
no probe): B1 = **573**, B2 = **357**, B3 = **985** → **1,915 tok / 6 calls**.
**Everything incl. tool enumeration + full schema dump**: **8,241 tok / 8 calls**.

Per-call sizes: median 874 chars (~219 tok), max 22,366 chars (the `schema` dump) — that one
call alone is 68% of the whole round's token spend.

---

## Blunt friction list

1. **Native exposure is broken/absent (the headline).** `aa` is `enabled:true` in
   `~/.omp/agent/mcp.json` and the server runs, yet **zero MCP tools reach the subagent
   tool list** — not just aa, but every other configured server too (all disabled, but
   `aa` isn't). If this round's goal was "use the native tools", that goal is **not met**:
   I had to fall back to the stdio harness for all three questions. This is a
   registration/host-plumbing finding, not an aa-mcp finding.

2. **`client.py schema` dumps every tool's full JSON Schema in one 22.4k-char blob
   (~5,592 tok).** There is no `schema <tool>` selector, so asking about one tool's
   arguments costs ~5.6k tokens. I only wanted `aa_compare`'s `metrics` semantics. Worst
   offender of the round by far.

3. **`aa_compare`'s `metrics` default is a trap.** Default `metrics:""` gives only
   **13** rows and labels them "default set"; the question ("every metric AA publishes")
   needs `metrics:"all"` → **58** rows. The tool *does* footnote this ("metrics=all: every
   rankable key…") but only *after* you call with `all`; the default output says nothing
   about a larger set existing. A first-try reader answers B3 with 13 rows and is wrong.
   (Cost of discovering this: one extra 266-tok probe.)

4. **`aa_compare` ignores `compact` when `metrics=` is given** — the tool says so
   explicitly ("compact is ignored when metrics= is given"). So the caller cannot get a
   compact `metrics:"all"` view; the only all-metrics output is the 3.9k-char wide table.

5. **Nothing was "too large" except the schema dump** (see #2). The widest real answer,
   `metrics:"all"` at 3,939 chars / 985 tok, is acceptable and honest. Search/leaderboard
   outputs (0.4k–1.9k chars) are well sized.

6. **No tool had to be guessed at.** The routing was correct on the first try for all
   three questions: `aa_benchmarks` for "search a benchmark/index" (B1, B2) and
   `aa_compare` for "compare N models on metrics" (B3). The tool *descriptions* were
   sufficient — `aa_benchmarks`'s "Search everything rankable" and `aa_compare`'s
   "every rankable metric" are exactly what the questions needed. The one description
   gap is the `metrics` default (#3), which is a schema/default issue, not a routing one.

7. **Everything asked was obtainable** — no unanswerable question. The only thing I could
   *not* do is the round's actual premise (drive the native `aa_*` tools), because they
   are not in my tool list (#1).

8. **Minor:** `aa_benchmark_leaderboard benchmark="CWE-Bench-AA"` (the display name)
   worked, but the search result had advertised the key as `cweBench`; two spellings for
   the same thing is a small inconsistency in the "How to query" hints.

9. **Minor:** the harness prints its `[harness] …chars ≈ …tok` line to **stderr** while
   the payload goes to stdout; a caller who only captures stdout loses the exact size
   metrics the round asks for. Easy to miss.
