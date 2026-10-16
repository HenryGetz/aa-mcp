# Coverage audit — what artificialanalysis.ai publishes vs. what aa-mcp exposes

Recon date: **2026-10-16**. Everything below was measured against live responses from
`https://artificialanalysis.ai` (no API key) and against the live MCP server driven through
`eval/client.py`. Every "covered" claim was proved with a real tool call; every "missing"
claim was proved by attempting the obvious tool + argument and showing the failure.

Reproduce the site side with the raw-RSC recipe (`RSC: 1` header → flight payload); reproduce
the MCP side with:

```bash
cd /home/wavy/ai/aa-mcp
.venv/bin/python eval/client.py tools
.venv/bin/python eval/client.py call <tool> '<json>'
```

---

## 1. Universe inventory (grouped by source)

### 1.1 `sitemap.xml` — 5,251 canonical URLs

| Section | URLs | What it is | Notes |
|---|---:|---|---|
| `/models` | 4,531 | model pages + comparison/release/creator views | 463 plain `/models/<slug>`; **460** `/models/<slug>/providers`; 2,415 `/models/comparisons/*`; 1,111 `/models/releases/*`; 59 `/models/creators/*`; 16 `/models/multilingual*`; 7 `/models/capabilities*`; 4 `/models/open-source*` |
| `/text-to-speech` | 256 | TTS models/providers/leaderboards | 101 `/models/*`, 101 `/providers/*`, 48 `/model-families/*`, 3 leaderboards, 1 arena, 1 speech-explorer, 1 voice-playground |
| `/articles` | 129 | blog/analysis | not a data surface |
| `/speech-to-text` | 58 | STT boards | 56 `/models/*` + `/non-streaming` + `/streaming` |
| `/image` | 57 | image boards | 27 models, 14 model-families, 9 providers, 4 leaderboards, 1 arena, 1 image-lab |
| `/providers` | 56 | provider landing pages | |
| `/evaluations` | 43 | **the named benchmarks** | 42 eval pages + the index |
| `/agents` | 40 | agent boards | 38 under `/agents/coding-agents` (37 are A-vs-B comparison pages), 1 chatbots, 1 search-api |
| `/video` | 30 | video boards | 9 models, 7 providers, 6 leaderboards, 6 model-families, 1 arena |
| `/methodology` | 20 | method write-ups | incl. `mobile-device-benchmark-set`, `endpoint-accuracy-index`, `agentperf` |
| `/hardware-inference-stack` | 5 | inference/hardware | `datacenter`, `laptops-workstations(+ /configs)`, `mobile-phones` |
| `/data-api` | 4 | paid-API docs | |
| `/speech-to-speech` | 3 | STS arena | |
| `/music` | 3 | music arena + 2 leaderboards | |
| `/leaderboards` | 2 | `/models`, `/providers` | |
| singletons | 14 | `/`, `/about`, `/api-reference`, `/brand-kit`, `/changelog`, `/contact`, `/faq`, `/government`, `/image-lab`, `/microevals`, `/privacy-policy`, `/terms-of-use`, `/tools`, `/trends` | |

### 1.2 Nav/config JSON (ships in **every** RSC payload, `…messages.nav.config…`)

Top-level keys: `languageModels`, `agents`, `trends`, `speechImageAndVideo`, `inference`,
`leaderboards`, `about`. Notable entries the MCP does *not* obviously cover:

| Nav entry | Route it implies | MCP |
|---|---|---|
| `languageModels.capabilities.{codingAgentIndex,searchIndex,cyberIndex,decisionIndex,opennessIndex}` | the five "Indexes" | covered (coding agent, search, cyber, decision, openness) |
| `languageModels.decisionModels` ("Decision Models") | `/evaluations/{aa-omniscience-decision,hle-multichoice,when2call,wildguardtest}` | **MISSING** (see §3) |
| `languageModels.aa3d` | `/evaluations/aa-3d` | covered (Elo) |
| `languageModels.tools.{modelComparison,llmPriceCalculator,caching,microevals}` | `/models/comparisons`, `/models/caching`, `/microevals` | caching **PARTIAL**, microevals **MISSING** |
| `inference.{serverlessApis,hardwareInferenceStacks,datacenter,workstation,portableDevices}` | `/hardware-inference-stack/*` | **MISSING** |
| `speechImageAndVideo.*` | all media boards | mostly covered; audio/silent video variants **MISSING** |

A second config (`messages.nav.search.categories`) names the site-search facets:
`models, providers, evaluations, agents, languages, imageGeneration, speech, video, music,
inference, leaderboards, apiReference, tools, about, modelAnalysis`.
`languages` and `modelAnalysis` have **no route** (`/languages` and `/models/analysis` both
404) — they are facets over the multilingual data (§3, gap 4).

### 1.3 Homepage payload (`/`)

14 chart-composition sections: Intelligence, Frontier trend, Coding Agent Index, Cyber, AA-3D,
Image & Video, Speech, Capability Indexes, Benchmarks, Openness Index, Output Tokens, Cost,
Speed & Latency, Providers.
Plus **5 embedded eval panels** (`eval:<slug>`): `artificial-analysis-cyber-index`,
`cwe-bench-aa`, `deepsecbench-aa`, `cybergym-e2e-aa`, and homepage media blocks
(`sttNonStreaming` 15, `sttStreaming` 28, `sts` 15, `tts` 15, `ttsControlledVoice` 15,
`textToImage`, capability-index rows, coding-agent rows).

Tab/metric values the homepage lets a user rank by (extracted from the composition):
`open-weights-vs-proprietary`, `reasoning-vs-non-reasoning`, `text-only-vs-multimodal`,
`country-analysis`, `cost-per-task`, `time-per-task`, `output-tokens-per-task`,
`intelligence-vs-{cost-per-task,time-per-task,output-tokens-per-task,output-tokens,total-cost,compute,price}`,
`cyber-index{,-by-benchmark,-vs-cost-per-task}`, `{cwe-bench,deepsecbench,cybergym-e2e}-aa-vs-cost-per-task`,
`text-to-image`, `image-editing`, `text-to-video-audio`, `image-to-video-audio`, `video-editing`,
`provider-voice-arena`, `controlled-voice-arena`, `aa-wer-index-non-streaming`,
`aa-wer-index-final-transcription`, `speech-to-speech`,
`aa-briefcase-elo`, `aa-briefcase-rubric-score`, `aa-briefcase-quality-elos`, `aa-briefcase-elo-vs-cost-per-task`,
`openness-index{,-components-stacked-bar-chart}`, `evaluation-breakdown`, `total-cost`,
`cache-hit-input-output-pricing`, `blended-price{,-stacked}`, `cache-discount`, `cache-hit-rate`,
`speed`, `latency`, `end-to-end-response-time`, `speed-over-time`,
`omniscience-index`, `omniscience-accuracy`, `omniscience-hallucination-rate`.

### 1.4 `/evaluations` + the 42 `/evaluations/<slug>` pages

`aa-3d, aa-analyst-agent, aa-briefcase, aa-omniscience-decision, aime-2025, apex-agents-aa,
artificial-analysis-cyber-index, artificial-analysis-decision-index,
artificial-analysis-intelligence-index, artificial-analysis-long-context-reasoning,
artificial-analysis-openness-index, automationbench-aa, critpt, cwe-bench-aa, cybergym-e2e-aa,
deepsecbench-aa, enterprise-ops-gym-aa, frontiercode, gdp-pdf, gdpval-aa, global-mmlu-lite,
gpqa-diamond, harvey-lab-aa, hle-multichoice, humanitys-last-exam, ifbench, itbench-aa,
livecodebench, math-500, mlcr-aa, mmlu-pro, mmmu-pro, omniscience, scicode, tau2-bench,
tau3-banking, terminal-bench-science, terminalbench-2-1, terminalbench-4-0, terminalbench-hard,
when2call, wildguardtest`.

`aa_raw kind=catalog` returns exactly these 42 slugs — the eval **catalog** is complete and
byte-identical to the sitemap. The gap is that four of them publish data the MCP cannot read
(§3, gap 1).

