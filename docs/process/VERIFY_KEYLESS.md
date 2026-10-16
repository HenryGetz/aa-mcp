# Independent verification — keyless-only migration + free Capability Indexes

Verifier: `verify-keyless` (independent; did not write any code under test).
Date: 2026-10-15. Tree: `/home/wavy/ai/aa-mcp` (working tree, uncommitted changes).
Method: read the tree, ran the static greps, the offline test suite, ruff, the
reference generator, and exercised the live server through the stdio harness
(`.venv/bin/python eval/client.py call ...`). Numbers were checked against AA's own
pages fetched with `curl` (no `aa_mcp` import) where noted.

Verdict: **6 of 7 checks PASS; check 6 FAIL** (stale/incorrect documentation
numbers). Two additional correctness findings that are not in the checklist are
recorded in the mismatch list (coverage footnote under filters; stale
`openapi.yaml` provenance comments).

---

## Check 1 — keyed-API / env-var leftovers in the tree

Command:

```
grep -rn "AA_API_KEY\|AA_SOURCE\|AA_API_TTL\|aa:api\|JSON API\|api/v2\|x-api-key" \
  src tests scripts README.md docs/INTERFACES.md docs/REFERENCE.md
```

Raw output (14 matches, 3 files; full list):

```
docs/INTERFACES.md:
  11: `AA_API_KEY` / `AA_SOURCE` / `AA_API_TTL`; if those are set in the environment the

src/aa_mcp/server.py:
  399: """One-time notice that ``AA_API_KEY``/``AA_SOURCE`` are no longer read."""
  404: stale = [name for name in ("AA_API_KEY", "AA_SOURCE") if os.environ.get(name)]
  423: gone, so the former ``AA_API_TTL`` branch no longer exists.

tests/test_server.py:
  1806: ``AA_API_KEY``/``AA_SOURCE`` is reported exactly once per process."""
  1807: monkeypatch.setenv("AA_API_KEY", "bogus")
  1808: monkeypatch.setenv("AA_SOURCE", "api")
  1815: assert "AA_API_KEY" in msgs[0] and "AA_SOURCE" in msgs[0]
  1816: assert "aa:api" not in server._header(count="1 of 1")
  1820: """No keyed cache: ``_lb_cache`` is constant and ``AA_API_TTL`` is ignored."""
  1821: monkeypatch.setenv("AA_API_TTL", "123")
  1824: assert server._cache_ttl(True) == 3600      # AA_API_TTL no longer read
  1985: assert "AA_API_KEY" not in out and "JSON API" not in out
  1999: assert "AA_API_KEY" not in text and "JSON API" not in text and "env" not in text
```

Adjudication of every hit:

| hit | legitimate? |
|---|---|
| `server.py:399,404,423` | **legitimate** — the one-time "no longer read" warning + its docstring; `_source_key()` returns the constant `"rsc"`, `_cache_ttl` ignores `AA_API_TTL`. |
| `tests/test_server.py:*` | **legitimate** — tests asserting the removal (env is ignored, header never says `aa:api`). |
| `docs/INTERFACES.md:11` | **legitimate** — documents the removal ("Nothing in the server reads …; if those are set … logs one warning and ignores them"). |

**PASS** — no hit is a live keyed path; every hit documents/asserts the removal.

Broader sweep (`AA_API`, `x-api-key`, `api/v2`, `models/free`, `openapi`, `aa:api`)
found only the same lines plus two **stale provenance comments** that reference a
fixture deleted in this change:

```
src/aa_mcp/catalog.py:4:   fixture). Field names come from AA's public API vocabulary (``openapi.yaml``,
src/aa_mcp/catalog.py:671: # Field names as they appear in AA's public OpenAPI vocabulary (openapi.yaml).
```

