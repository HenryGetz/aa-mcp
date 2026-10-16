# VERIFY_COVERAGE — independent cross-check of the new benchmark surfaces

Date: 2026-10-16. Verifier: `verify-coverage` (independent; the report
`docs/process/COVERAGE_AUDIT.md` and the worker summary were **not** trusted).

Method: every raw value below was parsed from the live site flight payload
(`curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1'
https://artificialanalysis.ai/<route>`, newline-separated `<id>:<json>`, dicts
filtered, `$<id>` / `$Q<id>` back-references resolved) with a standalone parser
(no `aa_mcp` import on the raw side). Every MCP value came from
`.venv/bin/python eval/client.py call <tool> '<json>'`. Nothing in `src/`,
`tests/`, `docs/` (other than this file) or git state was modified.

Verdict summary: **8 PASS, 0 FAIL, 1 PASS-with-caveat (item 1)**. Two real
numeric/claim mismatches found (Elo banker's-rounding; "disjoint 5+13" is not
disjoint). Details below.

---

## 1. Decision-Models family — PASS (with caveat)

Routes: `/evaluations/{aa-omniscience-decision,hle-multichoice,when2call,wildguardtest}`.

* Row count: all four pages carry exactly **28** contestants (`contestants` array
  under `…children[0][3].children[3]`). Claim **28 rows** → confirmed.
* "Different per-eval metrics": **caveat — partially false.** The four pages'
  `contestants[i].scores` blobs are **byte-identical** (sha256 of the whole
  28-row array is `c07de594865282cb` on all four pages), and all four expose the
  same five keys `{omniscienceAccuracy, omniscienceNonHallucinationRate,
  hleTextMcqAccuracy, when2callAccuracy, wildguardtestAverageF1}`. What *does*
  differ per page is the page-level primary `metric`:
  `aa-omniscience-decision → omniscienceAccuracy`, `hle-multichoice →
  hleTextMcqAccuracy`, `when2call → when2callAccuracy`, `wildguardtest →
  wildguardtestAverageF1`. So "different per-eval metrics" holds for the page's
  *ranking metric*, not for the `scores` payload (which is a shared superset).

Raw vs MCP (raw slug is `creator_<slug>`; MCP strips the prefix):

| benchmark | model | raw `scores` | raw→% | MCP |
|---|---|---|---|---|
| when2call | d1-ultra | 92.5796 | 92.6% | 92.6% |
| when2call | claude-opus-5-5 | 90.5346 | 90.5% | 90.5% |
| when2call | claude-opus-5-5-low | 88.0514 | 88.1% | 88.1% |
| when2call | celeris-1-decision | 83.6985 | 83.7% | 83.7% |
| when2call | glide | 83.6693 | 83.7% | 83.7% |
| hle-multichoice | claude-opus-5-5 | 70.1754 | 70.2% | 70.2% |
| hle-multichoice | claude-opus-5-5-low | 59.8441 | 59.8% | 59.8% |
| hle-multichoice | gpt-6-1-sol | 58.8694 | 58.9% | 58.9% |
| hle-multichoice | gpt-6-1-sol-low | 55.3606 | 55.4% | 55.4% |
| hle-multichoice | claude-haiku-5-5 | 37.4269 | 37.4% | 37.4% |

Other two benchmarks, also `aa_benchmark_leaderboard {"top":5}`:

* `omniscienceDecision` (raw `omniscienceAccuracy`): 93.4 / 93.4 / 93.0 / 91.0 /
  73.6 — raw 93.4 / 93.4 / 93.0 / 91.0 / 73.6. Match.
* `omniscienceDecisionNonHallucination` (raw `omniscienceNonHallucinationRate`):
  84.5 / 69.3 / 55.1 / 54.6 / 48.8 — raw 84.5029 / 69.3396 / 55.0725 /
  54.6218 / 48.7923. Match.