Each `/evaluations/<slug>` page that *does* carry a chart set ships an `initialModels` array of
**31 rows × 88 keys** (omniscience page) — the richest per-model payload on the site, richer
than the 703×94 rich dataset. New keys found there that the MCP does not read:
`omniscienceBreakdown` (31/31 non-null), `opennessBreakdown` (10/31), `terminalBenchSciencePassRateByDomain`
(20/31), `itbenchAvgTurnsPerTask` (11/31), `enterpriseOpsGymAvgConversationTurns` (9/31),
`canonicalEvalTokenCounts` (31/31), `medianCanonicalAnswerOutputSpeed` (28/31),
`briefcaseBreakdown` (31/31), `aa3dBreakdown` (22/22), `globalMmluLiteScoreByLanguage`.
(`healthbench`, `healthbenchProfessional`, `heygenCode2videoElo` are present as keys but
**null in every row** — placeholders, not published data.)

### 1.5 `/leaderboards/models` selector config

Column items: `contextWindow, outputSpeed, latencyTimeToFirstToken, indexCostPerTask,
inputPrice, cacheHit, cacheWrite, outputPrice, timePeriod`. The 703-row array carries 51 keys
(intelligence + raw evals + pricing + tps/ttft percentiles + `paramClass`/`priceClass`).

### 1.6 Model-page payloads

Two shapes:

* **rich dataset** (e.g. `/models/step-5`): **703 rows × 94 keys** — the cross-model overlay.
* **chart set**: 5–31 rows × 88 keys (eval pages), or 13 rows (`/models/multilingual`).

Rich keys the MCP does not surface: `microevalsEnabled`, `hostModelCount`, `pricePer1k1mpImages`,
`reasoningTokens` (exposed), `performanceByPromptType` (exposed as "TTFT by prompt"),
`timescaleData`, `openSourceCategorization`, `briefcaseTotalCost`, `canonicalIntelligenceIndexTokenCount`,
`intelligenceIndexEvaluations`, `outputSpeedVariance`, `timeToFirstChunkVariance`.

### 1.7 `/leaderboards/providers` + `/models/<slug>/providers`

