# Round 7 — independent correctness cross-check (no API key)

Verifier report. Everything below was measured on 2026-10-15 between 12:13 and 12:40
local. Nothing in `src/`, `tests/` or `docs/` was touched; the only file written is
this report. Raw payloads and helper scripts live in `/tmp/r7/`.

---

## 1. Method

### 1.1 No key

```
$ env | grep -i '^AA_'
(no output)
$ echo "[${AA_API_KEY:-UNSET}]"
[UNSET]
```

`AA_API_KEY` was **unset for every MCP call** in this report. Every reply header
carried `aa:rsc` (never `aa:api`), confirming the scrape path was used. No
`--env AA_API_KEY=…` override was passed to `eval/client.py`.

### 1.2 Raw payloads fetched by hand (independent of the MCP)

```
U=https://artificialanalysis.ai
curl -sfL -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" "$U/<path>" -o /tmp/r7/<name>
```

| path | file | bytes |
|---|---|---|
| `/leaderboards/models` | `lb.raw` | 1 189 439 |
| `/models/claude-opus-5-5` | `m_opus.raw` | 753 190 |
| `/models/mimo-v2-6-pro` | `m_mimo.raw` | 3 288 584 |
| `/models/gpt-5-2` | `m_gpt52.raw` | 3 227 155 |
| `/models/claude-opus-5-5/providers` | `p_opus.raw` | 421 393 |
| `/models/mimo-v2-6-pro/providers` | `p_mimo.raw` | 424 432 |
| `/leaderboards/providers` | `providers_board.raw` | 337 593 |
| `/image/leaderboard/text-to-image` | `media.raw` | 1 493 319 |
| `/evaluations/gpqa-diamond` | `eval_gpqa.raw` | 571 907 |
| `/evaluations/aa-3d` | `eval_aa3d.raw` | 893 929 |
| `/evaluations/aa-briefcase` | `eval_briefcase.raw` | 852 477 |
| `/evaluations/mlcr-aa` | `eval_mlcr.raw` | — |
| `/evaluations/cwe-bench-aa` | `eval_cwe.raw` | — |
| `/` (homepage panels) | `home.raw` | 1 117 874 |
| `/sitemap.xml` (eval slugs) | `sitemap.xml` | — |

`/evaluations` (the catalog page) was also fetched but is JS-chunk driven under
`RSC: 1`; the 42 published eval slugs came from `sitemap.xml` instead.

### 1.3 Independent parsing (no `aa_mcp` import)

The payloads are Next.js **RSC flight** streams, not plain JSON: `NN:<json>` lines
where nested arrays can mix strings/`null`/dicts. Five throwaway scripts in `/tmp/r7/`
do the extraction; none imports `aa_mcp`:

* `extract.py` — string-aware bracket matcher + `"key":` value extractor.
* `scan.py` — finds every JSON array-of-dicts in a payload (structure discovery).
* `fl.py` — parses each `id:<json>` flight line and walks it for a key
  (needed where the value sits inside `["$","$L3b",null,{…}]` wrappers).
* `recs.py` — pulls every rich model record (`{"id":"<uuid>","slug":…}`) out of a
  payload, keyed by slug; the model pages embed the full **702-record** rich dataset.
* `mktables.py` — builds the §2 verdict tables straight from the raw JSON + the MCP
  reply text (no hand transcription).

Raw values below come from `lb.raw` (the 700-row leaderboard array, key
`models`) unless a different file is named.

### 1.4 MCP calls

```
.venv/bin/python eval/client.py call aa_compare  '{"queries":[…6 models…],"metrics":"all","compact":false}'
.venv/bin/python eval/client.py call aa_model    '{"query":"<slug>"}'            # ×6
.venv/bin/python eval/client.py call aa_leaderboard '{"name":"…","fields":"…"}' # ×5
.venv/bin/python eval/client.py call aa_leaderboard '{"sort":"tps","top":5,"fields":"…"}'
.venv/bin/python eval/client.py call aa_benchmark_leaderboard '{"benchmark":"GPQA Diamond","top":12}'
.venv/bin/python eval/client.py call aa_providers '{"model":"…","top":20}'      # ×2 (+ fields= variants)
.venv/bin/python eval/client.py call aa_media     '{"board":"text_to_image","top":5}'
.venv/bin/python eval/client.py call aa_media     '{"board":"text_to_image","top":5,"fields":"elo,ci_lower,ci_upper,appearances,release,open_weights"}'
.venv/bin/python eval/client.py call aa_media     '{"board":"text_to_image","top":5,"open_weights":true,"fields":"elo,release,open_weights"}'
.venv/bin/python eval/client.py call aa_pareto    '{"x":"time_per_task","top":5}'
.venv/bin/python eval/client.py call aa_reference '{"topic":"overview"}' / '{"topic":"sources"}'
```

### 1.5 The six models

Chosen to span classes, and to include the awkward cases:

| role | slug | why |
|---|---|---|
| frontier | `claude-opus-5-5` | top of the active Intelligence Index (57.6) |
| effort variant | `claude-opus-5-5-high` | same family, different reasoning effort |
| open-weights | `mimo-v2-6-pro` | `isOpenWeights=true`, multi-host |
| cheap | `gemini-3-5-flash-lite` | $0.30/$2.50 per 1M, 437 tok/s |
| deprecated | `gpt-5-2` | `deprecated=true`, `intelligenceIndexIsEstimated=true` |
| sparse data | `jt-35b-flash` | 12 of the 22 requested fields are `null` in the raw row |

---

## 2. Field-by-field verdicts

Columns: the raw value, the value from `aa_leaderboard` (the leaderboard snapshot
surface), and the value from `aa_compare metrics=all` (the rich/compare surface).
Where a surface does not carry a field it shows `-`.