* `wildguardtest` (raw `wildguardtestAverageF1`): 95.4 / 95.1 / 93.8 / 93.8 /
  93.6 — raw 95.3515 / 95.0532 / 93.7514 / 93.8272 / 93.6139. Match.

**No value mismatches.**

## 2. Multilingual Index — PASS (one claim nuance)

`/models/multilingual` carries a 13-model `initialModels` array; each row has
`multilingual` **and** `globalMmluLite` (same content) = `average` + **16**
language keys (`ar,bn,de,en,es,fr,hi,id,it,ja,ko,pt,sw,yo,zh,my`) = 17 keys.
Claim "average + 16 languages for 13 models" → confirmed.

`aa_leaderboard {"sort":"multilingual","top":5}` (default active-only) returns
**4 of 13**; `include_deprecated=true` returns the full set (needs `top≥13`).
Values (raw average → MCP):

| model | raw avg | raw→% | MCP |
|---|---|---|---|
| gemini-3-pro | 0.9222396 | 92.2% | 92.2% |
| claude-opus-4-5-thinking | 0.9127604 | 91.3% | 91.3% |
| gpt-oss-120b | 0.8278125 | 82.8% | 82.8% |
| llama-4-maverick | 0.8246354 | 82.5% | 82.5% |
| magistral-medium-2509 | 0.8156771 | 81.6% | 81.6% |
| k2-v2 | 0.7859896 | 78.6% | 78.6% |

Language score (`sort=multilingual.ja`, raw `multilingual.ja`):
gemini-3-pro 0.9316667→93.2% (MCP 93.2%), claude-opus-4-5-thinking
0.9258333→92.6% (92.6%), gpt-5-2-medium 0.9075→90.8% (90.8%),
claude-4-5-sonnet-thinking 0.9066667→90.7% (90.7%). Match.

`globalMmluLiteScore` union: `/evaluations/global-mmlu-lite` carries **5** rows
via `globalMmluLiteScoreByLanguage.average` (claude-opus-4-6-adaptive,
gemini-3-1-pro-preview, gemini-3-pro, gemini-3-flash-reasoning, gemini-3-flash)
and `/models/multilingual` carries **13** rows (`globalMmluLite`). **The two
selections are NOT disjoint**: `gemini-3-pro` appears in both, so the union is
**17, not 18**. The worker's stated *result* (17) is right; the stated *reason*
("disjoint selections: 5 + 13") is wrong. For the overlapping model the two
sources agree exactly (both `0.9222395833333334`). MCP
`aa_benchmark_leaderboard {"benchmark":"globalMmluLiteScore"}` reports
"17 of 17 scored" and lists all 17 with matching values.

## 3. Audio vs silent video boards — PASS

`/video/leaderboard/text-to-video` → `withAudioData` **28** rows,
`withoutAudioData` **31** rows. `/video/leaderboard/image-to-video` →
`withAudioData` **23**, `withoutAudioData` **82**. Both arrays exist on both
pages (values are `$Q…` refs to rows `3a`/`281`; resolve them, do not count
document order). Claim 28/31 and 23/82 → confirmed.

Silent I2V top-3, raw vs `aa_media {"board":"image_to_video_silent","top":3}`:

| raw (fmt Elo / raw Elo / appear / price) | MCP |
|---|---|
| Gemini Omni Flash 1368 / 1368.15 / 5,821 / $6.00/min | 1368, 5,821, $6.00/min |
| Bach 1.0 Pro 1362 / 1362.01 / 5,519 / $7.20/min | 1362, 5,519, $7.20/min |
| Wan 3.0 1362 / 1361.76 / 3,137 / $12.00/min | 1362, 3,137, $12.00/min |

Name / Elo / price / appearances all match; MCP header says "3 of 82" (the
silent arena count).