`tests/fixtures/openapi.yaml` is deleted (`git status`: `D`). These are comments
only (the module docstring itself says "no runtime dependency on the OpenAPI
fixture"); they do **not** contradict the keyless claim, but they point at a file
that no longer exists. Classified as a cosmetic leftover, not a FAIL.

Runtime confirmation that the env vars are actually inert:

```
$ AA_API_KEY=bogus AA_SOURCE=api AA_API_TTL=123 .venv/bin/python eval/client.py call aa_leaderboard '{"top":2}'
AA_API_KEY, AA_SOURCE set, but the keyed JSON-API backend has been removed; ignoring it and using the keyless RSC source
# 2 of 267 scored (703 tracked) · Intel, active only · 52m ago · aa:rsc
| Model | Slug | Creator | Intel | $/Task | tok/s | TTFT | Ctx |
...
```

Header stays `aa:rsc`; one warning; no failure. (`AA_API_TTL` alone produces no
warning — `_warn_keyed_env_once` only inspects `AA_API_KEY`/`AA_SOURCE` — but the
TTL is still ignored, per the test above.)

---

## Check 2 — references to the deleted modules/symbols

```
$ grep -rn "aa_mcp\.api\|aa_mcp\.source\|fetch_models_free\|ApiAuthError\|parse_models_free\|with_licensing" src tests scripts
$ echo "EXIT=$?"
EXIT=1
```

**PASS** — empty output (exit 1). No reference to `aa_mcp.api`, `aa_mcp.source`,
`fetch_models_free`, `ApiAuthError`, `parse_models_free` or `with_licensing`
anywhere in `src`, `tests`, `scripts`. The deleted files
(`src/aa_mcp/api.py`, `src/aa_mcp/source.py`, `tests/test_api.py`,
`tests/test_source.py`, `tests/fixtures/api_models_free.json`,
`tests/fixtures/openapi.yaml`) are gone from the tree.

---

## Check 3 — test suite, lint, generated reference

```
$ AA_OFFLINE=1 uv run pytest -q
... (dots) ...
624 passed in 44.49s

$ uvx ruff check .
All checks passed!

$ uv run python scripts/gen_reference_md.py --check
/home/wavy/ai/aa-mcp/docs/REFERENCE.md is up to date (23043 chars)
```

**PASS** — **624 passed**, 0 failed, 0 errors. Ruff clean. Generated reference in
sync.

---

## Check 4 — live behaviour through the stdio harness

### 4a. Six Capability Indexes via `aa_leaderboard {"sort":"capabilities.<key>","top":3}`

All six return rows and a coverage footnote. Raw:

```
=====SORT=legal=====
# 3 of 133 scored (703 tracked) · Cap Legal, active only · 43m ago · aa:rsc + rich dataset (overlay 43m ago, seed step-5) + /models/capabilities/legal
| Model | Slug | Creator | Intel | $/Task | tok/s | TTFT | Ctx | Cap Legal |
|---|---|---|---|---|---|---|---|---|
| Claude Opus 5.5 (Max, Default Fallback) | claude-opus-5-5 | Anthropic | 57.6 | $5.98 | 96.3 | 666.7s | 1.0M | 63.3 |
| Claude Opus 5.5 (Xhigh, Default Fallback) | claude-opus-5-5-xhigh | Anthropic | 56.0 | $3.46 | 85.2 | 123.1s | 1.0M | 60.8 |
| Claude Fable 5.1 (Xhigh, Default Fallback) | claude-fable-5-1-xhigh | Anthropic | 53.2 | $5.98 | 66.4 | 67.7s | 1.0M | 60.8 |
— 2 models tie at 60.8; ordered by intelligence (56.0 vs 53.2)
— Cap Legal comes from /models/capabilities/legal (26 models), joined onto the leaderboard rows (133 scored in total)
— Cap Legal: 133 of 703 tracked variants scored; the index's own page (/models/capabilities/legal) carries its sub-scores for 1 of the 3 rows shown

=====SORT=engineering=====
# 3 of 133 scored (703 tracked) · Cap Engineer, active only · 43m ago · ... + /models/capabilities/engineering
| ... | Claude Opus 5.5 | claude-opus-5-5 | 60.4 |
| ... | Claude Opus 5.5 (Xhigh) | claude-opus-5-5-xhigh | 58.7 |
| ... | Claude Sonnet 5.5 | claude-sonnet-5-5 | 58.4 |
— Cap Engineer comes from /models/capabilities/engineering (26 models), joined onto the leaderboard rows (133 scored in total)
— Cap Engineer: 133 of 703 tracked variants scored; ... sub-scores for 2 of the 3 rows shown

=====SORT=economics=====
# 3 of 137 scored (703 tracked) · Cap Economic, active only · 43m ago · ... + /models/capabilities/economics
| Claude Opus 5.5 | claude-opus-5-5 | 65.6 |
| Claude Opus 5.5 (Xhigh) | claude-opus-5-5-xhigh | 63.0 |
| Claude Fable 5.1 (Max) | claude-fable-5-1 | 62.7 |
— Cap Economic comes from /models/capabilities/economics (26 models), joined onto the leaderboard rows (137 scored in total)
— Cap Economic: 137 of 703 tracked variants scored; ... sub-scores for 2 of the 3 rows shown

=====SORT=financeAndAccounting=====
# 3 of 133 scored (703 tracked) · Cap Finance, active only · 44m ago · ... + /models/capabilities/finance-and-accounting
| Claude Opus 5.5 | claude-opus-5-5 | 60.7 |
| Claude Opus 5.5 (Xhigh) | claude-opus-5-5-xhigh | 58.4 |
| Claude Sonnet 5.5 | claude-sonnet-5-5 | 57.2 |
— Cap Finance comes from /models/capabilities/finance-and-accounting (26 models), joined onto the leaderboard rows (133 scored in total)
— Cap Finance: 133 of 703 tracked variants scored; ... sub-scores for 2 of the 3 rows shown

=====SORT=strategyAndOps=====
# 3 of 133 scored (703 tracked) · Cap Strategy, active only · 44m ago · ... + /models/capabilities/strategy-and-ops
| Claude Opus 5.5 | claude-opus-5-5 | 63.7 |
| Claude Opus 5.5 (Xhigh) | claude-opus-5-5-xhigh | 61.6 |
| Claude Fable 5.1 (Max) | claude-fable-5-1 | 59.7 |
— Cap Strategy comes from /models/capabilities/strategy-and-ops (26 models), joined onto the leaderboard rows (133 scored in total)
— Cap Strategy: 133 of 703 tracked variants scored; ... sub-scores for 2 of the 3 rows shown

=====SORT=healthcareAndMedical=====
# 3 of 40 scored (703 tracked) · Cap Medical, active only · 44m ago · ... + /models/capabilities/healthcare-and-medical
| Claude Opus 5.5 | claude-opus-5-5 | 60.5 |
| Claude Sonnet 5.5 | claude-sonnet-5-5 | 58.1 |
| Claude Fable 5.1 (Max) | claude-fable-5-1 | 58.0 |
— Cap Medical comes from /models/capabilities/healthcare-and-medical (20 models), joined onto the leaderboard rows (40 scored in total)
— Cap Medical: 40 of 703 tracked variants scored; ... sub-scores for 3 of the 3 rows shown
```

With `include_deprecated=true` the totals become **221 / 221 / 221 / 82 / 220 / 228**
of 703 for Finance / Strategy / Legal / Healthcare / Engineering / Economics —
exactly the figures claimed in README line 172 and `docs/REFERENCE.md:134`.

**PASS** — all six are rankable keyless with a coverage footnote.

### 4b. `aa_benchmark_leaderboard {"benchmark":"capabilities.legal","top":3}`

```
# 3 of 221 scored (703 tracked) · Cap Legal · /models/capabilities/legal + rich dataset — not a full leaderboard · 44m ago · aa:rsc + rich dataset (overlay 44m ago, seed step-5)
| Model | Slug | Creator | Cap Legal | Intel | $/Task |
|---|---|---|---|---|---|
| Claude Opus 5.5 (Max, Default Fallback) | claude-opus-5-5 | Anthropic | 63.3 | 57.6 | $5.98 |
| Claude Opus 5.5 (Xhigh, Default Fallback) | claude-opus-5-5-xhigh | Anthropic | 60.8 | 56.0 | $3.46 |
| Claude Fable 5.1 (Xhigh, Default Fallback) | claude-fable-5-1-xhigh | Anthropic | 60.8 | 53.2 | $5.98 |
— capabilities.legal is one of AA's six Capability Indexes; its own page (/models/capabilities/legal) carries the index's sub-scores for 1 of the 3 rows shown
```

**PASS** — works; identical values to 4a.

### 4c. `aa_pareto {"score":"capabilities.legal","top":5}`

```
# 5 of 16 frontier points · Legal Index vs $/task (Pareto frontier, cost ascending) · 44m ago · aa:rsc + rich dataset
| Model | Slug | Creator | Legal Index | $/task | Legal Index/$/task |
| K2 Horizon 375B A23B | k2-horizon-375b-a23b | Institute of Foundation Models | 31.9 | $0.00 | - |
| GPT-6 Luna (Medium) | gpt-6-luna-medium | OpenAI | 33.0 | $0.02 | 1,891 |
| GPT-6 Luna (High) | gpt-6-luna-high | OpenAI | 35.4 | $0.03 | 1,220 |
| GPT-6 Luna (Xhigh) | gpt-6-luna-xhigh | OpenAI | 37.2 | $0.04 | 883 |
| GPT-6 Luna (Max) | gpt-6-luna | OpenAI | 40.3 | $0.07 | 594 |
— frontier: 16 non-dominated of 118 models scored on both axes (703 tracked, active only; showing the 5 cheapest, include_all=true for the rest)
— knee ≈ GPT-6.1 Sol (Low): $/task $0.13, Legal Index 49.9 (5× cost/score cliff)
```

**PASS** — capability index usable as a Pareto score axis.

### 4d. `aa_model {"query":"claude-opus-5-5","sections":"indexes"}`

```
## Indices
| Index | Score |
|---|---|
| Intel | 57.6 |
| Omniscience | 46.4 |
— Coding Index, Agentic Index: AA publishes these composites only through its paid data API, so no free page carries a per-model value. The free constituents are rankable — aa_benchmarks query=coding (SciCode, LiveCodeBench, FrontierCode, Terminal-Bench, τ²-Bench)

## Capability indexes
| Capability index | Score |
|---|---|
| Economics | 65.6 |
| Engineering | 60.4 |
| Finance & Accounting | 60.7 |
| Healthcare & Medical | 60.5 |
| Legal | 63.3 |
| Strategy & Ops | 63.7 |
— sub-scores, from each index's own page (/models/capabilities/<slug>):
  Economics: Agentic knowledge work 66.7 · Knowledge 66.3 · Long context 84.7 · Reasoning 61.4
  Engineering: Agentic knowledge work 66.7 · Agentic terminal use 59.6 · Knowledge 68.9 · Reasoning 46.5
  Finance & Accounting: Agentic knowledge work 66.7 · Agentic tool use 66.5 · Knowledge 55.0 · Long context 55.4 · Non-hallucination 50.4 · Reasoning 61.4
  Healthcare & Medical: Agentic knowledge work 66.7 · Agentic tool use 77.3 · Knowledge 56.9 · Long context 66.7 · Non-hallucination 29.2 · Reasoning 61.4
  Legal: Agentic knowledge work 66.7 · Agentic tool use 77.3 · Knowledge 64.2 · Long context 55.4 · Non-hallucination 55.0 · Reasoning 61.4
  Strategy & Ops: Agentic knowledge work 66.7 · Agentic tool use 70.2 · Knowledge 55.0 · Long context 55.4
— the six capability indexes are rankable: aa_leaderboard sort=capabilities.legal (any of the six)
```

Six scores present; sub-scores present for all six (4–6 each). Same for
`claude-sonnet-5-5`.

Wording audit on the raw output:

```
$ grep -n -i "AA_API\|env\b\|api key\|x-api\|environment" /tmp/model_idx.txt   # exit=1 (no match)
$ grep -o "paid data API" /tmp/model_idx.txt | wc -l
1
```

**PASS** — the literal phrase "paid data API" appears once (this is the *required*
phrasing: "not published on AA's public pages (paid data API only)"); **no**
env-var, `AA_API_KEY`, `x-api-key` or "set a key" wording appears anywhere.

### 4e. Openness and Decision Index

```
# 3 of 171 scored (703 tracked) · Openness, active only · ... + /evaluations/artificial-analysis-openness-index
| K2 Think V2 | k2-think-v2 | 88.9 |  (3 rows shown)
— Openness comes from /evaluations/artificial-analysis-openness-index (326 models), joined onto the leaderboard rows (171 scored in total)

# 3 of 15 scored (703 tracked) · Decision, active only · ... + /evaluations/artificial-analysis-decision-index
| Claude Opus 5.5 (Max, Default Fallback) | claude-opus-5-5 | 79.0 |
| Claude Opus 5.5 (Low, Default Fallback) | claude-opus-5-5-low | 75.4 |
| GPT-6.1 Sol (Low) | gpt-6-1-sol-low | 71.5 |
— Decision comes from /evaluations/artificial-analysis-decision-index (15 models of the 28 rows it publishes), joined onto the leaderboard rows (15 scored in total)
```

Independently confirmed from the pages (curl, no `aa_mcp`):

```
openness page: full array length 326, all 326 with non-null opennessIndex   -> "326 models" claim TRUE
decision page: "contestants" array length 28 (Counter: {'llm': 15, 'decisionModel': 13}) -> "15 models of the 28 rows" TRUE
```

**PASS** — both wired, both footnotes accurate.

### 4f. Coding / Agentic wording

```
$ aa_benchmarks {"query":"coding index"}
| Artificial Analysis Coding Index | index | index | not published free (AA's paid data API only) | aa_benchmark_leaderboard benchmark=scicode | ...
| Artificial Analysis Coding Agent Index | arena | index | arena board | aa_agents board=coding_agents | ...
| SciCode | benchmark | % | leaderboard (232/703) | aa_leaderboard sort=scicode | ...
| Terminal-Bench 4.0 | benchmark | % | leaderboard (221/703) | aa_leaderboard sort=terminalBench40 | ...

$ aa_leaderboard {"sort":"coding"}
Tool 'aa_leaderboard' failed: "Error executing tool aa_leaderboard: 'Coding': AA publishes this composite only through its paid data API, and no public page carries a per-model value — there is no cross-model ranking to sort by.
— rank the free constituents instead: scicode, livecodebench, frontierCode, terminalBench40 (aa_benchmark_leaderboard benchmark=<one of those>)"

$ aa_benchmark_leaderboard {"benchmark":"agentic"}
Tool 'aa_benchmark_leaderboard' failed: "Error executing tool aa_benchmark_leaderboard: 'Agentic': AA publishes this composite only through its paid data API, and no public page carries a per-model value — there is no cross-model ranking to sort by.
— rank the free constituents instead: terminalBench40, tau2, tauBanking, automationBenchPartialScore (aa_benchmark_leaderboard benchmark=<one of those>)"
```

**PASS** — honest ("not published free / paid data API only", names free
constituents), no env var or key mentioned. Note both `coding` calls **raise** an
error rather than returning a table; that is the intended "honest no-rank error"
(`scripts/surface_sweep.py` lists them under `EXPECTED_FAILURES`).

### 4g. `aa_agents {"board":"coding_agents","top":3}`

```
# 3 of 41 rows · Artificial Analysis Coding Agent Index (DeepSWE v1.1 + Terminal-Bench 4.0 + SWE-Atlas-QnA) · agents, not models · 34m ago · aa:rsc
| 1 | Claude Code | Sonnet 5.5 (max) | Anthropic | 68.4 | $14.19 |
| 2 | Devin Fusion CLI | Claude Opus 5.5 Max + GPT-6 Luna High | Cognition | 68.1 | $9.01 |
| 3 | Muse Code | Muse Wonder Full (max) | Meta | 68.0 | - |
— the Coding Agent Index ranks agent x model combinations ...
```

**PASS** — 41 rows, matches README/REFERENCE ("41 rows").

**Check 4 overall: PASS** (all calls behaved as specified; one footnote-accuracy
defect under filters is recorded in the mismatch list).

---

## Check 5 — independent number check (curl vs MCP)

Fetched directly with `curl -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1"`,
parsed the `initialModels` array's `weightedIndex` with a plain JSON decoder (no
`aa_mcp` import).