#### claude-opus-5-5 — Claude Opus 5.5 (Max, Default Fallback)

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` — Artificial Analysis Intelligence Index | 57.6223698102963 | 57.6 | 57.6 | OK |
| `intelligenceIndexIsEstimated` — Est. (leaderboard flag) | no | no | - | OK |
| `price1mInputTokens` — Input Price (USD per 1M tokens) | 4 | $4.00 | $4.00 | OK |
| `price1mOutputTokens` — Output Price (USD per 1M tokens) | 20 | $20.00 | $20.00 | OK |
| `cacheHitPrice` — Cache Read Price (USD per 1M tokens) | 0.2 | $0.20 | $0.20 | OK |
| `contextWindowTokens` — Context Window | 1000000 | 1.0M | 1.0M | OK |
| `medianOutputTokensPerSecond` — Speed (output tokens/s) | 95.7262977194631 | 95.7 | 95.2 | source note — see §4.3 |
| `medianTimeToFirstTokenSeconds` — Time to First Token | 679.2383941665 | 679.2s | 661.2s | source note — see §4.3 |
| `intelligenceIndexCostPerTask` — Cost per Task | 5.982012019521066 | $5.98 | $5.98 | OK |
| `isOpenWeights` — Open (leaderboard flag) | no | no | - | OK |
| `deprecated` — Depr. (leaderboard flag) | no | no | - | OK |
| `gpqa` — GPQA Diamond | null | - | - | OK — both blank |
| `hle` — HLE | 0.613531047265987 | - | 61.4% | OK |
| `scicode` — SciCode | 0.668981481481482 | - | 66.9% | OK |
| `terminalBench21` — Terminal-Bench 2.1 | null | - | - | OK — both blank |
| `terminalBench40` — Terminal-Bench 4.0 | 0.595959595959596 | - | 59.6% | OK |
| `tauBanking` — τ³-Banking | null | - | - | OK — both blank |
| `lcr` — AA-LCR | 0.846666666666667 | - | 84.7% | OK |
| `ifbench` — IFBench | null | - | - | OK — both blank |
| `critpt` — CritPt | 0.317142857142857 | - | 31.7% | OK |
| `mmmuPro` — MMMU-Pro | 0.876878612716763 | - | 87.7% | OK |
| `gdpvalNormalized` — GDPval-AA | 0.6831349999999999 | - | 68.3% | OK |

#### claude-opus-5-5-high — Claude Opus 5.5 (High, Default Fallback)

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` | 53.5831959822067 | 53.6 | 53.6 | OK |
| `intelligenceIndexIsEstimated` | no | no | - | OK |
| `price1mInputTokens` | 4 | $4.00 | $4.00 | OK |
| `price1mOutputTokens` | 20 | $20.00 | $20.00 | OK |
| `cacheHitPrice` | 0.2 | $0.20 | $0.20 | OK |
| `contextWindowTokens` | 1000000 | 1.0M | 1.0M | OK |
| `medianOutputTokensPerSecond` | 77.0708909487442 | 77.1 | 77.1 | source note — see §4.3 |
| `medianTimeToFirstTokenSeconds` | 51.914182409 | 51.9s | 47.2s | source note — see §4.3 |
| `intelligenceIndexCostPerTask` | 1.822504718771704 | $1.82 | $1.82 | OK |
| `isOpenWeights` | no | no | - | OK |
| `deprecated` | no | no | - | OK |
| `gpqa` | null | - | - | OK — both blank |
| `hle` | 0.555607043558851 | - | 55.6% | OK |
| `scicode` | 0.604166666666667 | - | 60.4% | OK |
| `terminalBench21` | null | - | - | OK — both blank |
| `terminalBench40` | 0.565656565656566 | - | 56.6% | OK |
| `tauBanking` | null | - | - | OK — both blank |
| `lcr` | 0.826666666666667 | - | 82.7% | OK |
| `ifbench` | null | - | - | OK — both blank |
| `critpt` | 0.308571428571429 | - | 30.9% | OK |
| `mmmuPro` | 0.858381502890173 | - | 85.8% | OK |
| `gdpvalNormalized` | 0.602185 | - | 60.2% | OK |

#### mimo-v2-6-pro — MiMo-V2.6-Pro

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` | 46.3242065310383 | 46.3 | 46.3 | OK |
| `intelligenceIndexIsEstimated` | no | no | - | OK |
| `price1mInputTokens` | 0.435 | $0.43 | $0.43 | OK |
| `price1mOutputTokens` | 0.87 | $0.87 | $0.87 | OK |
| `cacheHitPrice` | 0.0036 | $0.0036 | $0.0036 | OK |
| `contextWindowTokens` | 1000000 | 1.0M | 1.0M | OK |
| `medianOutputTokensPerSecond` | 47.3172710259822 | 47.3 | 47.3 | source note — see §4.3 |
| `medianTimeToFirstTokenSeconds` | 3.9633936985 | 4.0s | 4.1s | source note — see §4.3 |
| `intelligenceIndexCostPerTask` | 0.13322318937213493 | $0.13 | $0.13 | OK |
| `isOpenWeights` | yes | yes | - | OK |
| `deprecated` | no | no | - | OK |
| `gpqa` | null | - | - | OK — both blank |
| `hle` | 0.493512511584801 | - | 49.4% | OK |
| `scicode` | 0.608796296296296 | - | 60.9% | OK |
| `terminalBench21` | null | - | - | OK — both blank |
| `terminalBench40` | 0.348484848484849 | - | 34.8% | OK |
| `tauBanking` | null | - | - | OK — both blank |
| `lcr` | 0.863333333333333 | - | 86.3% | OK |
| `ifbench` | null | - | - | OK — both blank |
| `critpt` | 0.265714285714286 | - | 26.6% | OK |
| `mmmuPro` | null | - | - | OK — both blank |
| `gdpvalNormalized` | 0.59217 | - | 59.2% | OK |

#### gemini-3-5-flash-lite — Gemini 3.5 Flash-Lite

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` | 22.1685424839812 | 22.2 | 22.2 | OK |
| `intelligenceIndexIsEstimated` | no | no | - | OK |
| `price1mInputTokens` | 0.3 | $0.30 | $0.30 | OK |
| `price1mOutputTokens` | 2.5 | $2.50 | $2.50 | OK |
| `cacheHitPrice` | 0.03 | $0.03 | $0.03 | OK |
| `contextWindowTokens` | 1000000 | 1.0M | 1.0M | OK |
| `medianOutputTokensPerSecond` | 437.771635033392 | 437.8 | 437.8 | source note — see §4.3 |
| `medianTimeToFirstTokenSeconds` | 7.05799588200011 | 7.1s | 7.1s | source note — see §4.3 |
| `intelligenceIndexCostPerTask` | 0.1927430131409478 | $0.19 | $0.19 | OK |
| `isOpenWeights` | no | no | - | OK |
| `deprecated` | no | no | - | OK |
| `gpqa` | 0.838383838383838 | - | 83.8% | OK |
| `hle` | 0.188137164040778 | - | 18.8% | OK |
| `scicode` | 0.413194444444444 | - | 41.3% | OK |
| `terminalBench21` | 0.535580524344569 | - | 53.6% | OK |
| `terminalBench40` | 0.0101010101010101 | - | 1.0% | OK |
| `tauBanking` | 0.175257731958763 | - | 17.5% | OK |
| `lcr` | 0.76 | - | 76.0% | OK |
| `ifbench` | null | - | - | OK — both blank |
| `critpt` | 0 | - | 0.0% | OK |
| `mmmuPro` | 0.790173410404624 | - | 79.0% | OK |
| `gdpvalNormalized` | 0.24164 | - | 24.2% | OK |