1,222 endpoint rows, each `{host{functionCallingUrl,jsonModeUrl}, model{…19 evals…},
features{contextWindowTokens,functionCalling,jsonMode,openaiCompatible}, pricing{…},
performance{12 percentiles}}` plus `hostApiId` (the model's API id on that host).
`/models/caching` publishes a further **155-row** cache table with `cacheTtl`,
`cacheMinimumTokens`, `cacheStoragePricePerHourPer1mTokens`, `cacheAutoenabled`,
`cacheHitDiscountPercent` — none of these four are in the MCP.

### 1.8 Media / arena boards

| Board | Route | Rows | Extra structure |
|---|---|---:|---|
| Text-to-Image | `/image/leaderboard/text-to-image` | 104 | 19 category sub-boards (10 useCase + 9 capability) |
| Image Editing | `/image/leaderboard/editing` | 71 | 17 category sub-boards (10 useCase + 7 editingAction) |
| Text-to-Video (audio) | `/video/leaderboard/text-to-video` | 28 | AA-Video-T2V **v2.1**; 20 category sub-boards |
| Text-to-Video (silent) | same page, `withoutAudioData` | 31 | **AA-Video-T2V-Silent v2.1** |
| Image-to-Video (audio) | `/video/leaderboard/image-to-video` | 23 | AA-Video-I2V **v1.1** |
| Image-to-Video (silent) | same page, `withoutAudioData` | 82 | **AA-Video-I2V-Silent v1.0** |
| Video Editing | `/video/leaderboard/video-editing` | 9 | 5 editCapability categories |
| TTS Provider Voice | `/text-to-speech/leaderboard/provider-voice` | 97 | 4 useCase categories |
| TTS Controlled Voice | `/text-to-speech/leaderboard/controlled-voice` | 43 | 11 language subsets |
| Music Instrumental | `/music/leaderboard/instrumental` | 19 | — |
| Music with Vocals | `/music/leaderboard/vocals` | 13 | — |
| STT non-streaming | `/speech-to-text/non-streaming` | 36 | per-dataset WER (`aaWerIndex`, `earnings22CleanedWer`, `voxpopuliCleanedWer`, `aaSttDatasetWer`) |
| STT streaming | `/speech-to-text/streaming` | 45 | `aaWerStreamingIndex`, per-dataset streaming WER, `timeToFirstPartialTranscript`, `timeToFinalTranscript` |
| Speech-to-Speech | `/speech-to-speech/arena` | 80 | `stsQualityIndexV2Components` = {bigBenchAudio, tau3Voice, arenaScore, taskSuccessRate}; multiple `sliceKey` slices |
| TTS `/models` table | `/text-to-speech/models` | 107 | `latencyPerformance`, `performance`, chars/sec, variance |
| TTS pronunciation suite | `/text-to-speech/models` tabs | — | `pronunciation`, `text-normalization`, `sequence-fidelity`, `contextual-disambiguation`, `term-pronunciation`, `characters-per-second{,-variance,-over-time}` |

**Audio variants exist on the site.** The homepage media tabs literally carry
`text-to-video-audio` / `image-to-video-audio`, and the video leaderboard ships
`withAudioData` / `withoutAudioData` for both T2V and I2V.

### 1.9 Public OpenAPI spec (`/api/v2/openapi`, readable without a key)

33 evaluation fields, plus media schemas. Vocabulary worth cross-checking:

* `Evaluations` includes `artificial_analysis_multilingual_index` (site: `/models/multilingual`)
  and `mlcr_overall` — and `artificial_analysis_coding_index` / `artificial_analysis_agentic_index`
  which the site does **not** publish free (MCP documents this correctly).
* `ModelDataExternal` adds `aa_omniscience_breakdown` (7 domains),
  `artificial_analysis_openness_index_breakdown` (9 components),
  `artificial_analysis_intelligence_index_token_counts` (input/answer/output/reasoning),
  `intelligence_index_cost` (total/input/reasoning/answer), `huggingface_url`, `openrouter_api_id`.
* `SpeechToTextModelResult` = `aa_wer_index, aa_agenttalk, voxpopuli_cleaned_aa, earnings_22_cleaned_aa`.
* `SpeechToSpeechResult` = `bba_score, fdb_score, tau_voice_score` (Big Bench Audio, Full Duplex
  Bench, τ-Voice).
* Media paths list `/media/text-to-video-audio/models` and `/media/image-to-video-audio/models`
  as separate endpoints.

---

## 2. Per-item coverage

Legend: **FULLY** = rankable and/or per-model through a working tool argument with honest
coverage; **PARTIAL** = reachable but a named subset/sub-score is missing; **MISSING** = the
site publishes it and no tool+argument reaches it.

### 2.1 Text / language benchmarks and indexes

| # | Item | AA route(s) | Payload key path | MCP surface | Live coverage | Status |
|---|---|---|---|---|---|---|
| 1 | AA Intelligence Index | `/leaderboards/models` | `[…].intelligenceIndex` | `aa_leaderboard sort=intelligence` | 693/703 | FULLY |
| 2 | AA Coding Index | — | — | `aa_benchmark_leaderboard benchmark=scicode` (documented fallback) | 0 (paid API only) | PARTIAL (honest: MCP says so) |
| 3 | AA Agentic Index | — | — | `aa_benchmark_leaderboard benchmark=terminalBench40` | 0 | PARTIAL (honest) |
| 4 | AA Openness Index | `/evaluations/artificial-analysis-openness-index` | `opennessIndex` | `aa_leaderboard sort=openness` | 326/703 | FULLY |
| 5 | Openness components (9) | same | `opennessBreakdown.{modelAvailability,modelTransparency,transparencyPreTrainingData,transparencyPostTrainingData,transparencyMethodology,dataPretrainAccess,dataPretrainLicense,dataPosttrainAccess,dataPosttrainLicense}` | **NONE** | 0 | **MISSING** |
| 6 | AA Cyber Index | `/evaluations/artificial-analysis-cyber-index` | `cyberIndex` | `aa_leaderboard sort=cyberIndex` | 20 | FULLY |
| 7 | CWE-Bench-AA / CyberGym-E2E-AA / DeepSecBench-AA | eval pages + home panel | `cweBench`, `cybergymE2e`, `deepsecBench` | `aa_leaderboard sort=<key>` | 20/20/22 | FULLY |
| 8 | Cyber refusal rates ×4 + mitigation status | eval pages | `*RefusalRate`, `mitigationStatus` | `aa_leaderboard sort=*RefusalRate`, `sort=cyberMitigationStatus` | 20 | FULLY |
| 9 | AA Decision Index | `/evaluations/artificial-analysis-decision-index` | `indexScore` (28-row array) | `aa_benchmark_leaderboard benchmark=decisionIndex` | **15 of 28** | PARTIAL |
| 10 | When2Call | `/evaluations/when2call` | 28-row array `.scores.when2callAccuracy`, `.indexScore` | `aa_benchmark_leaderboard benchmark=when2call` → **"no data"** | 0 | **MISSING** |
| 11 | WildGuardTest | `/evaluations/wildguardtest` | `.scores.wildguardtestAverageF1`, `.indexScore` | same → **"no data"** | 0 | **MISSING** |
| 12 | HLE-MultiChoice | `/evaluations/hle-multichoice` | `.scores.hleTextMcqAccuracy`, `.indexScore` | `benchmark=hle-multichoice` → **unknown benchmark** | 0 | **MISSING** |
| 13 | AA-Omniscience-Decision | `/evaluations/aa-omniscience-decision` | `.scores.omniscienceAccuracy`, `.indexScore` | `benchmark=aa-omniscience-decision` → **unknown** | 0 | **MISSING** |
| 14 | AA-Omniscience Index | `/leaderboards/models`, `/evaluations/omniscience` | `omniscience` | `aa_leaderboard sort=omniscience` | 577/703 | FULLY |
| 15 | Omni accuracy / non-halluc / halluc | same | `omniscienceAccuracy`, `omniscienceNonHallucination`, `omniscienceHallucinationRate` | `aa_leaderboard sort=<key>` | 577 | FULLY |
| 16 | Omniscience **by domain** (6) | `/evaluations/omniscience` | `omniscienceBreakdown.byDomain` | **NONE** | 0 | **MISSING** |
| 17 | Omniscience **by SWE language** (13) | same | `omniscienceBreakdown.bySweLanguage` | **NONE** | 0 | **MISSING** |
| 18 | AA-3D Elo | `/evaluations/aa-3d` | `aa3dElo` | `aa_leaderboard sort=aa3dElo` | 22 | FULLY |
| 19 | AA-3D breakdown (turns/toolCalls/token percentiles) | `/evaluations/aa-3d` | `aa3dBreakdown` | declared `aa3dBreakdown` → container error, `aa_model` shows nothing | 0 | **MISSING** |
| 20 | GPQA Diamond | leaderboard | `gpqa` | `aa_leaderboard sort=gpqa` | 617/703 | FULLY |
| 21 | HLE | leaderboard | `hle` | `aa_leaderboard sort=hle` | 665/703 | FULLY |
| 22 | HLE Diamond | model pages | `hleDiamond` | `aa_leaderboard sort=hleDiamond` → "no per-model values" | 0 | **MISSING** |
| 23 | SciCode / LiveCodeBench / FrontierCode | leaderboard+rich | `scicode`, `livecodebench`, `frontierCode` | `aa_leaderboard sort=<key>` | 232/343/39 | FULLY |
| 24 | Terminal-Bench 2.1 / 4.0 / Hard / Science | leaderboard+rich | `terminalBench21`, `terminalBench40`, `terminalbenchHard`, `terminalBenchScience` | `aa_leaderboard sort=<key>` | 242/221/432/52 | FULLY |
| 25 | Terminal-Bench Science **by domain** | eval chart | `terminalBenchSciencePassRateByDomain` | **NONE** | 0 | **MISSING** |
| 26 | τ²-Bench / τ³-Banking | leaderboard | `tau2`, `tauBanking` | `aa_leaderboard sort=<key>` | 440/209 | FULLY |
| 27 | AA-LCR / IFBench / CritPt / MMMU-Pro | leaderboard | `lcr`,`ifbench`,`critpt`,`mmmuPro` | `aa_leaderboard sort=<key>` | 576/450/580/288 | FULLY |
| 28 | GDPval-AA Elo + normalized | rich | `gdpval`, `gdpvalNormalized` | `aa_leaderboard sort=<key>` | 295 | FULLY |
| 29 | GDPval breakdown | eval chart | `gdpvalBreakdown` | container error; `aa_model` shows nothing | 0 | **MISSING** |
| 30 | GDP.pdf | rich | `gdpPdfAllPass` | `aa_leaderboard sort=gdpPdfAllPass` | 223 | FULLY |
| 31 | GDP.pdf breakdown | eval chart | `gdpPdfBreakdown` | container error | 0 | **MISSING** |
| 32 | AA-AnalystAgent + pass@1/pass@k | leaderboard+chart | `analystAgent`, `analystAgentPassAt1/PassAtK` | `aa_leaderboard sort=<key>` | 50/24/24 | FULLY |
| 33 | APEX-Agents-AA | leaderboard | `apexAgents` | `aa_leaderboard sort=apexAgents` | 33 | FULLY |
| 34 | ITBench-AA SRE | leaderboard | `itbenchSre` | `aa_leaderboard sort=itbenchSre` | 45 | FULLY |
| 35 | ITBench avg turns/task | eval chart | `itbenchAvgTurnsPerTask` | **NONE** | 0 | **MISSING** |
| 36 | AutomationBench | rich | `automationBenchPartialScore` | `aa_leaderboard sort=automationBenchPartialScore` | 224 | FULLY |
| 37 | AutomationBench breakdown | eval chart | `automationBenchBreakdown` | container error | 0 | **MISSING** |
| 38 | AA-Briefcase Elo | rich | `briefcaseElo` | `aa_leaderboard sort=briefcaseElo` | 232 | FULLY |
| 39 | AA-Briefcase rubric score + Analytical-Quality/Presentation Elo | eval chart | `briefcaseBreakdown.{elo,analyticalQuality,prese…}` | declared container; `aa_model` shows nothing | 0 | **MISSING** |
| 40 | AIME 2025 | rich | `aime25` | `aa_leaderboard sort=aime25` | 270 | FULLY |
| 41 | MLCR-AA + accuracy/completeness/conciseness | rich+chart | `mlcrOverall`, `mlcrAccuracy`, `mlcrCompleteness`, `mlcrConciseness` | `aa_leaderboard sort=<key>` | 96/25/25/25 | FULLY |
| 42 | Harvey LAB-AA | rich | `harveyLab` | `aa_leaderboard sort=harveyLab` | 27 | FULLY |
| 43 | Harvey breakdown | eval chart | `harveyLabBreakdown` | container error | 0 | **MISSING** |
| 44 | EnterpriseOps-Gym | rich | `enterpriseOpsGym` | `aa_leaderboard sort=enterpriseOpsGym` | 50 | FULLY |
| 45 | EnterpriseOps by domain / avg conversation turns | eval chart | `enterpriseOpsGymSuccessRateByDomain`, `enterpriseOpsGymAvgConversationTurns` | container error / NONE | 0 | **MISSING** |
| 46 | MMLU-Pro | eval chart | `mmluPro` | `aa_leaderboard sort=mmluPro` | **1 active** (rest deprecated) | PARTIAL |
| 47 | MATH-500 | eval chart | `math500` | `aa_leaderboard sort=math500` | **1 active** of 5 | PARTIAL |
| 48 | Global-MMLU-Lite | eval chart | `globalMmluLiteScore` | `aa_leaderboard sort=globalMmluLiteScore` | **5** (site has 13 on `/models/multilingual`) | PARTIAL |
| 49 | Global-MMLU-Lite by language | `/models/multilingual` | `globalMmluLite{ar,bn,de,en,es,fr,hi,id,it,ja,ko,pt,sw,yo,zh,my}` | **NONE** | 0 | **MISSING** |
| 50 | **Multilingual Index** | `/models/multilingual` | `multilingual.average` | `sort=multilingual` → unknown; `benchmark=multilingual` → unknown | 0 | **MISSING** |
| 51 | Multilingual by language (16 langs) | `/models/multilingual` | `multilingual.{ar,…,my}` | **NONE** | 0 | **MISSING** |
| 52 | Six Capability Indexes | `/models/capabilities/<slug>` | `weightedIndex` + `subScores` | `aa_leaderboard sort=capabilities.<x>`; `aa_model` shows sub-scores | 222/222/222/82/221/229 | FULLY |
| 53 | Canonical eval token counts (per-eval in/answer/reasoning) | eval chart | `canonicalEvalTokenCounts` | **NONE** | 0 | **MISSING** |
| 54 | medianCanonicalAnswerOutputSpeed | eval chart | `medianCanonicalAnswerOutputSpeed` | **NONE** | 0 | **MISSING** |
| 55 | HealthBench / HealthBench Professional | eval chart keys | `healthbench`, `healthbenchProfessional` | — | **null everywhere** | not published (no gap) |
| 56 | HeyGen Code2Video Elo | eval chart key | `heygenCode2videoElo` | — | **null everywhere** | not published (no gap) |
| 57 | Coding-Agent / Chatbot / Search boards | `/agents/*` | see §2.3 | `aa_agents board=<key>` | 41/26/26 | see §2.3 |

### 2.2 Media / arena boards

| # | Item | AA route | Payload key path | MCP surface | Live coverage | Status |
|---|---|---|---|---|---|---|
| 58 | Text-to-Image Arena | `/image/leaderboard/text-to-image` | arena `values.elo` | `aa_media board=text_to_image` | 104 | FULLY |
| 59 | Text-to-Image categories (19) | same page | 19 sibling arena arrays | **NONE** | 0 | **MISSING** |
| 60 | Image Editing Arena | `/image/leaderboard/editing` | `values.elo` | `aa_media board=image_editing` | 71 | FULLY |
| 61 | Image Editing categories (17) | same page | 17 sibling arrays | **NONE** | 0 | **MISSING** |
| 62 | Text-to-Video Arena (**with audio**) | `/video/leaderboard/text-to-video` | `withAudioData` arena | `aa_media board=text_to_video` | 28 | FULLY |
| 63 | Text-to-Video **Silent** | same page | `withoutAudioData` arena | `board=text_to_video_silent` → **unknown board** | 0 | **MISSING** |
| 64 | Image-to-Video Arena (**with audio**) | `/video/leaderboard/image-to-video` | `withAudioData` | `aa_media board=image_to_video` | 23 | FULLY |
| 65 | Image-to-Video **Silent** | same page | `withoutAudioData` arena | `board=image_to_video_silent` → **unknown board** | 0 | **MISSING** |
| 66 | Video categories (T2V 20, video-editing 5; I2V has none) | video boards | tag sub-arrays | **NONE** | 0 | **MISSING** |
| 67 | Video Editing Arena | `/video/leaderboard/video-editing` | `values.elo` | `aa_media board=video_editing` | 9 | FULLY |
| 68 | TTS Provider Voice Arena | `/text-to-speech/leaderboard/provider-voice` | `values.elo` | `aa_media board=text_to_speech` | 97 | FULLY |
| 69 | TTS use-case categories (4) | same page | 4 sub-arrays | **NONE** | 0 | **MISSING** |
| 70 | TTS Controlled Voice Arena | `/text-to-speech/leaderboard/controlled-voice` | `values.elo` | `aa_media board=text_to_speech_controlled` | 43 | FULLY |
| 71 | TTS controlled-voice languages (11) | same page | 11 sub-arrays | **NONE** | 0 | **MISSING** |
| 72 | TTS pronunciation suite | `/text-to-speech/models` | `pronunciation`, `text-normalization`, `sequence-fidelity`, `contextual-disambiguation`, `term-pronunciation` | **NONE** | 0 | **MISSING** |
| 73 | TTS throughput/latency | `/text-to-speech/models` | `latencyPerformance`, `performance`, chars/sec + variance | **NONE** | 0 | **MISSING** |
| 74 | Music Instrumental Arena | `/music/leaderboard/instrumental` | `values.elo` | `aa_media board=music_instrumental` | 19 | FULLY |
| 75 | Music with Vocals Arena | `/music/leaderboard/vocals` | `values.elo` | `aa_media board=music_with_vocals` | 13 | FULLY |
| 76 | STT word-error-rate board | `/speech-to-text/non-streaming` | 36-row array `aaWerIndex`/`wordErrorRate` | `aa_media board=speech_to_text` (homepage panel) | **15 of 36** | PARTIAL |
| 77 | STT per-dataset WER (Earnings22-Cleaned-AA, VoxPopuli-Cleaned-AA, AA-AgentTalk) | same | `earnings22CleanedWer`, `voxpopuliCleanedWer`, `aaSttDatasetWer` | `fields=earnings22CleanedWer` ignored | 0 | **MISSING** |
| 78 | STT streaming board | `/speech-to-text/streaming` | 45-row array `aaWerStreamingIndex` | `aa_media board=speech_to_text_streaming` (home panel) | **28 of 45** | PARTIAL |
| 79 | STT streaming latency | same | `timeToFirstPartialTranscriptSeconds`, `timeToFinalTranscriptSeconds` | **NONE** | 0 | **MISSING** |
| 80 | Speech-to-Speech Index | `/speech-to-speech/arena` | 80-row `stsQualityIndexV2Score` | `aa_media board=speech_to_speech` (home panel) | **15 of 80** | PARTIAL |
| 81 | STS components | same | `stsQualityIndexV2Components.{bigBenchAudio,tau3Voice,arenaScore,taskSuccessRate}` | **NONE** | 0 | **MISSING** |
| 82 | STS slices / task-completion | same | `sliceKey`, `taskCompletionRate` | **NONE** | 0 | **MISSING** |

### 2.3 Agent boards

| # | Item | AA route | Key | MCP | Coverage | Status |
|---|---|---|---|---|---|---|
| 83 | Coding Agent Index | `/agents/coding-agents` | 41-row `indexScore` | `aa_agents board=coding_agents` | 41 | FULLY |
| 84 | Chatbot board | `/agents/chatbots` | 26-row `featuresScore` + flags/price | `aa_agents board=chatbots` | 26 | PARTIAL — prints `featuresScore` **as a percentage** (5.8 → "580.0%"); feature flags, `priceMonthly`, `intelligenceIndex` not exposed |
| 85 | Search API Index | `/agents/search-api` | 26-row `aaSearchQualityIndex` | `aa_agents board=search_api` | 26 | PARTIAL — only score + $/task; `browsecompAccuracy`, `deepsearchqaAvgF1`, `omniscienceAccuracy`, `avgLatencyS`, `costPerSearchQueryUsd`, `benchmarkCount` missing |

### 2.4 Providers, tools, hardware

| # | Item | AA route | MCP | Coverage | Status |
|---|---|---|---|---|---|
| 86 | Provider endpoint board | `/leaderboards/providers` | `aa_providers` | 1,222 endpoints | FULLY |
| 87 | Per-model endpoints | `/models/<slug>/providers` | `aa_providers model=<slug>` | works | FULLY |
| 88 | Caching table | `/models/caching` | `aa_providers fields=cache_read,cache_write` only | partial | PARTIAL — `cacheTtl`, `cacheMinimumTokens`, `cacheStoragePricePerHourPer1mTokens`, `cacheAutoenabled` MISSING |
| 89 | MicroEvals (11,228 prompt evals × model responses/votes) | `/microevals`, `/microevals/<slug>` | **NONE** | 0 | **MISSING** |
| 90 | On-device / mobile benchmark set (90 rows × 7 evals incl. **BFCL**) | `/hardware-inference-stack/mobile-phones` | **NONE** | 0 | **MISSING** |
| 91 | Hardware/laptop model-fit views | `/hardware-inference-stack/laptops-workstations` | **NONE** | 0 | **MISSING** (accelerator + `doesNotFitOn` data) |
| 92 | Model Recommender / Comparisons / Releases / Trends | `/models/recommend`, `/models/comparisons/*`, `/models/releases/*`, `/trends` | derived views over leaderboard data | — | not a distinct benchmark |
| 93 | Image Lab / Voice Playground / Speech Explorer / Optima / Government / Data API | various | product/tool pages | — | not a benchmark |

---

## 3. Ranked gap list

Ranked by (genuine benchmark × uniqueness of the data × cost to add).

### 1. Decision-Models family — 4 evaluations the MCP cannot read (MISSING, hard-ish)
*What:* `/evaluations/{aa-omniscience-decision,hle-multichoice,when2call,wildguardtest}` all
ship **one and the same** 28-row array (`kind` ∈ {`llm`,`decisionModel`}) — the `scores`
blobs are byte-identical across the four pages — with `indexScore` plus a `scores` map
`{omniscienceAccuracy, omniscienceNonHallucinationRate, hleTextMcqAccuracy,
when2callAccuracy, wildguardtestAverageF1}` and a `byDataset` cost/time map. What differs per
page is only the primary `metric` its own config declares (`{"metric":"when2callAccuracy"}`,
`hleTextMcqAccuracy`, `wildguardtestAverageF1`, `omniscienceAccuracy`). The MCP's own
`decisionIndex` entry only reaches 15 of these 28 rows and exposes none of the four
constituent scores.
*Why:* this is the whole "Decision Models" nav category, a headline AA product, and four
genuinely distinct named benchmarks. Today `aa_benchmark_leaderboard benchmark=when2call`
answers **"no data"** even though the site has 28 scored rows.
*Recipe:* add a loader that, for an eval page with no `initialModels`, finds the array whose
first dict has `indexScore` + `byDataset` (repo: `flight.find_arrays(payload, ("indexScore","byDataset"))`),
map `indexScore` → the eval's own rankable and the `scores.*` keys → four new benchmark keys
(`when2call`, `wildguardtest`, `hleTextMcq`, `omniscienceDecision`), and register each with
`slug=<eval-slug>`, `source_hint="chart"`. The 28 rows also include `kind=decisionModel`
entries that are not in the 703-row leaderboard.
*Difficulty:* **moderate** (new parse path + 4 catalog entries + `_CHART_EVAL_KEYS` additions).

### 2. Multilingual Index + per-language scores (MISSING, moderate)
*What:* `/models/multilingual` publishes `multilingual.average` and 16 per-language scores
(`ar,bn,de,en,es,fr,hi,id,it,ja,ko,pt,sw,yo,zh,my`) for 13 models, plus
`globalMmluLite` with the same language split. AA's own OpenAPI calls this
`artificial_analysis_multilingual_index`.
*Why:* it is a **named index** AA advertises (nav search category `languages`), the MCP's
`aa_benchmarks query=multilingual` returns only Global-MMLU-Lite, and `sort=multilingual`
errors. Global-MMLU-Lite itself is under-served: its eval page charts 5 models, the
multilingual page adds 12 more (the two selections overlap on `gemini-3-pro`), so the union
is **17**.
*Recipe:* add `SOURCE_URLS["multilingual"] = "/models/multilingual"`, a loader reading
`initialModels` → `multilingual.average` (index) and `multilingual.<lang>` (16 sub-keys), add
`multilingual` as a `BENCHMARKS` entry with `source_hint="chart"` and a
`slug="multilingual"`-less chart join by slug, and union `globalMmluLiteScore`'s two chart
pages for the 17-model coverage.
*Difficulty:* **trivial-to-moderate**.

### 3. Audio vs silent video boards + per-category Elo (MISSING, trivial-moderate)
*What:* `/video/leaderboard/{text-to-video,image-to-video}` ship **two** arenas each
(`withAudioData` / `withoutAudioData`): T2V 28 (audio) + 31 (silent); I2V 23 (audio) + 82
(silent). The MCP's `_media_arena` takes the first slot in document order, so it serves the
audio boards and silently drops the silent ones — including the **82-row I2V-Silent** board,
which is larger than the one it exposes. The homepage tabs already name them
`text-to-video-audio` / `image-to-video-audio`. Separately, the image, T2V, video-editing and
TTS boards each ship 4–20 category sub-arrays the MCP never exposes.
*Why:* the silent variants are real, distinct leaderboards (AA-Video-T2V-Silent v2.1,
AA-Video-I2V-Silent v1.0); a user asking "best silent video model" gets the audio board today.
*Recipe:* extend `loaders.MEDIA_BOARDS` with `text_to_video_silent` /
`image_to_video_silent` pointing at the same routes, and in `_media_arena` select by the
`withAudioData`/`withoutAudioData` ref (`$Q3a`/`$Q281`) rather than by document order. Add an
optional `category=` argument to `aa_media` selecting the sibling tag array by its
`slug`/`displayName` from the page's `tags` config.
*Difficulty:* **trivial** for the silent boards, **moderate** for categories.

### 4. Breakdown sub-scores that the catalog already advertises but no tool returns (MISSING, moderate)
*What:* `briefcaseBreakdown` (rubric + `analyticalQuality`/`presentation` Elo),
`aa3dBreakdown` (turn/tool-call/token percentiles), `gdpvalBreakdown`, `harveyLabBreakdown`,
`gdpPdfBreakdown`, `automationBenchBreakdown`, `enterpriseOpsGymSuccessRateByDomain`,
plus undeclared ones: `omniscienceBreakdown.byDomain` (6 domains) + `bySweLanguage` (13),
`opennessBreakdown` (9 components), `terminalBenchSciencePassRateByDomain`,
`enterpriseOpsGymAvgConversationTurns`, `itbenchAvgTurnsPerTask`, `canonicalEvalTokenCounts`,
`medianCanonicalAnswerOutputSpeed`.
*Why:* the catalog lists seven "Breakdown" containers and their `how` hint tells the caller to
run `aa_model <slug> sections=benchmarks` — but that section **prints no breakdown rows**
(verified: `aa_model query=claude-opus-5-5` contains no "Breakdown"/"Analytical"/"presentation"
text), and `aa_benchmark_leaderboard benchmark=briefcaseBreakdown` returns a container error.
So the advertised path is dead and the data is unreachable. The Openness components and the
Omniscience domain/language split are independently meaningful (AA's own API exposes them).
*Recipe:* carry the breakdown dicts on `Model` (a `breakdowns: dict[str, dict]` field in
`normalize.from_chart`), render them in `aa_model sections=benchmarks`, and register the
multi-model ones (openness components, omniscience byDomain/bySweLanguage,
terminalBenchScience byDomain) as rankable sub-metrics on the eval-chart join.
*Difficulty:* **moderate**.

### 5. MicroEvals + the on-device/mobile benchmark set (MISSING, moderate–hard)
*What:* `/microevals` is a gallery of **11,228** community prompt-evals (paginated, 562 pages
of 20), and each `/microevals/<slug>` page publishes a prompt plus 14 model responses with
`voteCount` — a per-microeval vote ranking. `/hardware-inference-stack/mobile-phones`
publishes a 90-row on-device benchmark with `quant`, `servedContextTokens`,
`indexOutputTokens`, `contextCapRate` and `evalScores` over **`gpqa, ifbench, ifstruct,
math_500, omniscience, bfcl_500, bfcl_small`**.
*Why:* MicroEvals is a first-class nav "Tool"; the mobile set is a genuine benchmark suite —
and it means the MCP's `UNTRACKED_BENCHMARKS` claim *"AA does not track BFCL (Berkeley
Function Calling)"* is **factually wrong**: AA publishes `bfcl_500`/`bfcl_small` on the
mobile-device set. `ifstruct` (IFStruct) is likewise unlisted.
*Recipe:* MicroEvals: fetch `/microevals?page=N` (20 cards) and `/microevals/<slug>`
(`responses[]` + `voteCount`), expose `aa_raw kind=microeval query=<slug>` and a search tool.
Mobile set: add `SOURCE_URLS["mobile"]="/hardware-inference-stack/mobile-phones"`, read the
90-row `evalScores` array, register the seven evals as benchmarks with a new
`aa_media`/`aa_hardware` board; fix the BFCL text in `catalog.UNTRACKED_BENCHMARKS`.
*Difficulty:* **hard** (MicroEvals: 562 pages, new pagination surface) / **moderate** (mobile set).

### 6. STT/STS full boards, per-dataset WER, STS components (PARTIAL → easy win, trivial)
*What:* the MCP's `speech_to_text` / `speech_to_text_streaming` / `speech_to_speech` boards are
the **homepage panels** (15/28/15 rows) while the real pages carry 36/45/80 rows plus
per-dataset WER (`earnings22CleanedWer`, `voxpopuliCleanedWer`, `aaSttDatasetWer`), streaming
latency, and the STS component split (Big Bench Audio, τ³-Voice, Arena score, task success).
*Why:* a 15-row panel is presented as the board; ~60% of the STT rows and ~80% of the STS rows
are unreachable.
*Recipe:* point `_SPEECH_BOARDS` at `/speech-to-text/non-streaming`,
`/speech-to-text/streaming` and `/speech-to-speech/arena` (the pages already parse as
`values/formatted`-style rows for the arena; STT needs the `aaWerIndex`-shaped arrays), and
add the per-dataset WER fields to `_MEDIA_BOARD_KEYS`.
*Difficulty:* **trivial**.

### 7. Search-API and Chatbot board detail (PARTIAL, trivial)
*What:* `search_api` exposes only `aaSearchQualityIndex` + `$/task` out of ~30 columns
(`browsecompAccuracy`, `deepsearchqaAvgF1`, `omniscienceAccuracy`, `avgLatencyS`,
`costPerSearchQueryUsd`, `answerTokensPerTask`, `isNativeSearch`, …); `chatbots` prints
`featuresScore` as a **percentage** (5.8 → "580.0%") and drops `priceMonthly`, the ~25
`supports*` flags, `connectors`, and `intelligenceIndex`.
*Why:* two of the three agent boards are effectively one-column. The percentage formatting is
also a plain correctness bug.
*Recipe:* widen `_AGENT_EXTRA_KEYS` and the default column set; treat `featuresScore` as a
0–6 score, not a percent (fix `_fmt`/unit selection for the chatbots board).
*Difficulty:* **trivial**.

---

## 4. Is "every single possible benchmark" true today?

**No.**

The MCP's `aa_benchmarks` returned **105 rankables** (57 benchmark, 16 derived, 15 arena,
13 index, 4 view) at recon time and returns **187** now. It covers the text/language
evaluation suite remarkably well: all 42 `/evaluations/<slug>` routes are catalogued by
`aa_raw kind=catalog`, and **all 42** are now reachable end-to-end — the 37 that map to a
benchmark slug, `artificial-analysis-decision-index` from its own page, and the four
Decision-Models pages (`when2call`, `wildguardtest`, `hle-multichoice`,
`aa-omniscience-decision`) which at recon time returned "no data" / "unknown benchmark".