`/models/capabilities/legal` (HTTP 200; 26 models, all with non-null `weightedIndex`):

| slug | independent `weightedIndex` | MCP `capabilities.legal` | match |
|---|---|---|---|
| `claude-opus-5-5` | 63.2602763791642 | 63.3 | ✓ |
| `claude-sonnet-5-5` | 56.435055775641 | 56.4 | ✓ |

`/models/capabilities/economics` (HTTP 200; 26 models):

| slug | independent `weightedIndex` | MCP `capabilities.economics` | match |
|---|---|---|---|
| `claude-opus-5-5` | 65.6045449876429 | 65.6 | ✓ |
| `claude-sonnet-5-5` | 60.8401739843992 | 60.8 | ✓ |

Sub-score spot check (opus, legal) — independent page `subScores` vs MCP:

```
page: knowledge 64.2, reasoning 61.353, longContext 55.433, agenticToolUse 77.321,
      nonHallucination 55.028, agenticKnowledgeWork 66.7005
MCP : Knowledge 64.2, Reasoning 61.4, Long context 55.4, Agentic tool use 77.3,
      Non-hallucination 55.0, Agentic knowledge work 66.7
```

**PASS** — no mismatch. (Minor: `66.35` renders as `66.3` and `59.65` as `59.6`,
i.e. one decimal uses truncation/banker's rounding on exact `.x5` values — see
"could not verify"/mismatch notes; the headline index values themselves match.)

