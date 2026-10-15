# Round 7 — cold start: "super easy comparison, no API key?"

**Agent**: `R7_ColdStart` (new agent, no prior knowledge of the repo, no `src/`, no `docs/`, no web).
**Surface used**: only `.venv/bin/python eval/client.py {tools,schema,call,read}`.
**Date**: 2026-10-15.

## 0. Environment check (done first, as instructed)

```
$ env | grep -i aa_api      # → no output, exit 1
```
**`AA_API_KEY` is unset** — confirmed. Everything below was produced with no key.

**Total invocations: 44** = 41 MCP tool calls + `client.py tools` + `client.py schema` + one `client.py read` with no URI (argparse usage error, not an MCP call).
Harness-reported cost is `[harness] N chars ≈ T tok · Xms · error=B` (T = ceil(chars/4) of the *returned text*). `client.py tools` and `client.py schema` do **not** print a `[harness]` line, so they have no token cost reported.

---

## 1. Per-question answers

### Q1 — Claude Opus 5.5 vs GPT-6 Astra for a long-context agentic coding assistant

**Verdict: Claude Opus 5.5 (`claude-opus-5-5`) — pick it for quality; GPT-6 Astra (`gpt-6-astra`) only if $/task or wall-clock matter more than the score.**

Numbers (all from one `aa_compare`, `metrics=all`):

| | Claude Opus 5.5 (`claude-opus-5-5`) | GPT-6 Astra (`gpt-6-astra`) |
|---|---|---|
| Intelligence Index | **57.6** | 52.7 |
| AA-LCR (long-context reasoning) | **84.7%** | 80.7% |
| FrontierCode | **52.2%** | 47.0% |
| Terminal-Bench 4.0 (agentic) | 59.6% | 59.1% |
| Terminal-Bench Science | 59.0% | **63.3%** |
| Terminal-Bench Hard | *not published* | *not published* |
| LiveCodeBench | *not published* | *not published* |
| SciCode | **66.9%** | 56.5% |
| AutomationBench | **69.5%** | 68.5% |
| GDPval-AA | **68.3%** | 53.6% |
| HLE | **61.4%** | 54.7% |
| Context window | 1.0M | 1.0M |
| $/task | $5.98 | **$3.26** |
| In / Out $ per 1M | **$4.00 / $20.00** | $10.00 / $50.00 |
| Cache read / write $ per 1M | **$0.20 / $5.00** | $1.00 / $12.50 |
| Output tokens per index task | 119k | **27k** |
| tok/s | **95.2** | 44.2 |
| Time to first token | 661.2s | **288.2s** |
| End-to-end response time | 666.4s | **299.5s** |
| Cost to run the whole index suite | $8,708 | **$5,324** |

Read: Opus 5.5 leads on the two things the question actually names — long context (AA-LCR +4.0 pts) and agentic coding (FrontierCode +5.2 pts; Terminal-Bench 4.0 a dead heat). It also leads the aggregate index by 4.9 pts and is 2.2× faster per token, despite being the *cheaper* model per token. Astra's lower $/task ($3.26 vs $5.98) is purely a verbosity artefact: it emits 27k output tokens per index task vs Opus's 119k (4.4× fewer), so its higher per-token price still yields a lower per-task cost. For a long-context agent (multi-turn, tool-heavy, cache-reused) the cache-read price ($0.20 vs $1.00) and the 2.2× tok/s matter more than $/task.

**Calls (4 to answer, +4 to probe the edges):**
1. `call aa_search '{"query":"opus 5.5"}'` — 336 tok
2. `call aa_search '{"query":"gpt-6 astra"}'` — 147 tok
3. `call aa_compare '{"queries":["claude-opus-5-5","gpt-6-astra"]}'` — 194 tok
4. `call aa_compare '{"queries":["claude-opus-5-5","gpt-6-astra"],"metrics":"all"}'` — 821 tok
5. `call aa_compare ... "metrics":["livecodebench","frontierCode","terminalBench40","terminalBenchHard","lcr","swe-bench-verified"]` — 56 tok, **error** (one bad key aborted the whole call)
6. same call without `swe-bench-verified` — 228 tok
7. `call aa_compare '{"queries":["claude-opus-5.5","gpt-6-astra"]}'` — 194 tok (dot-slug guess, silently worked)
8. `call aa_model '{"query":"claude-opus-5-5","sections":"specs"}'` — 46 tok; `aa_model '{"query":"gpt-6-astra","sections":"specs"}'` — 38 tok