But of the surfaces the site actually publishes:

The §2 table assesses **93** catalogued universe items. Tally:

| | before (recon) | after (post-implementation) | after (speech/search pass) |
|---|---:|---:|---:|
| FULLY COVERED | 38 | 66 | **77** |
| PARTIAL | 12 | 13 | **8** |
| MISSING | 38 | 9 | **3** |
| not published / not a benchmark | 5 | 5 | 5 |

**Second pass (see §8):** 11 more items moved to FULLY COVERED — the three speech boards
(full boards instead of the homepage panels), the STT per-dataset WERs, the STS components and
slices, the TTS pronunciation suite and its throughput/latency metrics, the Search API Index's
per-row metrics, and the TTS use-case sub-boards. **No addable benchmark is left MISSING**: the
3 remaining MISSING rows are one metric AA publishes no cross-model surface for (HLE Diamond)
and two non-benchmark surfaces (MicroEvals, the hardware pages).

**28 items moved into FULLY COVERED** — 27 out of MISSING and 1 (`Global-MMLU-Lite`,
5 → 17 models) out of PARTIAL: the Decision-Models family (4 evals), the six dead breakdown
containers, the omniscience domain/language splits, the 9 Openness components, the Multilingual
Index + its 16 languages, the silent video boards, the media category sub-boards, the on-device
benchmark set, and `medianCanonicalAnswerOutputSpeed`. **Two items moved MISSING → PARTIAL**
(`canonicalEvalTokenCounts`, readable per model but not a ranking column; and the TTS use-case
categories, whose boards are referenced by a `data` ref rather than a slug wrapper). See **§6**
for the itemised before/after with the call that proves each, and **§7** for what is left.

