# Fidelity verification report — `aa_mcp` parsed data vs artificialanalysis.ai payloads

- **Date:** 2026-10-14
- **Verifier:** independent (second pair of eyes); no changes made under `src/` or `tests/`.
- **Method:** the raw payload arrays were extracted with *independent* code (SPARK-free:
  `/tmp/fid/raw.py`, a self-contained `json.JSONDecoder` scan — it does **not** import
  `aa_mcp.flight`), then compared field-by-field against the library output obtained
  through the real loader entry points (`aa_mcp.loaders.*`) running in `AA_OFFLINE=1`
  against a cache primed with the captured fixtures (`/tmp/fid/cache`).
- **Sources compared:** (a) the 2026-10-14 fixtures in `tests/fixtures/*.rsc`; (b) fresh
  live payloads fetched by the verifier with
  `curl -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1"` into `/tmp/fid/live/`
  (`leaderboard.rsc`, `prov_claude-opus-5-5.rsc`, `prov_claude-opus-5.rsc`).
- **Non-goals / not touched:** `src/` and `tests/`; the JSON-API backend (`api.py`,
  `aa_models_free.json`) was not exercised (needs a key / out of the requested scope).

---

## TL;DR — mismatches found

1. **One real data-fidelity bug (provider endpoints, `cost/task` silently dropped).**
   `loaders.provider_endpoints()` returns `cost_per_task = None` for every live
   `/models/<slug>/providers` endpoint, even though the raw payload carries
   `performance.intelligenceIndexCostPerTask` as a **flat** dict `{"total": 5.98, ...}`.
   `loaders._cost_per_task()` only understands a float or the *nested*
   `{"cost": {"total": ...}}` shape (the model-page/chart shape), so the flat provider
   shape yields `None`. Observed on **7/7** live endpoints across two models
   (claude-opus-5-5 ×4, claude-opus-5 ×3). The `providers_model.rsc` fixture happens to
   **omit** the key entirely, which is why the offline test suite cannot catch this.
2. **Everything else matched.** 0 mismatches on: 8 leaderboard variants × 35 fields,
   3 chart records (≈40 fields each incl. `capabilities.*`, briefcase Elo,
   cost breakdown, per-eval costs, effort, params, license, modalities), 20 provider-board
   rows × 19 fields, and 8 endpoint records × 19 fields (1 fixture + 7 live; every field
   matched except the 7 `cost_per_task` cases below).
3. **Silent drops (by design or oversight) and coverage gaps** are enumerated in
   “Claims vs delivery” below. The most notable: leaderboard `release_date` is always
   `None` although AA publishes it in a *sibling* array of the **same** payload; and
   `cost_per_task` / `speed.*` are absent for the majority of leaderboard rows.

---

## Surface 1 — Leaderboard (8 variants vs the 700-row metrics array)

**Independent extraction:** the metrics array is the 700-item array whose items carry
`slug` + `intelligenceIndex` (the payload also holds a 700-item 3-key nav array, a
506-item `{name,creator,deprecated,slug,releaseDate}` array, and small filter arrays).
Library path: `aa_mcp.loaders.leaderboard()` → `parse_leaderboard()` →
`normalize.from_leaderboard()`.

Variants picked to span the requested categories: frontier (`claude-opus-5-5`),
open-weights (`mimo-v2-6-pro`), effort variant (`claude-opus-5-5-xhigh`), deprecated
(`claude-opus-5`, `gemini-3-5-flash`), cheap/free (`north-mini-code`), null-heavy
(`claude-4-1-opus`, `deepseek-v2-5-sep-2024`).

**Mismatch list:** none. All 35 compared fields agreed exactly (float equality) for all
8 variants — including the `None == None` cases that dominate the null-heavy models.

### Per-field tables (field \| raw \| library \| verdict)

### `claude-opus-5-5` (frontier)

| field | raw | library | verdict |
|---|---|---|---|
| name | Claude Opus 5.5 (Max, Default Fallback) | Claude Opus 5.5 (Max, Default Fallback) | OK |
| shortName | Claude Opus 5.5 (max with fallback) | Claude Opus 5.5 (max with fallback) | OK |
| modelCreatorName | Anthropic | Anthropic | OK |
| intelligenceIndex | 57.6224 | 57.6224 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0.683135 | 0.683135 | OK |
| gpqa | None | None | OK |
| hle | 0.613531 | 0.613531 | OK |
| scicode | 0.668981 | 0.668981 | OK |
| terminalBench21 | None | None | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | None | None | OK |
| lcr | 0.846667 | 0.846667 | OK |
| ifbench | None | None | OK |
| critpt | 0.317143 | 0.317143 | OK |
| mmmuPro | 0.876879 | 0.876879 | OK |
| itbenchSre | 0.382298 | 0.382298 | OK |
| apexAgents | None | None | OK |
| analystAgent | 0.5625 | 0.5625 | OK |
| omniscience | 46.4167 | 46.4167 | OK |
| omniscienceAccuracy | 0.662167 | 0.662167 | OK |
| omniscienceNonHallucination | 0.413912 | 0.413912 | OK |
| price1mInputTokens | 4 | 4 | OK |
| price1mOutputTokens | 20 | 20 | OK |
| cacheHitPrice | 0.2 | 0.2 | OK |
| cacheWritePrice | 5 | 5 | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| isOpenWeights | False | False | OK |
| isReasoning | True | True | OK |
| deprecated | False | False | OK |
| medianOutputTokensPerSecond | 94.8311 | 94.8311 | OK |
| medianTimeToFirstTokenSeconds | 650.105 | 650.105 | OK |
| medianEndToEndResponseTimeSeconds | 655.378 | 655.378 | OK |
| intelligenceIndexCostPerTask | 5.98201 | 5.98201 | OK |

### `mimo-v2-6-pro` (open-weights)

| field | raw | library | verdict |
|---|---|---|---|
| name | MiMo-V2.6-Pro | MiMo-V2.6-Pro | OK |
| shortName | MiMo-V2.6-Pro | MiMo-V2.6-Pro | OK |
| modelCreatorName | Xiaomi | Xiaomi | OK |
| intelligenceIndex | 46.3242 | 46.3242 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0.59104 | 0.59104 | OK |
| gpqa | None | None | OK |
| hle | 0.493513 | 0.493513 | OK |
| scicode | 0.608796 | 0.608796 | OK |
| terminalBench21 | None | None | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | None | None | OK |
| lcr | 0.863333 | 0.863333 | OK |
| ifbench | None | None | OK |
| critpt | 0.265714 | 0.265714 | OK |
| mmmuPro | None | None | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | 0.375 | 0.375 | OK |
| omniscience | 8.38333 | 8.38333 | OK |
| omniscienceAccuracy | 0.3485 | 0.3485 | OK |
| omniscienceNonHallucination | 0.593758 | 0.593758 | OK |
| price1mInputTokens | 0.435 | 0.435 | OK |
| price1mOutputTokens | 0.87 | 0.87 | OK |
| cacheHitPrice | 0.0036 | 0.0036 | OK |
| cacheWritePrice | None | None | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| isOpenWeights | True | True | OK |
| isReasoning | True | True | OK |
| deprecated | False | False | OK |
| medianOutputTokensPerSecond | 46.7821 | 46.7821 | OK |
| medianTimeToFirstTokenSeconds | 4.01455 | 4.01455 | OK |
| medianEndToEndResponseTimeSeconds | 57.4538 | 57.4538 | OK |
| intelligenceIndexCostPerTask | 0.133223 | 0.133223 | OK |

### `claude-opus-5-5-xhigh` (effort variant)

| field | raw | library | verdict |
|---|---|---|---|
| name | Claude Opus 5.5 (Xhigh, Default Fallback) | Claude Opus 5.5 (Xhigh, Default Fallback) | OK |
| shortName | Claude Opus 5.5 (xhigh with fallback) | Claude Opus 5.5 (xhigh with fallback) | OK |
| modelCreatorName | Anthropic | Anthropic | OK |
| intelligenceIndex | 55.9874 | 55.9874 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0.6679 | 0.6679 | OK |
| gpqa | None | None | OK |
| hle | 0.57507 | 0.57507 | OK |
| scicode | 0.650463 | 0.650463 | OK |
| terminalBench21 | None | None | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | None | None | OK |
| lcr | 0.846667 | 0.846667 | OK |
| ifbench | None | None | OK |
| critpt | 0.317143 | 0.317143 | OK |
| mmmuPro | 0.865896 | 0.865896 | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | None | None | OK |
| omniscience | 42.65 | 42.65 | OK |
| omniscienceAccuracy | 0.653833 | 0.653833 | OK |
| omniscienceNonHallucination | 0.343284 | 0.343284 | OK |
| price1mInputTokens | 4 | 4 | OK |
| price1mOutputTokens | 20 | 20 | OK |
| cacheHitPrice | 0.2 | 0.2 | OK |
| cacheWritePrice | 5 | 5 | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| isOpenWeights | False | False | OK |
| isReasoning | True | True | OK |
| deprecated | False | False | OK |
| medianOutputTokensPerSecond | 82.485 | 82.485 | OK |
| medianTimeToFirstTokenSeconds | 144.788 | 144.788 | OK |
| medianEndToEndResponseTimeSeconds | 150.85 | 150.85 | OK |
| intelligenceIndexCostPerTask | 3.45911 | 3.45911 | OK |

### `claude-opus-5` (deprecated)

| field | raw | library | verdict |
|---|---|---|---|
| name | Claude Opus 5 (Max) | Claude Opus 5 (Max) | OK |
| shortName | Claude Opus 5 (max) | Claude Opus 5 (max) | OK |
| modelCreatorName | Anthropic | Anthropic | OK |
| intelligenceIndex | 50.7771 | 50.7771 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0.61095 | 0.61095 | OK |
| gpqa | 0.932323 | 0.932323 | OK |
| hle | 0.548656 | 0.548656 | OK |
| scicode | 0.563657 | 0.563657 | OK |
| terminalBench21 | 0.891386 | 0.891386 | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | 0.420619 | 0.420619 | OK |
| lcr | 0.793333 | 0.793333 | OK |
| ifbench | None | None | OK |
| critpt | 0.291429 | 0.291429 | OK |
| mmmuPro | 0.847399 | 0.847399 | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | 0.5375 | 0.5375 | OK |
| omniscience | 37.0667 | 37.0667 | OK |
| omniscienceAccuracy | 0.608667 | 0.608667 | OK |
| omniscienceNonHallucination | 0.391823 | 0.391823 | OK |
| price1mInputTokens | 5 | 5 | OK |
| price1mOutputTokens | 25 | 25 | OK |
| cacheHitPrice | 0.5 | 0.5 | OK |
| cacheWritePrice | 6.25 | 6.25 | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| isOpenWeights | False | False | OK |
| isReasoning | True | True | OK |
| deprecated | True | True | OK |
| medianOutputTokensPerSecond | 56.2641 | 56.2641 | OK |
| medianTimeToFirstTokenSeconds | 100.036 | 100.036 | OK |
| medianEndToEndResponseTimeSeconds | 108.922 | 108.922 | OK |
| intelligenceIndexCostPerTask | 5.8584 | 5.8584 | OK |

### `north-mini-code` (cheap (free))