---

## Check 6 — contradiction hunt: shipped text vs reality

`catalog.RANKABLES` size:

```
$ .venv/bin/python -c "from aa_mcp import catalog; print(len(catalog.RANKABLES), len(catalog.BENCHMARKS))"
105 70
```

Kind breakdown: `{'index': 13, 'benchmark': 57, 'derived': 16, 'arena': 15, 'view': 4}`.
`aa_benchmarks` reports `105 rankables`. Tracked variants (live): **703**
(`len(_lb_rows())`; the leaderboard RSC `models`/metrics arrays are both 703 rows).

### Mismatches

1. **README:146 — "a 95-entry rankable index (67 cross-model benchmarks …)".**
   Reality: `catalog.RANKABLES` = **105**, and there are **57** benchmark-kind
   rankables (35 of them leaderboard/rich; the `BENCHMARKS` registry has 70, of
   which 13 are not rankable). Neither 95 nor 67 matches anything in the registry.
   *Pre-existing* — the same line is in `git show HEAD:README.md` and was **not**
   touched by this change, but it is still wrong in shipped text.

2. **"700 tracked" vs 703.** The server prints `(703 tracked)`; README and
   `docs/REFERENCE.md` say 700 in several places. `docs/REFERENCE.md` is
   **internally inconsistent**: line 134 says "of the 703 variants" while lines 84,
   150, 200, 216, 231, 317, 319 say "700 tracked" / "700-row leaderboard" /
   "700 variants". Also `src/aa_mcp/render.py:101` docstring example says
   `"15 of 270 scored (700 tracked)"`.