**Was it easy?** `needed 4 calls` — and it *was* easy: call 3 (bare `queries`, no metric names) already contained the deciding numbers. Two things were not easy:
- **Which variant?** `aa_search` returns *five* slugs for "Claude Opus 5.5" (`claude-opus-5-5`, `-xhigh`, `-high`, `-medium`, `-low`) and the bare slug is labelled "(Max, Default Fallback)". Nothing says which one a user means; `aa_compare` silently picks Max. Same for Astra (5 variants).
- **The Coding Index is invisible**: the metric a user would most want for "coding assistant" is API-key-only (see §3).

---

### Q2 — Is Muse Wonder Full actually better than Claude Sonnet 5.5, or just newer?

**Verdict: not clearly better — it's a wash on quality and Muse Wonder Full is *unpriceable*, so Sonnet 5.5 is the defensible pick.**

`muse-wonder-full` (Meta, released **2026-10-12**) vs `claude-sonnet-5-5` (Anthropic, released **2026-09-28** → Muse is 14 days newer).

| | Muse Wonder Full (`muse-wonder-full`) | Claude Sonnet 5.5 (`claude-sonnet-5-5`) |
|---|---|---|
| Intelligence Index | 55.8 | **56.0** |
| AA-Omniscience | 30.1 | **32.3** |
| AA-LCR | **83.7%** | 82.7% |
| Terminal-Bench 4.0 | 57.1% | **63.6%** |
| Terminal-Bench Science | *not published* | **53.3%** |
| FrontierCode | *not published* | **45.8%** |
| SciCode | **62.6%** | 61.0% |
| GDPval-AA | **67.9%** | 66.9% |
| AA-Briefcase Elo | 1729 | **1819** |
| HLE | 53.6% | **55.0%** |
| Omni Non-Halluc | **77.0%** | 53.0% |
| Omni Accuracy | 43.2% | **53.9%** |
| Harvey LAB-AA | **13.1%** | 2.8% |
| $/task | **not published** | $5.46 |
| In / Out $ per 1M | **not published** | $2.00 / $10.00 |
| tok/s, TTFT | **not published** | 128.8, 433.5s |

The two headline indexes are a tie (0.2 pt apart = noise). It splits by capability: Muse wins hallucination (77.0 vs 53.0 non-hallucination — a big, real gap), GDPval, SciCode, Harvey; Sonnet wins Terminal-Bench 4.0 (+6.5), Briefcase Elo (+90), HLE, Omni accuracy. So "newer" is doing most of the work in the question's premise: there is no evidence Muse Wonder Full is a better model, and there is *no price at all* for it, so you cannot even argue "same quality, cheaper".

**Calls (2):** `aa_search '{"query":"muse wonder"}'` (67 tok), `aa_compare '{"queries":["muse-wonder-full","claude-sonnet-5-5"],"metrics":"all"}'` (589 tok). Plus `aa_model '{"query":"claude-sonnet-5-5","sections":"specs,pricing"}'` (93 tok) for the release date.

**Was it easy?** `needed 2 calls`, then `could not answer` the value half: the pricing column is empty for `muse-wonder-full` and no tool in the surface can fill it (§2 "missing data").

---

### Q3 — The three cheapest models above Intelligence 40, on coding benchmarks

**Verdict: MiMo-V2.6-Pro is the only one of the three that is actually a coding model; GPT-6.1 Sol (Low) is the weakest evidence base.**

`aa_leaderboard '{"sort":"cost_per_task","min_intelligence":40,"top":15}'` → 42 models qualify. Cheapest:

| Rank | Model | Slug | Intel | $/task | tok/s | TTFT |
|---|---|---|---|---|---|---|
| 1 | Claude Haiku 5.5 (Xhigh) | `claude-haiku-5-5-xhigh` | 41.2 | **$0.12** | 181.1 | 75.7s |
| 2= | GPT-6.1 Sol (Low) | `gpt-6-1-sol-low` | 42.1 | **$0.13** | 44.3 | 3.4s |
| 2= | MiMo-V2.6-Pro | `mimo-v2-6-pro` | **46.3** | **$0.13** | 47.3 | 4.0s |
| (4) | Claude Haiku 5.5 (Max) | `claude-haiku-5-5` | 43.4 | $0.21 | 238.2 | 336.9s |

Ranks 2 and 3 are a genuine tie — AA reports `$/task` to 2 decimals and both are `$0.13` in `aa_leaderboard`, `aa_compare` *and* `aa_pareto`, so **the tie cannot be broken with this surface** (Intel/$ differs: 322 vs 348, which favours MiMo).

Coding benchmarks for the three (from `aa_compare` with `metrics=benchmarks`):