| field | raw | library | verdict |
|---|---|---|---|
| name | North Mini Code | North Mini Code | OK |
| shortName | North Mini Code | North Mini Code | OK |
| modelCreatorName | Cohere | Cohere | OK |
| intelligenceIndex | 9.91463 | 9.91463 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0 | 0 | OK |
| gpqa | 0.756566 | 0.756566 | OK |
| hle | 0.110751 | 0.110751 | OK |
| scicode | 0.387731 | 0.387731 | OK |
| terminalBench21 | 0.355805 | 0.355805 | OK |
| terminalbenchHard | 0.310606 | 0.310606 | OK |
| tau2 | 0.374269 | 0.374269 | OK |
| tauBanking | 0.0639175 | 0.0639175 | OK |
| lcr | 0.373333 | 0.373333 | OK |
| ifbench | 0.57551 | 0.57551 | OK |
| critpt | 0.00285714 | 0.00285714 | OK |
| mmmuPro | None | None | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | None | None | OK |
| omniscience | -48.5833 | -48.5833 | OK |
| omniscienceAccuracy | 0.189 | 0.189 | OK |
| omniscienceNonHallucination | 0.1679 | 0.1679 | OK |
| price1mInputTokens | 0 | 0 | OK |
| price1mOutputTokens | 0 | 0 | OK |
| cacheHitPrice | None | None | OK |
| cacheWritePrice | None | None | OK |
| contextWindowTokens | 256000 | 256000 | OK |
| isOpenWeights | True | True | OK |
| isReasoning | True | True | OK |
| deprecated | False | False | OK |
| medianOutputTokensPerSecond | 100.525 | 100.525 | OK |
| medianTimeToFirstTokenSeconds | 0.422058 | 0.422058 | OK |
| medianEndToEndResponseTimeSeconds | 25.2914 | 25.2914 | OK |
| intelligenceIndexCostPerTask | 0 | 0 | OK |

### `claude-4-1-opus` (null-heavy/deprecated)

| field | raw | library | verdict |
|---|---|---|---|
| name | Claude 4.1 Opus (Non-reasoning) | Claude 4.1 Opus (Non-reasoning) | OK |
| shortName | Claude 4.1 Opus (non-reasoning) | Claude 4.1 Opus (non-reasoning) | OK |
| modelCreatorName | Anthropic | Anthropic | OK |
| intelligenceIndex | 18.567 | 18.567 | OK |
| intelligenceIndexIsEstimated | True | True | OK |
| gdpvalNormalized | None | None | OK |
| gpqa | None | None | OK |
| hle | None | None | OK |
| scicode | None | None | OK |
| terminalBench21 | None | None | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | None | None | OK |
| lcr | None | None | OK |
| ifbench | None | None | OK |
| critpt | None | None | OK |
| mmmuPro | None | None | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | None | None | OK |
| omniscience | None | None | OK |
| omniscienceAccuracy | None | None | OK |
| omniscienceNonHallucination | None | None | OK |
| price1mInputTokens | 15 | 15 | OK |
| price1mOutputTokens | 75 | 75 | OK |
| cacheHitPrice | 1.5 | 1.5 | OK |
| cacheWritePrice | 18.75 | 18.75 | OK |
| contextWindowTokens | 200000 | 200000 | OK |
| isOpenWeights | False | False | OK |
| isReasoning | False | False | OK |
| deprecated | True | True | OK |
| medianOutputTokensPerSecond | None | None | OK |
| medianTimeToFirstTokenSeconds | None | None | OK |
| medianEndToEndResponseTimeSeconds | None | None | OK |
| intelligenceIndexCostPerTask | None | None | OK |

### `deepseek-v2-5-sep-2024` (null-heavy/open-weights)

| field | raw | library | verdict |
|---|---|---|---|
| name | DeepSeek-V2.5 | DeepSeek-V2.5 | OK |
| shortName | DeepSeek-V2.5 | DeepSeek-V2.5 | OK |
| modelCreatorName | DeepSeek | DeepSeek | OK |
| intelligenceIndex | 6.55309 | 6.55309 | OK |
| intelligenceIndexIsEstimated | True | True | OK |
| gdpvalNormalized | None | None | OK |
| gpqa | None | None | OK |
| hle | None | None | OK |
| scicode | None | None | OK |
| terminalBench21 | None | None | OK |
| terminalbenchHard | None | None | OK |
| tau2 | None | None | OK |
| tauBanking | None | None | OK |
| lcr | None | None | OK |
| ifbench | None | None | OK |
| critpt | None | None | OK |
| mmmuPro | None | None | OK |
| itbenchSre | None | None | OK |
| apexAgents | None | None | OK |
| analystAgent | None | None | OK |
| omniscience | None | None | OK |
| omniscienceAccuracy | None | None | OK |
| omniscienceNonHallucination | None | None | OK |
| price1mInputTokens | None | None | OK |
| price1mOutputTokens | None | None | OK |
| cacheHitPrice | None | None | OK |
| cacheWritePrice | None | None | OK |
| contextWindowTokens | 128000 | 128000 | OK |
| isOpenWeights | True | True | OK |
| isReasoning | False | False | OK |
| deprecated | True | True | OK |
| medianOutputTokensPerSecond | None | None | OK |
| medianTimeToFirstTokenSeconds | None | None | OK |
| medianEndToEndResponseTimeSeconds | None | None | OK |
| intelligenceIndexCostPerTask | None | None | OK |

### `gemini-3-5-flash` (deprecated/rich)

| field | raw | library | verdict |
|---|---|---|---|
| name | Gemini 3.5 Flash (High) | Gemini 3.5 Flash (High) | OK |
| shortName | Gemini 3.5 Flash (high) | Gemini 3.5 Flash (high) | OK |
| modelCreatorName | Google | Google | OK |
| intelligenceIndex | 32.5983 | 32.5983 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| gdpvalNormalized | 0.35113 | 0.35113 | OK |
| gpqa | 0.922222 | 0.922222 | OK |
| hle | 0.426784 | 0.426784 | OK |
| scicode | 0.539352 | 0.539352 | OK |
| terminalBench21 | 0.786517 | 0.786517 | OK |
| terminalbenchHard | 0.409091 | 0.409091 | OK |
| tau2 | 0.953216 | 0.953216 | OK |
| tauBanking | 0.321649 | 0.321649 | OK |
| lcr | 0.733333 | 0.733333 | OK |
| ifbench | 0.763265 | 0.763265 | OK |
| critpt | 0.131429 | 0.131429 | OK |
| mmmuPro | 0.842775 | 0.842775 | OK |
| itbenchSre | 0.403484 | 0.403484 | OK |
| apexAgents | 0.470501 | 0.470501 | OK |
| analystAgent | 0.45 | 0.45 | OK |
| omniscience | 21.1833 | 21.1833 | OK |
| omniscienceAccuracy | 0.514 | 0.514 | OK |
| omniscienceNonHallucination | 0.378258 | 0.378258 | OK |
| price1mInputTokens | 1.5 | 1.5 | OK |
| price1mOutputTokens | 9 | 9 | OK |
| cacheHitPrice | 0.15 | 0.15 | OK |
| cacheWritePrice | None | None | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| isOpenWeights | False | False | OK |
| isReasoning | True | True | OK |
| deprecated | True | True | OK |
| medianOutputTokensPerSecond | 189.373 | 189.373 | OK |
| medianTimeToFirstTokenSeconds | 17.3002 | 17.3002 | OK |
| medianEndToEndResponseTimeSeconds | 19.9405 | 19.9405 | OK |
| intelligenceIndexCostPerTask | 3.69369 | 3.69369 | OK |


### Leaderboard fields the library silently drops

Raw metrics-array keys never surfaced on `Model` (union over the 700 rows):

`modelCreatorColor`, `modelCreatorLogo`, `priceClass`,
`percentile05OutputTokensPerSecond`, `quartile25OutputTokensPerSecond`,
`quartile75OutputTokensPerSecond`, `percentile95OutputTokensPerSecond`,
`percentile05TimeToFirstTokenSeconds`, `quartile25TimeToFirstTokenSeconds`,
`quartile75TimeToFirstTokenSeconds`, `percentile95TimeToFirstTokenSeconds`.

(11 keys — colour/logo/price-class metadata plus the full latency/throughput
distribution, which is useful for tail-latency questions. `medianReasoningTimeSeconds`
and `medianTimeToFirstAnswerTokenSeconds` **are** surfaced as `speed.reasoning_s` /
`speed.ttfa`.)

### Leaderboard coverage gaps (documented `Model` fields that come out empty)

Counts over all 700 rows (library output, `AA_SOURCE=rsc`):

| field | non-empty rows | note |
|---|---|---|
| `release_date` | **0 / 700** | raw metrics array carries no `releaseDate`; AA has it in the sibling 506-row array of the same payload (joinable, not joined) |
| `creator_slug` | **0 / 700** | raw has no creator slug on the metrics array |
| `effort` | 0 / 700 | by design (chart-only per docs) |
| `params_b`, `active_params_b`, `license`, `license_url`, `weights_url` | 0 / 700 | not in the metrics array |
| `knowledge_cutoff` | 0 / 700 | not in the metrics array |
| `modalities_in`, `modalities_out` | 0 / 700 | not in the metrics array |
| `cost_breakdown`, `per_eval_cost` | 0 / 700 | chart-only shape; leaderboard has a bare float |
| `cost_per_task` | **186 / 700** (`intelligenceIndexCostPerTask` present on 186 rows) | docs imply coverage; the field is genuinely absent on 514 rows |
| `speed.tps` / `ttft` / `e2e` | **367 / 700** | ~half the rows carry no speed block |
| `evals` non-empty | 676 / 700 | per-benchmark sparsity in the table below |

Per-eval key presence (leaderboard): `hle` 662, `gpqa` 616, `critpt` 577,
`omniscienceAccuracy`/`omniscienceNonHallucination` 574, `lcr` 573, `ifbench` 450,
`tau2` 440, `terminalbenchHard` 432, `gdpvalNormalized` 291, `mmmuPro` 287,
`terminalBench21` 241, `scicode` 229, `terminalBench40` 218, `tauBanking` 209,
`analystAgent` 47, `itbenchSre` 45, `apexAgents` 33.

> Note on the doc claim “700 variants × 50 metrics”: rows are **heterogeneous** — the
> union of keys across the 700 rows is **51**, individual rows carry 36–51 keys
> (full 51-key rows for models with speed+cost; 36-key rows for sparse/deprecated ones).

---

## Surface 2 — Model-page chart records (3 models vs `initialModels`)

**Independent extraction:** the 27-record `initialModels` array (items carry
`chartDefaultSelected`, `releaseDate`, `suffix`). Library path:
`aa_mcp.loaders.model(slug)[slug]` → `parse_chart()` → `normalize.from_chart()`.

Models: `claude-opus-5-5` (effort label `max`, capability indices), `mimo-v2-6-pro`
(open weights, params/license), `glm-5-3` (open weights, effort, license).

