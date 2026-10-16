# Where artificialanalysis.ai publishes its indexes (free pages only)

Recon date: **2026-10-15**. Everything below was measured against live responses from
`https://artificialanalysis.ai` with no API key. Reproduce with `python3 /tmp/recon_indexes.py`
(prints `name, source, coverage, 3 samples` for every index).

---

## 0. How every fetch in this document works

The site is Next.js App Router. Requesting any route with the `RSC: 1` header returns the
React Server Component **flight payload** instead of HTML — that payload contains the same
data the page renders, as JSON. It is a newline-separated stream of `<lineId>:<json>` records;
parse each line's JSON after the first `:` and walk it.

```bash
curl -s --compressed \
  -H 'User-Agent: Mozilla/5.0' \
  -H 'RSC: 1' \
  'https://artificialanalysis.ai/<route>'
```

Two gotchas:

* Arrays in the payload may contain **string back-references** (`"$29:props:children:props:rows:0"`)
  instead of objects — they point at nodes elsewhere in the same (or a lazily fetched) payload.
  Filter `isinstance(x, dict)` and resolve the page's `currentModel` separately (see §3).
* `GET /leaderboards/models` (192 KB compressed) contains **703 model variants × ~50 keys**
  (`[3].children[0][3].models[]`), but **none of the indexes below** — only `intelligenceIndex`
  plus raw eval scores. `/leaderboards/providers` (1 199 endpoint rows at
  `[3].children[1][3].children[0][3].rows[]`) is likewise index-free.

AA's own machine-readable metadata for the six capability indexes is in the nav config that
ships with **every** page (`…messages.nav.config.languageModels.capabilities.config`):

```json
"capabilities":{"config":{
  "financeAndAccounting":{"name":"Finance & Accounting Index","shortName":"Finance & Accounting", …},
  "strategyAndOps":      {"name":"Strategy & Ops Index",       "shortName":"Strategy & Ops",       …},
  "legal":               {"name":"Legal Index",                "shortName":"Legal",                …},
  "healthcareAndMedical":{"name":"Healthcare & Medical Index", "shortName":"Healthcare & Medical", …},
  "engineering":         {"name":"Engineering Index",          "shortName":"Engineering",          …},
  "economics":           {"name":"Economics Index",            "shortName":"Economics",            …}}}
```

The sibling `…nav.config.languageModels.capabilities` object is AA's complete **"Indexes"**
nav dropdown, and it lists only five entries — `codingAgentIndex`, `searchIndex`, `cyberIndex`,
`decisionIndex`, `opennessIndex`. There is no "coding index" and no "agentic index" entry
(see §5).

---

## 1. Coverage table

`703` = the number of model variants on `/leaderboards/models`. "Subset" = a curated
chart selection, not a leaderboard.

| # | Index | Free source URL | JSON key path | Coverage | Full leaderboard or subset |
|---|---|---|---|---|---|
| 1 | **Artificial Analysis Coding Agent Index** (a.k.a. "AA Coding Index") | `/agents/coding-agents` (also `/`) | `[3].children[3].benchmarkRows[]` → `indexScore`; on `/` → `[3].rows[]` → `indexScore` | **41 coding-agent rows** (33 inline + 8 lazy back-refs) — *agents, not the 703 model variants* | Full leaderboard (agent-level) |
| 2 | **AA Agentic Index** | — | — | **0 — not published anywhere free** | — |
| 3 | **Finance & Accounting Index** | `/models/capabilities/finance-and-accounting` (also `/`) | `[3].initialModels[]` → `weightedIndex`; full matrix → `…models[]` → `capabilities.financeAndAccounting` | **221 / 703** (chart subset = 26) | Subset on the index page; full coverage only via a model page |
| 4 | **Strategy & Ops Index** | `/models/capabilities/strategy-and-ops` (also `/`) | `[3].initialModels[]` → `weightedIndex`; `capabilities.strategyAndOps` | **221 / 703** (chart subset = 26) | Subset / full via model page |
| 5 | **Legal Index** | `/models/capabilities/legal` (also `/`) | `[3].initialModels[]` → `weightedIndex`; `capabilities.legal` | **221 / 703** (chart subset = 26) | Subset / full via model page |
| 6 | **Healthcare & Medical Index** | `/models/capabilities/healthcare-and-medical` (also `/`) | `[3].initialModels[]` → `weightedIndex`; `capabilities.healthcareAndMedical` | **82 / 703** (chart subset = 20) | Subset / full via model page |
| 7 | **Engineering Index** | `/models/capabilities/engineering` (also `/`) | `[3].initialModels[]` → `weightedIndex`; `capabilities.engineering` | **220 / 703** (chart subset = 26) | Subset / full via model page |
| 8 | **Economics Index** | `/models/capabilities/economics` (also `/`) | `[3].initialModels[]` → `weightedIndex`; `capabilities.economics` | **228 / 703** (chart subset = 26) | Subset / full via model page |