| Coding metric | `claude-haiku-5-5-xhigh` | `gpt-6-1-sol-low` | `mimo-v2-6-pro` |
|---|---|---|---|
| FrontierCode | 45.5% | *not published* | 45.4% |
| SciCode | 51.7% | 53.2% | **60.9%** |
| Terminal-Bench 4.0 | 29.3% | 30.8% | **34.8%** |
| Terminal-Bench Science | 18.1% | *not published* | 5.7% |
| LiveCodeBench | *not published* | *not published* | *not published* |
| Artificial Analysis Coding Index | *API key only* | *API key only* | *API key only* |

MiMo-V2.6-Pro wins every coding row it shares with the others, and it has the highest Intelligence of the three. Caveat: LiveCodeBench is published for only 82/700 variants (all older models — its top scorer is `gpt-oss-120b` at 87.8%), so none of these three have it, and the *Coding Index* that would settle this in one number is behind the key.

**Calls (3):** `aa_leaderboard '{"sort":"cost_per_task","min_intelligence":40,"top":15}'` (419 tok); `aa_compare '{"queries":["claude-haiku-5-5-xhigh","gpt-6-1-sol-low","mimo-v2-6-pro","claude-haiku-5-5"],"metrics":"benchmarks"}'` (731 tok); `aa_pareto '{"score":"intelligence","x":"cost_per_task","min_intelligence":40,"top":6}'` (227 tok, tie-break attempt).

**Was it easy?** `needed 3 calls, obvious` — this is the one question where the tool surface answered cleanly on the first try (`sort=cost_per_task` + `min_intelligence=40` are self-documenting and appear in the `tools` listing).

---

### Q4 — Best value for high-volume classification

**Verdict: `could not answer` as asked — there is no classification benchmark on AA.** `aa_benchmarks '{"query":"classif"}'` fails outright. The closest published proxies are **IFBench** (instruction following) and **AA-Omniscience non-hallucination**, and on those:

- **Best value: `command-a-plus`** (Cohere Command A+, open weights Apache 2.0, 218B/25B active) — IFBench **73.9%**, Omni Non-Halluc **85.8%**, **$0.00/task**, **183.0 tok/s**, TTFT 0.5s.
- **Runner-up: `gemma-4-31b`** (Gemma 4 31B Reasoning, Apache 2.0) — IFBench **75.6%** (higher), $0.00/task, but only **35.5 tok/s** → 5× less throughput for the same price, which is what "high-volume" punishes.
- **Best *paid* option** (if $0.00 is an artefact, see below): `qwen3-7-plus` — IFBench **78.0%** at **$0.22/task**, 56.0 tok/s, 1.0M ctx. Cheapest-at-scale alternative: `nvidia-nemotron-3-nano-30b-a3b-reasoning` — IFBench 71.1% at $0.02/task and 228.8 tok/s (highest throughput in the cheap band).

**Why "best value" is shaky here**: both top picks are open-weights models whose recorded price is literally `$0.00` in/out and `$/task` (confirmed via `aa_model` on both). AA is publishing a *number*, not a dash — so the surface cannot distinguish "free hosted endpoint", "self-host, you pay for GPUs", and "price not published". For a high-volume decision that distinction is the whole answer.

**Calls (5):** `aa_benchmarks '{"query":"classif"}'` (54 tok, **error**); `aa_benchmarks '{"query":"cyber"}'`… see Q5; `aa_leaderboard '{"sort":"ifbench","top":25}'` (619 tok); `aa_leaderboard '{"sort":"omniscienceNonHallucination","top":12}'` (315 tok); `aa_model '{"query":"command-a-plus","sections":"pricing,specs"}'` (90 tok) + `aa_model '{"query":"gemma-4-31b","sections":"pricing,specs"}'` (91 tok).

**Was it easy?** `could not answer` — no classification benchmark exists; `had to guess` that IFBench/Omniscience are the right stand-ins, and neither tool names a substitute.

---

### Q5 — Security team: top models on cyber benchmarks

**Verdict: `gpt-6-sol-daybreak-blue` is the strongest cyber model, but it has no Intelligence score; `mimo-v2-6-pro` is the value outlier (56.1 Cyber Index at $0.13/task).**

From `aa_leaderboard '{"sort":"cyberIndex","top":12}'` (only **19 of 700** variants are scored on the Cyber Index), then `aa_compare` on the eight cyber keys:

| Model | Slug | AA Cyber Index | CWE-Bench-AA | CyberGym-E2E-AA | DeepSecBench-AA | Refusals (CWE/Cyber/CyberGym) | $/task |
|---|---|---|---|---|---|---|---|
| GPT-6 Sol (Daybreak Blue, max) | `gpt-6-sol-daybreak-blue` | **68.7** | 64.7% | **93.1%** | **48.1%** | 0.0 / 0.0 / 0.0% | – |
| Grok 4.7 (Xhigh) | `grok-4-7` | 56.4 | **68.3%** | 74.0% | 26.9% | 0.0 / 0.0 / 0.0% | $3.74 |
| MiMo-V2.6-Pro | `mimo-v2-6-pro` | 56.1 | 63.3% | 78.6% | 26.2% | 0.0 / 0.0 / 0.0% | **$0.13** |
| GPT-6 Luna (Max) | `gpt-6-luna` | 52.7 | 56.7% | 77.9% | 23.5% | 0.0 / 0.0 / 0.0% | $0.07 |
| GLM-5.3-Flash | `glm-5-3-flash` | 49.9 | 55.8% | 74.0% | 19.9% | 0.0 / 0.0 / 0.0% | $0.28 |
| DeepSeek V4.1 Flash (Max) | `deepseek-v4-1-flash` | 40.8 | 68.3% | 22.9% | 31.2% | 0.0 / 0.0 / 0.0% | $0.27 |
| Claude Opus 5.5 (Max) | `claude-opus-5-5` | **28.7** | 58.3% | **0.8%** | 26.9% | 9.2 / 35.9 / **98.5%** | $5.98 |

Two things a security team must know, both visible in the data: (a) **Anthropic's frontier model is last on the Cyber Index and refuses almost every CyberGym task (98.5% refusal, 0.8% E2E)** — its raw capability isn't 28.7, it's refusing; the tool surfaces refusal rates as first-class metrics, which is exactly right. (b) `gpt-6-sol-daybreak-blue` has `Intel = -` in the leaderboard while topping the cyber panel — you cannot cross-check it against the general index.

**Calls (2):** `aa_leaderboard '{"sort":"cyberIndex","top":12}'` (363 tok); `aa_compare '{"queries":["gpt-6-sol-daybreak-blue","grok-4-7","mimo-v2-6-pro","gpt-6-luna","glm-5-3-flash","claude-opus-5-5"],"metrics":[...8 cyber keys...]}'` (395 tok). Discovery: `aa_benchmarks '{"query":"cyber"}'` (416 tok).

**Was it easy?** `needed 3 calls, obvious` — `aa_benchmarks '{"query":"cyber"}'` handed over every cyber key *and* the exact `sort=` alias for each, so no guessing was required.

---

### Q6 — One table for `mimo-v2-6-pro`, `deepseek-v4-1-flash`, `gpt-6-luna-xhigh`, `muse-wonder-full`

| | `mimo-v2-6-pro` | `deepseek-v4-1-flash` | `gpt-6-luna-xhigh` | `muse-wonder-full` |
|---|---|---|---|---|
| Creator | Xiaomi | DeepSeek | OpenAI | Meta |
| Intelligence | 46.3 | 39.5 | 34.6 | **55.8** |
| $/task | $0.13 | $0.27 | **$0.04** | **not published** |
| Intel/$ | 347.7 | 148.8 | **819.2** | **not published** |
| In / Out $ per 1M | $0.43 / $0.87 | $0.30 / $1.20 | **$0.10 / $0.50** | **not published** |
| Cache read $ per 1M | **$0.0036** | $0.0060 | $0.01 | – |
| tok/s | 45.8 | **173.9** | 111.3 | – |
| TTFT (long prompt) | 4.0s | **1.1s** | 32.7s | – |
| Context | 1.0M | 1.0M | 1.0M | 1.0M |
| FrontierCode | 45.4% | 44.0% | *n/p* | *n/p* |
| SciCode | **60.9%** | 51.9% | 51.7% | 62.6% |
| Terminal-Bench 4.0 | 34.8% | 26.8% | 8.1% | **57.1%** |
| AA-LCR | **86.3%** | 84.0% | 80.0% | 83.7% |
| GDPval-AA | 59.2% | 55.0% | 43.2% | **67.9%** |
| Omni Non-Halluc | 59.4% | 3.5% | 17.6% | **77.0%** |
| AA Cyber Index | **56.1** | 40.8 | – | – |
| AA-Omniscience | 8.4 | **-5.3** | -1.8 | **30.1** |
| Cap Engineering | 46.9 | 39.3 | 33.7 | **57.0** |
| Openness Index | 52.8 | 44.4 | – | – |

