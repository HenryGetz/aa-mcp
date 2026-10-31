# Live-site drift audit — artificialanalysis.ai vs `aa-mcp`

- **Audited head:** `c4360dc` — `fix: tolerate partially scored leaderboard payloads during AA index v5.0 rollout` (Henry Getz, 2026-10-31 15:43:26 -0500). Prior: `48cf09a`, `705947c`, `8ae2b0e`, `a012bfb`. Working tree clean.
  The owner's commit message matches the live state exactly (86 of 275 leaderboard rows scored, Intel v5.0 roll-out), which corroborates that this is the owner's current push. A sibling was still pulling during the audit; every finding below is against `c4360dc`.
- **Fetch window:** 2026-10-31, 15:58–16:12 local (UTC-5). All requests sent `RSC: 1` (raw Next.js flight rows).
- **Artifacts kept under `/tmp/ld/`** (re-fetchable with the stated URL):

| artifact | URL |
|---|---|
| `lb_models.rsc` | `/leaderboards/models` |
| `lb_providers.rsc` | `/leaderboards/providers` |
| `model_frontier.rsc` | `/models/gpt-6-astra-medium` |
| `model_open.rsc` | `/models/deepseek-v4-flash` |
| `model_deprecated.rsc` | `/models/gpt-4o` |
| `model_step5.rsc` | `/models/step-5` (rich-dataset seed; 719 records) |
| `evals.rsc` | `/evaluations` |
| `eval_gpqa.rsc` | `/evaluations/gpqa-diamond` |
| `eval_cyber.rsc` | `/evaluations/artificial-analysis-cyber-index` |
| `eval_briefcase.rsc` | `/evaluations/aa-briefcase` |
| `eval_gdpval.rsc` | `/evaluations/gdpval-aa` (added while pinning the silent-wrong value) |
| `cap_{finance-and-accounting,strategy-and-ops,legal,healthcare-and-medical,engineering,economics}.rsc` | `/models/capabilities/<slug>` — each answers **308 → `/indexes/<slug>`** |
| `multilingual.rsc` | `/models/multilingual` |
| `ag_coding.rsc`, `ag_chat.rsc`, `ag_search.rsc` | `/agents/{coding-agents,chatbots,search-api}` |
| `img_tt.rsc` | `/image/leaderboard/text-to-image` |
| `vid_ttv.rsc`, `vid_itv.rsc` | `/video/leaderboard/{text-to-video,image-to-video}` |
| `tts_models.rsc` | `/text-to-speech/models` |
| `stt_nonstream.rsc` | `/speech-to-text/non-streaming` |
| `s2s_arena.rsc` | `/speech-to-speech/arena` |
| `home.rsc` | `/` |
| `sitemap.xml` | `/sitemap.xml` (4,245 `<loc>`) |
| `microevals.rsc` | `/microevals` |
| `mobile.rsc` | `/hardware-inference-stack/mobile-phones` |
| `trends.rsc` | `/trends` |