#### gpt-5-2 — GPT-5.2 (Xhigh) — deprecated

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` | 30.448181916806 | 30.4 | 30.4 | OK |
| `intelligenceIndexIsEstimated` | yes | yes | - | OK |
| `price1mInputTokens` | 1.75 | $1.75 | $1.75 | OK |
| `price1mOutputTokens` | 14 | $14.00 | $14.00 | OK |
| `cacheHitPrice` | 0.175 | $0.17 | $0.17 | OK |
| `contextWindowTokens` | 400000 | 400k | 400k | OK |
| `medianOutputTokensPerSecond` | 73.8399801276855 | 73.8 | 75.6 | source note — see §4.3 |
| `medianTimeToFirstTokenSeconds` | 81.310532091 | 81.3s | 81.3s | source note — see §4.3 |
| `intelligenceIndexCostPerTask` | null | - | - | OK — both blank |
| `isOpenWeights` | no | no | - | OK |
| `deprecated` | yes | yes | - | OK |
| `gpqa` | 0.903030303030303 | - | 90.3% | OK |
| `hle` | 0.376737720111214 | - | 37.7% | OK |
| `scicode` | null | - | - | OK — both blank |
| `terminalBench21` | null | - | - | OK — both blank |
| `terminalBench40` | null | - | - | OK — both blank |
| `tauBanking` | null | - | - | OK — both blank |
| `lcr` | 0.826666666666667 | - | 82.7% | OK |
| `ifbench` | 0.754421768707483 | - | 75.4% | OK |
| `critpt` | 0.115510204081633 | - | 11.6% | OK |
| `mmmuPro` | null | - | - | OK — both blank |
| `gdpvalNormalized` | null | - | - | OK — both blank |

#### jt-35b-flash — JT-35B-Flash — sparse

| field | raw payload | MCP aa_leaderboard | MCP aa_compare metrics=all | verdict |
|---|---|---|---|---|
| `intelligenceIndex` | 18.6626376411117 | 18.7 | 18.7 | OK |
| `intelligenceIndexIsEstimated` | yes | yes | - | OK |
| `price1mInputTokens` | null | - | - | OK — both blank |
| `price1mOutputTokens` | null | - | - | OK — both blank |
| `cacheHitPrice` | null | - | - | OK — both blank |
| `contextWindowTokens` | 256000 | 256k | 256k | OK |
| `medianOutputTokensPerSecond` | null | - | - | OK — both blank |
| `medianTimeToFirstTokenSeconds` | null | - | - | OK — both blank |
| `intelligenceIndexCostPerTask` | null | - | - | OK — both blank |
| `isOpenWeights` | no | no | - | OK |
| `deprecated` | no | no | - | OK |
| `gpqa` | 0.829292929292929 | - | 82.9% | OK |
| `hle` | 0.0644114921223355 | - | 6.4% | OK |
| `scicode` | null | - | - | OK — both blank |
| `terminalBench21` | null | - | - | OK — both blank |
| `terminalBench40` | null | - | - | OK — both blank |
| `tauBanking` | null | - | - | OK — both blank |
| `lcr` | 0.656666666666667 | - | 65.7% | OK |
| `ifbench` | 0.420408163265306 | - | 42.0% | OK |
| `critpt` | 0 | - | 0.0% | OK |
| `mmmuPro` | null | - | - | OK — both blank |
| `gdpvalNormalized` | null | - | - | OK — both blank |

`jt-35b-flash` is the sparse case and behaves correctly in both surfaces: every raw
`null` renders `-`, and `aa_leaderboard` names them explicitly in its footer
(`— no data for: tok/s, TTFT, TTFA, E2E, In $/M, Out $/M, CacheRd $/M, CacheWr $/M,
Cost (shown as -)`), as does `aa_model` (`Pricing → no pricing recorded`).

---

## 3. Mismatch list

**No value-level mismatches.** All 22 requested fields × 6 models = 132 comparisons
agree with the raw payload to the tool's displayed precision, in every case where the
MCP and the raw payload both carry a value. Every cell where the MCP shows `-`, the
raw payload is `null` for that model too (verified in the table above); there is no
case of the MCP blanking a field the raw payload populates *for these six models*.

The only deviations from a literal equality are the four rows that the MCP
deliberately sources from a **different AA surface** than the leaderboard column of
the same name (§4.3) and the derived `time_per_task` (§4.4). Neither is a parse
error; both are described below.

Independently confirmed exactness on the leaderboard surface:

* `aa_leaderboard sort=tps top=5` → `celeris-1 1430.6, k2-horizon-375b-a23b 891.4,
  mercury-2-5 693.2, gemini-3-5-flash-lite 437.8, trinity-large-thinking 346.0`
  = raw `medianOutputTokensPerSecond` order and values exactly.
* `aa_leaderboard sort=intelligence top=5` → `claude-opus-5-5 57.6, claude-sonnet-5-5
  56.0, claude-opus-5-5-xhigh 56.0, muse-wonder-full 55.8, claude-opus-5-5-high 53.6`
  = raw order (including the 56.0 tie) and values exactly.
* Header coverage counts are honest: `5 of 162 scored (700 tracked)` for `tok/s`
  (exactly 162 *active* raw rows have a non-null `medianOutputTokensPerSecond`; 369
  across all 700, which is the `leaderboard (369/700)` figure `aa_benchmarks` prints
  for the same key), `5 of 265 scored` for `intelligence` (265 active rows have a
  non-null `intelligenceIndex`).

---

## 4. Comparison-path findings

### 4.1 Does `aa_compare` agree with the raw payload for every field both know?

Yes, with the two documented exceptions of §4.3/§4.4. The six-model reply
(`# 6 models · 67 metrics · 8m ago · aa:rsc + rich dataset`) was checked row by row
against `lb.raw` and against the model-page records embedded in `m_gpt52.raw` /
`m_mimo.raw` (the model pages carry the **same 702-record rich dataset** the MCP
merges, so both sides of every comparison could be read from raw bytes).