3. **README:135 / REFERENCE.md:216 — cost-per-task coverage "186 of 700".**
   Live: `aa_leaderboard mode=value` reports **194/703**:
   `— 509 rows skipped: no measured cost per task (AA has cost per task for 194/703 variants)`.

4. **README example numbers (README:127) are stale.**
   README shows `# 5 of 109 scored by value (700 tracked)` and
   `— 514 rows skipped … 186/700 variants`. Live `mode=value` returns
   `# 3 of 113 scored by value (703 tracked)` and `509 rows skipped … 194/703`.

5. **Coverage footnote misreports when a filter narrows the set** (tool-side, not
   docs). `aa_leaderboard {"sort":"capabilities.legal","name":"claude-sonnet-5-5"}`:

   ```
   # 2 shown of 5 matching (703 tracked) · Cap Legal, active only, name~claude-sonnet-5-5 · ...
   — Cap Legal comes from /models/capabilities/legal (26 models), joined onto the leaderboard rows (5 scored in total)
   — Cap Legal: 5 of 703 tracked variants scored; ...
   ```

   "5 of 703 tracked variants scored" is false — 5 is the *matching* count after the
   `name=` filter; 133 variants are actually scored (as the same tool reports with no
   filter). Cause: `server.py:2104` computes `sort_scored` over the already-filtered
   `models` list and the capability footnote at `server.py:2123-2125` reuses it as
   "N of 703 tracked variants scored". `_benchmark_leaderboard` has the same pattern
   (`server.py:4201`: `{len(pairs)} scored ({len(lb)} tracked)`).