**Best price/performance: `gpt-6-luna-xhigh` — 819.2 Intelligence-per-$/task, 6× `deepseek-v4-1-flash` and 2.4× `mimo-v2-6-pro`.** With the caveat that it buys that on the *aggregate* index only: it is the worst of the four on every agentic/coding row (Terminal-Bench 4.0 8.1%, Omni Non-Halluc 17.6%, Omni Halluc 82.4%). If "performance" means coding/agentic rather than the blended index, `mimo-v2-6-pro` is the value pick ($0.13/task, FrontierCode 45.4%, TB4.0 34.8%, Cyber Index 56.1). `muse-wonder-full` **cannot be ranked on price/performance at all** — no $/task, no per-token price, no speed.

**Calls (2):** `aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"],"metrics":"all"}'` (981 tok) and the same call with no `metrics` (307 tok) because **`Intel/$` appears in the default 8-row view but *not* in `metrics=all`** — a trap: asking for *more* metrics silently loses the value metric.

**Was it easy?** `needed 2 calls, obvious` — with the caveat that the second call was needed only because `metrics=all` hides `Intel/$`.

---

## 2. Every place I had to guess (with the quoted error text)

| What I guessed | Result | Error text / message |
|---|---|---|
| Metric key `swe-bench-verified` (SWE-bench Verified — the obvious coding benchmark) | **fails the whole call** | `Error executing tool aa_compare: unknown metric 'swe-bench-verified' — closest: cwe-bench-aa, terminalbench-hard, terminal-bench-science, itbenchSre, cweBenchRefusalRate\n— aa_reference topic=fields lists every accepted name` |
| Board name `cyber` for `aa_media` | fails, but lists all valid boards | `Error executing tool aa_media: unknown media board 'cyber' — valid: image_editing, image_to_video, music_instrumental, music_with_vocals, text_to_image, text_to_speech, text_to_speech_controlled, text_to_video, video_editing, speech_to_speech, speech_to_text, speech_to_text_streaming (hyphens/spaces/case are ignored, e.g. text-to-image == text_to_image; realtime-voice == speech_to_speech)` |
| Topic `routing` for `aa_reference` | fails, but lists topics | `Error executing tool aa_reference: unknown topic 'routing' — topics: overview, indexes, benchmarks, pricing, speed, providers, media, fields, sources, all` |
| Benchmark name `classif` / `classification` | no such thing | `Error executing tool aa_benchmarks: no rankable matches query=classif — closest: gdpPdfAllPass, Analyst Pass@k, Analyst Pass@1\n— aa_benchmarks with no arguments lists every rankable thing (101), or try domain=<name>` |
| Slug `claude-opus-5.5` (dot instead of dash) | **no error — silently fuzzy-matched** to `claude-opus-5-5` | (returned the normal table; the tool never says it corrected the slug) |
| Metric key for the coding index: `benchmark=coding` on `aa_benchmark_leaderboard` | fails, explains why | `Error executing tool aa_benchmark_leaderboard: 'Coding': AA exposes this index per model only on the scrape source (model pages) and through the JSON API (AA_API_KEY) — there is no cross-model ranking to sort by.\n— read one model with aa_model <slug>, or set AA_API_KEY; aa_benchmark_leaderboard has no slug for these.` |
| `aa_providers '{"model":"muse-wonder-full"}'` (assumed providers would carry the price) | fails; **`refresh=true` does not help** | `Error executing tool aa_providers: no JSON array of dicts containing keys ['host', 'jsonMode', 'model', 'pricing'] in payload\nthe payload cached at /home/wavy/.cache/aa-mcp/providers_muse-wonder-full.rsc is unusable — retry with refresh=true to refetch https://artificialanalysis.ai/models/muse-wonder-full/providers` (retried with `refresh:true` → identical error) |

**Not guessed (found by discovery, no error):** every `sort=` alias, metric key and board key I used for Q3/Q5/Q6 came from `aa_benchmarks` output, which prints the exact `how to query` string next to each metric. That is the single best-designed part of the surface: `aa_benchmarks '{"query":"cyber"}'` → 9 metrics each with its `aa_leaderboard sort=…` alias. Same for `aa_search` giving slugs directly.

**Notable error-handling behaviours, good and bad:**
- ✅ Unknown *board* / *topic* / *benchmark* errors enumerate every valid value.
- ✅ Unknown *metric* suggests the 5 closest keys.
- ❌ **One unknown metric key aborts the entire `aa_compare` call** — there is no "warn and drop". I lost a call to a single bad key out of six.
- ❌ The fuzzy slug match is silent — a typo'd slug returns another model's numbers with no warning.
- ❌ The tool description for `aa_reference` says it is for "tool routing" but `routing` is not an accepted topic.