Beyond the 22 fields, these rows were verified against the raw rich records and all
matched:

| `aa_compare metrics=all` row | raw field | opus | opus-high | mimo | gem-lite | gpt-5.2 | jt-35b |
|---|---|---|---|---|---|---|---|
| Cost to Run the Intelligence Index (whole suite) | `intelligenceIndexCost.total` | 8708.198→$8,708 | 2172.428→$2,172 | 206.655→$207 | 365.634→$366 | null→`-` | null→`-` |
| Output Tokens per Intelligence Index Task | `intelligenceIndexOutputTokensPerTask.output` | 119166→119k | 35584→36k | 64276→64k | 17507→18k | null→`-` | null→`-` |
| Total Parameters (B) | `parameters` | – | – | 1020→1,020 | – | – | 35→35 |
| Active Parameters (B) | `inferenceParametersActiveBillions` | – | – | 42→42 | – | – | – |
| GDPval-AA Elo | `gdpval` | 1866.27→1866 | 1704.37→1704 | 1684.34→1684 | 983.28→983 | null→`-` | null→`-` |
| AA-Omniscience Index | `omniscience` | 46.417→46.4 | 40.633→40.6 | 8.383→8.4 | 5.233→5.2 | −0.883→−0.9 | −24.217→−24.2 |
| Omni Accuracy | `omniscienceAccuracy` | 0.6622→66.2% | 0.6456→64.6% | 0.3477→34.8% | 0.2947→29.5% | 0.4431→44.3% | 0.2416→24.2% |
| Omni Halluc | `omniscienceHallucinationRate` | 0.5859→58.6% | 0.6758→67.6% | 0.4057→40.6% | 0.3436→34.4% | 0.8119→81.2% | 0.6376→63.8% |
| AA-Briefcase Elo | `briefcaseBreakdown.overall.elo` | 1804.52→1805 | 1687.39→1687 | 1515.98→1516 | 650.26→650 | null→`-` | null→`-` |

Rounding is consistent (round-half-up on the displayed precision; `$0.435 → $0.43`,
`1,020` with a thousands separator, `437.7716 → 437.8`).

### 4.2 Does `metrics=all` include chart-set/panel metrics the raw leaderboard lacks?

**Yes**, and the values are correct. `lb.raw`'s 700-row array has no `aa3dElo`,
`briefcaseElo`, `cyberIndex`, `cweBench`, `analystAgentPassAt1/PassAtK`, `mlcrAccuracy`
etc. — those live on the eval pages and the homepage panel. Each joined value was
re-fetched and checked at the source:

| MCP row (opus / mimo / other) | raw source (fetched by hand) | raw value → MCP |
|---|---|---|
| AA-3D Elo | `/evaluations/aa-3d`, 21-model chart set, `aa3dElo` | 1190.0668→1190, 977.235→977 |
| AA-Briefcase Elo | `/evaluations/aa-briefcase`, 32-model chart set, `briefcaseElo` | 1804.52→1805, 1515.98→1516, 1687.39→1687 |
| AA Cyber Index | homepage panel, `score` for `evalSlug=artificial-analysis-cyber-index` | 28.6636→28.7, 56.0656→56.1 |
| Cyber Refusal | same panel, `refusalRate` | 0.35880→35.9%, 0→0.0% |
| CWE-Bench-AA | `/evaluations/cwe-bench-aa`, `cweBench` | 0.58333→58.3%, 0.63333→63.3% |
| CWE Refusal | same page, `cweBenchRefusalRate` | 0.09167→9.2%, 0→0.0% |
| MLCR Accuracy / Complete / Concise | `/evaluations/mlcr-aa`, `mlcrAccuracy` / `mlcrCompleteness` / `mlcrConciseness` | 0.93151→93.2% / 0.88356→88.4% / 0.81111→81.1%; 0.54887→54.9% / 0.42105→42.1% / 0.73889→73.9% |
| MLCR-AA | rich record `mlcrOverall` | 0.66667→66.7%, 0.18333→18.3% |
| AIME 2025, LiveCodeBench, τ²-Bench, Terminal-Bench Hard | rich record `aime25` / `livecodebench` / `tau2` / `terminalbenchHard` for deprecated `gpt-5-2` | 0.99→99.0%, 0.88889→88.9%, 0.84795→84.8%, 0.46970→47.0% |
| EnterpriseOps-Gym / Harvey LAB-AA / GDP.pdf / Terminal-Bench Science / AutomationBench | rich record of `gemini-3-5-flash-lite` | 0.42346→42.3%, 0→0.0%, 0.136→13.6%, 0→0.0%, 0.25011→25.0% |