**How the coverage numbers were counted (two independent ways, agreeing exactly):**

1. Counting non-null numerics in the 703-entry array embedded on a model page (§3):
   finance 220 + 1 (`currentModel`) = **221**, strategy 221, legal 221, healthcare 81 + 1 = **82**,
   engineering 219 + 1 = **220**, economics 227 + 1 = **228**.
2. AA's own published counts, shipped as `placeholderTotalCount` next to each capability
   selector on model pages:

```json
{"capability":"financeAndAccounting","placeholderTotalCount":221}
{"capability":"strategyAndOps","placeholderTotalCount":221}
{"capability":"legal","placeholderTotalCount":221}
{"capability":"healthcareAndMedical","placeholderTotalCount":82}
{"capability":"engineering","placeholderTotalCount":220}
{"capability":"economics","placeholderTotalCount":228}
```

(The other `placeholderTotalCount` values seen on those pages are `703` = all models and
`220/231/326/577` = other selectors.)

---

## 2. The six Capability Indexes — how to fetch

Each has its own public page (listed in `sitemap.xml`):

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' \
  'https://artificialanalysis.ai/models/capabilities/finance-and-accounting'
# → parse each `<id>:<json>` line, then take  [3].initialModels[]
#   score = item.weightedIndex  (identical to item.headlineValue)
```

`[3].initialModels[]` is the page's curated chart set: **26 models** for finance-and-accounting,
strategy-and-ops, legal, engineering, economics and **20** for healthcare-and-medical. It is a
subset, not a leaderboard. Item shape (trimmed):

```json
{
 "slug": "claude-opus-5-5",
 "name": "Claude Opus 5.5 (Max, Default Fallback)",
 "intelligenceIndex": 57.6223698102963,
 "headlineValue": 65.6045449876429,
 "weightedIndex": 65.6045449876429,
 "subScores": { "knowledge": 66.35, "reasoning": 61.353104726598694,
                "longContext": 84.6666666666667, "agenticKnowledgeWork": 66.7005 }
}
```

`subScores` keys differ per index (they mirror the "Capabilities evaluated" description):
finance/legal/healthcare = `knowledge, reasoning, longContext, agenticKnowledgeWork,
agenticToolUse, nonHallucination`; strategy = `knowledge, longContext, agenticKnowledgeWork,
agenticToolUse`; engineering = `knowledge, reasoning, agenticKnowledgeWork,
agenticTerminalUse`; economics = `knowledge, reasoning, longContext, agenticKnowledgeWork`.

The **homepage** carries the same 26/20-row set (same values) at a different path:

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' 'https://artificialanalysis.ai/'
# → [3].initialData[]  where items are model-shaped (they carry "capabilities")
#   NOTE: the payload also contains a *creator*-shaped [3].initialData[] (59 rows,
#   keys id/name/slug/logo/color/country/modelIds) — pick the one whose [0] has "capabilities".
```

```json
{"slug":"step-5","name":"Step 5 Preview",
 "capabilities":{"financeAndAccounting":45.3728047646677,"strategyAndOps":47.1241657884068,
  "legal":46.2280066508375,"healthcareAndMedical":40.8171769208551,
  "engineering":44.9763545147623,"economics":52.8491063677788}}
```

**Sample values (spot-checkable, identical across all three sources):**