---

## 3. Missing / contradictory / ambiguous data

1. **`muse-wonder-full` has no price and no speed anywhere.** `aa_compare` (both default and `metrics=all`): `$/task`, `In $/1M`, `Out $/1M`, `tok/s`, `TTFT` all `-`, and the footnote says `missing: Intel/$ (Muse Wonder Full (max)), $/task …, tok/s …, TTFT …`. `aa_model` prints literally `## Pricing — no pricing recorded`. `aa_providers` errors on an unusable payload. **This is "not published", and the surface is honest about it — but it silently removes the model from every value ranking.**
2. **`$0.00` for `command-a-plus` and `gemma-4-31b`** is ambiguous: a real number, not a dash. Both are open-weights (Apache 2.0), so it plausibly means "self-host / free endpoint" rather than "free inference". Cannot tell which from the surface — and it makes any "cheapest model" query return self-host models.
3. **`Intel/$` is missing from `metrics=all`** but present in the default 8-row subset. Asking for more data gives you less.
4. **TTFT disagreement between two views of the same tool**: default `aa_compare` reports TTFT **679.2s** for `claude-opus-5-5`, `metrics=all` reports "Time to First Token **661.2s**" and "Time to First Answer Token 661.2s". Same tool, same call pair, different numbers, no explanation beyond "TTFT is AA's long-prompt median".
5. **`$/task` tie at `$0.13`** (`gpt-6-1-sol-low` vs `mimo-v2-6-pro`) is unresolvable at the published precision in `aa_leaderboard`, `aa_compare` and `aa_pareto` alike.
6. **`gpt-6-sol-daybreak-blue` tops the Cyber Index (68.7) with `Intel = -`** — no Intelligence Index, so it can't be sanity-checked or value-ranked.
7. **Coverage cliffs that look like model gaps**: LiveCodeBench is scored for 82/700 variants (its leader is `gpt-oss-120b`, Intelligence 11.6 — i.e. it only covers old/small models); Terminal-Bench Hard and Terminal-Bench 2.1 are missing for both frontier models; the Cyber Index covers 19/700; `MLCR-*` covers 27. `aa_compare` does footnote `missing: …`, which is the difference between "not published" and "you asked wrongly" — that footnote is what makes these trustworthy.
8. **`$`/task vs per-token price point in opposite directions** for Q1 (Astra: 2.5× pricier per token, 45% cheaper per task, because it is 4.4× less verbose). Nothing in the output warns that `$/task` is a verbosity proxy.
9. **Harness-level**: `client.py read <uri>` requires a URI and there is no way to *list* resource URIs (no `resources` subcommand; `tools` lists tools only). So the "resources, if you need them" escape hatch is unusable for a cold-start agent — you can't discover a URI to read.

---

## 4. What I could not do because there is no API key

Everything the questions needed was reachable **except two headline indexes**, and the tools said so **clearly and consistently** — this is handled well:

- **Artificial Analysis Coding Index** — `aa_benchmarks` marks it `index | api only (AA_API_KEY)`; `aa_benchmark_leaderboard benchmark=coding` refuses with: *"AA exposes this index per model only on the scrape source (model pages) and through the JSON API (AA_API_KEY) — there is no cross-model ranking to sort by."*; `aa_model` prints: *"Coding Index, Agentic Index need AA_API_KEY (JSON API); unavailable on the scrape source"*.
- **Artificial Analysis Agentic Index** — same, `aa_benchmarks` row says `api only (AA_API_KEY)`, `aa_benchmark_leaderboard benchmark=agentic`.
- Consequence: **Q1 and Q3 — the two coding questions — cannot be answered with the single number a user would most want.** I substituted FrontierCode / SciCode / Terminal-Bench / AA-LCR, which is a defensible workaround, but it is a workaround.
- I did **not** attempt any authenticated call and made **no** curl/web request to artificialanalysis.ai, per the rules.

Nothing else required a key: leaderboards, comparisons, model digests, providers, pareto, media, agents, reference and benchmarks were all fully available keyless.

---

## 5. Top 3 things that would make comparison easier or better