The reply footnotes each provenance group (`… from AA's eval chart set (top ~27
models)`, `… from AA's eval chart set / homepage panel (top ~22 models)`, `Cyber
Refusal from AA's homepage panel (top ~20 models)`), and models outside a chart set
correctly get `-` (e.g. `jt-35b-flash` has no AA-3D Elo, and is absent from the
21-model AA-3D chart set). **No chart-set metric is silently attributed to the
leaderboard, and no chart-set value was found wrong.**

### 4.3 The same row label carries two different AA numbers (source switch)

This is the one place where "does the MCP agree with the raw payload" needs a
qualified answer, because AA publishes two different speed/latency aggregates and the
MCP's `aa_compare` picks one or the other depending on **which alias you type**.

| row label | raw `lb.raw` (leaderboard) | raw model page (`timescaleData`) | `aa_leaderboard` | `aa_compare metrics=all` |
|---|---|---|---|---|
| Speed (output tokens/s) — opus | `medianOutputTokensPerSecond` 95.7263 | `medianOutputSpeed` 95.1537 | 95.7 | 95.2 |
| Speed (output tokens/s) — gpt-5-2 | 73.8400 | 75.6305 | 73.8 | 75.6 |
| Time to First Token — opus | `medianTimeToFirstTokenSeconds` 679.2384 | `medianTimeToFirstChunk` 661.1524 | 679.2s | 661.2s |
| Time to First Token — opus-high | 51.9142 | 47.1817 | 51.9s | 47.2s |
| Time to First Token — mimo | 3.9634 | 4.0628 | 4.0s | 4.1s |
| Time to First Answer Token — opus | 679.2384 | `timeToFirstAnswerToken.total` 661.1524 | 679.2s | 661.2s |
| End-to-End Response Time — opus | 684.4616 | `endToEndResponseTime.total` 666.4071 | 684.5s | 666.4s |
| End-to-End Response Time — gpt-5-2 | 88.0819 | 87.9216 | 88.1s | 87.9s |

Both numbers are genuine AA publications, and `aa_model` states the difference
(`— speed from the model page (first-party measurement); aa_leaderboard reports the
leaderboard snapshot and may differ slightly`). What is *not* consistent is
`aa_compare`:

```
$ .venv/bin/python eval/client.py call aa_compare '{"queries":["claude-opus-5-5","gpt-5-2"],"metrics":"ttft","compact":false}'
# 2 models · 1 metrics · 16m ago · aa:rsc
| Time to First Token | 679.2s | 81.3s |

$ .venv/bin/python eval/client.py call aa_compare '{"queries":["claude-opus-5-5","gpt-5-2"],"metrics":"time_to_first_token","compact":false}'
# 2 models · 1 metrics · 16m ago · aa:rsc + rich dataset
| Time to First Token | 661.2s | 81.3s |

$ .venv/bin/python eval/client.py call aa_compare '{"queries":["claude-opus-5-5","gpt-5-2"],"metrics":"ttft,time_to_first_token,tps","compact":false}'
# 2 models · 3 metrics · 15m ago · aa:rsc + rich dataset
| Time to First Token | 661.2s | 81.3s |
| Time to First Token | 661.2s | 81.3s |
| Speed (output tokens/s) | 95.2 | 75.6 |
```

Same label, same tool, same models — `679.2s` or `661.2s` depending on the spelling.
And asking for one rich-only alias **silently re-sources the whole reply**: with
`metrics=ttft,time_to_first_token,tps`, the `tps` row flips from the leaderboard
`95.7` to the model-page `95.2` even though `tps` alone returns `95.7`. The
`_rich_needed()` heuristic (any requested key absent from the leaderboard rows ⇒ load
the rich overlay) is the cause, and it means the *same* metric set can return
different numbers for unrelated rows. `aa:rsc` vs `aa:rsc + rich dataset` in the
header is the only signal, and the footer only explains TTFT, not Speed.

Mitigation present: `aa_model`'s footer explains the two surfaces; `aa_compare`'s
footer explains TTFT only (`— TTFT is AA's long-prompt median; aa_model has the
per-prompt-type breakdown`), which is accurate for the rich path but misleading for
the `ttft` alias path, where 679.2s is *not* the long-prompt median (661.2s is).

### 4.4 `Time per Intelligence Index Task` is a derived mean, not AA's field of that name

`aa_compare`'s row labelled **Time per Intelligence Index Task** is not AA's
`intelligenceIndexTimePerTask`. It is the unweighted mean of the 10 per-evaluation
`timePerTask` values (confirmed by arithmetic and by `_axis_value()` in
`src/aa_mcp/server.py`, whose docstring calls both derived axes "model-page fields" —
true for `index_total_cost`, not for this one):

| model | AA's `intelligenceIndexTimePerTask` | mean of the 10 per-eval `timePerTask` | MCP row |
|---|---|---|---|
| claude-opus-5-5 | 797.4806 | 697.1366 | 697.1s |
| claude-opus-5-5-high | 289.6097 | 250.5000 | 250.5s |
| mimo-v2-6-pro | 1257.9040 | 1115.95 | 1,116.0s |
| gemini-3-5-flash-lite | 37.1564 | 37.11 | 37.1s |

Across all 189 rich records that carry both, the derived mean differs from AA's field
by a **median of −6.7 %** (range −25.7 % … +10.6 %); only 6.9 % agree within 1 %.
`aa_pareto x=time_per_task` uses the same helper, and its footer says "s/task is
model-page data (rich dataset), not a leaderboard column" — accurate, but it does not
say the number is a recomputation rather than AA's published value. The model page
does publish `intelligenceIndexTimePerTask` (797.4806 for opus) and carries a panel
labelled "Intelligence Index vs. Time per Task" with `"timeTooltip": "{value} min"`, so
a user reconciling the MCP's `s/task` against that page/chart sees a ~7–13 % gap with
no explanation. (That AA's chart plots `intelligenceIndexTimePerTask` rather than the
per-eval mean is `[INFERENCE]` from the field's name and its presence on the record;
the divergence itself is measured.)