Flight parsing note: rows are `<id>:<json>`; large arrays are shipped as `<id>:I<json>`, so a parser that only accepts `:

`[`/`{` after the id misses the rich dataset. The repo's `flight.py` already anchors on `[` anywhere and is unaffected.

---

## Per-surface diff

| # | Surface | Required keys (file:line) | Live keys / scale | Status | Evidence (raw) | MCP output |
|---|---|---|---|---|---|---|
| 1 | `/leaderboards/models` | `("slug","intelligenceIndex")` `loaders.py:526`; release join `("releaseDate","deprecated","creator")` `loaders.py:550`; flat eval keys `normalize.py:171,349` | 275-row array `slug,intelligenceIndex,name,shortName,deprecated,isReasoning,isOpenWeights,paramClass,priceClass,modelCreator*,contextWindowTokens,omniscience,scores,intelligenceIndexCostPerTask,price1m*,median*/percentile*`; sibling 518-row release index; 719-row release list; **86** non-null `intelligenceIndex`; **0** deprecated; **no flat eval keys** | **DRIFTED** | `"scores":{"aa-briefcase":1461.69,"gpqa-diamond":0.93939,"gdpval-aa-normalized":1498.47,"critpt-v2-hard":0.71,...}`; `"intelligenceIndex":59.4257...` | `# 3 of 86 scored (275 tracked) · Intel, active only` — Gemini 4 Carbon (High) 59.4, Claude Opus 5.5 58.4 |
| 2 | `/leaderboards/providers` | `("host","model","features","pricing")` `loaders.py:1321`; `_endpoint` `loaders.py:1231` | 509 rows, same five keys; `pricing{price1mInputTokens,price1mOutputTokens,cacheHitPrice,cacheWritePrice,priceClass}`, `performance{median*,percentile*,quartile*}`, `features{contextWindowTokens,functionCalling,jsonMode,openaiCompatible}` | **OK** (scale/docstring only) | first row: host Alibaba Cloud, `pricing.price1mInputTokens=0.4` | `# 4 of 509 endpoints · cheapest across all hosts` |
| 3 | `/models/gpt-6-astra-medium` | `_CHART_REQUIRED = ("chartDefaultSelected","releaseDate","suffix")` `loaders.py:527`; `initialModels` path `parse_chart` `loaders.py:880`; rich `_RICH_MIN=100` `loaders.py:608` | 29-row chart (all three required keys present); rich 719 via `/models/step-5`; `currentModel` absent (modern page) | **OK** (+ NEW fields) | chart keys include `healthbench=0.5822`, `healthbenchProfessional`, `code2videoElo=1426.78`, `critptAgenticHard=0.705`, `frontierCode20=0.4237`, `hleDiamond`, `gdpval=1583.69` | `aa_model` prints Intel 51.5, Omni 41.4, all six capability scores, GPQA 93.9%, HLE 52.7%, Briefcase Elo 1462 |
| 4 | `/models/deepseek-v4-flash` | same as #3 | 29-row chart; `currentModel` present | **OK** | `loaders.model("deepseek-v4-flash")` returns 29 records incl. requested slug | `aa_model query=deepseek-v4-flash` resolves **name → `deepseek-v4-flash-vision`** with a warning; not a parse break |
| 5 | `/models/gpt-4o` (deprecated) | same as #3 | `currentModel` present; chart present; page not in the 275-row leaderboard | **DRIFTED** (reachability) | rich dataset contains 444 deprecated records, incl. `gpt-4o-2024-08-06`; leaderboard has 0 | `aa_model query=gpt-4o` → `no model matches 'gpt-4o' — closest slugs: none`; same for `gpt-4o-2024-08-06` |
| 6 | `/evaluations` catalog | server-rendered `<a href="/evaluations/…">` cards `parse_eval_catalog` `loaders.py:2383`; union with sitemap `eval_catalog` `loaders.py:2436`, `parse_sitemap` `loaders.py:2700` | 38 RSC cards; 48 flat sitemap eval slugs | **OK** | `loaders.eval_catalog()` → 48 rows; first: `artificial-analysis-intelligence-index`, title “Artificial Analysis Intelligence Index v5.0” | not a tool; used by `aa_raw kind=eval` validation (`server.py:5795`) |
| 7 | `/evaluations/gpqa-diamond` | chart keys `loaders.py:527` / `initial_models` `loaders.py:880` | 27-row chart; `releaseDate` and `suffix` present | **OK** | `gpqa=0.9606` for `gpt-6-astra` | `aa_benchmark_leaderboard gpqa-diamond` → `4 of 210 scored` (rich used; eval page parses too) |
| 8 | `/evaluations/artificial-analysis-cyber-index` | chart keys + homepage panel `_PANEL_FIELDS` `server.py:4530` | 25-row chart; 5-row companion panel | **OK** | chart fields `cyberIndex,cweBench,cybergymE2e,deepsecBench,*RefusalRate` | `aa_benchmark_leaderboard cyberIndex` → `3 of 25 scored` |
| 9 | `/evaluations/aa-briefcase` | chart keys | 28-row chart **plus a 245-row Elo table** `{analyticalQualityElo,elo,presentationElo,rubricPassRate,confidenceInterval}` | **OK** (+ NEW board) | `Gemini 4 Carbon`: `elo=1610.19`, `presentationElo=1598.74`, `rubricPassRate=0.6182` | `aa_benchmark_leaderboard briefcaseElo` → `3 of 141 scored` (rich) |
| 10 | `/models/capabilities/{6}` | `("slug","weightedIndex")` `loaders.py:2487`; `parse_capability_index` `2495` | **308 → `/indexes/<slug>`**; 28 rows with `slug,weightedIndex,headlineValue,subScores` | **OK** (redirect) | `gemini-4-carbon weightedIndex=61.9585`; subScores `{knowledge,reasoning,longContext,agenticToolUse,nonHallucination,agenticKnowledgeWork}` | `aa_leaderboard sort=capabilities.legal` → Cap Legal 62.0; “comes from /models/capabilities/legal (28 models)” |
| 11 | `/models/multilingual` | `multilingual`/`globalMmluLite` `normalize.py:516`; `EXTRA_EVAL_PAGES` `loaders.py:131` | 13 rows with `multilingual`, `globalMmluLite` | **OK** | `gemini-3-pro` 92.2 | `aa_benchmark_leaderboard multilingual` → `3 of 13 scored` |
| 12 | `/agents/coding-agents` | `("agentName","indexScore")` `loaders.py:2163` | 34 rows | **OK** | `indexScore` present on every row | `aa_agents board=coding_agents` → `4 of 34 rows`, Claude Code 61.7 |
| 13 | `/agents/chatbots` | `("featuresScore","tier")` `loaders.py:2163` | 26 rows | **OK** | `featuresScore` | `2 of 26 rows`, SuperGrok Heavy 5.80 |
| 14 | `/agents/search-api` | `("providerKey","aaSearchQualityIndex")` `loaders.py:2163` | 26 rows | **OK** | `aaSearchQualityIndex` | `2 of 26 rows`, Exa 80.3% |
| 15 | `/image/leaderboard/text-to-image` | `_MEDIA_BOARD_KEYS["text_to_image"]=("name","elo","pricePer1kImages")` `loaders.py:1636`; arena slot `_arena_slot` `loaders.py:1745` | 106-row arena `{formatted,values}` | **OK** | `GPT Image 2.5 Sunburst (max) elo=1221.96` | `4 of 106 text_to_image`, 1222 |
| 16 | `/video/leaderboard/text-to-video` | `("name","elo","pricePerMinute")` `loaders.py:1636`; `withAudioData` ref `loaders.py:1760` | 31-row arena | **OK** | Elo present | `3 of 31 text_to_video`, Wan 3.0 1175 |
| 17 | `/video/leaderboard/image-to-video` | `("name","elo","pricePerMinute")` | 29-row arena | **OK** | Elo present | `3 of 29 image_to_video`, Dreamina Seedance 2.5 1153 |
| 18 | `/text-to-speech/models` | `("pricePer1mCharacters","isRepresentative")` `loaders.py:534-543`; `_adapt_tts` `loaders.py:778` | 112 rows; `performance` **dict on 85/112**; `model.qualityElo` on 108; pronunciation array 35 rows keyed `ttsModelId` | **DRIFTED** (partial) | `perf: null` on 27 rows | not exposed through `aa_media` (that board is the 100-row arena); `eval_models('tts')` silently drops chars/sec + generation time for 27 rows |
| 19 | `/speech-to-text/non-streaming` | `("aaWerIndex",)` `loaders.py:534-543`; `_adapt_stt` `loaders.py:688` | 39 rows | **OK** | MAI-Transcribe-2 `aaWerIndex=0.0204` | `3 of 39 rows`, 2.0% |
| 20 | `/speech-to-speech/arena` | `("sliceKey","stsQualityIndexV2Score")`; `_adapt_sts` `loaders.py:742` | 90 rows (30 `overall`); `stsQualityIndexV2Components` **dict on only 22/90** | **DRIFTED** (partial) | overall rows missing components for 8 models | `3 of 30 rows`, Phonic 1 87.1 |
| 21 | `/` (home) | keyed objects `sttNonStreaming`,`sttStreaming`,`sts` `parse_home_boards` `loaders.py:1403`; eval panels `_EVAL_PANEL_RE` `loaders.py:1382` | **no `sttNonStreaming`/`sttStreaming`/`"sts"` keys; 0 `"evalSlug"` panels**; 35-row decision table, 34-row agent table, 28-row chart, 25-row cyber panel | **DRIFTED** (panels moved) | `home.rsc` key/`evalSlug` absent | `home_boards()` falls back to the dedicated speech pages; homepage eval-panel fallback in `server.py:4340` is dead but silent |
| 22 | `/sitemap.xml` | `parse_sitemap` `loaders.py:2700` | 4,245 URLs; new sections `/indexes` (6), `/decision-models` (20), `/microevals`, `/3d`, `/optima`, `/tools`, `/hardware-inference-stack` (5) | **OK** | section counts above | used by catalog union |
| 23 | `/microevals` | — | 118-row chart `{chartDefaultSelected,intelligenceIndex,name,releaseDate,slug}` + 20 vote cards `{slug,title,description,image,voteCount}` | **NEW** | first card: `p5.js physics`, 50 votes | not exposed anywhere |
| 24 | `/hardware-inference-stack/mobile-phones` | `("evalScores",)` `loaders.py:536`; `_mobile_scores` `normalize.py:498` | 90-row `evalScores` table **plus 3,250-row `{deviceKey,metric,prefillTokens,value}`** (2 devices; metrics `decode_throughput, prefill_throughput, ttft, end_to_end_latency, peak_memory`) | **OK** (+ NEW table) | 90 rows as expected | `aa_benchmark_leaderboard mobile` → `3 of 57 scored` |
| 25 | `/trends` | — | 28-row chart `{chartDefaultSelected,intelligenceIndex,inferenceParametersActiveBillions,...}` | **NEW** | same shape as a chart set | not exposed |

**Counts: 25 surfaces — 18 OK, 5 DRIFTED, 2 NEW** (plus 12 NEW items found inside OK/DRIFTED surfaces).

---

## DRIFTED — ordered by severity

### D1. `gdpvalNormalized` is silently wrong: briefcase Elo is read as a 0-1 fraction (×100)
**What changed.** AA no longer publishes a normalized GDPval score on the free pages. On `/evaluations/gdpval-aa` the only field is `gdpval` = **Elo** (`gemini-4-carbon` = `1732.68`); `gdpvalNormalized` is `None` on all 27 chart rows and on all 719 rich records. The 275-row leaderboard's new `scores` map carries `"gdpval-aa-normalized": 1498.47` — also **Elo**, despite the key's name.

**Code path.** `_raw_chart_pairs` (`server.py:4492`) is the fallback for chart-set benchmarks; when the requested key is absent it unconditionally substitutes `briefcaseBreakdown.elo` (`server.py:4515-4520`):

```python
value = rec.get(key)
if value is None:
    breakdown = rec.get("briefcaseBreakdown")
    if isinstance(breakdown, dict):
        value = breakdown.get("elo")
```

`gdpvalNormalized` is declared `%` in `catalog.py:142`, so the formatter multiplies by 100.

**Observed wrong output** (actual CLI run):
```
$ aa-mcp-cli call aa_benchmark_leaderboard '{"benchmark":"gdpvalNormalized","top":3}'
# 3 of 27 scored (275 tracked) · GDPval-AA · AA chart set — not a full leaderboard
| Gemini 4 Carbon (High) | gemini-4-carbon | Google | 161019.0% | 59.4 |
```
`1610.19` is `briefcaseBreakdown.elo` (or `briefcaseElo`) for that model. This is **silently wrong**, not a crash, and it is the only such output found.

**Smallest correct fix.** Delete the unconditional briefcase fallback, or gate it to `key == "briefcaseElo"`. Separately mark `gdpvalNormalized` as unpublished (the site now ships Elo only) or map it from an explicit normalized field if AA reintroduces one. Add a regression test asserting `gdpvalNormalized` is absent/!≈1610 for a model whose briefcase Elo is present.

### D2. Leaderboard per-eval columns moved into a `scores` map keyed by benchmark slug
**What changed.** `from_leaderboard` (`normalize.py:317`) reads flat `_LEADER_EVAL_KEYS` (`normalize.py:171`, consumed at `normalize.py:349`): `gpqa`, `hle`, `tau2`, `gdpvalNormalized`, `terminalBench21`, … None of those keys exist on the live 275-row array. AA now ships one `scores` object keyed by **eval slug**:

```
"aa-briefcase":1461.69, "artificial-analysis-long-context-reasoning":0.7967,
"automationbench-aa":0.6459, "critpt":0.2914, "critpt-v2-hard":0.71,
"frontiercode":0.3942, "frontiercode-2-0":0.3658, "gdp-pdf":0.304,
"gdpval-aa-normalized":1498.47, "hle-diamond":0.527, "humanitys-last-exam":0.5273,
"mlcr-aa":0.3833, "omniscience-accuracy":0.5963, "omniscience-non-hallucination":0.5483,
"scicode":0.5417, "terminal-bench-science":0.5333, "terminalbench-4-0":0.4949
```

**Will now break/silently degrade.** `Model.evals` on leaderboard rows is **empty**; every benchmark column silently disappears on any path that does not also merge the rich dataset. Today `aa_benchmark_leaderboard`/`aa_compare` are rescued by the 719-row rich overlay (`aa_benchmark_leaderboard gpqa-diamond` → “210 scored … rich dataset”), but `aa_leaderboard` itself has no eval columns.

**Also rescaled.** `scores` values are 0-1 (GPQA 0.939, HLE 0.527) except `gdpval-aa-normalized` and `aa-briefcase`, which are Elo. The 275 rows and 86 scored rows are real (v5.0 roll-out), not truncation: `_MIN_SCORED_MODELS = 25` (`loaders.py:370`) deliberately passes this payload.

**Smallest correct fix.** In `from_leaderboard`, read `rec["scores"]` and map known slug keys to catalog keys (explicit map, because `gdpval-aa-normalized` is Elo, not a fraction); keep the flat-key path for legacy payloads. Extend `_LEADER_EVAL_KEYS` coverage via the catalog rather than a second hand-list.

### D3. Deprecated models are unreachable by name (search/resolve only cover the 275 active rows)
**What changed.** The 275-row leaderboard contains **0** deprecated records. Deprecated models exist in the 719 rich records (**444**) and on their own pages (`/models/gpt-4o` still renders a `currentModel`), but name resolution uses `_lb_rows()` (`server.py:237`).

**Observed**:
```
$ aa-mcp-cli call aa_model '{"query":"gpt-4o"}'
no model matches 'gpt-4o' — closest slugs: none
$ aa-mcp-cli call aa_model '{"query":"gpt-4o-2024-08-06"}'
no model matches 'gpt-4o-2024-08-06' — closest slugs: none
```
`aa_search deepseek` likewise reports only active rows. `include_deprecated` on `aa_leaderboard` has nothing to include.

**Smallest correct fix.** Resolve/search over `_models_state(rich=True)` (or the union of leaderboard + deprecated rich rows) instead of `_lb_rows()` alone; keep `include_deprecated` filtering on that pool.

### D4. `/text-to-speech/models`: `performance` is null on 27 of 112 rows
`_adapt_tts` (`loaders.py:778`) reads `rec["performance"]` for `ttsCharactersPerSecond` and `ttsGenerationTime` (`loaders.py:791-795`). Live: `performance` is a dict on **85/112** rows only. The 27 representative rows silently lose characters/sec and generation time. Pronunciation still joins: 35 rows carry `ttsModelId` (`loaders.py:786`).

**Smallest fix.** Treat `performance: null` as “no perf data” and fall back to the nested `model.performance`/omit the keys; do not assume the dict exists.

### D5. `/speech-to-speech/arena`: `stsQualityIndexV2Components` on only 22 of 90 rows
`_adapt_sts` (`loaders.py:742`) reads components only from the `overall` slice. Live: 30 `overall` rows, but the components map is present on **22** — 8 overall models silently lose `stsBigBenchAudio`, `stsTauVoice`, `stsArenaScore`, `stsTaskSuccess`. `sts` itself (`stsQualityIndexV2Score`) is present and ranks correctly (`3 of 30`).

**Smallest fix.** Accept a components map on any slice (prefer `overall`), or record the missing components as absent rather than assuming coverage.

### D6. Homepage panels moved: `parse_home_boards` expects keys the page no longer ships
`parse_home_boards` (`loaders.py:1403`) looks for keyed objects `sttNonStreaming`, `sttStreaming`, `sts`, and `_eval_panels` (`loaders.py:1382`) scans for `{"evalSlug":…}`. Live `home.rsc`: **none of those keys**, and **0** `evalSlug` panels. The page now carries a 35-row decision table, a 34-row agent table, a 28-row chart and a 25-row cyber panel.

**Effect.** `home_boards()` still works because `_full_speech_boards` replaces panels with the dedicated speech pages, but the homepage eval-panel source is dead: `server.py:4340`/`4967`/`5758` silently get `[]`. Not wrong today (chart/eval-page sources cover those metrics) but a lost surface.

**Smallest fix.** Find the new panel key in `home.rsc` and update `parse_home_boards`; or drop the homepage-panel branch and document that panels are no longer a source.

### D7. Capability pages are 308 redirects to `/indexes/<slug>`
`SOURCE_URLS["capability"]` (`loaders.py:117`) still points at `/models/capabilities/<slug>`. The live site answers **308 → `/indexes/<slug>`** (all six). Parsing still succeeds because `urllib` follows redirects, but the cache key and docstrings name a deprecated route, and a future redirect-policy change would break all six capability joins.

**Smallest fix.** Point the slug map at `/indexes/<slug>` (keep the old path as fallback if desired) and update the docstring.

### D8. Docstring/scale drift (not functional)
- `parse_leaderboard` says “the 700-row one” (`loaders.py:590`) — live is 275 tracked / 86 scored.
- `provider_board` says “The 1201-row provider leaderboard.” (`loaders.py:1345`) — live is 509.
- Capability comment says 26 models / 20 healthcare (`loaders.py:2480` area) — live is 28.
- `aa_providers` header is honest (“509 endpoints”); only comments are stale.

---

## NEW — ordered by value

1. **New benchmark pages/metrics (highest value).** The sitemap publishes seven flat eval slugs that have no catalog entry/slug mapping, and the live chart/rich records carry their fields:
   - `/evaluations/healthbench` → `healthbench` (0.582 on `gpt-6-astra`), `healthbenchProfessional`, `healthbenchBreakdown`, `healthbenchProfessionalBreakdown`; **14** rich records.
   - `/evaluations/code2video-aa` → `code2videoElo` (1426.78), `code2videoBreakdown`, `code2videoEloInterval`; **27** rich records.
   - `/evaluations/critpt-v2` → `critptAgentic`, `critptAgenticHard` (0.705); **95** rich records.
   - `/evaluations/frontiercode-2-0` → `frontierCode20` (0.4237); **89** rich records.
   - `/evaluations/hle-diamond` → `hleDiamond` (0.638), `hleDiamondScoreByPartition`; **138** rich records.
   - `/evaluations/artificial-analysis-decision-index` → the `decisionIndex` key exists (`catalog.py:87`) but its slug is `None`; the page is live.
   - `/evaluations/aa-personalitybench` (41 URLs: 8 `/indexes/*` trait indexes + 30 `/traits/*` pages) — no catalog representation at all.
   **Recipe:** add `_B` rows in `catalog.py:79` (key, label, slug, unit, desc, tags, member), add the payload keys to `normalize._CHART_EVAL_KEYS` (`normalize.py:178`) and the breakdown maps if any, keep `loaders.SOURCE_URLS` as-is (all use `/evaluations/<slug>`), then regenerate `scripts/gen_reference_md.py` and add fixture tests.
2. **Canonical `/indexes/<slug>` routes (6).** Sitemap lists `/indexes/{finance-and-accounting,strategy-and-ops,legal,healthcare-and-medical,engineering,economics}` — the redirect targets of the capability pages. Add to the URL map (D7) and to `CAPABILITY_INDEXES`-driven joins. Same payload shape (`slug`, `weightedIndex`, `headlineValue`, `subScores`).
3. **`/microevals`.** 118-model chart (`chartDefaultSelected`, `intelligenceIndex`, `releaseDate`, `slug`) + 20 pairwise vote cards (`slug`, `title`, `description`, `image`, `voteCount`; e.g. `p5.js physics`, 50 votes). Worth exposing as a small board/resource if the product wants it; reuse `parse_chart` for the model array and a 20-row card parser. Not covered by any current tool.
4. **Mobile device telemetry.** `/hardware-inference-stack/mobile-phones` now ships 3,250 rows `{deviceKey, metric, prefillTokens, value}` (2 device keys; metrics `decode_throughput`, `prefill_throughput`, `ttft`, `end_to_end_latency`, `peak_memory`). The existing 90-row `evalScores` table is parsed; the device-level throughput/latency table is not exposed. Add a loader (`parse_first_dict_array` on `("deviceKey","metric","value")`) and a resource/tool only if hardware questions are in scope.
5. **`/trends`.** 28-row chart with `chartDefaultSelected`, `intelligenceIndex`, `inferenceParametersActiveBillions`, pricing/modality fields. Duplicates leaderboard/model-page data; low value, likely no action.
6. **Leaderboard `scores` map.** Internal new shape (see D2); exposing it is the fix, not a new surface.
7. **`intelligenceIndexEvaluations` per-eval rows** are present on model pages and already parsed by `_per_eval` (`normalize.py:380`) for cost/speed; no action.
8. **New CI/metadata fields on chart records:** `briefcaseEloInterval`, `aa3dEloInterval`, `gdpvalInterval`, `cacheHitRate`, `hostModelCount`, `canonicalIntelligenceIndexTokenCount`, `briefcaseTotalCost`, `evalCost`, `headlineValue`. Mostly CI/context; expose only if confidence intervals are a product requirement.
9. **New sitemap sections:** `/3d`, `/optima`, `/tools`, `/hardware-inference-stack/*` (5), `/decision-models/*` (20). `/decision-models/*` are per-model pages for the decision cohort; the existing decision table + eval pages already cover the scores. No immediate loader work.
10. **`aa-briefcase` 245-row Elo table** (`analyticalQualityElo`, `elo`, `presentationElo`, `rubricPassRate`, `confidenceInterval`). This is a full arena-style board (245 rows) vs the 28-row chart the MCP reads. If Briefcase detail matters, expose it as a board (same recipe as `aa_media`).

---

## Numeric cross-checks (raw artifact vs MCP)

| Surface | Raw value (artifact) | MCP call | MCP value | Match |
|---|---|---|---|---|
| Leaderboard metric | `gemini-4-carbon intelligenceIndex = 59.425738829526` (`lb_models.rsc`) | `aa_leaderboard top=3` | 59.4 | ✅ |
| Model-page rich field | `gpt-6-astra-medium gpqa = 0.939393939393939` (`model_frontier.rsc` chart) | `aa_model query=gpt-6-astra-medium` | GPQA Diamond 93.9% | ✅ |
| Capability index | `gemini-4-carbon weightedIndex = 61.9585486390271` (`cap_legal.rsc`) | `aa_leaderboard sort=capabilities.legal` | Cap Legal 62.0 | ✅ |
| Provider price | first `/leaderboards/providers` row: host Alibaba Cloud, `price1mInputTokens = 0.4` (`lb_providers.rsc`) | `aa_providers top=4` | `$0.40` In $/M, Alibaba Cloud | ✅ |
| Media Elo | `GPT Image 2.5 Sunburst (max) elo = 1221.96` (`img_tt.rsc`) | `aa_media board=text_to_image` | 1222 | ✅ |
| Speech WER | `MAI-Transcribe-2 aaWerIndex = 0.0204` (`stt_nonstream.rsc`) | `aa_media board=speech_to_text` | 2.0% | ✅ |

The one mismatch found in the same pass is D1 (`gdpvalNormalized` 161019.0% vs no live normalized field).

---

## Verdict

The MCP **still answers correctly today** on every path exercised end-to-end: leaderboard, model digests (frontier/open/deprecated pages), providers, agents (all three boards), capability joins, eval/index leaderboards (`gpqa-diamond`, `cyberIndex`, `briefcaseElo`, `multilingual`, `mobile`, `when2call`), media (image, both video arenas, TTS, STT, STS), and `aa_compare`/`aa_search`. The rich-dataset overlay is doing a lot of quiet load-bearing work; without it the leaderboard would have no per-eval values (D2).

One **silently wrong** output was reproduced: `aa_benchmark_leaderboard benchmark=gdpvalNormalized` prints `161019.0%` (briefcase Elo ×100) because `_raw_chart_pairs` falls back to `briefcaseBreakdown.elo` for any missing key. Two silent degradations were also found: TTS perf on 27/112 rows (D4) and STS components on 8/30 overall rows (D5); plus the deprecated-model reachability gap (D3).

**Top 5 fixes, in order**
1. `_raw_chart_pairs` (`server.py:4492-4520`): remove/gate the `briefcaseBreakdown.elo` fallback; decide what `gdpvalNormalized` means now that AA ships Elo only (D1 — the only silently wrong answer).
2. `from_leaderboard` (`normalize.py:317`): parse the new `scores` map (slug-keyed; note GDPval is Elo), and keep the flat-key path for old payloads (D2).
3. Resolve/search deprecated models over the rich pool, not only `_lb_rows()` (`server.py:237`); make `include_deprecated` meaningful (D3).
4. Update `parse_home_boards` to the new homepage payload or delete the dead homepage-panel branch (`loaders.py:1403`, `server.py:4340`); fix TTS null `performance` and STS partial components (`loaders.py:778,742`) (D4-D6).
5. Add the new benchmarks/pages (healthbench, code2video, critpt-v2, frontiercode-2-0, hle-diamond) and point capability URLs at `/indexes/<slug>`; then consider `/microevals` and mobile device metrics (NEW 1-4).