`aa_media {"board":"image_to_video","top":3}` still returns the **audio-capable**
arena: MiniMax H3 (768p) 1141/$5.40, Dreamina Seedance 2.5 1139/$24.60, Gemini
Omni Flash 1.1 1134/$9.12 — exactly the raw `withAudioData` top-3 (raw Elo
1140.59/1138.88/1134.12, appearances 4,009/3,475/3,176). Count "3 of 23" = the
audio arena. Cross-check: `text_to_video_silent` also matches the raw silent
T2V top-3 (Wan 3.0 1135, MiniMax H3 1121, MiniMax H3 Max 1119; "3 of 31").

## 4. Media categories — PASS (category arg IS available)

The `eval/client.py tools` summary does **not** list `category`, but the arg
exists and works (`server.py` `aa_media(board, …, category=…)`).
`/image/leaderboard/text-to-image` ships a 20-group array of `[category,
rows]` pairs (group 0 = overall, 104 rows). `marketing-and-advertising` has
**90** rows.

`aa_media {"board":"text_to_image","category":"marketing-and-advertising","top":5}`
returns "5 of 90" with the same names / Elo / appearances as the raw group:

| rank | raw name / raw Elo (raw float) / appear | MCP |
|---|---|---|
| 1 | GPT Image 2.5 Flare (max) / 1198 (1197.66) / 1,059 | 1198 / 1,059 |
| 2 | GPT Image 2 (high) / 1194 (1193.79) / 1,128 | 1194 / 1,128 |
| 3 | GPT Image 2.5 Sunburst (max) / 1192 (1192.04) / 1,097 | 1192 / 1,097 |
| 4 | MAI-Image-2.6 / 1167 (1167.34) / 795 | 1167 / 795 |
| 5 | Grok Imagine Image 2.0 / 1147 (1146.50) / 719 | **1146** / 719 ← mismatch |

**Mismatch #1 (Elo rounding).** The loader uses the raw float
(`values.elo = 1146.5`) and formats with Python `round`/`:.0f`, which is
banker's rounding → `1146`, while AA's own page displays `1147` (half-up). 1 of
90 rows in this category. Reproduced independently on the silent I2V board:
`Seedance 1.0 Mini` raw `1138.5`, AA displays `1139`, MCP rank 63 shows
**1138**. Scan of the fetched boards: 1/82 (I2V silent), 0/23 (I2V audio),
2/589 (T2V silent), 3/588 (T2V audio) rows differ by 1 Elo. Cosmetic but real:
the MCP disagrees with the site's own displayed Elo on `.5` values.

## 5. On-device / mobile set — PASS

`/hardware-inference-stack/mobile-phones` publishes a 90-row `models` array,
each with `evalScores` over **7** evals
(`bfcl_500, bfcl_small, gpqa, ifbench, ifstruct, math_500, omniscience`).
Non-null counts in the raw payload: `bfcl_500` **17**, `bfcl_small` **57**,
`gpqa` **57**, `ifbench` 55, `ifstruct` 11, `math_500` 57, `omniscience` 58.

`aa_benchmark_leaderboard {"benchmark":"mobile.bfcl_500"}` → "5 of **17**
scored": LFM2.5-8B-A1B 42.7% (raw 0.42733), Qwen3.5 4B 42.1% (0.42133),
Gemma 4 E4B 34.4% (0.344), Qwen3.5 2B 30.9% (0.30933), Gemma 4 E2B 28.6%
(0.286). Match.
`mobile.gpqa` → "5 of **57** scored": 79.5% (0.79495), 79.1% (0.79091), 79.1%,
77.6% (0.77576), 76.7% (0.76667). Match. Coverage counts confirmed (17 / 57).

## 6. BFCL correction — PASS

`aa_benchmarks {"query":"bfcl"}` returns two honest rows ("On-device BFCL-500"
17 scored, "On-device BFCL-Small" 57 scored) and **no** "AA does not track
BFCL" text. Both hints run cleanly:
`aa_leaderboard sort=mobile.bfcl_500` → "3 of 17" (LFM2.5-8B-A1B 42.7%, …);
`aa_leaderboard sort=mobile.bfcl_small` → "3 of 57". Values match raw.
Minor cosmetic: the column header is truncated to "On-device BF" (see item 8).