### 4.5 Staleness: the rich overlay's age is not what the header reports

Two identical six-model calls twelve minutes apart returned different numbers:

| row | run A (12:21) | run B (12:33) | live raw payload (12:13) |
|---|---|---|---|
| mimo Speed | 45.8 | 47.3 | 47.3173 |
| mimo TTFT | 4.0s | 4.1s | 4.0628 |
| mimo E2E | 58.5s | 56.9s | 56.8976 |
| gpt-5-2 Speed | 73.3 | 75.6 | 75.6305 |
| gpt-5-2 E2E | 88.1s | 87.9s | 87.9216 |

Run B matches the raw bytes; run A did not, and run A's reply still claimed
`3m ago`. The rich overlay is cached separately from the leaderboard
(`rich_dataset.json`, `AA_RICH_TTL` default **21600 s = 6 h**, vs `AA_CACHE_TTL`
3600 s), and the reply header only reports one age. `aa_reference topic=overview`
says "scraped payloads are cached (default 1 h, `AA_CACHE_TTL`); the header line shows
age and flags `stale`" — but the age and the `stale` flag describe the *leaderboard*
payload, and neither of the two replies above (both within the 1 h leaderboard TTL)
carried any marker for the overlay that was actually producing the numbers.
`aa_reference topic=sources` documents `AA_CACHE_TTL` and `AA_API_TTL` but not
`AA_RICH_TTL`. Passing `refresh: true` re-fetches and restores exact agreement
(verified: with `"refresh":true`, `metrics=all` returned gpt-5-2 Speed 75.6 / E2E 87.9,
i.e. the raw values). `[INFERENCE]` the drift is AA's own rolling-median
recomputation between overlay refreshes, not a parse error — every value in both runs
is arithmetically consistent with an AA payload of *some* vintage.

### 4.6 Anything silently blank that the raw payload has?

One case found, in `aa_providers`:

```
$ … call aa_providers '{"model":"mimo-v2-6-pro","top":20}'
| Host | Model | Prec | In $/M | Out $/M | $/Task | tok/s |
| GMI (BF16) | mimo-v2-6-pro | bf16 | $0.43 | $0.87 | $0.12 | 51.0 |
| … 4 more rows, all with the model slug …

$ … call aa_providers '{"model":"mimo-v2-6-pro","top":20,"fields":"host,model,precision,in,out,cache_read,cost_per_task,tok/s,ttft"}'
— no data for: Model (shown as -)
| Host | Model | Precision | In $/M | Out $/M | CacheRd $/M | Cost | tok/s | TTFT |
| GMI (BF16) | - | bf16 | $0.43 | $0.87 | $0.0034 | $0.12 | 51.0 | 3.2s |
| Novita | - | - | $0.43 | $0.87 | $0.0036 | $0.13 | 43.3 | 3.3s |
| … | - | …
```

The raw `hostModels` array carries `"model":{"id":…,"slug":"mimo-v2-6-pro"}` on every
endpoint, and the default view renders it — but as soon as an explicit `fields=` list
that includes `model` is passed, the Model column comes back `-` and the footer
asserts `no data for: Model`, which is false. Reproduced on both `mimo-v2-6-pro`
(5/5 endpoints) and `claude-opus-5-5` (4/4 endpoints). Same run also shows
`no data for: Precision` for opus, which *is* genuinely absent (raw opus endpoints
carry no precision), so the two are indistinguishable to the reader.

Everything else checked was honest rather than silent: `aa_compare metrics=all`
footers the per-model gap counts (`missing on requested metrics: … 12 / 31 / 13 / 26 /
45 / 53`), `aa_leaderboard` names the blank columns in its footer, `aa_model` prints
`Pricing → no pricing recorded` for `jt-35b-flash`, and `aa_media` prints
`no data for: Model` only where the board really has none. No `aa_compare` cell was
blank where the raw payload had a value, for any of the six models.

---

## 5. Provider spot-checks

### 5.1 `claude-opus-5-5` — 4 endpoints, 4 in raw

`p_opus.raw` `hostModels` (first-party host list):

| host slug | host | in | out | cache read | precision |
|---|---|---|---|---|---|
| `anthropic_claude-opus-5-5` | Anthropic | 4 | 20 | 0.2 | — |
| `amazon_bedrock_claude-opus-5-5` | Amazon Bedrock | 4 | 20 | 0.2 | — |
| `google_claude-opus-5-5` | Google | 4 | 20 | 0.2 | — |
| `azure_claude-opus-5-5` | Microsoft Azure | 4 | 20 | 0.2 | — |

`aa_providers model=claude-opus-5-5` → `4 of 4 endpoints`, same four hosts, same
`$4.00 / $20.00`. Per-host tok/s matches the raw `performance.outputSpeed.median`:
Anthropic 95.2 (95.1537), Amazon Bedrock 95.2 (95.1835), Microsoft Azure 96.7
(96.7240), Google 98.3 (98.3029). Per-host TTFT matches
`performance.timeToFirstToken.median`: 661.2s (661.1524), 723.8s (723.8011),
695.9s (695.9345), 708.9s (708.8838).

`$/Task` is not a literal in `p_opus.raw`; it comes from `/leaderboards/providers`
(`providers_board.raw`, fetched by hand), whose endpoint records carry
`pricing.costPerTask`. Paired by the host that precedes each
`"model":{"slug":"claude-opus-5-5"}` record, the board says Anthropic 5.9820, Amazon
Bedrock 5.9820, Google 11.6277, Microsoft Azure 6.6961 — exactly the MCP's
$5.98 / $5.98 / $11.63 / $6.70. (A first read of the board that paired each model slug
with the *following* host produced a rotated mapping; the record order is
`host` → `model` → `pricing` → `performance`, and the MCP's pairing is the correct
one.)

### 5.2 `mimo-v2-6-pro` — 5 endpoints, 5 in raw