The **38 MISSING** rows the recon found were all data-bearing surfaces. Grouped:

* **4** decision-model evaluations (`When2Call`, `WildGuardTest`, `HLE-MultiChoice`,
  `AA-Omniscience-Decision`) — 28 scored rows each, today returning "no data"/"unknown";
* **6** eval-chart breakdowns (`briefcaseBreakdown`, `aa3dBreakdown`, `gdpvalBreakdown`,
  `harveyLabBreakdown`, `gdpPdfBreakdown`, `automationBenchBreakdown`) — declared in the
  catalog, reachable by no tool;
* **6** more eval-chart sub-metrics (`omniscienceBreakdown.byDomain`, `.bySweLanguage`,
  `opennessBreakdown` 9 components, `terminalBenchSciencePassRateByDomain`,
  `enterpriseOpsGymAvgConversationTurns`, `itbenchAvgTurnsPerTask`);
* **4** multilingual surfaces (Multilingual Index, per-language, Global-MMLU-Lite-by-language,
  the 13-row multilingual chart);
* **2** video audio/silent variants (T2V-Silent 31 rows, I2V-Silent 82 rows) and **5** media
  category/sub-board families (image T2I 19, image editing 17, video, TTS use-case 4,
  TTS controlled languages 11);
* **4** TTS/STT/STS sub-metrics (TTS pronunciation suite, TTS throughput/latency, STT
  per-dataset WER, STT streaming latency, STS components + slices);