| Index | claude-opus-5-5 | claude-sonnet-5-5 | claude-fable-5-1 |
|---|---|---|---|
| Finance & Accounting | 60.73 | 57.23 | 56.42 |
| Strategy & Ops | 63.68 | 59.62 | 59.67 |
| Legal | 63.26 | 57.90 | 60.49 |
| Healthcare & Medical | 60.54 | 58.06 | 58.00 |
| Engineering | 60.35 | 58.37 | 55.40 |
| Economics | 65.60 | 60.84 | 62.67 |

(Values from the capability pages' `weightedIndex` / the homepage's `capabilities.*`; the
rich 703-model array reproduces them exactly, e.g. `claude-opus-5-5.economics = 65.6045449876429`.)

There is also a landing page at `/models/capabilities` (linked from the homepage "Capability
Indexes" section). It is client-rendered — it ships only the index metadata
(`messages.page.skillsHeading = "By Skill"`, `domainsHeading = "By Domain"`) plus the nav
config; the list of index cards is not in the RSC payload. Use the six URLs above instead.

---

## 3. Full-coverage source: the 703-model array embedded on *some* model pages

A model page can embed the complete model matrix (703 entries × 80 keys) including the six
capability indexes. Key path:

```
[3].children[0][3].children[3].children[1][3].children[1][3].children[0][3].models[]
                                                          → item.capabilities.<indexKey>
```

```json
{"slug":"claude-opus-5-5","name":"Claude Opus 5.5 (Max, Default Fallback)",
 "intelligenceIndex":57.6223698102963,
 "capabilities":{"financeAndAccounting":60.7295442846867,"strategyAndOps":63.6788820379322,
  "legal":63.2602763791642,"healthcareAndMedical":60.5359874288733,
  "engineering":60.3546025055266,"economics":65.6045449876429}}
```

Recipe:

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' \
  'https://artificialanalysis.ai/models/step-5'
# walk each `<id>:<json>` line for the list under key "models" with >100 dict items
# whose first item has a "capabilities" dict; also read the node under "currentModel"
# (the array stores the page's own model as a back-reference at index 35, so add it back).
```

### Stability — this array is NOT on every model page

I sampled 40 model routes (every 11th single-segment `/models/<slug>` in `sitemap.xml`,
`2026-10-15`) and classified each by whether the 703-row capabilities array was present:

* **32 / 40 — present** (full 703×80 array, ~3.2 MB decompressed payload)
* **7 / 40 — absent**, page instead embeds only a **27-model** subset at
  `[3].children[3].children[3].initialModels[]` (~0.7–0.8 MB payload). Same six keys, same
  values, just a much smaller set. Examples: `gpt-6-luna`, `gpt-6-luna-medium`,
  `gpt-6-luna-non-reasoning`, `gpt-6-astra-xhigh`, `claude-haiku-5-5`,
  `claude-opus-5-5-medium`, `glm-5-3`, `gemini-3-8-flash-low`, `gemma-4-26b-a4b`,
  `nova-2-0-lite`, `nova-2-0-omni`, `qwen3-8-27b`, `qwen3-8-27b-low`, `qwen3-5-397b-a17b`, `kimi-k3`.
* **1 / 40 — neither** (`nova-2-0-pro-preview`).

The split is **deterministic per URL** (re-fetching, adding cache-busting query params, and
`x-vercel-cache: HIT` all return the same variant; the payload even carries
`"manifest":{"path":"/data/<hash>.txt","key":"…"}` on the reduced variant). It is not
correlated with `deprecated`, `chartDefaultSelected`, `microevalsEnabled`, having a
`/providers` page, or being a release slug — recent models skew toward the reduced variant,
but `nova-2-0-lite` (released 2025-10-29) is reduced while many 2026 models are full, so
there is **no public rule** to rely on. Treat the full matrix as opportunistic: try a known-good
page and fall back.

**Verified full-coverage pages (checked again at the end of this recon, all `occ=225`):**
`/models/step-5`, `/models/minimax-m3`, `/models/gemini-4-argon`, `/models/longcat-2-0`.

**Verdict:** the rich 699×94-style dataset is *reachable* from a stable, discoverable URL
pattern, but *not guaranteed* for a given model page. For the six capability indexes the
practical recipe is: read the 26/20-row subset from `/models/capabilities/<slug>` (always
available), and use a verified-full model page when you need all 221/82/220/228 values.

---

## 4. The Coding Agent Index — how to fetch

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' \
  'https://artificialanalysis.ai/agents/coding-agents'
# → [3].children[3].benchmarkRows[]      (41 entries; 33 inline dicts, 8 are lazy back-refs)
#   score = item.indexScore              (raw 0–1 fraction; the site displays indexScore × 100)
```

Complete 41-row copy (all dicts) is on the homepage:

```bash
curl -s --compressed -H 'User-Agent: Mozilla/5.0' -H 'RSC: 1' 'https://artificialanalysis.ai/'
# → [3].rows[] → indexScore              (41 rows)
```

Row shape (trimmed) and the page's own definition of the index:

```json
{"agentName":"Muse Code 1.0.2 RC","provider":"meta",
 "display":{"agent":"Muse Code","model":"Muse Spark 1.3 (xhigh)"},
 "displayLabel":"Muse Code - Muse Spark 1.3 (xhigh)",
 "indexComponentCount":3,"evalCount":3,
 "indexScore":0.482993172759088,
 "evals":[{"datasetIndexName":"deep-swe-v1.1","evaluationDatasetSlug":"DeepSWE v1.1",
           "weight":0.333333333333333,"mean":{"reward":0.731563421828909}}, …]}
```

> "The Artificial Analysis Coding Agent Index is our composite score for coding-agent
> performance across the public benchmark suite on this page. It combines DeepSWE v1.1,
> Terminal-Bench 4.0, and SWE-Atlas-QnA …"
> — FAQ JSON-LD on `/agents/coding-agents`; methodology at `/methodology/coding-agents-benchmarking`.

Scale check: the article `/articles/cursor-composer-2-5-coding-agent-index` states
"Composer 2.5 scored **62** on our Coding Agent Index", and the payload stores Composer's
`indexScore` as `0.62…` → **`indexScore` is a 0–1 fraction; ×100 = the displayed score.**

Top 3 rows (spot-checkable):

| Row (`displayLabel`) | `indexScore` | displayed |
|---|---|---|
| Claude Code – Sonnet 5.5 (max) | 0.6835783373750831 | 68.4 |
| Devin Fusion CLI – Claude Opus 5.5 Max + GPT-6 Luna High | 0.6810374657220217 | 68.1 |
| Muse Code – Muse Wonder Full (max) | 0.6803093740718634 | 68.0 |

**Scope warning:** these 41 rows are **agent × model harness combinations** (`agentName`,
`display.model`), not the 703 model variants. There is no per-model coding index on any free
page — see §5.

---

## 5. Indexes that are NOT published on any free page

### 5.1 "AA Coding Index" (model-level) — does not exist free

The only coding index AA publishes publicly is the **agent-level Coding Agent Index** in §4.
Evidence:

* `sitemap.xml` (5 110 URLs) contains exactly one non-article coding route:
  `https://artificialanalysis.ai/agents/coding-agents` (plus `/agents/coding-agents/comparisons/*`
  and `/methodology/coding-agents-benchmarking`). There is no `/…/coding-index` route.
* `grep` for `"codingIndex"` / `"Coding Index"` over the RSC payloads of `/`, `/leaderboards/models`,
  `/leaderboards/providers`, `/agents/coding-agents`, `/agents/chatbots`, `/agents/search-api`,
  `/evaluations`, four `/evaluations/<slug>` pages, 50+ `/models/<slug>` pages, all seven
  `/models/capabilities*` pages, `/data-api`, `/api-reference`, `/methodology` → **0 hits**.
  (`"codingAgentIndex"` / `"codingAgentsIndex"` exist, but they are nav labels for the
  agent-level index.)
* `/leaderboards/models` model objects have **no** coding-index field (keys: `intelligenceIndex`,
  `omniscience*`, `gdpvalNormalized`, `analystAgent`, `terminalbenchHard`, `terminalBench21`,
  `terminalBench40`, `tau2`, `tauBanking`, `lcr`, `hle`, `gpqa`, `scicode`, `ifbench`, `critpt`,
  `apexAgents`, `itbenchSre`, `mmmuPro`, prices/speeds …). Its "Coding" table *column group*
  is backed by those raw eval scores, not by a composite index.
* `/evaluations/<slug>` `initialModels[]` rows (78–86 keys) do carry `cyberIndex` and
  `opennessIndex`, but **not** any coding or agentic index.

### 5.2 "AA Agentic Index" — not published anywhere free

Evidence:

* **Routes:** `grep -i agentic sitemap.xml` returns only `/articles/*` pages
  (`…-agentic-knowledge-work`, `…-agentic-cost`, `…-agentic-real-world-knowledge-tasks`, …).
  No `/agentic*` route exists.
* **Keys:** `grep` for `"agenticIndex"` / `"Agentic Index"` over the same payload set as §5.1
  → **0 hits**. The token "agentic" only ever appears as
  (a) `Agentic Knowledge Work`, `Agentic Tool Use`, `Agentic Terminal Use`, `Agentic Office
  Work`, `Agentic Coding & Terminal Use` — *sub-scores / benchmark labels* used inside the
  capability indexes and the models leaderboard, and
  (b) the nav/`messages` strings for those labels.
* **AA's own index inventory** (nav config, present on every page) is
  `codingAgentIndex, searchIndex, cyberIndex, decisionIndex, opennessIndex` — no agentic entry.
  Their public homes are `/agents/coding-agents`, `/agents/search-api`
  (`aaSearchIndex`/`aaSearchQualityIndex`), `/evaluations/artificial-analysis-cyber-index`,
  `/evaluations/artificial-analysis-decision-index`,
  `/evaluations/artificial-analysis-openness-index`.
* **Only mention of a model-level Coding/Agentic index anywhere:** the paid Data API marketing
  page `/data-api`:

  > "Intelligence, Coding, Agentic, Math, Openness, and Multilingual Index scores for every
  > tracked model, plus Capability Indexes for six industries."

  alongside `GET /api/v2/language/models`. That is the paid API (`/api-reference` is a stub
  here), not a free page. No free payload contains such fields.

### 5.3 Related: how much coverage other indexes do get (for comparison)

| Index | Free source | Coverage |
|---|---|---|
| Openness Index | `/evaluations/artificial-analysis-openness-index` → `[3].models[]` → `opennessIndex` | **326** models (a genuine full array) |
| Cyber Index | `/evaluations/artificial-analysis-cyber-index` → `[3].children[0][3].children[3].initialModels[]` | 20 (subset) |
| Decision Index | `/evaluations/artificial-analysis-decision-index` → same path | subset |
| Intelligence Index | `/evaluations/artificial-analysis-intelligence-index` → same path | 31 (subset); full 703 via `/leaderboards/models` |
| Omniscience Index | `/leaderboards/models` → `omniscience` | 703 |

So AA *does* ship full index leaderboards for some indexes (Openness: 326). The six capability
indexes are the exception — their public pages are 26/20-row subsets, and the only way to get
the full 221/82/220/228 rows is the opportunistic 703-model array on a model page (§3).

---

## 6. TL;DR for an implementation

| Need | Do this |
|---|---|
| Any of the six capability indexes, top ~26 models | `GET /models/capabilities/<slug>` with `RSC: 1`; read `[3].initialModels[].weightedIndex` |
| All 221/221/221/82/220/228 capability values | `GET /models/<verified-rich-slug>` with `RSC: 1`; walk to the `models` list (>100 dict items) whose items have `capabilities`; resolve the `currentModel` back-reference. Re-verify the page is still "rich" before relying on it (32/40 hit rate). |
| Coding Agent Index (41 agent rows) | `GET /` with `RSC: 1`; read `[3].rows[].indexScore` (×100 for display). `/agents/coding-agents` → `[3].children[3].benchmarkRows[].indexScore` is equivalent but 8 rows are lazy back-refs. |
| Agentic Index | **No free source exists.** |
| Model-level Coding Index | **No free source exists** (paid `/api/v2/language/models` advertises one). |

## Static bundle recon (independent method)

Method: read the site's own client code (Next.js chunks) and route table, not the
payloads. Captured 2026-10-15.

### Commands

```bash
mkdir -p /tmp/bundle && cd /tmp/bundle
curl -sfL -H "User-Agent: Mozilla/5.0" --compressed \
  https://artificialanalysis.ai/leaderboards/models -o lb.html          # 2,483,187 B

# every chunk the leaderboard page references (+ app-router chunks)
grep -o '/_next/static/chunks/[A-Za-z0-9._%/-]*\.js' lb.html | sort -u | tee chunks.txt
# 39 URLs; downloaded all to js/ (1.6 MB total), 0 failures
while read -r u; do
  curl -sfL -H "User-Agent: Mozilla/5.0" --compressed \
    "https://artificialanalysis.ai$u" -o "js/$(echo "$u" | sed 's#/_next/static/chunks/##; s#/#__#g')"
done < chunks.txt
```

### Route table

| route | named by (chunk) | exists | payload keys carrying index values | coverage | 3 sample model values |
|---|---|---|---|---|---|
| `/models/capabilities` | `app__%5Blocale%5D__layout-*.js` (`defaultLeaves:Object.values(eP.M)`, `href:"/models/capabilities/".concat(slug)`) | **200**, 243,074 B | nav/index page; lists the six | 6 links | — |
| `/models/capabilities/finance-and-accounting` | `js/16633-34df69561cec0ce5.js` module `70926`: `financeAndAccounting:"finance-and-accounting"` | **200**, 405,143 B | `headlineValue`, `weightedIndex`, `subScores{knowledge,reasoning,longContext,agenticToolUse,agenticKnowledgeWork,nonHallucination}` | **26** rows | claude-opus-5-5 **60.73**, claude-sonnet-5-5 57.23, muse-wonder-full 54.15 |
| `/models/capabilities/strategy-and-ops` | `js/16633-…js` mod 70926 | **200**, 396,847 B | same | **26** | claude-opus-5-5 **63.68**, claude-sonnet-5-5 59.62, muse-wonder-full 57.77 |
| `/models/capabilities/legal` | `js/16633-…js` mod 70926 | **200**, 406,219 B | same | **26** | claude-opus-5-5 **63.26**, claude-sonnet-5-5 56.44, muse-wonder-full 54.73 |
| `/models/capabilities/healthcare-and-medical` | `js/16633-…js` mod 70926 | **200**, 397,390 B | same | **20** | claude-opus-5-5 **60.54**, claude-sonnet-5-5 58.06, claude-fable-5-1 58.00 |
| `/models/capabilities/engineering` | `js/16633-…js` mod 70926 | **200**, 396,077 B | same | **26** | claude-opus-5-5 **60.35**, claude-sonnet-5-5 58.37, muse-wonder-full 56.97 |
| `/models/capabilities/economics` | `js/16633-…js` mod 70926 | **200**, 387,634 B | same | **26** | claude-opus-5-5 **65.60**, claude-sonnet-5-5 60.84, muse-wonder-full 60.73 |
| `/models/<slug>` (rich model page) | n/a (known surface) | **200**, 753,590 B | `capabilities:{financeAndAccounting,strategyAndOps,legal,healthcareAndMedical,engineering,economics}` **per model** | all models with the evals | claude-opus-5-5 → FA 45.37, SO 47.12, Legal 46.23, H&M 40.82, Eng 44.98, Econ 52.85 |
| `/methodology/capability-indices` | `sitemap.xml` | **200**, 245,355 B | prose only (no per-model values) | — | — |

The six-slug registry is exactly module `70926` in `js/16633-34df69561cec0ce5.js`:

```js
70926:(e,n,i)=>{i.d(n,{Q:()=>s});let s={
  financeAndAccounting:"finance-and-accounting", strategyAndOps:"strategy-and-ops",
  legal:"legal", healthcareAndMedical:"healthcare-and-medical",
  engineering:"engineering", economics:"economics"}}
```

The nav builds its "Indexes" menu from it:
`defaultLeaves:Object.values(eP.M).map(e=>{let{slug:a,name:t,…}=e; … href:"/models/capabilities/".concat(a) …})`
(`app__%5Blocale%5D__layout-7fefd88bab76a965.js`).

`/models/capabilities` (index page) lists exactly the six labels — `"Finance & Accounting Index"`,
`"Strategy & Ops Index"`, `"Legal Index"`, `"Healthcare & Medical Index"`, `"Engineering Index"`,
`"Economics Index"` — and nothing else.

### Coding Index / Agentic Index — verdict: **NOT present in the bundles or any payload fetched**

Greps run (all from `/tmp/bundle`, over the 39 downloaded chunks and the payloads):

```bash
grep -oh 'codingIndex'  js/*.js | sort | uniq -c     # empty
grep -oh 'agenticIndex' js/*.js | sort | uniq -c     # empty
grep -l  'Coding Index'  js/*.js                     # empty
grep -l  'Agentic Index' js/*.js                     # empty
grep -oh 'getScore:[a-z]=>e\.[A-Za-z0-9_.]*' js/*.js | sort -u
#   38 score paths; no codingIndex/agenticIndex (list ends: …opennessIndex, omniscience,
#   scicode, tau2, tauBanking, terminalBench21, terminalBench40, terminalBenchScience, terminalbenchHard)

grep -oh 'shortName:"[^"]*"' js/66861-a92db3a5365b05c0.js | sort -u
#   the eval/index registry has Intelligence, Openness, Cyber, Decision, Omniscience …
#   no "Artificial Analysis Coding Index" / "Agentic Index" entry
```

Route probes (all with `-H "RSC: 1"`):

```bash
for p in /models/capabilities/coding /models/capabilities/agentic /models/coding /models/agentic \
         /leaderboards/coding /leaderboards/agentic /coding-index /agentic-index \
         /models/coding-index /models/agentic-index \
         /evaluations/artificial-analysis-coding-index /evaluations/artificial-analysis-agentic-index; do
  curl -s -o /dev/null -w '%{http_code}  '"$p"'\n' -H "User-Agent: Mozilla/5.0" --compressed \
    -H "RSC: 1" "https://artificialanalysis.ai$p"
done
# 404 for every one of them
```

Payload greps:

```bash
grep -o 'codingIndex'  routes/model-opus.rsc | wc -l   # 0
grep -o 'agenticIndex' routes/model-opus.rsc | wc -l   # 0
grep -o 'codingIndex'  lb.rsc | wc -l                  # 0
grep -o 'agenticIndex' lb.rsc | wc -l                  # 0
grep -o 'codingIndex'  routes/home.rsc | wc -l         # 0
grep -o 'agenticIndex' routes/home.rsc | wc -l         # 0
```

`/sitemap.xml` (5,859,644 B) contains **no** coding/agentic *model-index* route. The only
`coding`/`agentic` index paths are the **Coding Agent Index** — a different thing:

```
https://artificialanalysis.ai/agents/coding-agents
https://artificialanalysis.ai/methodology/coding-agents-benchmarking
```

That board is named `codingAgentIndex` / `codingAgentsIndex` in the client (and
`"AA Coding Agent Index"` in the agents registry) and ranks **agents**, not models. In the
leaderboard payload `coding` / `agentic` appear only as i18n skill/tag labels
(`"skills":{"coding":"Coding",…,"agentic":"Agentic"}`), never as score columns.

**Bottom line:** the model-level **Coding Index** and **Agentic Index** have no free
page, route, chunk reference, sitemap entry, or payload key anywhere I looked. If they are
reachable without a key at all, it is not via a statically-referenced URL — they remain
keyed-API-only (`/api/v2/language/models/free`, `artificial_analysis_coding_index` /
`artificial_analysis_agentic_index`).

### Free recipe for what *was* found

Six capability indexes — per-model page (best coverage, keyless):

```bash
curl -sfL -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" \
  https://artificialanalysis.ai/models/<slug> -o model.rsc
# key path:  …"capabilities":{"financeAndAccounting":45.37,"strategyAndOps":47.12,
#            "legal":46.23,"healthcareAndMedical":40.82,"engineering":44.98,"economics":52.85}
```

Six capability indexes — cross-model ranking page (26/20 models):

```bash
curl -sfL -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" \
  https://artificialanalysis.ai/models/capabilities/<slug> -o cap.rsc
# <slug> ∈ finance-and-accounting | strategy-and-ops | legal
#          | healthcare-and-medical | engineering | economics
# key path per row: "slug":"<model>","name":"<model name>", … "headlineValue":<n>,
#                   "weightedIndex":<n>, "subScores":{…}
```
