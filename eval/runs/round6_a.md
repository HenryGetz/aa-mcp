# Round 6 — native MCP test, set A (`round6_a`)

Runner: subagent `EvalR6a`. Date: 2026-10-15. Repo: `/home/wavy/ai/aa-mcp`.

---

## Step 1 — native-tool finding (the primary result)

**I cannot see any `aa_*` MCP tools in my own tool list. None. Not one.**

My complete, literal tool list in this session is:

| tool | kind |
|---|---|
| `read` | file/URL reader |
| `bash` | shell |
| `edit` | string replacement |
| `eval` | Python/JS kernel |
| `glob` | filename globbing |
| `grep` | regex search |
| `task` | subagent spawner |
| `wait` | background-job barrier |
| `web_search` | web search |
| `write` | file writer |

Plus two `xd://` tool devices documented as available on demand: `xd://ast_edit`,
`xd://debug`. That is the entire inventory.

Specifically **absent**: `aa_leaderboard`, `aa_model`, `aa_compare`, `aa_pareto`,
`aa_search`, `aa_benchmarks`, `aa_benchmark_leaderboard`, `aa_providers`, `aa_media`,
`aa_agents`, `aa_reference`, `aa_raw`. I can name them only because they are written in
`eval/questions_round6_native.md` and because the harness `eval/client.py tools` lists
them — **not** because they are registered as callable tools in my session.

I attempted no tool call against a native `aa_*` name because no such name exists in my
tool namespace; the harness is the only path that reaches the server (confirmed by
`.venv/bin/python eval/client.py tools`, which lists all 12 tools over stdio).

**Interpretation (INFERENCE):** the `aa` server is registered and `enabled: true` in
`~/.omp/agent/mcp.json` (verified — a stdio server pointing at
`/home/wavy/.local/bin/aa-mcp`, timeout 180000), and the stdio harness reaches it fine, but
that registration does **not** propagate native `aa_*` tools into this subagent's tool list.
So round 6's hypothesis is **not confirmed for subagents**: native exposure is not reaching
subagents, even though the server itself is healthy. This is a valid negative finding.

**Path actually used for A1–A3:** the stdio harness,
`.venv/bin/python eval/client.py call <tool> '<json>'` (per step 3 of the question file).

---

## Set A answers

### A1. Best value above Intelligence 45, and the knee of the intelligence-vs-cost frontier

**Best value above Intel 45: `MiMo-V2.6-Pro` (Xiaomi)** — Intelligence **46.3** at
**$0.13/task** (highest Intel/$ of anything scoring >45; the next-cheapest model above 45 is
GPT-6.1 Sol (Medium) at $0.21, then GPT-6 Astra (Low) at $0.82 for a *lower* 45.8).

**Knee of the Intelligence-vs-Cost frontier: `MiMo-V2.6-Pro`** — $0.13/task, Intel 46.3;
the server states the cliff explicitly: *"knee ≈ MiMo-V2.6-Pro: $/task $0.13, Intel 46.3
(5× cost/score cliff)"*.

**Frontier models (16 non-dominated of 117 scored, cheapest → smartest):**

| Model | Intel | $/task |
|---|---|---|
| K2 Horizon 375B A23B | 30.5 | $0.00 |
| GPT-6 Luna (High) | 32.9 | $0.03 |
| GPT-6 Luna (Xhigh) | 34.6 | $0.04 |
| MiMo-V2.6-Flash | 37.9 | $0.06 |
| GPT-6 Luna (Max) | 38.1 | $0.07 |
| Claude Haiku 5.5 (Xhigh) | 41.2 | $0.12 |
| GPT-6.1 Sol (Low) | 42.1 | $0.13 |
| **MiMo-V2.6-Pro (knee)** | **46.3** | **$0.13** |
| GPT-6.1 Sol (Medium) | 47.8 | $0.21 |
| GPT-6.1 Sol (High) | 50.2 | $0.32 |
| GPT-6.1 Sol (Xhigh) | 51.0 | $0.39 |
| GPT-6.1 Sol (Max) | 51.8 | $0.72 |
| Claude Opus 5.5 (High) | 53.6 | $1.82 |
| Claude Opus 5.5 (Xhigh) | 56.0 | $3.46 |
| Claude Sonnet 5.5 (Max) | 56.0 | $5.46 |
| Claude Opus 5.5 (Max) | 57.6 | $5.98 |