## 7. Breakdowns — PASS

`aa_model {"query":"claude-opus-5-5","sections":"benchmarks"}` vs the raw rich
array (`/models/step-5`, the ~703-row `models` array):

| field | raw | MCP |
|---|---|---|
| briefcaseBreakdown.analyticalQuality.elo | 2142.71 | Briefcase Analytical Elo 2143 |
| briefcaseBreakdown.presentation.elo | 1714.96 | Briefcase Presentation Elo 1715 |
| briefcaseBreakdown.rubricPassRate | 0.6121212 | Briefcase Rubric Pass 61.2% |
| briefcaseBreakdown.overall.elo | 1802.99 | AA-Briefcase Elo 1803 |

Second model `glm-4-5v` (raw rich record) vs
`aa_model {"query":"glm-4-5v","sections":"benchmarks"|"indexes"}`:
opennessIndex 52.7778→52.8 (MCP Openness 52.8), gpqa 0.572727→57.3%,
hle 0.034754→3.5%, ifbench 0.286395→28.6%, livecodebench 0.352381→35.2%,
aime25 0.153333→15.3%, omniscienceAccuracy 0.182167→18.2% (Omni Accuracy),
omniscienceHallucinationRate 0.902384→90.2% (Omni Halluc), omniscience
-55.5833→-55.6. All match. (The raw `openness` *components*
`modelAvailability=6, transparencyMethodology=3, …` are not surfaced by
`aa_model`; only the index value is, so components were not cross-checkable via
`aa_model` — the openness *index* matches.)

## 8. Catalog sanity sweep — PASS

`len(catalog.RANKABLES)` = **187** (matches the worker's claim; the pre-change
audit said 105).

Kind counts: `benchmark` 106, `index` 46, `derived` 16, `arena` 15, `view` 4.
Surface counts: `chart` 110, `leaderboard` 36, `rich` 24, `board` 15, `none` 2.

Every rankable's `how` hint is well-formed: all 187 match `aa_<tool> …` (or are
the literal `—`); **0 malformed**. 16 sampled hints (one per new family, plus
derived/view/leaderboard controls) were actually executed through the MCP and
all returned `error=False`:

`when2call, hleMultichoice, omniscienceDecision` (decision) ·
`multilingual.ja` (multilingual) · `globalMmluLiteScore` (global-MMLU) ·
`mobile.bfcl_500` (mobile) · `text_to_image` (arena board) ·
`briefcaseAnalyticalQualityElo` (breakdown) · `openness.modelAvailability` ·
`omniscience.domain.business` · `terminalBenchScience.domain.life-sciences` ·
`enterpriseOpsGym.domain.csm` · `tps` (derived) · `intelligence_vs_speed`
(view) · `coding`→scicode · `agentic`→terminalBench40.

Cosmetic defect seen in these runs: `aa_leaderboard` truncates the metric
column header to 12 characters, so the header reads "HLE-MultiCho",
"AA-Omniscien", "Global-MMLU-", "On-device BF", "Briefcase An", "Openness · M",
"TB-Science ·", "EnterpriseOp". Display-only; values are correct.

## 9. Regressions — PASS

* `AA_OFFLINE=1 uv run pytest` → **687 passed** in 32.4s, 0 failed.
* `uvx ruff check .` → **All checks passed!**
* `scripts/surface_sweep.py` (live) → **UNEXPECTED FAILURES: 0**; 20 documented
  expected failures (unknown sort/x/domain/category, paid-only Coding/Agentic
  indexes, container benchmarks, etc.). Run clean.

---

## Mismatch list