**Mismatch list:** none. 0 mismatches on the ≈40 compared fields per model, including
`capabilities.*` (all six), `omniscience`/accuracy/hallucination-rate, `briefcaseElo`
(from `briefcaseBreakdown.overall.elo`), `automationBenchPartialScore`, the full
`cost_breakdown` dict, the `per_eval_cost` list (slug + `weightedCostPerTask`), the
`effort.label`, `parameters`, `inferenceParametersActiveBillions`, `licenseName`,
`licenseUrl`, `modelWeightsSourceUrl`, `knowledgeCutoffDate`, release/deprecation,
modalities, all pricing/blended fields, and every speed field
(`timescaleData`, `endToEndResponseTime`, `timeToFirstAnswerToken`,
`intelligenceIndexOutputTokensPerTask`).

### Per-field tables (field \| raw \| library \| verdict)

### `claude-opus-5-5` (effort label max; capability indices)

| field | raw | library | verdict |
|---|---|---|---|
| intelligenceIndex | 57.6224 | 57.6224 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| capabilities.financeAndAccounting | 60.7295 | 60.7295 | OK |
| capabilities.strategyAndOps | 63.6789 | 63.6789 | OK |
| capabilities.legal | 63.2603 | 63.2603 | OK |
| capabilities.healthcareAndMedical | 60.536 | 60.536 | OK |
| capabilities.engineering | 60.3546 | 60.3546 | OK |
| capabilities.economics | 65.6045 | 65.6045 | OK |
| omniscience | 46.4167 | 46.4167 | OK |
| omniscienceAccuracy | 0.662167 | 0.662167 | OK |
| omniscienceHallucinationRate | 0.586088 | 0.586088 | OK |
| briefcaseElo (briefcaseBreakdown.overall.elo) | 1804.52 | 1804.52 | OK |
| automationBenchPartialScore | 0.695387 | 0.695387 | OK |
| cost_per_task (cost.total) | 5.98201 | 5.98201 | OK |
| cost_breakdown | {"total": 5.982012, "input": 3.598692, "nonCacheInput": 0.103237, "cacheRead": 2.424229, "cacheWrite": 1.071226, "output": 2.38332, "reasoning": 1.678582, "answer": 0.704739} | {"total": 5.982012, "input": 3.598692, "nonCacheInput": 0.103237, "cacheRead": 2.424229, "cacheWrite": 1.071226, "output": 2.38332, "reasoning": 1.678582, "answer": 0.704739} | OK |
| per_eval_cost (slug,weighted) | [["aa-briefcase", 3.1568959073487983], ["gdpval-aa", 0.8918386645138963], ["automationbench-aa", 0.07143775552710561], ["terminalbench-4-0", 1.3109276120148785], ["scicode", 0.04691160138888889], ["hu | [["aa-briefcase", 3.1568959073487983], ["gdpval-aa", 0.8918386645138963], ["automationbench-aa", 0.07143775552710561], ["terminalbench-4-0", 1.3109276120148785], ["scicode", 0.04691160138888889], ["hu | OK |
| effort (effort.label) | max | max | OK |
| parameters | None | None | OK |
| inferenceParametersActiveBillions | None | None | OK |
| licenseName | None | None | OK |
| licenseUrl | None | None | OK |
| modelWeightsSourceUrl | None | None | OK |
| knowledgeCutoffDate | None | None | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| releaseDate | 2026-09-22 | 2026-09-22 | OK |
| release.deprecatedTo | None | None | OK |
| isOpenWeights | False | False | OK |
| isReasoning | True | True | OK |
| sizeClass/openSourceCategorization | large | large | OK |
| input modalities | ('text', 'image') | ('text', 'image') | OK |
| output modalities | ('text',) | ('text',) | OK |
| price1mInputTokens | 4 | 4 | OK |
| price1mOutputTokens | 20 | 20 | OK |
| cacheHitPrice | 0.2 | 0.2 | OK |
| cacheWritePrice | 5 | 5 | OK |
| cacheHitDiscountPercent | 0.95 | 0.95 | OK |
| price1mBlended0To3To1 | 8 | 8 | OK |
| price1mBlended7To2To1 | 2.94 | 2.94 | OK |
| timescaleData.medianOutputSpeed (tps) | 95.4019 | 95.4019 | OK |
| timescaleData.medianTimeToFirstChunk (ttft) | 679.238 | 679.238 | OK |
| timeToFirstAnswerToken.total (ttfa) | 679.238 | 679.238 | OK |
| endToEndResponseTime.total (e2e) | 684.479 | 684.479 | OK |
| endToEndResponseTime.reasoning (reasoning_s) | 0 | 0 | OK |
| intelligenceIndexOutputTokensPerTask.output | 119166 | 119166 | OK |

### `mimo-v2-6-pro` (open weights; params/license)

| field | raw | library | verdict |
|---|---|---|---|
| intelligenceIndex | 46.3242 | 46.3242 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| capabilities.financeAndAccounting | 46.0836 | 46.0836 | OK |
| capabilities.strategyAndOps | 47.7833 | 47.7833 | OK |
| capabilities.legal | 44.7508 | 44.7508 | OK |
| capabilities.healthcareAndMedical | 41.8204 | 41.8204 | OK |
| capabilities.engineering | 46.8982 | 46.8982 | OK |
| capabilities.economics | 53.2172 | 53.2172 | OK |
| omniscience | 8.38333 | 8.38333 | OK |
| omniscienceAccuracy | 0.3485 | 0.3485 | OK |
| omniscienceHallucinationRate | 0.406242 | 0.406242 | OK |
| briefcaseElo (briefcaseBreakdown.overall.elo) | 1515.98 | 1515.98 | OK |
| automationBenchPartialScore | 0.586234 | 0.586234 | OK |
| cost_per_task (cost.total) | 0.133223 | 0.133223 | OK |
| cost_breakdown | {"total": 0.133223, "input": 0.077303, "nonCacheInput": 0.004245, "cacheRead": 0.01947, "cacheWrite": 0.053589, "output": 0.05592, "reasoning": 0.032642, "answer": 0.023278} | {"total": 0.133223, "input": 0.077303, "nonCacheInput": 0.004245, "cacheRead": 0.01947, "cacheWrite": 0.053589, "output": 0.05592, "reasoning": 0.032642, "answer": 0.023278} | OK |
| per_eval_cost (slug,weighted) | [["aa-briefcase", 0.057027382027649516], ["gdpval-aa", 0.016121702931689817], ["automationbench-aa", 0.002113084625318502], ["terminalbench-4-0", 0.04380502238483266], ["scicode", 0.000779584494791666 | [["aa-briefcase", 0.057027382027649516], ["gdpval-aa", 0.016121702931689817], ["automationbench-aa", 0.002113084625318502], ["terminalbench-4-0", 0.04380502238483266], ["scicode", 0.000779584494791666 | OK |
| effort (effort.label) | None | None | OK |
| parameters | 1020 | 1020 | OK |
| inferenceParametersActiveBillions | 42 | 42 | OK |
| licenseName | MIT | MIT | OK |
| licenseUrl | https://huggingface.co/datasets/choosealicense/licenses/blob/main/markdown/mit.md | https://huggingface.co/datasets/choosealicense/licenses/blob/main/markdown/mit.md | OK |
| modelWeightsSourceUrl | https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL | https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL | OK |
| knowledgeCutoffDate | None | None | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| releaseDate | 2026-09-21 | 2026-09-21 | OK |
| release.deprecatedTo | None | None | OK |
| isOpenWeights | True | True | OK |
| isReasoning | True | True | OK |
| sizeClass/openSourceCategorization | large | large | OK |
| input modalities | ('text', 'image', 'speech', 'video') | ('text', 'image', 'speech', 'video') | OK |
| output modalities | ('text',) | ('text',) | OK |
| price1mInputTokens | 0.435 | 0.435 | OK |
| price1mOutputTokens | 0.87 | 0.87 | OK |
| cacheHitPrice | 0.0036 | 0.0036 | OK |
| cacheWritePrice | None | None | OK |
| cacheHitDiscountPercent | 0.991724 | 0.991724 | OK |
| price1mBlended0To3To1 | 0.54375 | 0.54375 | OK |
| price1mBlended7To2To1 | 0.17652 | 0.17652 | OK |
| timescaleData.medianOutputSpeed (tps) | 45.8067 | 45.8067 | OK |
| timescaleData.medianTimeToFirstChunk (ttft) | 4.06275 | 4.06275 | OK |
| timeToFirstAnswerToken.total (ttfa) | 47.7245 | 47.7245 | OK |
| endToEndResponseTime.total (e2e) | 58.6399 | 58.6399 | OK |
| endToEndResponseTime.reasoning (reasoning_s) | 43.6617 | 43.6617 | OK |
| intelligenceIndexOutputTokensPerTask.output | 64275.7 | 64275.7 | OK |

### `glm-5-3` (open weights; effort; license)

| field | raw | library | verdict |
|---|---|---|---|
| intelligenceIndex | 44.7774 | 44.7774 | OK |
| intelligenceIndexIsEstimated | False | False | OK |
| capabilities.financeAndAccounting | 44.7076 | 44.7076 | OK |
| capabilities.strategyAndOps | 47.5751 | 47.5751 | OK |
| capabilities.legal | 42.0364 | 42.0364 | OK |
| capabilities.healthcareAndMedical | 46.6708 | 46.6708 | OK |
| capabilities.engineering | 47.1451 | 47.1451 | OK |
| capabilities.economics | 51.2281 | 51.2281 | OK |
| omniscience | 14.3 | 14.3 | OK |
| omniscienceAccuracy | 0.3385 | 0.3385 | OK |
| omniscienceHallucinationRate | 0.29554 | 0.29554 | OK |
| briefcaseElo (briefcaseBreakdown.overall.elo) | 1508.36 | 1508.36 | OK |
| automationBenchPartialScore | 0.622029 | 0.622029 | OK |
| cost_per_task (cost.total) | 2.00564 | 2.00564 | OK |
| cost_breakdown | {"total": 2.005638, "input": 1.692676, "nonCacheInput": 0.013454, "cacheRead": 1.521848, "cacheWrite": 0.157374, "output": 0.312962, "reasoning": 0.21441, "answer": 0.098552} | {"total": 2.005638, "input": 1.692676, "nonCacheInput": 0.013454, "cacheRead": 1.521848, "cacheWrite": 0.157374, "output": 0.312962, "reasoning": 0.21441, "answer": 0.098552} | OK |
| per_eval_cost (slug,weighted) | [["aa-briefcase", 0.8473184620626165], ["gdpval-aa", 0.22569955738459915], ["automationbench-aa", 0.023022340810111726], ["terminalbench-4-0", 0.8064202070800424], ["scicode", 0.008202589583333333], [ | [["aa-briefcase", 0.8473184620626165], ["gdpval-aa", 0.22569955738459915], ["automationbench-aa", 0.023022340810111726], ["terminalbench-4-0", 0.8064202070800424], ["scicode", 0.008202589583333333], [ | OK |
| effort (effort.label) | max | max | OK |
| parameters | 753 | 753 | OK |
| inferenceParametersActiveBillions | 40 | 40 | OK |
| licenseName | GLM-5.3 License | GLM-5.3 License | OK |
| licenseUrl | https://huggingface.co/zai-org/GLM-5.3/blob/main/LICENSE | https://huggingface.co/zai-org/GLM-5.3/blob/main/LICENSE | OK |
| modelWeightsSourceUrl | https://huggingface.co/zai-org/GLM-5.3 | https://huggingface.co/zai-org/GLM-5.3 | OK |
| knowledgeCutoffDate | None | None | OK |
| contextWindowTokens | 1000000 | 1000000 | OK |
| releaseDate | 2026-08-18 | 2026-08-18 | OK |
| release.deprecatedTo | None | None | OK |
| isOpenWeights | True | True | OK |
| isReasoning | True | True | OK |
| sizeClass/openSourceCategorization | large | large | OK |
| input modalities | ('text',) | ('text',) | OK |
| output modalities | ('text',) | ('text',) | OK |
| price1mInputTokens | 1.4 | 1.4 | OK |
| price1mOutputTokens | 4.4 | 4.4 | OK |
| cacheHitPrice | 0.26 | 0.26 | OK |
| cacheWritePrice | None | None | OK |
| cacheHitDiscountPercent | 0.814286 | 0.814286 | OK |
| price1mBlended0To3To1 | 2.15 | 2.15 | OK |
| price1mBlended7To2To1 | 0.902 | 0.902 | OK |
| timescaleData.medianOutputSpeed (tps) | 60.5128 | 60.5128 | OK |
| timescaleData.medianTimeToFirstChunk (ttft) | 3.49563 | 3.49563 | OK |
| timeToFirstAnswerToken.total (ttfa) | 36.5465 | 36.5465 | OK |
| endToEndResponseTime.total (e2e) | 44.8092 | 44.8092 | OK |
| endToEndResponseTime.reasoning (reasoning_s) | 33.0509 | 33.0509 | OK |
| intelligenceIndexOutputTokensPerTask.output | 71127.6 | 71127.6 | OK |


### Chart fields the library silently drops

Raw chart keys never surfaced (union across the 3 picks):

`briefcaseTotalCost`, `canonicalIntelligenceIndexTokenCount`, `chartHighlighted`,
**`enterpriseOpsGym`**, `hostModelCount`, `id`, `intelligenceIndexCost`
(aggregate $ over all runs, e.g. 8708.19 for opus-5-5), `intelligenceIndexEvaluations`
(per-eval `score`/`outputTokensPerTask`/`costPerTask`/`timePerTask` — richer than the
`per_eval_cost` the library keeps), `intelligenceIndexTimePerTask`, `microevalsEnabled`,
`outputSpeedVariance`, `performanceByPromptType`, `performanceDataSource`,
`pricePer1k1mpImages`, `reasoningTokens`, `timeToFirstChunkVariance`.

> **`enterpriseOpsGym` is the one substantive drop:** it is a real per-benchmark score
> present in the chart payload (10/27 records non-null, e.g. `glm-5-3` = 0.3644,
> `qwen3-8-max` = 0.4763) and it has a `Benchmark` entry in `catalog.py`
> (`enterpriseOpsGym`, slug `enterprise-ops-gym-aa`) — but `_CHART_EVAL_KEYS` in
> `normalize.py` does not list it, so it is never read. Its companion
> `enterpriseOpsGymSuccessRateByDomain` is likewise never read.

### Cross-source observation (not a parser bug)

The **same model** disagrees between the two raw sources for TTFT:
`claude-opus-5-5` reports `medianTimeToFirstTokenSeconds = 650.105` on the leaderboard
but `timescaleData.medianTimeToFirstChunk = 679.238` on the model page. The library
faithfully reproduces each source (verified identical on both), but callers that mix
`aa_leaderboard` and `aa_model` numbers for the same model will see two different values.

---

## Surface 3 — Providers

### 3a. Providers board — 20 rows of `/leaderboards/providers`

Independent extraction of the 1201-row `rows` array (`host`/`model`/`features`/`pricing`);
library path `aa_mcp.loaders.provider_board()`.

**Mismatch list:** none. All 20 rows × 19 fields matched exactly. (The board carries no
`intelligenceIndexCostPerTask`, no `cacheHitDiscountPercent`, and no precision tag, so
`cost_per_task`, `cache_hit_discount` and `precision` are `None` on **both** sides —
faithful.)

Full per-item table: see “Appendix A”.

### 3b. Per-model endpoints (`/models/<slug>/providers`, `hostModels`)

Sources: the `providers_model.rsc` fixture (`glm-4-5v`, 1 endpoint — **no cost key**),
plus two **live** payloads fetched by the verifier (claude-opus-5-5 ×4 endpoints,
claude-opus-5 ×3 endpoints). Library path `aa_mcp.loaders.provider_endpoints(slug)`.

**Mismatch list — 7 mismatches, all the same bug:**

| source | host | field | raw | library | verdict |
|---|---|---|---|---|---|
| claude-opus-5-5 (live) | Anthropic | `cost_per_task` | 5.98201 | None | **MISMATCH** |
| claude-opus-5-5 (live) | Amazon Bedrock | `cost_per_task` | 5.98201 | None | **MISMATCH** |
| claude-opus-5-5 (live) | Google | `cost_per_task` | 11.6277 | None | **MISMATCH** |
| claude-opus-5-5 (live) | Microsoft Azure | `cost_per_task` | 6.69606 | None | **MISMATCH** |
| claude-opus-5 (live) | Amazon Bedrock | `cost_per_task` | 5.8584 | None | **MISMATCH** |
| claude-opus-5 (live) | Anthropic | `cost_per_task` | 5.8584 | None | **MISMATCH** |
| claude-opus-5 (live) | Google | `cost_per_task` | 9.37958 | None | **MISMATCH** |

**Root cause (evidence, not fixed):** in the live payload the value is flat:

```json
"intelligenceIndexCostPerTask": {"total": 5.982012019521066, "input": 3.598..., "cacheRead": 2.424..., ...}
```

but `src/aa_mcp/loaders.py::_cost_per_task` resolves only
`value["cost"]["total"]` / `value["cost"]["totalCost"]` for the dict case:

```python
if isinstance(value, dict):
    total = _dig(value, "cost", "total")
    if total is None:
        total = _dig(value, "cost", "totalCost")
    return _num(total)
```

`"intelligenceIndexCostPerTask":{"cost"` does **not** occur anywhere in the live
provider payloads (`grep`-verified), so the branch always returns `None`. The docstring
of `_cost_per_task` (“float or `{"cost":{"total":..}}`”) and
`docs/INTERFACES.md`’s providers-board row (“per-endpoint pricing/performance,
`intelligenceIndexCostPerTask`”) describe a shape that no longer matches the live
provider payload.

Consequence: `Endpoint.cost_per_task` is `None` for every live endpoint, which also
silently breaks the documented “cheapest `cost_per_task` first” ordering in
`parse_provider_endpoints`/`provider_endpoints` (it degenerates to price-in order).

All other endpoint fields matched: `host`, `host_slug`, `precision` (None — no
`fp4/fp8/...` token in the endpoint slug), `price_in`, `price_out`, `cache_read`,
`cache_write`, `cache_hit_discount`, `tps`, `ttft`, `e2e`, `function_calling`,
`json_mode`, `openai_compatible`, `context_tokens`, `intelligence`.

Full per-item table: see “Appendix B”.

### Provider fields the library drops

- **Board rows:** `id`, `hostApiId`, `footnotes`, `host.custom_url`s/logo/color, the whole
  `model.*` benchmark block (24 keys: `intelligenceIndex*`, `omniscience*`, `gpqa`, `hle`,
  `scicode`, `tau2`, `tauBanking`, `terminalBench21/40`, `terminalbenchHard`,
  `livecodebench`, `aime25`, `critpt`, `mmmuPro`, `apexAgents`, `itbenchSre`, `lcr`,
  `ifbench`, `gdpvalNormalized`, `harveyLab`, `automationBench`, `creator`, `sizeClass`,
  `isOpenWeights`, `deprecated`, `reasoningModel`), `pricing.priceClass`/blended fields/
  `cacheHitRate`, and all `performance` percentiles/quartiles plus
  `medianTimeToFirstAnswerTokenSeconds`/`medianReasoningTimeSeconds`.
  (`Endpoint` is intentionally a thin record, but the benchmark block — 24 fields,
  including `intelligenceIndex` — is a large silent drop for callers wanting board-level
  eval data.)
- **`hostModels` endpoints:** `id`, the whole `pricing.price1mBlended*`/`cacheHitRate`
  block, `performance.byPromptType`, all percentiles/quartiles, `intelligenceIndex*`
  on the performance block.

---

## Surface 4 — Derived rankings & media cross-check

### Intelligence sort order

- **The library preserves the raw payload order** (`loaders.leaderboard()` order == the
  raw metrics-array order, exactly): `True`.
- **The raw payload is NOT sorted by intelligence**: `False` (it is some other/curated
  order), so “library intelligence order == raw payload order” is **no** — the raw order
  is not an intelligence ranking at all.
- **`select.sort_models(models, 'intelligence')` is correct**: its non-null prefix is
  byte-for-byte identical to a fresh descending sort of the raw `intelligenceIndex`
  values (690 present, 10 `None`, `None` sorted last). Top-3 = `claude-opus-5-5`,
  `claude-sonnet-5-5`, `claude-opus-5-5-xhigh`; worst-first (`desc=False`) top-3 =
  `k2-horizon-0-9b`, `gemma-3-12b`, `nvidia-nemotron-3-nano-4b`. No rank error found.

### `media('text_to_image')[0]` vs the page's own JSON-LD FAQ

- Library row: `name = "GPT Image 2.5 Sunburst (max)"`, `elo = 1217.12`, `rank = 1`.
- Page JSON-LD (`Question` objects): *“GPT Image 2.5 Sunburst (max) has an Elo score of
  **1217** across 12,743 comparisons…”* and *“…currently leads … with an Elo score of
  **1217**.”* → **name matches exactly; Elo matches** (JSON-LD rounds to the integer 1217).
- The longest `values`+`formatted` array (102 items) is a **superset** of every other
  arena array on the page (all 19 filtered variants are subsets), so the
  “use the longest array” heuristic picks the true full board here. All 102 rows matched
  raw `values.name`/`values.elo` (0 mismatches).

---

## Surface 5 — Live site vs the 2026-10-14 fixtures

Re-fetched `https://artificialanalysis.ai/leaderboards/models` (RSC) during this run:

- **MD5 identical to the fixture:** `fadcd5ed63653985d5bcb4448741eea3`
  (fixture `/home/wavy/ai/aa-mcp/tests/fixtures/leaderboard.rsc` and the live download
  are the **same 1,187,412 bytes**). No drift.
- **Model count:** 700 on both sides.
- **5 spot values** (`intelligenceIndex`, both prices, `contextWindowTokens`, `hle`,
  `gpqa`) verified identical for `claude-opus-5-5`, `gemini-3-8-flash`,
  `deepseek-v4-1-flash`, `gpt-4-1`, `llama-4-maverick` — all `True`.

Live provider pages (`prov_claude-opus-5-5.rsc`, `prov_claude-opus-5.rsc`) were used for
Surface 3b and are byte-fresh (fetched today).

---

## Surface 6 — Claims vs delivery (things the library claims but does not deliver)

1. **`Endpoint.cost_per_task` on `/models/<slug>/providers`** — claimed by
   `docs/INTERFACES.md` (model-providers row: “`intelligenceIndexCostPerTask`”) and by
   `_cost_per_task`’s docstring; delivered as `None` for every live endpoint because the
   live shape is flat `{"total": ...}` (see Surface 3b). **Bug.**
2. **`release_date` on the leaderboard surface** — `Model.release_date` is a documented
   field and `aa_leaderboard` renders a Released column, but `from_leaderboard` reads a
   `releaseDate` key that the metrics array never has → **always `None` (0/700)**, even
   though the *same* `/leaderboards/models` payload contains a 506-row
   `{name,creator,deprecated,slug,releaseDate}` array that could be joined by slug.
3. **`cost_per_task` / `speed.*` coverage on the leaderboard** — present on only
   **186/700** and **367/700** rows respectively; any filter that requires them
   (`max_cost_per_task`, `min_speed`, `max_ttft`) silently discards the remaining rows.
   Faithful to the payload, but the docs’ “50 metrics” framing overstates density.
4. **`enterpriseOpsGym` (+ `...SuccessRateByDomain`)** — `catalog.BENCHMARKS` advertises
   them and the chart payload carries real values (10/27 non-null), but
   `normalize._CHART_EVAL_KEYS` never reads them → a catalogued benchmark that can never
   produce a value from any surface. **Coverage claim not delivered.**
5. **`openness` index from chart records** — `from_legacy` reads
   `openness.opennessIndex`, but `from_chart` does **not** read `openness`; on the chart
   payload the key exists but is `null` in this capture, so no loss *today*, but the
   chart path will drop it if AA fills it.
6. **Doc drift, minor:** `docs/INTERFACES.md` says the leaderboard array is “700 model
   variants x 50 metrics”; rows are heterogeneous (36–51 keys, union 51). Also the
   provider-endpoint `intelligenceIndexCostPerTask` shape in the docs (implicitly the
   chart `{"cost":{...}}` shape) no longer matches the live flat shape.
7. **Not a claim, but worth knowing:** `providers_model.rsc` (the only offline provider
   fixture) has a **single** endpoint for `glm-4-5v` and **no**
   `intelligenceIndexCostPerTask`, so the offline suite cannot detect the cost bug.

---

## Confidence

### Proved (executed in this session, reproducible)
- Leaderboard: 8 variants × 35 fields, exact float equality — **0 mismatches**
  (`/tmp/fid/cmp_lb.py`).
- Chart: 3 models × ~40 fields incl. `capabilities.*`, briefcase Elo, cost breakdown,
  per-eval costs, effort, params, license, modalities, knowledge cutoff, speed —
  **0 mismatches** (`/tmp/fid/cmp_chart.py`).
- Providers board: 20 rows × 19 fields — **0 mismatches** (`/tmp/fid/cmp_prov.py`).
- Provider endpoints: `glm-4-5v` fixture (1) + 2 live pages (7) × 19 fields —
  **7 mismatches, all `cost_per_task`** (same flat-dict bug).
- Rankings: library preserves raw order; `select.sort_models('intelligence')` matches a
  fresh raw descending sort; 10 null-intelligence rows sorted last.
- Media: `media('text_to_image')` top row == page JSON-LD FAQ (name exact, Elo rounding
  only); longest-array selection is the superset; 102/102 rows match raw.
- Drift: live leaderboard MD5 == fixture MD5; 700 rows; 5/5 spot values identical.
- Dropped-field lists are derived from set differences over the actual raw records
  (leaderboard 700 rows; chart 92–94 keys; board 1201 rows).

### Unchecked / out of scope (do not over-read this report)
- **JSON-API backend** (`api.py`, `api_models_free.json`, `AA_SOURCE=api`): not exercised.
- **Media boards other than `text_to_image`** (t2v, image/video editing, TTS, music) and
  the **agents** boards, **homepage** panels, **eval pages/catalog**, **legacy model
  pages**, **sitemap**: not compared here (the task scoped leaderboard + 3 chart records +
  providers + media t2i).
- **Derived aggregates** `value_rank`/`pareto`/`search`/`resolve`: not independently
  verified beyond `sort_models`.
- The **7 endpoint mismatches** are attributed to `_cost_per_task` by static reading plus
  the shape mismatch; the fix was not applied (no `src/` edits allowed).
- “Stable over time”: only **one** live re-fetch of the leaderboard was compared; AA
  redeploys often, so this proves equality *now*, not permanently.

---

## Reproduction — exact commands

All comparisons run with the repo venv (`.venv/bin/python`) and the fixture cache:

```bash
mkdir -p /tmp/fid/cache /tmp/fid/live
cp tests/fixtures/leaderboard.rsc        /tmp/fid/cache/leaderboard.rsc
cp tests/fixtures/providers_board.rsc    /tmp/fid/cache/providers_board.rsc
cp tests/fixtures/providers_model.rsc    /tmp/fid/cache/providers_glm-4-5v.rsc
cp tests/fixtures/model_page_chart.rsc   /tmp/fid/cache/model_claude-opus-5-5.rsc
cp tests/fixtures/model_page_chart.rsc   /tmp/fid/cache/model_mimo-v2-6-pro.rsc
cp tests/fixtures/model_page_chart.rsc   /tmp/fid/cache/model_glm-5-3.rsc
cp tests/fixtures/media_t2i.rsc          /tmp/fid/cache/media_text_to_image.rsc

# live payloads (verifier-fetched)
curl -sS -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" \
  -o /tmp/fid/live/leaderboard.rsc https://artificialanalysis.ai/leaderboards/models
curl -sS -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" \
  -o /tmp/fid/live/prov_claude-opus-5-5.rsc https://artificialanalysis.ai/models/claude-opus-5-5/providers
curl -sS -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" \
  -o /tmp/fid/live/prov_claude-opus-5.rsc  https://artificialanalysis.ai/models/claude-opus-5/providers
cp /tmp/fid/live/prov_claude-opus-5-5.rsc /tmp/fid/cache/providers_claude-opus-5-5.rsc
cp /tmp/fid/live/prov_claude-opus-5.rsc  /tmp/fid/cache/providers_claude-opus-5.rsc

# harnesses (each sets AA_OFFLINE=1, AA_CACHE_DIR=/tmp/fid/cache, AA_SOURCE=rsc)
PYTHONPATH=src .venv/bin/python /tmp/fid/cmp_lb.py         # leaderboard 8x35
PYTHONPATH=src .venv/bin/python /tmp/fid/cmp_chart.py      # chart 3 models
PYTHONPATH=src .venv/bin/python /tmp/fid/cmp_prov.py       # board 20 rows + endpoints
PYTHONPATH=src .venv/bin/python /tmp/fid/cmp_rank_media.py # sort order + media JSON-LD
PYTHONPATH=src .venv/bin/python /tmp/fid/gen_tables2.py    # appendix tables + rank/media facts
PYTHONPATH=src .venv/bin/python /tmp/fid/final_facts.py    # drift md5 + spot values
```

`/tmp/fid/raw.py` is the independent extractor (no `aa_mcp` import). The libraries
themselves were reached only through `aa_mcp.loaders.leaderboard()`,
`aa_mcp.loaders.model(slug)`, `aa_mcp.loaders.provider_board()`,
`aa_mcp.loaders.provider_endpoints(slug)` and `aa_mcp.loaders.media(board)`.

Note: the harnesses deliberately run with `AA_OFFLINE=1` because the repo owner was
mid-fix of the `SOURCE_URLS` relative-path → `fetch.get` URL bug during this run; offline
mode exercises the identical parse/normalize code path without the (unrelated) URL issue.

---

## Appendix A — providers board, 20 rows × 19 fields

| row | model_slug | field | raw | library | verdict |
|---|---|---|---|---|---|
| 0 | glm-4-5v | model_slug | glm-4-5v | glm-4-5v | OK |
| 0 | glm-4-5v | model_name | GLM-4.5V (non-reasoning) | GLM-4.5V (non-reasoning) | OK |
| 0 | glm-4-5v | host | Novita | Novita | OK |
| 0 | glm-4-5v | host_slug | novita | novita | OK |
| 0 | glm-4-5v | precision | None | None | OK |
| 0 | glm-4-5v | price_in | 0.6 | 0.6 | OK |
| 0 | glm-4-5v | price_out | 1.8 | 1.8 | OK |
| 0 | glm-4-5v | cache_read | 0.11 | 0.11 | OK |
| 0 | glm-4-5v | cache_write | None | None | OK |
| 0 | glm-4-5v | cache_hit_discount | None | None | OK |
| 0 | glm-4-5v | cost_per_task | None | None | OK |
| 0 | glm-4-5v | tps | 49.5248 | 49.5248 | OK |
| 0 | glm-4-5v | ttft | 2.76025 | 2.76025 | OK |
| 0 | glm-4-5v | e2e | 12.8562 | 12.8562 | OK |
| 0 | glm-4-5v | function_calling | True | True | OK |
| 0 | glm-4-5v | json_mode | True | True | OK |
| 0 | glm-4-5v | openai_compatible | True | True | OK |
| 0 | glm-4-5v | context_tokens | 65536 | 65536 | OK |
| 0 | glm-4-5v | intelligence | 6.6967 | 6.6967 | OK |
| 1 | gemini-3-5-flash | model_slug | gemini-3-5-flash | gemini-3-5-flash | OK |
| 1 | gemini-3-5-flash | model_name | Gemini 3.5 Flash (high) AI Studio | Gemini 3.5 Flash (high) AI Studio | OK |
| 1 | gemini-3-5-flash | host | Google | Google | OK |
| 1 | gemini-3-5-flash | host_slug | google | google | OK |
| 1 | gemini-3-5-flash | precision | None | None | OK |
| 1 | gemini-3-5-flash | price_in | 1.5 | 1.5 | OK |
| 1 | gemini-3-5-flash | price_out | 9 | 9 | OK |
| 1 | gemini-3-5-flash | cache_read | 0.15 | 0.15 | OK |
| 1 | gemini-3-5-flash | cache_write | None | None | OK |
| 1 | gemini-3-5-flash | cache_hit_discount | None | None | OK |
| 1 | gemini-3-5-flash | cost_per_task | None | None | OK |
| 1 | gemini-3-5-flash | tps | 189.373 | 189.373 | OK |
| 1 | gemini-3-5-flash | ttft | 17.3002 | 17.3002 | OK |
| 1 | gemini-3-5-flash | e2e | 19.9405 | 19.9405 | OK |
| 1 | gemini-3-5-flash | function_calling | True | True | OK |
| 1 | gemini-3-5-flash | json_mode | True | True | OK |
| 1 | gemini-3-5-flash | openai_compatible | True | True | OK |
| 1 | gemini-3-5-flash | context_tokens | 1000000 | 1000000 | OK |
| 1 | gemini-3-5-flash | intelligence | 32.5983 | 32.5983 | OK |
| 2 | mimo-v2-5-pro | model_slug | mimo-v2-5-pro | mimo-v2-5-pro | OK |
| 2 | mimo-v2-5-pro | model_name | MiMo-V2.5-Pro | MiMo-V2.5-Pro | OK |
| 2 | mimo-v2-5-pro | host | Novita | Novita | OK |
| 2 | mimo-v2-5-pro | host_slug | novita | novita | OK |
| 2 | mimo-v2-5-pro | precision | None | None | OK |
| 2 | mimo-v2-5-pro | price_in | 0.522 | 0.522 | OK |
| 2 | mimo-v2-5-pro | price_out | 1.044 | 1.044 | OK |
| 2 | mimo-v2-5-pro | cache_read | 0.0043 | 0.0043 | OK |
| 2 | mimo-v2-5-pro | cache_write | None | None | OK |
| 2 | mimo-v2-5-pro | cache_hit_discount | None | None | OK |
| 2 | mimo-v2-5-pro | cost_per_task | None | None | OK |
| 2 | mimo-v2-5-pro | tps | 32.2264 | 32.2264 | OK |
| 2 | mimo-v2-5-pro | ttft | 2.23688 | 2.23688 | OK |
| 2 | mimo-v2-5-pro | e2e | 79.8129 | 79.8129 | OK |
| 2 | mimo-v2-5-pro | function_calling | True | True | OK |
| 2 | mimo-v2-5-pro | json_mode | True | True | OK |
| 2 | mimo-v2-5-pro | openai_compatible | True | True | OK |
| 2 | mimo-v2-5-pro | context_tokens | 1048576 | 1048576 | OK |
| 2 | mimo-v2-5-pro | intelligence | 25.9869 | 25.9869 | OK |
| 3 | mimo-v2-5-pro | model_slug | mimo-v2-5-pro | mimo-v2-5-pro | OK |
| 3 | mimo-v2-5-pro | model_name | MiMo-V2.5-Pro | MiMo-V2.5-Pro | OK |
| 3 | mimo-v2-5-pro | host | GMI | GMI | OK |
| 3 | mimo-v2-5-pro | host_slug | gmi | gmi | OK |
| 3 | mimo-v2-5-pro | precision | None | None | OK |
| 3 | mimo-v2-5-pro | price_in | 0.348 | 0.348 | OK |
| 3 | mimo-v2-5-pro | price_out | 0.696 | 0.696 | OK |
| 3 | mimo-v2-5-pro | cache_read | 0.002 | 0.002 | OK |
| 3 | mimo-v2-5-pro | cache_write | None | None | OK |
| 3 | mimo-v2-5-pro | cache_hit_discount | None | None | OK |
| 3 | mimo-v2-5-pro | cost_per_task | None | None | OK |
| 3 | mimo-v2-5-pro | tps | None | None | OK |
| 3 | mimo-v2-5-pro | ttft | None | None | OK |
| 3 | mimo-v2-5-pro | e2e | None | None | OK |
| 3 | mimo-v2-5-pro | function_calling | True | True | OK |
| 3 | mimo-v2-5-pro | json_mode | True | True | OK |
| 3 | mimo-v2-5-pro | openai_compatible | True | True | OK |
| 3 | mimo-v2-5-pro | context_tokens | 1050000 | 1050000 | OK |
| 3 | mimo-v2-5-pro | intelligence | 25.9869 | 25.9869 | OK |
| 4 | mimo-v2-5-pro | model_slug | mimo-v2-5-pro | mimo-v2-5-pro | OK |
| 4 | mimo-v2-5-pro | model_name | MiMo-V2.5-Pro | MiMo-V2.5-Pro | OK |
| 4 | mimo-v2-5-pro | host | DeepInfra | DeepInfra | OK |
| 4 | mimo-v2-5-pro | host_slug | deepinfra | deepinfra | OK |
| 4 | mimo-v2-5-pro | precision | None | None | OK |
| 4 | mimo-v2-5-pro | price_in | 0.39 | 0.39 | OK |
| 4 | mimo-v2-5-pro | price_out | 1.17 | 1.17 | OK |
| 4 | mimo-v2-5-pro | cache_read | 0.078 | 0.078 | OK |
| 4 | mimo-v2-5-pro | cache_write | None | None | OK |
| 4 | mimo-v2-5-pro | cache_hit_discount | None | None | OK |
| 4 | mimo-v2-5-pro | cost_per_task | None | None | OK |
| 4 | mimo-v2-5-pro | tps | 34.3543 | 34.3543 | OK |
| 4 | mimo-v2-5-pro | ttft | 1.31681 | 1.31681 | OK |
| 4 | mimo-v2-5-pro | e2e | 74.088 | 74.088 | OK |
| 4 | mimo-v2-5-pro | function_calling | True | True | OK |
| 4 | mimo-v2-5-pro | json_mode | True | True | OK |
| 4 | mimo-v2-5-pro | openai_compatible | True | True | OK |
| 4 | mimo-v2-5-pro | context_tokens | 65536 | 65536 | OK |
| 4 | mimo-v2-5-pro | intelligence | 25.9869 | 25.9869 | OK |
| 5 | mimo-v2-5-pro | model_slug | mimo-v2-5-pro | mimo-v2-5-pro | OK |
| 5 | mimo-v2-5-pro | model_name | MiMo-V2.5-Pro | MiMo-V2.5-Pro | OK |
| 5 | mimo-v2-5-pro | host | Zyphra | Zyphra | OK |
| 5 | mimo-v2-5-pro | host_slug | zyphra | zyphra | OK |
| 5 | mimo-v2-5-pro | precision | None | None | OK |
| 5 | mimo-v2-5-pro | price_in | 1 | 1 | OK |
| 5 | mimo-v2-5-pro | price_out | 3 | 3 | OK |
| 5 | mimo-v2-5-pro | cache_read | 0.02 | 0.02 | OK |
| 5 | mimo-v2-5-pro | cache_write | None | None | OK |
| 5 | mimo-v2-5-pro | cache_hit_discount | None | None | OK |
| 5 | mimo-v2-5-pro | cost_per_task | None | None | OK |
| 5 | mimo-v2-5-pro | tps | 51.8074 | 51.8074 | OK |
| 5 | mimo-v2-5-pro | ttft | 1.12791 | 1.12791 | OK |
| 5 | mimo-v2-5-pro | e2e | 49.3836 | 49.3836 | OK |
| 5 | mimo-v2-5-pro | function_calling | True | True | OK |
| 5 | mimo-v2-5-pro | json_mode | True | True | OK |
| 5 | mimo-v2-5-pro | openai_compatible | True | True | OK |
| 5 | mimo-v2-5-pro | context_tokens | 1048576 | 1048576 | OK |
| 5 | mimo-v2-5-pro | intelligence | 25.9869 | 25.9869 | OK |
| 6 | mimo-v2-5-pro | model_slug | mimo-v2-5-pro | mimo-v2-5-pro | OK |
| 6 | mimo-v2-5-pro | model_name | MiMo-V2.5-Pro | MiMo-V2.5-Pro | OK |
| 6 | mimo-v2-5-pro | host | Xiaomi | Xiaomi | OK |
| 6 | mimo-v2-5-pro | host_slug | xiaomi | xiaomi | OK |
| 6 | mimo-v2-5-pro | precision | None | None | OK |
| 6 | mimo-v2-5-pro | price_in | 0.435 | 0.435 | OK |
| 6 | mimo-v2-5-pro | price_out | 0.87 | 0.87 | OK |
| 6 | mimo-v2-5-pro | cache_read | 0.0036 | 0.0036 | OK |
| 6 | mimo-v2-5-pro | cache_write | None | None | OK |
| 6 | mimo-v2-5-pro | cache_hit_discount | None | None | OK |
| 6 | mimo-v2-5-pro | cost_per_task | None | None | OK |
| 6 | mimo-v2-5-pro | tps | 38.6179 | 38.6179 | OK |
| 6 | mimo-v2-5-pro | ttft | 2.30908 | 2.30908 | OK |
| 6 | mimo-v2-5-pro | e2e | 67.046 | 67.046 | OK |
| 6 | mimo-v2-5-pro | function_calling | True | True | OK |
| 6 | mimo-v2-5-pro | json_mode | True | True | OK |
| 6 | mimo-v2-5-pro | openai_compatible | True | True | OK |
| 6 | mimo-v2-5-pro | context_tokens | 1000000 | 1000000 | OK |
| 6 | mimo-v2-5-pro | intelligence | 25.9869 | 25.9869 | OK |
| 7 | gpt-6-sol-low | model_slug | gpt-6-sol-low | gpt-6-sol-low | OK |
| 7 | gpt-6-sol-low | model_name | GPT-6 Sol (low) | GPT-6 Sol (low) | OK |
| 7 | gpt-6-sol-low | host | OpenAI | OpenAI | OK |
| 7 | gpt-6-sol-low | host_slug | openai | openai | OK |
| 7 | gpt-6-sol-low | precision | None | None | OK |
| 7 | gpt-6-sol-low | price_in | 2 | 2 | OK |
| 7 | gpt-6-sol-low | price_out | 10 | 10 | OK |
| 7 | gpt-6-sol-low | cache_read | 0.2 | 0.2 | OK |
| 7 | gpt-6-sol-low | cache_write | 2.5 | 2.5 | OK |
| 7 | gpt-6-sol-low | cache_hit_discount | None | None | OK |
| 7 | gpt-6-sol-low | cost_per_task | None | None | OK |
| 7 | gpt-6-sol-low | tps | 97.2059 | 97.2059 | OK |
| 7 | gpt-6-sol-low | ttft | 1.94198 | 1.94198 | OK |
| 7 | gpt-6-sol-low | e2e | 7.0857 | 7.0857 | OK |
| 7 | gpt-6-sol-low | function_calling | True | True | OK |
| 7 | gpt-6-sol-low | json_mode | True | True | OK |
| 7 | gpt-6-sol-low | openai_compatible | True | True | OK |
| 7 | gpt-6-sol-low | context_tokens | 1050000 | 1050000 | OK |
| 7 | gpt-6-sol-low | intelligence | 34.1549 | 34.1549 | OK |
| 8 | mercury-2 | model_slug | mercury-2 | mercury-2 | OK |
| 8 | mercury-2 | model_name | Mercury 2 | Mercury 2 | OK |
| 8 | mercury-2 | host | Inception | Inception | OK |
| 8 | mercury-2 | host_slug | inception | inception | OK |
| 8 | mercury-2 | precision | None | None | OK |
| 8 | mercury-2 | price_in | 0.25 | 0.25 | OK |
| 8 | mercury-2 | price_out | 0.75 | 0.75 | OK |
| 8 | mercury-2 | cache_read | 0.025 | 0.025 | OK |
| 8 | mercury-2 | cache_write | None | None | OK |
| 8 | mercury-2 | cache_hit_discount | None | None | OK |
| 8 | mercury-2 | cost_per_task | None | None | OK |
| 8 | mercury-2 | tps | 535.041 | 535.041 | OK |
| 8 | mercury-2 | ttft | 7.61017 | 7.61017 | OK |
| 8 | mercury-2 | e2e | 8.54467 | 8.54467 | OK |
| 8 | mercury-2 | function_calling | True | True | OK |
| 8 | mercury-2 | json_mode | True | True | OK |
| 8 | mercury-2 | openai_compatible | True | True | OK |
| 8 | mercury-2 | context_tokens | 128000 | 128000 | OK |
| 8 | mercury-2 | intelligence | 13.7691 | 13.7691 | OK |
| 9 | qwen3-5-omni-plus | model_slug | qwen3-5-omni-plus | qwen3-5-omni-plus | OK |
| 9 | qwen3-5-omni-plus | model_name | Qwen3.5 Omni Plus | Qwen3.5 Omni Plus | OK |
| 9 | qwen3-5-omni-plus | host | Alibaba Cloud | Alibaba Cloud | OK |
| 9 | qwen3-5-omni-plus | host_slug | alibaba_cloud | alibaba_cloud | OK |
| 9 | qwen3-5-omni-plus | precision | None | None | OK |
| 9 | qwen3-5-omni-plus | price_in | 0.4 | 0.4 | OK |
| 9 | qwen3-5-omni-plus | price_out | 4.8 | 4.8 | OK |
| 9 | qwen3-5-omni-plus | cache_read | None | None | OK |
| 9 | qwen3-5-omni-plus | cache_write | None | None | OK |
| 9 | qwen3-5-omni-plus | cache_hit_discount | None | None | OK |
| 9 | qwen3-5-omni-plus | cost_per_task | None | None | OK |
| 9 | qwen3-5-omni-plus | tps | 89.2043 | 89.2043 | OK |
| 9 | qwen3-5-omni-plus | ttft | 2.10728 | 2.10728 | OK |
| 9 | qwen3-5-omni-plus | e2e | 7.71239 | 7.71239 | OK |
| 9 | qwen3-5-omni-plus | function_calling | True | True | OK |
| 9 | qwen3-5-omni-plus | json_mode | True | True | OK |
| 9 | qwen3-5-omni-plus | openai_compatible | True | True | OK |
| 9 | qwen3-5-omni-plus | context_tokens | 256000 | 256000 | OK |
| 9 | qwen3-5-omni-plus | intelligence | 20.384 | 20.384 | OK |
| 10 | nova-2-0-omni-reasoning-medium | model_slug | nova-2-0-omni-reasoning-medium | nova-2-0-omni-reasoning-medium | OK |
| 10 | nova-2-0-omni-reasoning-medium | model_name | Nova 2.0 Omni (medium) | Nova 2.0 Omni (medium) | OK |
| 10 | nova-2-0-omni-reasoning-medium | host | Amazon Bedrock | Amazon Bedrock | OK |
| 10 | nova-2-0-omni-reasoning-medium | host_slug | amazon_bedrock | amazon_bedrock | OK |
| 10 | nova-2-0-omni-reasoning-medium | precision | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | price_in | 0.3 | 0.3 | OK |
| 10 | nova-2-0-omni-reasoning-medium | price_out | 2.5 | 2.5 | OK |
| 10 | nova-2-0-omni-reasoning-medium | cache_read | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | cache_write | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | cache_hit_discount | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | cost_per_task | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | tps | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | ttft | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | e2e | None | None | OK |
| 10 | nova-2-0-omni-reasoning-medium | function_calling | True | True | OK |
| 10 | nova-2-0-omni-reasoning-medium | json_mode | False | False | OK |
| 10 | nova-2-0-omni-reasoning-medium | openai_compatible | False | False | OK |
| 10 | nova-2-0-omni-reasoning-medium | context_tokens | 1000000 | 1000000 | OK |
| 10 | nova-2-0-omni-reasoning-medium | intelligence | 13.6465 | 13.6465 | OK |
| 11 | nova-2-0-omni-reasoning-medium | model_slug | nova-2-0-omni-reasoning-medium | nova-2-0-omni-reasoning-medium | OK |
| 11 | nova-2-0-omni-reasoning-medium | model_name | Nova 2.0 Omni (medium) | Nova 2.0 Omni (medium) | OK |
| 11 | nova-2-0-omni-reasoning-medium | host | Amazon Bedrock | Amazon Bedrock | OK |
| 11 | nova-2-0-omni-reasoning-medium | host_slug | amazon_bedrock | amazon_bedrock | OK |
| 11 | nova-2-0-omni-reasoning-medium | precision | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | price_in | 0.3 | 0.3 | OK |
| 11 | nova-2-0-omni-reasoning-medium | price_out | 2.5 | 2.5 | OK |
| 11 | nova-2-0-omni-reasoning-medium | cache_read | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | cache_write | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | cache_hit_discount | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | cost_per_task | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | tps | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | ttft | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | e2e | None | None | OK |
| 11 | nova-2-0-omni-reasoning-medium | function_calling | True | True | OK |
| 11 | nova-2-0-omni-reasoning-medium | json_mode | False | False | OK |
| 11 | nova-2-0-omni-reasoning-medium | openai_compatible | False | False | OK |
| 11 | nova-2-0-omni-reasoning-medium | context_tokens | 1000000 | 1000000 | OK |
| 11 | nova-2-0-omni-reasoning-medium | intelligence | 13.6465 | 13.6465 | OK |
| 12 | gpt-5-2-codex | model_slug | gpt-5-2-codex | gpt-5-2-codex | OK |
| 12 | gpt-5-2-codex | model_name | GPT-5.2 Codex (xhigh) | GPT-5.2 Codex (xhigh) | OK |
| 12 | gpt-5-2-codex | host | Microsoft Azure | Microsoft Azure | OK |
| 12 | gpt-5-2-codex | host_slug | azure | azure | OK |
| 12 | gpt-5-2-codex | precision | None | None | OK |
| 12 | gpt-5-2-codex | price_in | 1.75 | 1.75 | OK |
| 12 | gpt-5-2-codex | price_out | 14 | 14 | OK |
| 12 | gpt-5-2-codex | cache_read | 0.175 | 0.175 | OK |
| 12 | gpt-5-2-codex | cache_write | None | None | OK |
| 12 | gpt-5-2-codex | cache_hit_discount | None | None | OK |
| 12 | gpt-5-2-codex | cost_per_task | None | None | OK |
| 12 | gpt-5-2-codex | tps | 136.204 | 136.204 | OK |
| 12 | gpt-5-2-codex | ttft | 136.233 | 136.233 | OK |
| 12 | gpt-5-2-codex | e2e | 139.904 | 139.904 | OK |
| 12 | gpt-5-2-codex | function_calling | True | True | OK |
| 12 | gpt-5-2-codex | json_mode | True | True | OK |
| 12 | gpt-5-2-codex | openai_compatible | True | True | OK |
| 12 | gpt-5-2-codex | context_tokens | 400000 | 400000 | OK |
| 12 | gpt-5-2-codex | intelligence | 28.5017 | 28.5017 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | model_slug | qwen3-5-122b-a10b-non-reasoning | qwen3-5-122b-a10b-non-reasoning | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | model_name | Qwen3.5 122B A10B (non-reasoning) (FP4) | Qwen3.5 122B A10B (non-reasoning) (FP4) | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | host | DeepInfra | DeepInfra | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | host_slug | deepinfra | deepinfra | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | precision | None | None | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | price_in | 0.29 | 0.29 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | price_out | 2.4 | 2.4 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | cache_read | None | None | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | cache_write | None | None | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | cache_hit_discount | None | None | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | cost_per_task | None | None | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | tps | 41.4986 | 41.4986 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | ttft | 1.26887 | 1.26887 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | e2e | 13.3175 | 13.3175 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | function_calling | True | True | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | json_mode | True | True | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | openai_compatible | True | True | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | context_tokens | 262144 | 262144 | OK |
| 13 | qwen3-5-122b-a10b-non-reasoning | intelligence | 17.748 | 17.748 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | model_slug | qwen3-5-122b-a10b-non-reasoning | qwen3-5-122b-a10b-non-reasoning | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | model_name | Qwen3.5 122B A10B (non-reasoning) | Qwen3.5 122B A10B (non-reasoning) | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | host | Alibaba Cloud | Alibaba Cloud | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | host_slug | alibaba_cloud | alibaba_cloud | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | precision | None | None | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | price_in | 0.4 | 0.4 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | price_out | 3.2 | 3.2 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | cache_read | None | None | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | cache_write | None | None | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | cache_hit_discount | None | None | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | cost_per_task | None | None | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | tps | 142.186 | 142.186 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | ttft | 2.30438 | 2.30438 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | e2e | 5.82091 | 5.82091 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | function_calling | True | True | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | json_mode | True | True | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | openai_compatible | True | True | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | context_tokens | 262144 | 262144 | OK |
| 14 | qwen3-5-122b-a10b-non-reasoning | intelligence | 17.748 | 17.748 | OK |
| 15 | gemma-4-12b-non-reasoning | model_slug | gemma-4-12b-non-reasoning | gemma-4-12b-non-reasoning | OK |
| 15 | gemma-4-12b-non-reasoning | model_name | Gemma 4 12B (non-reasoning) | Gemma 4 12B (non-reasoning) | OK |
| 15 | gemma-4-12b-non-reasoning | host | SiliconFlow | SiliconFlow | OK |
| 15 | gemma-4-12b-non-reasoning | host_slug | siliconflow | siliconflow | OK |
| 15 | gemma-4-12b-non-reasoning | precision | None | None | OK |
| 15 | gemma-4-12b-non-reasoning | price_in | 0.1 | 0.1 | OK |
| 15 | gemma-4-12b-non-reasoning | price_out | 0.3 | 0.3 | OK |
| 15 | gemma-4-12b-non-reasoning | cache_read | None | None | OK |
| 15 | gemma-4-12b-non-reasoning | cache_write | None | None | OK |
| 15 | gemma-4-12b-non-reasoning | cache_hit_discount | None | None | OK |
| 15 | gemma-4-12b-non-reasoning | cost_per_task | None | None | OK |
| 15 | gemma-4-12b-non-reasoning | tps | 113.493 | 113.493 | OK |
| 15 | gemma-4-12b-non-reasoning | ttft | 2.51939 | 2.51939 | OK |
| 15 | gemma-4-12b-non-reasoning | e2e | 6.92496 | 6.92496 | OK |
| 15 | gemma-4-12b-non-reasoning | function_calling | True | True | OK |
| 15 | gemma-4-12b-non-reasoning | json_mode | True | True | OK |
| 15 | gemma-4-12b-non-reasoning | openai_compatible | True | True | OK |
| 15 | gemma-4-12b-non-reasoning | context_tokens | 262144 | 262144 | OK |
| 15 | gemma-4-12b-non-reasoning | intelligence | 9.37989 | 9.37989 | OK |
| 16 | gemini-3-5-flash-minimal | model_slug | gemini-3-5-flash-minimal | gemini-3-5-flash-minimal | OK |
| 16 | gemini-3-5-flash-minimal | model_name | Gemini 3.5 Flash (minimal) AI Studio | Gemini 3.5 Flash (minimal) AI Studio | OK |
| 16 | gemini-3-5-flash-minimal | host | Google | Google | OK |
| 16 | gemini-3-5-flash-minimal | host_slug | google | google | OK |
| 16 | gemini-3-5-flash-minimal | precision | None | None | OK |
| 16 | gemini-3-5-flash-minimal | price_in | 1.5 | 1.5 | OK |
| 16 | gemini-3-5-flash-minimal | price_out | 9 | 9 | OK |
| 16 | gemini-3-5-flash-minimal | cache_read | 0.15 | 0.15 | OK |
| 16 | gemini-3-5-flash-minimal | cache_write | None | None | OK |
| 16 | gemini-3-5-flash-minimal | cache_hit_discount | None | None | OK |
| 16 | gemini-3-5-flash-minimal | cost_per_task | None | None | OK |
| 16 | gemini-3-5-flash-minimal | tps | 181.349 | 181.349 | OK |
| 16 | gemini-3-5-flash-minimal | ttft | 0.793084 | 0.793084 | OK |
| 16 | gemini-3-5-flash-minimal | e2e | 3.55019 | 3.55019 | OK |
| 16 | gemini-3-5-flash-minimal | function_calling | True | True | OK |
| 16 | gemini-3-5-flash-minimal | json_mode | True | True | OK |
| 16 | gemini-3-5-flash-minimal | openai_compatible | True | True | OK |
| 16 | gemini-3-5-flash-minimal | context_tokens | 1000000 | 1000000 | OK |
| 16 | gemini-3-5-flash-minimal | intelligence | 23.8488 | 23.8488 | OK |
| 17 | gpt-35-turbo | model_slug | gpt-35-turbo | gpt-35-turbo | OK |
| 17 | gpt-35-turbo | model_name | GPT-3.5 Turbo | GPT-3.5 Turbo | OK |
| 17 | gpt-35-turbo | host | OpenAI | OpenAI | OK |
| 17 | gpt-35-turbo | host_slug | openai | openai | OK |
| 17 | gpt-35-turbo | precision | None | None | OK |
| 17 | gpt-35-turbo | price_in | 0.5 | 0.5 | OK |
| 17 | gpt-35-turbo | price_out | 1.5 | 1.5 | OK |
| 17 | gpt-35-turbo | cache_read | None | None | OK |
| 17 | gpt-35-turbo | cache_write | None | None | OK |
| 17 | gpt-35-turbo | cache_hit_discount | None | None | OK |
| 17 | gpt-35-turbo | cost_per_task | None | None | OK |
| 17 | gpt-35-turbo | tps | None | None | OK |
| 17 | gpt-35-turbo | ttft | None | None | OK |
| 17 | gpt-35-turbo | e2e | None | None | OK |
| 17 | gpt-35-turbo | function_calling | True | True | OK |
| 17 | gpt-35-turbo | json_mode | True | True | OK |
| 17 | gpt-35-turbo | openai_compatible | True | True | OK |
| 17 | gpt-35-turbo | context_tokens | 4096 | 4096 | OK |
| 17 | gpt-35-turbo | intelligence | 5.48558 | 5.48558 | OK |
| 18 | claude-sonnet-5-5-medium | model_slug | claude-sonnet-5-5-medium | claude-sonnet-5-5-medium | OK |
| 18 | claude-sonnet-5-5-medium | model_name | Claude Sonnet 5.5 (medium with fallback) | Claude Sonnet 5.5 (medium with fallback) | OK |
| 18 | claude-sonnet-5-5-medium | host | Anthropic | Anthropic | OK |
| 18 | claude-sonnet-5-5-medium | host_slug | anthropic | anthropic | OK |
| 18 | claude-sonnet-5-5-medium | precision | None | None | OK |
| 18 | claude-sonnet-5-5-medium | price_in | 2 | 2 | OK |
| 18 | claude-sonnet-5-5-medium | price_out | 10 | 10 | OK |
| 18 | claude-sonnet-5-5-medium | cache_read | 0.1 | 0.1 | OK |
| 18 | claude-sonnet-5-5-medium | cache_write | 2.5 | 2.5 | OK |
| 18 | claude-sonnet-5-5-medium | cache_hit_discount | None | None | OK |
| 18 | claude-sonnet-5-5-medium | cost_per_task | None | None | OK |
| 18 | claude-sonnet-5-5-medium | tps | 94.794 | 94.794 | OK |
| 18 | claude-sonnet-5-5-medium | ttft | 1.09993 | 1.09993 | OK |
| 18 | claude-sonnet-5-5-medium | e2e | 6.37453 | 6.37453 | OK |
| 18 | claude-sonnet-5-5-medium | function_calling | True | True | OK |
| 18 | claude-sonnet-5-5-medium | json_mode | False | False | OK |
| 18 | claude-sonnet-5-5-medium | openai_compatible | True | True | OK |
| 18 | claude-sonnet-5-5-medium | context_tokens | 1000000 | 1000000 | OK |
| 18 | claude-sonnet-5-5-medium | intelligence | 40.8387 | 40.8387 | OK |
| 19 | grok-4-20-0309 | model_slug | grok-4-20-0309 | grok-4-20-0309 | OK |
| 19 | grok-4-20-0309 | model_name | Grok 4.20 0309 | Grok 4.20 0309 | OK |
| 19 | grok-4-20-0309 | host | SpaceXAI | SpaceXAI | OK |
| 19 | grok-4-20-0309 | host_slug | xai | xai | OK |
| 19 | grok-4-20-0309 | precision | None | None | OK |
| 19 | grok-4-20-0309 | price_in | 2 | 2 | OK |
| 19 | grok-4-20-0309 | price_out | 6 | 6 | OK |
| 19 | grok-4-20-0309 | cache_read | 0.2 | 0.2 | OK |
| 19 | grok-4-20-0309 | cache_write | None | None | OK |
| 19 | grok-4-20-0309 | cache_hit_discount | None | None | OK |
| 19 | grok-4-20-0309 | cost_per_task | None | None | OK |
| 19 | grok-4-20-0309 | tps | None | None | OK |
| 19 | grok-4-20-0309 | ttft | None | None | OK |
| 19 | grok-4-20-0309 | e2e | None | None | OK |
| 19 | grok-4-20-0309 | function_calling | True | True | OK |
| 19 | grok-4-20-0309 | json_mode | True | True | OK |
| 19 | grok-4-20-0309 | openai_compatible | True | True | OK |
| 19 | grok-4-20-0309 | context_tokens | 2000000 | 2000000 | OK |
| 19 | grok-4-20-0309 | intelligence | 25.2163 | 25.2163 | OK |

BOARD mismatch rows: 0


## Appendix B — per-model endpoints, all compared fields

| source | idx | host | field | raw | library | verdict |
|---|---|---|---|---|---|---|
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | model_slug | glm-4-5v | glm-4-5v | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | model_name | glm-4-5v | glm-4-5v | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | host | Novita | Novita | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | host_slug | novita | novita | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | precision | None | None | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | price_in | 0.6 | 0.6 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | price_out | 1.8 | 1.8 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | cache_read | 0.11 | 0.11 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | cache_write | None | None | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | cache_hit_discount | 0.816667 | 0.816667 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | cost_per_task | None | None | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | tps | 46.3085 | 46.3085 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | ttft | 2.76025 | 2.76025 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | e2e | 13.5574 | 13.5574 | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | function_calling | True | True | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | json_mode | True | True | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | openai_compatible | None | None | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | context_tokens | None | None | OK |
| /models/glm-4-5v/providers (fixture providers_model.rsc) | 0 | Novita | intelligence | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | model_slug | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | model_name | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | host | Anthropic | Anthropic | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | host_slug | anthropic | anthropic | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | precision | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | price_in | 4 | 4 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | price_out | 20 | 20 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | cache_read | 0.2 | 0.2 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | cache_write | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | cache_hit_discount | 0.95 | 0.95 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | cost_per_task | 5.98201 | None | MISMATCH |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | tps | 95.4019 | 95.4019 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | ttft | 679.238 | 679.238 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | e2e | 684.479 | 684.479 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | function_calling | True | True | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | json_mode | False | False | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | openai_compatible | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | context_tokens | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 0 | Anthropic | intelligence | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | model_slug | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | model_name | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | host | Amazon Bedrock | Amazon Bedrock | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | host_slug | amazon_bedrock | amazon_bedrock | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | precision | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | price_in | 4 | 4 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | price_out | 20 | 20 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | cache_read | 0.2 | 0.2 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | cache_write | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | cache_hit_discount | 0.95 | 0.95 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | cost_per_task | 5.98201 | None | MISMATCH |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | tps | 77.0483 | 77.0483 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | ttft | 747.915 | 747.915 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | e2e | 754.404 | 754.404 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | function_calling | True | True | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | json_mode | False | False | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | openai_compatible | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | context_tokens | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 1 | Amazon Bedrock | intelligence | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | model_slug | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | model_name | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | host | Google | Google | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | host_slug | google | google | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | precision | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | price_in | 4 | 4 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | price_out | 20 | 20 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | cache_read | 0.2 | 0.2 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | cache_write | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | cache_hit_discount | 0.95 | 0.95 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | cost_per_task | 11.6277 | None | MISMATCH |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | tps | 97.3905 | 97.3905 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | ttft | 758.487 | 758.487 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | e2e | 763.621 | 763.621 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | function_calling | True | True | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | json_mode | False | False | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | openai_compatible | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | context_tokens | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 2 | Google | intelligence | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | model_slug | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | model_name | claude-opus-5-5 | claude-opus-5-5 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | host | Microsoft Azure | Microsoft Azure | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | host_slug | azure | azure | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | precision | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | price_in | 4 | 4 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | price_out | 20 | 20 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | cache_read | 0.2 | 0.2 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | cache_write | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | cache_hit_discount | 0.95 | 0.95 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | cost_per_task | 6.69606 | None | MISMATCH |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | tps | 97.2838 | 97.2838 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | ttft | 764.038 | 764.038 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | e2e | 769.178 | 769.178 | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | function_calling | True | True | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | json_mode | False | False | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | openai_compatible | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | context_tokens | None | None | OK |
| /models/claude-opus-5-5/providers (LIVE) | 3 | Microsoft Azure | intelligence | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | model_slug | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | model_name | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | host | Amazon Bedrock | Amazon Bedrock | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | host_slug | amazon_bedrock | amazon_bedrock | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | precision | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | price_in | 5 | 5 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | price_out | 25 | 25 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | cache_read | 0.5 | 0.5 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | cache_write | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | cache_hit_discount | 0.9 | 0.9 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | cost_per_task | 5.8584 | None | MISMATCH |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | tps | 52.8856 | 52.8856 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | ttft | 92.9383 | 92.9383 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | e2e | 102.393 | 102.393 | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | function_calling | True | True | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | json_mode | False | False | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | openai_compatible | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | context_tokens | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 0 | Amazon Bedrock | intelligence | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | model_slug | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | model_name | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | host | Anthropic | Anthropic | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | host_slug | anthropic | anthropic | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | precision | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | price_in | 5 | 5 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | price_out | 25 | 25 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | cache_read | 0.5 | 0.5 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | cache_write | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | cache_hit_discount | 0.9 | 0.9 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | cost_per_task | 5.8584 | None | MISMATCH |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | tps | 56.0901 | 56.0901 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | ttft | 99.4545 | 99.4545 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | e2e | 108.369 | 108.369 | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | function_calling | True | True | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | json_mode | False | False | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | openai_compatible | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | context_tokens | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 1 | Anthropic | intelligence | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | model_slug | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | model_name | claude-opus-5 | claude-opus-5 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | host | Google | Google | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | host_slug | google | google | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | precision | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | price_in | 5 | 5 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | price_out | 25 | 25 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | cache_read | 0.5 | 0.5 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | cache_write | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | cache_hit_discount | 0.9 | 0.9 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | cost_per_task | 9.37958 | None | MISMATCH |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | tps | 56.8067 | 56.8067 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | ttft | 84.8957 | 84.8957 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | e2e | 93.6975 | 93.6975 | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | function_calling | True | True | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | json_mode | False | False | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | openai_compatible | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | context_tokens | None | None | OK |
| /models/claude-opus-5/providers (LIVE) | 2 | Google | intelligence | None | None | OK |

ENDPOINT mismatch rows: 7