**Call log (3 calls, 733 tok):**

| # | tool | args | chars | ≈tok | ms | err |
|---|---|---|---|---|---|---|
| 1 | `aa_pareto` | `{"x":"cost_per_task","include_all":true}` | 1689 | 423 | 1617 | no |
| 2 | `aa_leaderboard` | `{"min_intelligence":45,"sort":"intel_per_cost","top":10}` | 201 | 51 | 104 | **yes** — `unknown sort 'intel_per_cost'` |
| 3 | `aa_leaderboard` | `{"min_intelligence":45,"sort":"cost_per_task","top":8}` | 1033 | 259 | 250 | no |

First pick was right: `aa_pareto x=cost_per_task` gave both the knee and the full frontier in
one call. Call 2 was a self-inflicted guess at a sort name that does not exist (the error's
"closest" list does not contain any efficiency sort — so "best value" must be derived from
the frontier / cost-sorted leaderboard, not sorted directly).

---

### A2. `mimo-v2-6-pro` vs `deepseek-v4-1-flash` (cyber, coding, cost, with deltas)

One call, `metrics=all view=diff`: **57 metrics**, deltas vs the first model.

**Call log (1 call, 935 tok):**

| # | tool | args | chars | ≈tok | ms | err |
|---|---|---|---|---|---|---|
| 1 | `aa_compare` | `{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash"],"metrics":"all","view":"diff"}` | 3737 | **935** | 15321 | no |