1. **Close the price hole (and stop letting a model silently fall out of rankings).** `muse-wonder-full` is unpriced in `aa_compare`, `aa_model` and `aa_providers` (the last even fails with a payload-shape error that `refresh=true` does not fix). A comparison tool that quietly drops the value columns for one of four requested models invites a wrong decision. Fixes: (a) render `not published` in-cell rather than `-`, (b) when any requested model is missing the value axis, say so in the header line (`best price/performance: n/a — 1 of 4 models unpriced`) instead of leaving the reader to compute it, (c) treat "pricing" as its own coverage column in `aa_benchmarks`, (d) distinguish `$0.00` (real) from self-host/unknown, e.g. `$0.00 (open weights; no hosted price)`.
2. **Make the coding answer a first-class keyless path.** The Coding Index and Agentic Index are `api only`, and `LiveCodeBench` covers only 82/700 (old models), so "which is best for coding?" has no single published number keyless. Either publish a scrapeable cross-model coding/agentic composite, or have `aa_benchmarks`/`aa_reference` name the official proxy recipe (`FrontierCode + SciCode + Terminal-Bench 4.0 + AA-LCR`) with weights, so two agents comparing models produce the *same* answer instead of each inventing their own. Also: **there is no classification benchmark at all** — a very common user ask ("high-volume classification") currently has no metric and no named proxy; IFBench + Omniscience non-hallucination were my guess.
3. **Harden the parameter surface for cold starts.** Concretely: (a) an unknown metric key should **warn and drop**, not abort the whole call (one bad key of six killed a full comparison); (b) accept a *list* of candidate names or add `metrics=?` to print the accepted key list inline, instead of pointing at `aa_reference topic=fields`; (c) **say when a slug was fuzzy-corrected** (`claude-opus-5.5` → `claude-opus-5-5` silently) — a silent correction on a model name is a correctness hazard; (d) disambiguate reasoning-effort variants: "Claude Opus 5.5" resolves to 5 slugs with no "which is canonical" signal, and `aa_compare` silently picks Max; add an explicit default marker / `variant=` param; (e) include `Intel/$` in `metrics=all` (it is currently only in the default subset, so asking for everything hides the value metric); (f) give `client.py` a way to list resource URIs.

---

## 6. Full call log (44 invocations, in order)

Costs are the harness's own `[harness] N chars ≈ T tok` figures. `tools`/`schema` print no cost line.