| host slug | host | in | out | cache read | raw tok/s | MCP tok/s | raw TTFT | MCP TTFT |
|---|---|---|---|---|---|---|---|---|
| `xiaomi_mimo-v2-6-pro` | Xiaomi | 0.435 | 0.87 | 0.0036 | 47.3173 | 47.3 | 4.0628 | 4.1s |
| `deepinfra_mimo-v2-6-pro` | DeepInfra | 0.43 | 0.87 | 0.004 | 39.4154 | 39.4 | 1.3387 | 1.3s |
| `primalabs_mimo-v2-6-pro` | PrimaLabs | 0.43 | 0.87 | 0.0036 | 153.7935 | 153.8 | 0.9061 | 0.9s |
| `gmi_mimo-v2-6-pro_bf16` | GMI (BF16) | 0.435 | 0.87 | 0.00342 | 51.0441 | 51.0 | 3.2278 | 3.2s |
| `novita_mimo-v2-6-pro` | Novita | 0.435 | 0.87 | 0.0036 | 43.3384 | 43.3 | 3.2605 | 3.3s |

Quantization: the raw payload has no `quantization` key — precision is encoded in the
host label (`GMI (BF16)`). The MCP surfaces it correctly as `Precision = bf16` for
that row and `-` for the other four (whose raw entries carry no precision at all), so
the MCP is neither inventing nor dropping a precision. All prices, cache-read prices,
speeds and TTFTs match. Header coverage `5 of 5 endpoints` matches the raw count.

`$/Task` again matches the providers board's `pricing.costPerTask`: Xiaomi 0.13322 →
$0.13, GMI 0.12425 → $0.12, Novita 0.12668 → $0.13, PrimaLabs 0.14051 → $0.14,
DeepInfra 0.96320 → $0.96.

(§4.6 records the one defect here: `fields=…,model,…` blanks the Model column.)

---

## 6. Media arena spot-check

Raw source: `/image/leaderboard/text-to-image` → `media.raw`. The leaderboard line of
the payload (`32:[[null,[…]]]`) carries exactly **102** rows for this board, matching
the MCP's `5 shown of 102 matching` / `5 of 102 text_to_image`; the payload also
embeds 1 750 dicts with an `elo` key in total (other boards' data pre-fetched by the
page), which is why the board count had to be read from that line rather than from a
blanket scan.

| # | model | raw `elo` | MCP Elo | raw `ciLower`/`ciUpper` | MCP CI | raw `appearances` | MCP | raw `pricePer1kImages` | MCP price | raw `releaseDate` | MCP |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GPT Image 2.5 Sunburst (max) | 1217 | 1217 | 1207 / 1227 | 1207 / 1227 | 12792 | 12,792 | 210.72 | $210.72/1k imgs | 2026-09-08 | 2026-09-08 |
| 2 | GPT Image 2.5 Flare (max) | 1207.48 | 1207 | 1197.48 / 1217.48 | 1197 / 1217 | 12174 | 12,174 | 210.72 | $210.72/1k imgs | 2026-09-08 | 2026-09-08 |
| 3 | GPT Image 2 (high) | 1187.47 | 1187 | 1175.47 / 1199.47 | 1175 / 1199 | 12409 | 12,409 | 211 | $211.00/1k imgs | 2026-04-21 | 2026-04-21 |
| 4 | Nano Banana 2.1 | 1172.42 | 1172 | 1160.42 / 1184.42 | 1160 / 1184 | 5841 | 5,841 | 33.6 | $33.60/1k imgs | 2026-10-06 | 2026-10-06 |
| 5 | Grok Imagine Image 2.0 | 1165.94 | 1166 | 1152.94 / 1178.94 | 1153 / 1179 | 7039 | 7,039 | 60 | $60.00/1k imgs | 2026-08-07 | 2026-08-07 |

Top-3 Elo, CI, appearance counts, prices and release dates all match. Two benign
conventions: the MCP's `Rank` column is 1-based (raw `rank` is 0-based, raw
`storedRank` is 1-based — the MCP uses the latter), and CI bounds are rendered as
integers (raw `1152.94` → `1153`).

Open-weights: 525 of the 1 750 raw rows carry `openWeightsUrl` (so open-weights
entries exist on these boards). The MCP reports `Open = False` for the top 5 (raw: no
`openWeightsUrl` ✓) and, with `open_weights=true`, returns Qwen-Image-2.1 1041
(raw 1041.11), Ideogram 4.0 (Quality) 1024 (1023.54), Ideogram 4.0 1001 (1001.47),
FLUX.2 [dev] 1000 (1000), Ming-Image-0.1-Design 1000 (999.94) — all with `Open = True`
matching the raw `openWeightsUrl` presence. No false positives or negatives found.

---

## 7. Benchmark / eval-page spot-check

`aa_benchmark_leaderboard benchmark="GPQA Diamond" top=12` vs the
`/evaluations/gpqa-diamond` chart set (`gpqa`, 18 models):

| model | raw `gpqa` | MCP |
|---|---|---|
| gpt-6-astra-xhigh | 0.96263 | 96.3% |
| gpt-6-astra | 0.96061 | 96.1% |
| gemini-3-8-flash | 0.95253 | 95.3% |
| grok-4-6 | 0.94949 | 94.9% |
| gpt-6-astra-high | 0.94949 | 94.9% |
| gemini-3-7-flash | 0.94545 | 94.5% |
| gpt-5-6-sol | 0.94141 | 94.1% |
| claude-fable-5-1 | 0.93737 | 93.7% |

Exact, including ordering and the 94.9 tie. The header is honest about scope:
`12 of 616 scored (700 tracked) · GPQA Diamond · leaderboard`, while the eval page's
own chart set only carries 18 models — the MCP ranks the full leaderboard and joins
the chart set, as documented. Models outside the chart set correctly show `-`
(e.g. `claude-opus-5-5` has `gpqa: null` in `lb.raw` and `-` in the MCP).

---

## 8. What a no-key user cannot get, and what they cannot verify

### 8.1 Cannot get (and the MCP says so)