**→ The answer costs ≈ 935 tokens (3,737 characters), one call.** (The question's
"what does the answer cost you in tokens" = this call's result size.)

**Cyber — winner: `mimo-v2-6-pro`** (decisively on the headline indices):

| metric | MiMo | DeepSeek | Δ | winner |
|---|---|---|---|---|
| Artificial Analysis Cyber Index | 56.1 | 40.8 | −15.3 | **MiMo** |
| CyberGym-E2E-AA | 78.6% | 22.9% | −55.7pp | **MiMo** |
| CWE-Bench-AA | 63.3% | 68.3% | +5.0pp | DeepSeek |
| DeepSecBench-AA | 26.2% | 31.2% | +5.0pp | DeepSeek |
| Harvey LAB-AA | — | 1.7% | n/a | DeepSeek (only) |
| CWE/Cyber/CyberGym/DeepSec Refusal | 0.0% | 0.0% | 0.0 | tie |

Verdict: **MiMo wins cyber** (Cyber Index +15.3, CyberGym-E2E +55.7pp); DeepSeek takes the
narrower CWE/DeepSec/Harvey sub-benchmarks.

**Coding — winner: `mimo-v2-6-pro`** (general coding + agentic):

| metric | MiMo | DeepSeek | Δ | winner |
|---|---|---|---|---|
| FrontierCode | 45.4% | 44.0% | −1.4pp | **MiMo** |
| SciCode | 60.9% | 51.9% | −9.0pp | **MiMo** |
| Terminal-Bench 4.0 | 34.8% | 26.8% | −8.1pp | **MiMo** |
| AA-AnalystAgent | 37.5% | 35.0% | −2.5pp | **MiMo** |
| Analyst Pass@1 | 61.3% | 58.5% | −2.8pp | **MiMo** |
| Analyst Pass@k | 80.0% | 80.0% | 0.0 | tie |
| AA-Briefcase Elo | 1516 | 1422 | −94 | **MiMo** |
| MLCR-AA | 18.3% | 22.8% | +4.4pp | DeepSeek |
| MLCR Accuracy / Concise | 54.9 / 73.9 | 83.3 / 96.7 | +28.4 / +22.8pp | DeepSeek |
| MLCR Complete | 42.1% | 27.0% | −15.1pp | MiMo |
| MMMU-Pro | — | 77.0% | n/a | DeepSeek (only) |

Verdict: **MiMo wins coding** on the hard coding benchmarks (SciCode, Terminal-Bench,
FrontierCode, Analyst); DeepSeek wins the long-context MLCR accuracy/concise and MMMU-Pro.

**Cost — winner: `mimo-v2-6-pro`** (per-task and whole-suite), DeepSeek wins only the
*input* token price:

| metric | MiMo | DeepSeek | Δ | winner |
|---|---|---|---|---|
| Cost per Task | $0.13 | $0.27 | +$0.14 | **MiMo** |
| Cost to Run the Index (suite) | $207 | $477 | +$270 | **MiMo** |
| Output Price /1M | $0.87 | $1.20 | +$0.33 | **MiMo** |
| Cache Read Price /1M | $0.0036 | $0.0060 | +$0.0024 | **MiMo** |
| Input Price /1M | $0.43 | $0.30 | −$0.13 | DeepSeek |
| Output Tokens per Index Task | 64k | 89k | +24,298 | **MiMo** (fewer) |
| Speed (tok/s) | 45.8 | 173.9 | +128.1 | DeepSeek (≈3.8× faster) |
| TTFT | 4.0s | 1.1s | −2.9s | DeepSeek |
| Time per Index Task | 1194.2s | 334.9s | −859.3s | DeepSeek |

**Overall verdict: `mimo-v2-6-pro` wins cyber, coding and cost; `deepseek-v4-1-flash` wins
speed/latency and input-token price.** (Overall Intelligence 46.3 vs 39.5.) Note the server
emits **raw metric rows, not domain verdicts** — the three verdicts above are my aggregation.

---

### A3. Cheapest provider for `kimi-k3`, and best time-to-first-token

**Cheapest: `Makora`** — **$1.18/task**, input **$1.53 /1M**, output **$12.75 /1M**
(cheapest on all three). Next: LithosAI $1.69/task, Databricks $1.85.

**Best time-to-first-token: `LithosAI (ULTRA CHAT)`** — **0.7s** (next: Baseten 0.8s,
LithosAI 0.8s, Fireworks 1.0s, Databricks 1.0s). Note this is *not* the cheapest host — it
is $3.93/task at $5.60/$28.00 per 1M, i.e. TTFT and price are anti-correlated here. The
cheapest host, Makora, has a mid-pack TTFT of 1.2s.

**Call log (4 calls, 697 tok):**

| # | tool | args | chars | ≈tok | ms | err |
|---|---|---|---|---|---|---|
| 1 | `aa_providers` | `{"model":"kimi-k3"}` | 1073 | 269 | 1212 | no — sorted by `$ /task`, **no TTFT column** |
| 2 | `aa_providers` | `{"model":"kimi-k3","sort":"ttft"}` | 1062 | 266 | 756 | no — rows reordered, **still no TTFT column** |
| 3 | `aa_providers` | `{"model":"kimi-k3","sort":"ttft","fields":"all"}` | 169 | 43 | 600 | **yes** — `unknown field 'all'` |
| 4 | `aa_providers` | `{"model":"kimi-k3","sort":"ttft","fields":"ttft"}` | 474 | 119 | 663 | no — TTFT values finally visible |

First pick (`aa_providers`) was right, but the default column set omits TTFT, so the TTFT
answer needed a **second** call (`sort=ttft` only reorders) and then a **third**
(`fields=ttft`) to actually read the numbers. 17 endpoints tracked, 15 shown (2 hidden).

---

## Token-cost table (harness's own `chars/4` estimate)

| Q | call | tool | chars | ≈tok | ms | error |
|---|---|---|---|---|---|---|
| A1 | 1 | `aa_pareto` | 1689 | 423 | 1617 | |
| A1 | 2 | `aa_leaderboard` (bad sort) | 201 | 51 | 104 | ERR |
| A1 | 3 | `aa_leaderboard` | 1033 | 259 | 250 | |
| A2 | 1 | `aa_compare` | 3737 | 935 | 15321 | |
| A3 | 1 | `aa_providers` | 1073 | 269 | 1212 | |
| A3 | 2 | `aa_providers sort=ttft` | 1062 | 266 | 756 | |
| A3 | 3 | `aa_providers fields=all` | 169 | 43 | 600 | ERR |
| A3 | 4 | `aa_providers fields=ttft` | 474 | 119 | 663 | |
| **total** | **8 calls** | | **9,438** | **2,365** | | 2 errors |

| Q | calls | ≈tokens | notes |
|---|---|---|---|
| A1 | 3 | 733 | 1 wasted on a nonexistent sort name |
| A2 | 1 | **935** | the answer's own cost, as asked |
| A3 | 4 | 697 | 2 extra calls purely to surface TTFT |
| **total** | **8** | **2,365** | plus one non-logged `tools` listing (≈1.5k chars ≈ 375 tok) |

Per-question answer cost (single result): A1 = 423 tok (the pareto call), A2 = **935 tok**,
A3 = 119 tok (the `fields=ttft` call) — though A3 realistically costs 269+266+119 = 654 tok
because the price answer and the TTFT answer live in different column sets.

---

## Blunt friction list

1. **Native tools are absent (the headline finding).** `~/.omp/agent/mcp.json` enables the
   `aa` stdio server and the harness reaches it, but **zero `aa_*` tools appear in this
   subagent's tool list**. The round-6 premise (native exposure to an agent) is **not
   satisfied for subagents** — I had to fall back to `eval/client.py` per step 3.
2. **Output too large:** `aa_compare metrics=all` on 2 models = **3,737 chars / ≈935 tok**
   for one comparison. It is the single most expensive call in set A and is ~40% of my total
   token spend. (For 4 models — set B's B3 — this would be larger still.) It is *not*
   obviously trimmable (the user asked for every metric), but it is the dominant cost.
3. **A tool I had to guess at — sort names.** `aa_leaderboard sort=intel_per_cost` was a
   guess (I wanted "best value") and errored: `unknown sort 'intel_per_cost'`. The error's
   "closest" suggestions (`intelligence, intel, cost_per_task, out_tokens_per_task,
   tau2_telecom`) contain **no efficiency/Intel-per-dollar sort at all**, so "best value"
   cannot be asked for directly — it must be read off `aa_pareto`'s `Intel/$/task` column or
   derived from a cost-sorted leaderboard. Wasted a call.
4. **A tool I had to guess at — field names.** `aa_providers fields=all` errored
   (`unknown field 'all'`; closest suggestions were metric names like `when2call`, `gdpval`
   — not a sentinel like `all`/`*`). There is no obvious "give me everything" field token;
   you must name fields exactly, and the right names are only discoverable via
   `aa_reference topic=fields` (which I did not spend tokens on).
5. **`aa_providers` hides the column you sorted by.** `sort=ttft` reorders rows but the table
   still shows only `Host | Model | In | Out | $/Task | tok/s` — **no TTFT column**, so the
   sort is unreadable without a follow-up `fields=ttft` call. Same class of problem: sorting
   by a metric that the default column set omits. This is why A3 cost 4 calls instead of 2.
6. **No answer I could not get.** All three A questions were answered. The only genuinely
   missing data points are per-cell gaps inside A2 (AA-3D Elo missing for DeepSeek, Harvey
   LAB-AA / ITBench-AA SRE / MMMU-Pro missing for MiMo) — these are honest `-` cells with a
   `missing:` footer, not tool failures.
7. **First-try routing: mostly yes, with one caveat.** The *tool* was right first try in all
   three questions (`aa_pareto` → A1, `aa_compare` → A2, `aa_providers` → A3), so the tool
   descriptions are good enough for tool-level routing. The *arguments* were the friction:
   two of the eight calls failed on guessed enum values (`sort=intel_per_cost`,
   `fields=all`). So: **tool descriptions ≈ sufficient; argument vocabularies are
   under-documented in-context** (you must call `aa_reference topic=fields` or `aa_benchmarks`
   to learn accepted names — the error messages are helpful but cost a round-trip).
8. **Latency spike:** the `aa_compare metrics=all` call took **15.3 s** (vs 100–1600 ms for
   everything else); worth noting if an agent has tight per-call timeouts.

### Recommended fixes (blunt)
- Fix native registration so subagents actually receive `aa_*` tools (the round-6 goal).
- Let `aa_providers` **always include the sorted-by column** (or accept `fields=*`/`all`).
- Add an efficiency sort (`intel_per_cost` / `value`) to `aa_leaderboard`, or advertise in
  the error text that value must be read from `aa_pareto`.
- Accept a wildcard field token in `aa_compare`/`aa_providers` so agents stop guessing enum
  members.