6. **Stale provenance comments referencing a deleted fixture.**
   `src/aa_mcp/catalog.py:4` and `:671` cite `openapi.yaml`, which this change
   deleted; `tests/test_catalog.py:77` is named `test_openapi_vocabulary_aliases`
   over `_OPENAPI_ALIASES`. Comments/test-name only; no functional impact.

### Verified-correct doc claims (no mismatch)

- README:172 / REFERENCE.md:134 capability coverage **221/221/221/82/220/228 of 703**
  — matches `include_deprecated=true` exactly.
- README:172 / REFERENCE.md:132 curated page sizes **26 each, 20 for Healthcare & Medical**
  — page arrays parsed: 26 / 26 / 20. ✓
- README:173 / REFERENCE.md:120 **Openness "326-model array"** — parsed array length 326. ✓
- REFERENCE.md decision index **"15 models of the 28 rows it publishes"** — page
  `contestants` length 28 (`llm` 15 + `decisionModel` 13). ✓
- REFERENCE.md / README **"41 agent x harness rows"** — tool prints `3 of 41 rows`. ✓
- README:17 **"~50 metrics per model"** — leaderboard metrics array has 51 keys. ✓
- README **"17 cross-model benchmarks"** — ambiguous: the leaderboard array carries
  19 benchmark keys (+ `intelligenceIndex`/`omniscience`); 17 is reachable only if
  the two `omniscience*` sub-metrics are excluded. **Not flagged as a definite
  mismatch**, but the basis is undocumented.