* **2** other named benchmarks/surfaces: MicroEvals (11,228 prompt evals), the on-device/mobile
  benchmark set (incl. BFCL), plus `HLE Diamond` and the caching table.

Counting only *named benchmarks* (not sub-metrics or category boards), the headline number is
**~21**: the 4 decision evals, the 6 dead breakdowns, Multilingual Index, HLE Diamond,
T2V-Silent, I2V-Silent, MicroEvals, the mobile/on-device set, plus the openness/omniscience
domain-language splits.

**Headline: ~21 named benchmarks MISSING outright; 38 universe items MISSING overall; 12 PARTIAL.**

Two of the gaps are also **factual errors**, not just omissions:
1. `catalog.UNTRACKED_BENCHMARKS` says *"AA does not track BFCL"* — AA publishes
   `bfcl_500`/`bfcl_small` on `/hardware-inference-stack/mobile-phones`.
2. The container-benchmark hint (*"read one model's breakdown with
   `aa_model <slug> sections=benchmarks`"*) points at a code path that renders nothing.

---

## 5. What I could not determine

* **`/models/comparisons/*` (2,415 routes) and `/models/releases/*` (1,111)** — I sampled the
  parents only; they are A-vs-B / release-timeline views over data the MCP already has, not
  new metrics. I did not open individual comparison pages, so I cannot rule out a
  comparison-only metric.
* **`/hardware-inference-stack/datacenter`** — 727 KB payload with no benchmark array in the
  initial RSC response (data appears to be fetched lazily client-side). I could not confirm
  whether it publishes GPU/datacenter throughput numbers.
* **MicroEvals aggregate** — I confirmed per-microeval pages publish 14 model responses with
  `voteCount`, but found no cross-model MicroEvals leaderboard and no `/microevals/<slug>`
  route in the sitemap (the route works but is unlisted). Whether AA aggregates microeval votes
  into a model ranking is unresolved.
* **`messages.nav.search.categories.modelAnalysis`** — the facet has no route
  (`/models/analysis` 404s); I assume it is the client-side model-analysis search facet over
  `/models/<slug>`, but could not prove it.
* **`timescaleData`** (rich dataset key) — present per model, shape not inspected; may be a
  time series.
* **OpenAPI-only fields** — `huggingface_url`, `openrouter_api_id`, `provider.slug` etc. are in
  the paid-API schema; I checked the corresponding site payloads only where they appeared and
  did not exhaustively map every OpenAPI property to a site key.
* The `/evaluations/<slug>` pages for `when2call`, `wildguardtest`, `hle-multichoice`,
  `aa-omniscience-decision` share a single 28-row data array; I verified the shape on
  `when2call` and assumed the other three are identical (same byte-size class, same array
  signature).

---

## Appendix — key evidence (commands actually run)

```
# universe
curl -s --compressed -H 'User-Agent: Mozilla/5.0' https://artificialanalysis.ai/sitemap.xml   # 5,251 <loc>
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' https://artificialanalysis.ai/  # nav.config + 14 sections + 5 eval panels
curl -s --compressed -H 'User-Agent: Mozilla/5.0' https://artificialanalysis.ai/api/v2/openapi # 33 eval fields + media schemas
# rich dataset: /models/step-5 -> find_arrays(("chartDefaultSelected","releaseDate","suffix")) -> 703 x 94
# eval chart:   /evaluations/omniscience -> "initialModels" -> 31 x 88

# MCP side (proved)
.venv/bin/python eval/client.py call aa_benchmarks '{"verbose":true}'                    # 105 rankables
.venv/bin/python eval/client.py call aa_raw '{"kind":"catalog","fields":"slug"}'         # 42 eval slugs == sitemap
.venv/bin/python eval/client.py call aa_media '{"board":"speech_to_text","top":2}'       # 15 rows (site: 36)
.venv/bin/python eval/client.py call aa_media '{"board":"text_to_video_audio","top":2}'  # ERROR: unknown board
.venv/bin/python eval/client.py call aa_benchmark_leaderboard '{"benchmark":"when2call"}'# ERROR: no data
.venv/bin/python eval/client.py call aa_benchmark_leaderboard '{"benchmark":"hle-multichoice"}' # ERROR: unknown
.venv/bin/python eval/client.py call aa_benchmark_leaderboard '{"benchmark":"briefcaseBreakdown"}' # container error
.venv/bin/python eval/client.py call aa_model '{"query":"claude-opus-5-5"}'              # no breakdown rows
.venv/bin/python eval/client.py call aa_agents '{"board":"chatbots","top":8}'            # featuresScore shown as %
.venv/bin/python eval/client.py call aa_leaderboard '{"sort":"multilingual"}'            # ERROR: unknown sort
```

---

## Post-implementation corrections (2026-10-16)

Three claims in this recon were wrong. The counts the tools report were already correct;
the *rationales* were not, and are corrected here and in the code comments.

1. **Global-MMLU-Lite is charted on two pages that overlap, not two disjoint pages.**
   `/evaluations/global-mmlu-lite` charts 5 models and `/models/multilingual` charts 13, and
   `gemini-3-pro` is on **both** — so the union is **17**, not 18. Earlier wording in this
   document (and in the implementation comments) said "disjoint (5 + 13)"; `eval_models`
   unions the two pages by model slug and the reported coverage is 17.
2. **The four Decision-Models pages do not carry different per-eval metrics.** All four ship
   *one and the same* 28-row table, and their `scores` blobs are **byte-identical** (same five
   keys). Only the page-level primary `metric` differs (`when2callAccuracy`,
   `hleTextMcqAccuracy`, `wildguardtestAverageF1`, `omniscienceAccuracy`). The implementation
   therefore keys each page's own benchmark off that declared `metric` (authoritative), with
   the shared blob's keys mapped through a table for the companion scores.
3. **Elo display rounds half away from zero.** AA's own rendered string in the payload's
   `formatted.elo` shows `1146.5 -> "1147"` and `1092.5 -> "1093"`, where Python's `:.0f`
   rounds half-to-even and prints one lower. `catalog.format_value` now rounds half away from
   zero for the `elo` kind; a re-scan of all 31 media board/category arrays (7,596 Elo cells)
   finds **0** mismatches against the site's own rendered numbers.

---

## 6. Re-assessment (2026-10-16, post-implementation)

Every previously PARTIAL/MISSING item re-checked against the current tree; each "after" is
backed by the call in the last column (all run live, `AA_OFFLINE` unset). "before" is the
verdict this document recorded at recon time, kept so the delta is auditable.

| # | Item | before | after | Proof call |
|---|---|---|---|---|
| 5 | Openness components (9) | MISSING | **FULLY** | `aa_leaderboard {"sort":"openness.modelAvailability"}` → 25 scored; renders in `aa_model` |
| 10 | When2Call | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"when2call"}` → 28 scored |
| 11 | WildGuardTest | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"wildguardtest"}` → 28 scored |
| 12 | HLE-MultiChoice | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"hle-multichoice"}` → 28 scored |
| 13 | AA-Omniscience-Decision | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"aa-omniscience-decision"}` → 28 scored |
| 16 | Omniscience by domain (6) | MISSING | **FULLY** | `aa_leaderboard {"sort":"omniscience.domain.law"}` → 30 scored |
| 17 | Omniscience by SWE language (13) | MISSING | **FULLY** | `aa_leaderboard {"sort":"omniscience.language.python"}` → 30 scored |
| 19 | AA-3D breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"aa3dTurnsP50"}` → 22 scored |
| 25 | Terminal-Bench Science by domain | MISSING | **FULLY** | `aa_leaderboard {"sort":"terminalBenchScience.domain.life-sciences"}` → 24 scored |
| 29 | GDPval breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"gdpvalAvgTurns"}` → 31 scored |
| 31 | GDP.pdf breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"gdpPdfMacroPassRate"}` → 31 scored |
| 35 | ITBench avg turns | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"itbenchAvgTurnsPerTask"}` → 16 scored |
| 37 | AutomationBench breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"automationBenchStrictScore"}` → 31 scored |
| 39 | AA-Briefcase breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"briefcaseRubricPassRate"}` → 232 scored |
| 43 | Harvey breakdown | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"harveyCriteriaPass"}` → 23 scored |
| 45 | EnterpriseOps by domain / avg turns | MISSING | **FULLY** | `aa_leaderboard {"sort":"enterpriseOpsGym.domain.csm"}` → 9 scored; `benchmark=enterpriseOpsGymAvgTurns` → 12 |
| 48 | Global-MMLU-Lite | PARTIAL (5) | **FULLY** (17) | `aa_leaderboard {"sort":"globalMmluLiteScore"}` → chart set 17 scored (two pages unioned) |
| 49 | Global-MMLU-Lite by language | MISSING | **FULLY** | same data as `multilingual.<code>`; `aa_leaderboard {"sort":"multilingual.ja"}` → 4 joined |
| 50 | Multilingual Index | MISSING | **FULLY** | `aa_leaderboard {"sort":"multilingual"}` → chart set 13 scored |
| 51 | Multilingual by language (16) | MISSING | **FULLY** | `aa_leaderboard {"sort":"multilingual.ja"}`; 16 keys per row |
| 54 | medianCanonicalAnswerOutputSpeed | MISSING | **FULLY** | `aa_leaderboard {"sort":"medianCanonicalAnswerOutputSpeed"}` → 28 scored |
| 53 | canonical eval token counts | MISSING | PARTIAL | `aa_raw {"kind":"eval","query":"aa-briefcase"}` → `breakdowns.canonicalEvalTokenCounts` present (readable per model, not a ranking column) |
| 59 | Text-to-Image categories (19) | MISSING | **FULLY** | `aa_media {"board":"text_to_image","category":"marketing-and-advertising"}` → 90 rows |
| 61 | Image Editing categories (17) | MISSING | **FULLY** | `aa_media {"board":"image_editing","category":"…"}` (same mechanism; 17 published) |
| 63 | Text-to-Video **Silent** | MISSING | **FULLY** | `aa_media {"board":"text_to_video_silent"}` → 31 rows (vs `text_to_video` 28) |
| 65 | Image-to-Video **Silent** | MISSING | **FULLY** | `aa_media {"board":"image_to_video_silent"}` → 82 rows (vs `image_to_video` 23) |
| 66 | Video categories (T2V 20, VE 5) | MISSING | **FULLY** | `aa_media {"board":"text_to_video","category":"physics"}`; unknown slug errors with the published list |
| 69 | TTS use-case categories (4) | MISSING | PARTIAL | `aa_media {"board":"text_to_speech","category":"en-us"}` works, but the 4 use-case boards (`assistants`, `customer-service`, `entertainment`, `knowledge-sharing`) are declared in a `{"data":"$Q32","categories":[…]}` config and referenced by a `data` ref, not a `["slug",[rows]]` wrapper — `category=assistants` errors with only `en-gb, en-us` published |
| 71 | TTS controlled-voice languages (11) | MISSING | **FULLY** | `aa_media {"board":"text_to_speech_controlled","category":"ja"}` → 25 rows |
| 90 | On-device / mobile benchmark set | MISSING | **FULLY** | `aa_benchmark_leaderboard {"benchmark":"mobile.bfcl_500"}` → 17; `mobile.gpqa` → 57; `aa_benchmarks {"query":"on-device"}` → 7 evals |

Everything else in §2 keeps its recon verdict — re-verified live on the same date:
`aa_leaderboard {"sort":"hleDiamond"}` still errors (no cross-model surface);
`{"sort":"mmluPro"}` still "only published for deprecated models"; `{"sort":"math500"}` → 1
active; `aa_media {"board":"speech_to_text"}` → 15 rows, `speech_to_text_streaming` → 28,
`speech_to_speech` → 15; `aa_agents {"board":"chatbots"}` still renders `featuresScore` as
"580.0%"; `aa_providers fields=cache_read,cache_write` works but the caching table's
`cacheTtl`/`cacheMinimumTokens`/storage price are still absent.

## 7. Remaining gaps (the honest answer to "every benchmark on the site?")

**Still PARTIAL — 8** (was 13; the five speech/search rows moved to FULLY in §8)

| Item | Exactly what is missing | Benchmark? |
|---|---|---|
| AA Coding Index | no free per-model value exists (paid API only); constituents are covered | no — nothing on the site to scrape |
| AA Agentic Index | same | no — nothing on the site to scrape |
| AA Decision Index | joins 15 of 28 contestants to tracked models; the other 13 are decision-only entries (Clef, d1, Celeris-1 Decision, …) — the four constituents now cover all 28 | partly — the constituents already give the 28 rows |
| MMLU-Pro | only 1 non-deprecated model has a value in the current chart set | yes, but AA's live coverage is 1 → nothing to add |
| MATH-500 | same (1 active of 5 chart rows) | yes, but AA's live coverage is 1 → nothing to add |
| canonical eval token counts | exposed per model via `aa_raw kind=eval` `breakdowns`; not a ranking column (nested per-eval × 4 counters) | no — a cost/efficiency input |
| Chatbot board | `featuresScore` is printed as a percentage (5.8 → "580.0%") and only 1 of ~30 columns is exposed (`priceMonthly`, ~25 `supports*` flags, `connectors`, `intelligenceIndex`) | no — a product/feature board, not a benchmark; the display bug is a real defect |
| Caching table | `cacheTtl`, `cacheMinimumTokens`, `cacheStoragePricePerHourPer1mTokens`, `cacheAutoenabled` | no — pricing/ops metadata |

**Still MISSING — 3** (was 9; six rows moved to FULLY in §8)

| Item | What it is | Benchmark? |
|---|---|---|
| HLE Diamond | HLE subset, model pages only; AA publishes no cross-model column | yes in principle, but **not addable** — no site surface ranks it |
| MicroEvals | 11,228 user-submitted prompt evals; each page shows ~14 model responses with a vote count | **no** — user-voted response content, not an AA-run benchmark |
| Hardware pages | `/hardware-inference-stack/{laptops-workstations,datacenter}` (accelerator specs, `doesNotFitOn` model-fit); the datacenter page ships no benchmark array | **no** — hardware fit / inference content; the mobile-phones *benchmark* set is covered |

**Not benchmarks at all (checked, no data surface):** `/articles`, `/methodology/*`,
`/models/comparisons/*` (2,415 A-vs-B views), `/models/releases/*` (1,111), `/models/creators/*`,
`/models/recommend`, `/trends`, `/government`, `/about`, `/brand-kit`, `/changelog`, `/contact`,
`/faq`, `/data-api`, `/api-reference`, `/optima`, `/image-lab`, `/text-to-speech/voice-playground`,
`/text-to-speech/speech-explorer`, `/hardware-inference-stack/{datacenter,laptops-workstations}`,
and the image/video model-family detail pages — marketing, prose, or views over data the MCP
already serves.

**Verdict:** **no addable benchmark is left MISSING.** The 3 remaining MISSING rows are one
metric AA publishes no cross-model surface for (HLE Diamond) and two non-benchmark surfaces
(MicroEvals — user-voted prompt responses; the hardware/inference pages). The 8 PARTIAL rows are
likewise not addable benchmarks: two AA serves only through its paid API (Coding/Agentic Index),
two where AA's own live coverage is a single model (MMLU-Pro, MATH-500), one nested cost map
(canonical eval token counts), one pricing table (caching), one partly-joined index (Decision
Index — its four constituents now cover all 28 rows) and one **real defect that is not a
coverage gap**: the chatbot board's `featuresScore` is rendered as a percentage (5.8 →
"580.0%") and its other ~29 columns are not surfaced — that is a `server.py` display fix.

The honest answer to "does this cover every benchmark on the site?": **yes, with one caveat** —
every benchmark AA publishes is now reachable and rankable; what remains is a display bug on the
chatbot board and two AA-side surfaces that publish no cross-model data.


---

## 8. Second closing pass — the speech / voice / search gap (2026-10-16)

The §7 gaps are closed. Every claim below is a live call against the current tree.

### 8.1 The three speech boards now serve the **full** board

`loaders.SPEECH_BOARDS` maps the keys `home_boards` exposes to the page that carries the whole
board; `home_boards` prefers it and keeps the homepage's top-N panel as the fallback (a panel is
the same metric on a shorter list, never a different board).

| Board | was (homepage panel) | now (dedicated page) | route |
|---|---:|---:|---|
| `speech_to_text` | 15 | **36** | `/speech-to-text/non-streaming` |
| `speech_to_text_streaming` | 28 | **45** | `/speech-to-text/streaming` |
| `speech_to_speech` | 15 | **27** | `/speech-to-speech/arena` (the `overall` slice) |

The STS page's array is 80 rows, but only 27 of them are the `overall` slice — the other 53 are
the same models on the `agentic` (27) and `non_agentic` (26) slices, which would duplicate every
row in the board, the arena index and `aa_search`. The board therefore serves the `overall` slice
and each slice's Elo is registered separately (`stsOverallElo`, `stsAgenticElo`,
`stsNonAgenticElo`), so **all 80 rows are reachable** — as three rankable surfaces rather than one
board listing every model three times.

### 8.2 New rankables (39), each rankable through the standard paths

| Source page | slug | new rankables | live coverage |
|---|---|---|---|
| `/speech-to-text/non-streaming` | `stt` | `sttWerIndex`, `sttWordErrorRate`, `sttEarnings22Wer`, `sttVoxpopuliWer`, `sttAgenttalkWer` | 36 / 11 / 36 / 36 / 36 scored |
| `/speech-to-text/streaming` | `stt_streaming` | `sttStreamingWerIndex`, `sttStreamingEarnings22Wer`, `sttStreamingAgenttalkWer`, `sttStreamingTimeToFinal`, `sttStreamingTimeToFirstPartial` | 45 each |
| `/speech-to-speech/arena` | `sts` | `sts`, `stsOverallElo`, `stsAgenticElo`, `stsNonAgenticElo`, `stsTaskCompletionRate`, `stsBigBenchAudio`, `stsTauVoice`, `stsArenaScore`, `stsTaskSuccess` | 19 / 27 / 27 / 26 / 27 / 19 ×4 |
| `/text-to-speech/models` | `tts` | `ttsQualityElo`, `ttsPronunciationPassRate`, `ttsTermPronunciation`, `ttsTextNormalization`, `ttsSequenceFidelity`, `ttsContextualDisambiguation`, `ttsCharactersPerSecond`, `ttsGenerationTime` | 96 / 30 ×5 / 79 ×2 |
| `/agents/search-api` | `search-api` | `searchQualityIndex`, `searchBrowsecompAccuracy`, `searchDeepsearchqaF1`, `searchOmniscienceAccuracy`, `searchAvgLatency`, `searchCostPerQuery`, `searchCostPerTask`, `searchQueriesPerTask`, `searchQualityLift` | 26 each (25 for cost/query) |

Each is registered in `catalog.RANKABLES` with a real label/unit/tags/`how`, its WER/latency/cost
columns are marked lower-is-better, and each is reached by `aa_leaderboard sort=<key>` and
`aa_benchmark_leaderboard benchmark=<key>` (both proved for every key). The pages are reached
through `EXTRA_EVAL_PAGES` + `_CHART_ADAPTERS`, which turn each board's row shape into
chart-shaped records — the same mechanism the Decision-Models and on-device sets use.

Honest limits, not gaps: the board rows are their own model namespaces (a TTS voice is not a
language model), so `aa_pareto score=<key>` reports "no model has both" (these rows publish no
Intelligence-Index cost) and `aa_compare metrics=<key>` renders the metric but resolves rows
through `server.py`'s leaderboard/arena name index, which lists arena columns
(`elo`/`sts`/`wer`/`time_to_final`) rather than these board columns. Widening that is a
`server.py` change.

### 8.3 TTS use-case sub-boards reachable through `category=`

The TTS provider-voice page declares four use-case boards as `["<slug>","$Q…"]` **pairs**
pointing at other flight lines, not as inline `["<slug>",[<rows>]]` arrays, which is why
`aa_media category=` could not see them. `loaders._media_categories` now resolves both forms
(`_ref_rows`), so `aa_media board=text_to_speech category=assistants` returns 90 rows
(`knowledge-sharing` 97, `entertainment` 90, `customer-service` 92, alongside the inline
`en-us` 96 / `en-gb` 83).

### 8.4 What moved

11 §7 rows moved to FULLY COVERED: the three speech boards, STT per-dataset WER, STT streaming
latency, STS components, STS slices, the TTS pronunciation suite, TTS throughput/latency, the
Search API Index metrics, and the TTS use-case sub-boards. Tally now **77 FULLY / 8 PARTIAL /
3 MISSING / 5 not-a-benchmark** of the 93 assessed items.