| unavailable without `AA_API_KEY` | stated by the MCP? | where |
|---|---|---|
| AA **Coding Index** and **Agentic Index** | **Yes**, on every `aa_model` reply | `— Coding Index, Agentic Index need AA_API_KEY (JSON API); unavailable on the scrape source` |
| cross-model **ranking** on the six Capability Indexes | **Yes** | `— capability scores from the model page (rich dataset); AA_API_KEY adds the Coding/Agentic indexes and cross-model ranking` |
| the keyed JSON API's other conveniences (100 req/24 h free tier, `/api/v2` schema) | **Yes** | `aa_reference topic=overview` (`Adds the six Capability Indexes plus Coding/Agentic Indexes; 100 req/24 h free tier`) and `topic=sources` (JSON API + openapi schema URL) |

The six Capability Indexes (Economics, Engineering, Finance & Accounting, Healthcare
& Medical, Legal, Strategy & Ops) *are* available without a key — verified for all six
models against the rich records (e.g. opus Cap Economics 65.6 =
`capabilities.economics` 65.6045; gemini-3-5-flash-lite Cap Medical 23.1 =
`capabilities.healthcareAndMedical` 23.0741), so the "capability scores from the model
page (rich dataset)" footer is accurate.

Not verified here (no key): whether the keyed path returns identical numbers for the
fields both sources carry. Code inspection (`src/aa_mcp/api.py`) shows the keyed API
maps `tps`/`ttft`/`ttfa`/`e2e` to the *leaderboard* medians
(`median_output_tokens_per_second`, …) and sets `cost_breakdown`, `per_eval` and
`per_eval_cost` to `None`, so with a key the speed rows would read like
`aa_leaderboard` (95.7) rather than like `aa_compare metrics=all` (95.2).
`[INFERENCE]` — not exercised.

### 8.2 Cannot verify (and the MCP mostly does not say so)

| risk a no-key user carries | can they check it? | does the MCP say so? |
|---|---|---|
| **Rich-overlay staleness up to 6 h.** Speed/TTFT/E2E/cost-per-task/capability/chart-set values can be hours old while the header reports the leaderboard's age (`3m ago`) and flags `stale` only for the leaderboard payload. | Only by re-fetching AA by hand, or by passing `refresh: true`. | **Partly.** `aa_reference topic=overview` documents caching, the `stale` flag and `refresh=true` — but attributes all of it to the 1 h `AA_CACHE_TTL`; the separate 6 h rich-overlay TTL (`AA_RICH_TTL`) is documented nowhere (`topic=sources` lists only `AA_CACHE_TTL` and `AA_API_TTL`). |
| **Two different numbers behind one row label** (Speed / TTFT / TTFA / E2E from the leaderboard vs the model page, §4.3). | Yes, if you know to compare `aa_leaderboard` with `aa_compare`/`aa_model` and notice the header's `+ rich dataset`. | **Partly.** `aa_model` says it explicitly; `aa_compare` explains TTFT only, and its TTFT note is wrong for the `ttft` alias path. |
| **`Time per Intelligence Index Task` is a recomputed mean, not AA's field** (§4.4, median −6.7 %, up to −25.7 %). | Only by fetching the model page and reading `intelligenceIndexTimePerTask` yourself. | **No.** The row label matches AA's field name; `aa_pareto` calls it "model-page data (rich dataset)" without saying it is derived. |
| **Provider `$/Task` column** is not in the per-model providers payload (comes from the providers board). | Only by fetching `/leaderboards/providers`. | **No** — the footer only says `context is model-level, not per-endpoint`. |
| **Media `Rank` basis** (1-based `storedRank`, not the raw 0-based `rank`) and integer-rounded CIs. | Yes, by fetching the board payload. | **No.** |
| Whether a metric exists at all for a model (`aa_benchmarks` coverage counts, e.g. `rich dataset (211/700)`) | Yes — `aa_benchmarks` and `aa_leaderboard`/`aa_compare` headers state coverage honestly, and blanks are footnoted. | **Yes**, and this part is consistently accurate. |
| Which upstream URL a number came from | Only `aa_reference topic=sources` lists the page set at a coarse level; per-row provenance is footnoted by surface group (`eval chart set`, `homepage panel`, `rich dataset`, `leaderboard`). | **Yes**, at surface-group granularity. |

Net: for the fields AA publishes on more than one surface, a no-key user **cannot
tell which surface a number came from unless the tool volunteers it** — and the
volunteering is uneven (good in `aa_model` and in the chart-set footers, incomplete in
`aa_compare` for speed/latency, absent for `time_per_task`, provider `$/Task` and the
rich overlay's age).

---

## 9. Reproduce

```bash
# raw (no key needed; RSC: 1 header)
mkdir -p /tmp/r7 && U=https://artificialanalysis.ai
curl -sfL -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" "$U/leaderboards/models" -o /tmp/r7/lb.raw
# …the table in §1.2 for the rest

# MCP (key unset)
.venv/bin/python eval/client.py call aa_compare \
  '{"queries":["claude-opus-5-5","claude-opus-5-5-high","mimo-v2-6-pro","gemini-3-5-flash-lite","gpt-5-2","jt-35b-flash"],"metrics":"all","compact":false}'
.venv/bin/python eval/client.py call aa_compare \
  '{"queries":["claude-opus-5-5","gpt-5-2"],"metrics":"ttft,time_to_first_token,tps","compact":false}'   # §4.3
.venv/bin/python eval/client.py call aa_providers \
  '{"model":"mimo-v2-6-pro","top":20,"fields":"host,model,precision,in,out,cache_read,cost_per_task,tok/s,ttft"}'  # §4.6

# the raw-vs-MCP tables in §2 are generated by /tmp/r7/mktables.py (no aa_mcp import)
```

All raw values quoted above are reproducible from the payload files listed in §1.2;
all MCP values are reproducible from the commands in §1.4 (the only non-deterministic
input is AA's own rolling performance medians — see §4.5; pass `"refresh":true` for
live values).