**Check 6: FAIL** — items 1–4 and 6 are shipped-text/reality mismatches; item 5 is
a tool reporting defect. None of them break the keyless claim; they are accuracy
defects in the documentation/coverage claims.

---

## Check 7 — do `aa_benchmarks` "How to query" hints ever propose a call that cannot work?

Static validation of **all 105** hints (each `how` resolved against the registry):

```
bad hints: NONE
coding  -> aa_benchmark_leaderboard benchmark=scicode      | surface none
agentic -> aa_benchmark_leaderboard benchmark=terminalBench40 | surface none
```

Live spot-checks of the hinted calls:

- Coding Index row → `aa_benchmark_leaderboard benchmark=scicode`:
  `# 2 of 232 scored (703 tracked) · SciCode · leaderboard` — **works**.
- Agentic Index row → `aa_benchmark_leaderboard benchmark=terminalBench40`:
  `# 2 of 221 scored (703 tracked) · Terminal-Bench 4.0 · leaderboard` — **works**.
- All six capability rows → `aa_leaderboard sort=capabilities.<key>` — **all six work**
  (see 4a). No capability hint points at a key that is not free.
- Extra: `aa_benchmark_leaderboard benchmark=decisionIndex` → `# 2 of 15 scored … AA Decision Index`; `aa_leaderboard sort=cyberIndex` → `# 2 of 19 scored … chart set + homepage panel` — both **work**.