1. **Elo banker's-rounding** (`aa_media`): rows whose raw Elo ends in `.5`
   render 1 lower than AA's own page. Confirmed on
   `text_to_image/marketing-and-advertising` (Grok Imagine Image 2.0: MCP 1146
   vs AA 1147, raw 1146.5) and `image_to_video_silent` rank 63 (Seedance 1.0
   Mini: MCP 1138 vs AA 1139, raw 1138.5). Board scan: 1/82, 0/23, 2/589,
   3/588. Cause: `values.elo` float + `round()`/`:.0f` (banker's) instead of
   AA's half-up display.
2. **"Disjoint 5 + 13" is false**: `gemini-3-pro` is on both the
   `/evaluations/global-mmlu-lite` (5) and `/models/multilingual` (13)
   selections, so the union is 17, not 18. The reported count (17) and the
   values are still correct; only the stated rationale is wrong.
3. **"Four decision pages carry different per-eval metrics" is only half true**:
   the 28-row `scores` blobs are byte-identical across all four pages (same 5
   keys, same values); only the page-level primary `metric` differs.
4. **Multilingual Index default view is thin**: `aa_leaderboard sort=multilingual`
   (active-only) shows 4 of 13; the remaining 9 need `include_deprecated=true`.
   The footer discloses "13 scored in the dataset", so this is honest but the
   default surface understates coverage.
5. **Cosmetic**: rankable label truncated to 12 chars in `aa_leaderboard`
   headers ("On-device BF", "HLE-MultiCho", …).

## Not verified / limits

* `openness` *component* breakdowns are not exposed by `aa_model`, so only the
  openness index (52.8) could be cross-checked, not its 9 components.
* Live values drift: the MCP cache and the site are refreshed independently, so
  a re-run minutes later can move numbers slightly. All comparisons above were
  made from the same-hour snapshots.
* `scripts/surface_sweep.py` ran to completion but is a self-consistency sweep
  (it asserts the MCP's own documented expectations), not an independent
  raw-vs-MCP check; the raw-vs-MCP work is items 1–7.

## Verdict

The new surfaces are **trustworthy**. Every one of the eight families I could
cross-check against the live site payloads — the 4 decision evals (28 rows,
5 metrics), the Multilingual Index (13 models × 16 languages) and the 17-row
Global-MMLU-Lite union, the audio/silent video arenas (T2V 28/31, I2V 23/82)
including the silent I2V top-3, media category sub-boards (90-row
marketing-and-advertising), the 90-row × 7-eval mobile set (BFCL-500 17,
GPQA 57), the BFCL correction, and the briefcase/openness/GPQA breakdowns —
returned values that match the raw payloads to the published precision, and the
catalog's 187 rankables are well-formed with working hints (16/16 sampled ran
clean). The only numeric defect is a banker's-rounding off-by-one on Elo values
that end in `.5` (a handful of rows per board), and two claim-level inaccuracies
in the worker's narrative (the "disjoint 5+13" union and the "different
per-eval metrics" phrasing) that do not affect the exposed data. 687/687 tests
pass, ruff is clean, and the live surface sweep reports 0 unexpected failures.
The one caveat worth acting on is the `.5` Elo rounding, which makes the MCP
disagree with the site's own displayed value on those rows.

---

**Checks passed: 8/9** (item 1 PASS-with-caveat; items 2–9 PASS).
**Mismatches found: 3 substantive** (Elo `.5` rounding; "disjoint 5+13"
false → union 17 not 18; "different per-eval metrics" false at the `scores`
level) **+ 2 minor/cosmetic** (thin default multilingual view; 12-char header
truncation).

**3 worst findings:**
1. `aa_media` Elo is 1 lower than the site's displayed value on rows whose raw
   Elo ends in `.5` (banker's rounding) — e.g. Grok Imagine Image 2.0 1146 vs
   1147, Seedance 1.0 Mini 1138 vs 1139.
2. The Global-MMLU-Lite "5 + 13 disjoint" union is not disjoint
   (`gemini-3-pro` is in both); the true union is 17, not 18 — the worker's
   count is right but the reasoning behind it is wrong.
3. The claim that the four decision pages "carry different per-eval metrics" is
   false at the `scores` level: all four ship an identical 5-metric blob; only
   the page-level ranking metric differs.