| # | Call | Harness cost | Error |
|---|---|---|---|
| 1 | `client.py tools` | *(none reported)* | no |
| 2 | `aa_search '{"query":"opus 5.5"}'` | 336 tok · 5610ms | no |
| 3 | `aa_search '{"query":"gpt-6 astra"}'` | 147 tok · 2441ms | no |
| 4 | `aa_compare '{"queries":["claude-opus-5-5","gpt-6-astra"]}'` | 194 tok · 183ms | no |
| 5 | `aa_compare '{"queries":["claude-opus-5-5","gpt-6-astra"],"metrics":"all"}'` | 821 tok · 6823ms | no |
| 6 | `aa_benchmarks '{"query":"coding"}'` | 307 tok · 377ms | no |
| 7 | `aa_benchmark_leaderboard '{"benchmark":"coding","top":5}'` | 80 tok · 507ms | **yes** |
| 8 | `aa_benchmarks '{"query":"long"}'` | 298 tok · 447ms | no |
| 9 | `aa_search '{"query":"muse wonder"}'` | 67 tok · 3038ms | no |
| 10 | `aa_search '{"query":"sonnet 5.5"}'` | 390 tok · 3533ms | no |
| 11 | `aa_search '{"query":"mimo-v2-6-pro"}'` | 80 tok · 2893ms | no |
| 12 | `aa_search '{"query":"deepseek-v4-1-flash"}'` | 131 tok · 2843ms | no |
| 13 | `aa_search '{"query":"gpt-6-luna"}'` | 244 tok · 3203ms | no |
| 14 | `client.py schema aa_leaderboard` | *(none reported)* | no |
| 15 | `aa_benchmarks '{"query":"cyber"}'` | 416 tok · 466ms | no |
| 16 | `aa_benchmarks '{"query":"classif"}'` | 54 tok · 29ms | **yes** |
| 17 | `aa_benchmarks '{}'` (all 101 rankables) | 2702 tok · 3719ms | no |
| 18 | `aa_leaderboard '{"sort":"cost_per_task","min_intelligence":40,"top":15}'` | 419 tok · 265ms | no |
| 19 | `aa_compare '{"queries":["claude-haiku-5-5-xhigh","gpt-6-1-sol-low","mimo-v2-6-pro","claude-haiku-5-5"],"metrics":"benchmarks"}'` | 731 tok · 1787ms | no |
| 20 | `aa_compare '{"queries":["muse-wonder-full","claude-sonnet-5-5"],"metrics":"all"}'` | 589 tok · 986ms | no |
| 21 | `aa_compare '{"queries":["mimo-v2-6-pro","deepseek-v4-1-flash","gpt-6-luna-xhigh","muse-wonder-full"],"metrics":"all"}'` | 981 tok · 585ms | no |
| 22 | `aa_model '{"query":"muse-wonder-full"}'` | 353 tok · 870ms | no |
| 23 | `aa_providers '{"model":"muse-wonder-full"}'` | 79 tok · 466ms | **yes** |
| 24 | `aa_providers '{"model":"muse-wonder-full","refresh":true}'` | 79 tok · 777ms | **yes** |
| 25 | `aa_providers '{"model":"muse-wonder"}'` | 68 tok · 570ms | no |
| 26 | `aa_leaderboard '{"sort":"cyberIndex","top":12}'` | 363 tok · 398ms | no |
| 27 | `aa_leaderboard '{"sort":"ifbench","top":10}'` | 310 tok · 188ms | no |
| 28 | `aa_leaderboard '{"sort":"livecodebench","top":8}'` | 243 tok · 332ms | no |
| 29 | `aa_leaderboard '{"sort":"ifbench","top":25}'` | 619 tok · 158ms | no |
| 30 | `aa_leaderboard '{"sort":"omniscienceNonHallucination","top":12}'` | 315 tok · 133ms | no |
| 31 | `aa_compare '{"queries":[Q6 4 slugs]}'` (default view, for `Intel/$`) | 307 tok · 128ms | no |
| 32 | `aa_model '{"query":"command-a-plus","sections":"pricing,specs"}'` | 90 tok · 769ms | no |
| 33 | `aa_model '{"query":"gemma-4-31b","sections":"pricing,specs"}'` | 91 tok · 454ms | no |
| 34 | `aa_compare '{"queries":["claude-opus-5-5","gpt-6-astra"],"metrics":["livecodebench","frontierCode","terminalBench40","terminalBenchHard","lcr","swe-bench-verified"]}'` | 56 tok · 297ms | **yes** |
| 35 | same, `"metrics":["livecodebench","frontierCode","terminalBench40","terminalBenchHard","lcr"]` | 228 tok · 572ms | no |
| 36 | `aa_compare '{"queries":["claude-opus-5.5","gpt-6-astra"]}'` | 194 tok · 216ms | no (silent slug fix) |
| 37 | `aa_compare '{"queries":[6 cyber slugs],"metrics":[8 cyber keys]}'` | 395 tok · 706ms | no |
| 38 | `aa_media '{"board":"cyber"}'` | 98 tok · 20ms | **yes** |
| 39 | `aa_pareto '{"score":"intelligence","x":"cost_per_task","min_intelligence":40,"top":6}'` | 227 tok · 255ms | no |
| 40 | `aa_reference '{"topic":"routing"}'` | 39 tok · 14ms | **yes** |
| 41 | `aa_model '{"query":"claude-sonnet-5-5","sections":"specs,pricing"}'` | 93 tok · 561ms | no |
| 42 | `aa_model '{"query":"claude-opus-5-5","sections":"specs"}'` | 46 tok · 349ms | no |
| 43 | `aa_model '{"query":"gpt-6-astra","sections":"specs"}'` | 38 tok · 520ms | no |
| 44 | `client.py read` (no URI — argparse usage error, not an MCP call) | n/a | n/a |

**Totals:** 44 invocations, 8 of which returned errors (7 real tool errors + 1 argparse). Sum of harness-reported returned-text cost over the 41 calls that report one = **13,318 tok** (excluding `tools`/`schema`, which report none). Wall-clock: dominated by ~3–5s stdio server startup per invocation, not by tool work (tool work was 14ms–6.8s).

**First-tool-chosen scorecard** (was the tool I reached for first the right one?):

| Q | First tool | Right? |
|---|---|---|
| 1 | `aa_search` → `aa_compare` | ✅ exactly right |
| 2 | `aa_search` → `aa_compare` | ✅ right for quality; ❌ nothing can price the model |
| 3 | `aa_leaderboard sort=cost_per_task min_intelligence=40` | ✅ right first try |
| 4 | `aa_benchmarks query=classif` | ❌ no classification benchmark exists; `aa_benchmarks` *was* the right first tool (it proved the gap) |
| 5 | `aa_benchmarks query=cyber` → `aa_leaderboard sort=cyberIndex` | ✅ right first try |
| 6 | `aa_compare metrics=all` | ⚠️ mostly right, but `metrics=all` hides `Intel/$`, costing a second call |