The two `surface="none"` keys (`coding`, `agentic`) correctly point at their free
constituents, never at themselves; `API_ONLY_INDEXES` is the only source of
`surface="none"` hints.

Minor observation (not a broken hint): the capability rows' **Coverage** column
shows the *total* (incl. deprecated) count — e.g. `rich dataset (228/703)` for
Economics — while the hinted default call (`aa_leaderboard sort=capabilities.economics`,
active-only) reports `137`. Both are correct for their respective scopes; the column
does not say it includes deprecated.

**Check 7: PASS** — every hint resolves to a working call.

---

## What I could not verify

- **`aa:api` backend fully dead at the network layer.** I verified there is no code
  path, no import, and that the env vars are ignored at runtime; I did not attempt to
  prove that AA's paid API is never contacted (would require traffic capture).
- **Why `66.35 → 66.3` / `59.65 → 59.6`.** The one-decimal rendering of exact `.x5`
  sub-scores uses Python `format`/float semantics (banker's-ish). The headline index
  values match AA exactly; the sub-score rendering is off by 0.1 from round-half-up on
  two values I sampled. I did not audit `catalog.format_value` for intent.
- **Historical correctness of the "95-entry / 67" and "700" numbers** — whether they
  were ever right or were introduced by this change. They exist in `HEAD`, so they
  predate the keyless work; I did not bisect further.
- **Full README numeric audit.** I checked the rankable/coverage/index claims the
  task highlighted and the ones that intersect this change; I did not re-derive every
  README figure (e.g. "1,201 provider endpoints across 64 hosts", "9 media arenas",
  "~50 leaderboard metrics merged with a 700 × 94 dataset").
- **`docs/REFERENCE.md` topic-by-topic fidelity.** I checked the numeric claims and
  the index/capability text; I did not line-by-line verify every topic string against
  behaviour.
- **AA page content drift.** All live checks ran against a warm cache (~43–54 min
  old). The two independent `curl` fetches (legal, economics, openness, decision)
  were fresh and matched, so drift is unlikely to hide a mismatch, but I did not
  force `refresh=true` on every tool.
- **`scripts/surface_sweep.py` end-to-end run.** I read the diff (it now covers the
  six capability keys, openness, decisionIndex and the coding/agentic expected
  failures) but did not execute the full sweep.

---

## Summary

**Checks passed: 6 of 7** — checks 1, 2, 3, 4, 5, 7 PASS; check 6 FAIL.
The keyless migration itself is sound: the keyed backend is gone from code, imports
and tests; the env vars are inert at runtime; the suite is green (624 passed) and
lint-clean; all six Capability Indexes are rankable keyless with sub-scores whose
values match AA's pages to the reported precision; Openness (326) and Decision (28
rows) are wired; and the Coding/Agentic gap is reported honestly with free
constituents and **no** env-var/key wording.

**Three worst findings:**

1. **Documentation numbers are stale/wrong (check 6 FAIL).** README's
   "95-entry rankable index (67 cross-model benchmarks)" vs the actual **105**
   rankables / **57** benchmark entries; "700 tracked" and "186 of 700" cost coverage
   vs the live **703** and **194/703**; README's example output (`109` scored,
   `514` skipped) vs live `113`/`509`. `docs/REFERENCE.md` contradicts *itself*
   ("703 variants" at line 134, "700 tracked" at lines 84/150/200/216).
2. **The capability coverage footnote lies when a filter is applied.**
   `aa_leaderboard sort=capabilities.legal name=claude-sonnet-5-5` prints
   "**5 of 703 tracked variants scored**" — 5 is the post-filter match count; 133
   variants are scored. `server.py:2104` reuses the filtered count as the coverage
   number (same pattern in `_benchmark_leaderboard`, `server.py:4201`).
3. **Stale provenance references to a deleted fixture.** `catalog.py:4,671` and
   `test_openapi_vocabulary_aliases` still cite `openapi.yaml`, which this change
   removed. Cosmetic, but it is a leftover the sweep in check 1 was meant to catch.
