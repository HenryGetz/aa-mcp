# Round-2 quality & adversarial audit — keyless-only + free indexes

Auditor: `fresh-tree-audit` (independent; wrote only this file). Date: 2026-10-16.
Tree: `/home/wavy/ai/aa-mcp`, working tree at `dcc28e4` ("Keyless-only data source; free
Capability Indexes, Openness/Decision indexes and the Coding Agent Index").

Method: read the prior audits (`docs/process/AUDIT_QUALITY.md`, `AUDIT_ADVERSARIAL.md`,
`VERIFY_KEYLESS.md`, `API_REMOVAL_INVENTORY.md`, `INDEX_SOURCES.md`) to avoid re-reporting
fixed issues; then read `loaders.py` / `server.py` / `catalog.py` / `select.py` around the
new code; ran the offline suite, ruff, the reference generator and the full
`scripts/surface_sweep.py`; drove the live server through `eval/client.py`; and proved the
loader claims with a scratch probe (`/tmp/probe_loaders.py`) plus crafted cache files and a
loopback HTTP server — no repo file other than this report was modified.

Baseline re-verified first (so findings below are NEW or still-wrong, not re-reports):

```
630 tests collected · AA_OFFLINE=1 pytest -q → all pass (36.3 s)
ruff check . → All checks passed
gen_reference_md.py --check → docs/REFERENCE.md is up to date (23082 chars)
surface_sweep.py → 299 calls · 18 failures (18 expected, 0 unexpected) · ≈77 534 tokens (avg 259)
```

---

## HIGH

### H1 — A non-dict element in a capability/index row array crashes five tools with `AttributeError`

- `src/aa_mcp/loaders.py:1860-1862` (`parse_capability_index`) and `:1892-1897`
  (`parse_index_rows`) iterate `for rec in max(arrays, key=len)` and call `rec.get(...)`
  without checking `isinstance(rec, dict)`.
- `flight.find_arrays` deliberately returns the *raw* array (it only requires that the
  first **dict** item carries the keys), so an array that mixes dicts with a string
  back-reference is returned intact. `INDEX_SOURCES.md:20-23` explicitly warns AA payloads
  do exactly this: *"Arrays in the payload may contain **string back-references**
  (`"$29:props:children:props:rows:0"`) instead of objects"*.
- `index_models` (`loaders.py:2011`) catches only `LookupError`, and
  `_index_page_surface` (`server.py:1607`) catches only `(AAFetchError, ValueError)`, so the
  `AttributeError` escapes to the `_tool` boundary (`server.py:605`) as an unhelpful
  generic error — the opposite of the documented contract at `server.py:1599-1600` (*"an
  unreadable page is logged and treated as absent so a ranking degrades instead of
  failing"*).

Repro (crafted cached capability page; identical result for the real `/evaluations/...`
index pages):

```
$ printf '3:[{"slug":"a","weightedIndex":63.2},{"slug":"b","weightedIndex":1},"$29:props:children:props:rows:0"]' \
    > /tmp/mixcap/capability_legal.rsc        # warm leaderboard + rich cache copied in
$ eval/client.py --env AA_CACHE_DIR=/tmp/mixcap call aa_leaderboard '{"sort":"capabilities.legal","top":2}'
Tool 'aa_leaderboard' failed: "… aa_leaderboard failed: AttributeError: 'str' object has no attribute 'get'
— retry once; if it persists, report the tool name and arguments"
$ … call aa_benchmark_leaderboard '{"benchmark":"capabilities.legal","top":2}'   → same AttributeError
$ … call aa_model '{"query":"claude-opus-5-5","sections":"indexes"}'            → same AttributeError
```

Direct loader proof (no HTTP):

```
[ERR] capability mixed+string: AttributeError: 'str' object has no attribute 'get'
[ERR] index_rows  mixed+string: AttributeError: 'str' object has no attribute 'get'
find_arrays(cap): [[{...}, {...}, '$29:props:children:props:rows:0']]   # array kept verbatim
```

Failure a user hits: AA adds one lazy back-ref inside a capability chart set or the
Openness/Decision array (a payload shape the repo's own recon documents), and
`aa_leaderboard`, `aa_benchmark_leaderboard`, `aa_model`, `aa_pareto` and `aa_compare` all
return a bare `AttributeError` for that index — instead of degrading to the (already
implemented) "page unavailable, ranking from the rich dataset" path.

Smallest correct fix: skip non-dicts in both parsers, e.g.
`for rec in max(arrays, key=len): if not isinstance(rec, dict): continue` (and optionally
tighten `find_arrays`/`_matching` to drop arrays with non-dict members). One line each.

---

## MEDIUM

### M1 — A `name=` filter that normalises to zero tokens is silently a no-op but reported as applied

- `src/aa_mcp/select.py:39-43` `_tokens` splits on `[^a-z0-9]+`, so a non-ASCII or
  punctuation-only name yields `[]`. `select.py:130,140` then treats `[]` as "no filter",
  and `server.py:2020` still counts `name` as an explicit filter, so the header prints
  `name~<value>` as though it had been applied.

```
$ eval/client.py call aa_leaderboard '{"name":"日本"}'
# 10 shown of 267 matching (703 tracked) · Intel, active only, name~日本     ← all 267 returned
$ eval/client.py call aa_leaderboard '{"name":"-_-"}'          → 10 shown of 267 matching
$ eval/client.py call aa_leaderboard '{"name":"   "}'          → 10 shown of 134 matching
$ eval/client.py call aa_leaderboard '{"name":"zzzzzz"}'       → # no models match …   (correct)
```

Failure: an agent asking for a CJK/Cyrillic/emoji model name (or a punctuation token) gets
the *whole* leaderboard back with a header claiming it was filtered — a silently wrong
result set, not an error. Fix: treat a name whose token list is empty as "matches nothing"
(or reject it with the closest-slug message), so `name~日本` cannot mean "everything".

### M2 — `aa_benchmark_leaderboard`'s `*` "estimated" marker mislabels the new index scores

- `src/aa_mcp/server.py:4252` appends `"*"` to the **score** cell whenever `m.estimated`,
  and `:4293` legends it as *"AA-estimated score (fitted across variants of the same model
  family)"*. But `Model.estimated` is `intelligenceIndexIsEstimated` (`normalize.py:262`),
  i.e. a flag about the **Intelligence Index**, not about the displayed benchmark.

```
$ eval/client.py call aa_benchmark_leaderboard '{"benchmark":"openness","top":3}'
| K2 Think V2 | k2-think-v2 | Institute of Foundation Models | 88.9* | 11.5 |
— * = AA-estimated score (fitted across variants of the same model family)
# k2-think-v2: estimated=True (intelligence), openness=88.88888888888889 — a real published value
```

Failure: a consumer ranking by Openness (or a capability index, or any benchmark) sees a
star telling them the *displayed* number is a fitted estimate when it is AA's own published
value; a reasonable agent will discount real data. This class predates the change but is
newly visible on the free index surfaces. Smallest fix: only star when the displayed key is
`intelligence`, or reword the legend to "model's Intelligence Index is AA-estimated".

### M3 — `aa_pareto` still reports a post-filter denominator as if it were the dataset's

Same defect class as the fixed coverage bug, in the tool the fix missed.

```
$ eval/client.py call aa_pareto '{"score":"capabilities.legal","creator":"OpenAI","top":3}'
— frontier: 13 non-dominated of 25 models scored on both axes (703 tracked, active only)
$ eval/client.py call aa_pareto '{"score":"capabilities.legal","top":5}'
— frontier: 16 non-dominated of 119 models scored on both axes (703 tracked, active only)
```

`server.py:1824` computes `scored = sum(... for m in models ...)` over the already-filtered
list, then `:1856` prints it next to `({len(all_models)} tracked)`. The string is identical
with and without a filter, so "of 25 models scored on both axes (703 tracked)" reads as a
dataset claim when 25 is the OpenAI-only pool. Fix: reuse `_filter_match_note` semantics —
label it "… of N matching models scored on both axes" when a filter is active (mirroring
`aa_leaderboard`'s `"{len(shown)} shown of {matching} matching ({tracked} tracked)"`).

### M4 — User-facing text still says "700-row leaderboard" while the header says 703

The commit refreshed the docs to 703 but left the tool copy at 700. User-visible sites:

```
src/aa_mcp/server.py:1005  "'…' has no values in the 700-row leaderboard — it lives on the model page only."
src/aa_mcp/server.py:1018  "700-row leaderboard, and AA's eval chart set / homepage panel carry none …"
src/aa_mcp/server.py:1887  "TTFT is the 700-row leaderboard snapshot median here …"
src/aa_mcp/server.py:2095  "… is the 700-row leaderboard snapshot median …"
src/aa_mcp/server.py:3872  "… from the 700-row leaderboard snapshot (the model page is not …)"
src/aa_mcp/server.py:4204  "no data for benchmark '…': not in the 700-row leaderboard, …"
src/aa_mcp/server.py:5677  "… when the 700-row leaderboard snapshot differs by more than 2% …"
```

Confirmed emitted:

```
$ eval/client.py call aa_leaderboard '{"sort":"ttft","top":2}'
# 2 of 162 scored (703 tracked) · TTFT, active only · …
— TTFT is the 700-row leaderboard snapshot median (aa_compare reports the model page's …)
```

Fix: replace the seven strings with "703-row" (or "leaderboard snapshot" with no count).
`src/aa_mcp/render.py:98,101` carry the same stale example ("15 of 270 scored (700 tracked)").

---

## LOW

### L1 — Unreadable capability page → footnote falsely claims the models are not on the chart set

`src/aa_mcp/server.py:2280` appends `" (none of these is on that page's chart set)"` whenever
zero shown rows carry sub-scores — including when the page *failed to parse*. With a
truncated `capability_legal.rsc`:

```
$ AA_CACHE_DIR=/tmp/corrupt-cache eval/client.py call aa_leaderboard '{"sort":"capabilities.legal","top":2}'
index page for capabilities.legal unavailable (no capability rows found …); continuing without it
— Cap Legal: 222 of 703 tracked variants have a value (134 active); the index's own page
  (/models/capabilities/legal) publishes its sub-scores for 0 of the 2 rows shown
  (none of these is on that page's chart set)          ← false: claude-opus-5-5 IS on it
```

Fix: distinguish "page unreadable" (the `_index_page_surface` path) from "page read but
model absent" and word the footer accordingly. Also note the header names the capability
page as a source (`+ /models/capabilities/legal`) even when it was unavailable.

### L2 — Dead keyed-API plumbing left behind by the removal

`source_hint` can no longer be `"api"` (`catalog.py:233-236` now emits `"none"`), yet:

- `src/aa_mcp/catalog.py:933`, `src/aa_mcp/server.py:1265,2382,2826,3983` still test
  `source_hint in ("api", "none")` / `surface in ("api", "none")` — the `"api"` arm is
  unreachable.
- `src/aa_mcp/server.py:419` `_cache_ttl(api: bool = False)` — the `api` argument is
  unused (ruff `ARG001`); `_fresh(..., api=...)` and `_header(..., api=...)` thread it
  through for no behaviour. `_lb_cache()` (`:450`) returns a constant
  `("leaderboard", False)`, so the second tuple element is vestigial.
- `src/aa_mcp/server.py:190` `_cache_aware(message, name, refresh)` — `refresh` unused
  (ruff `ARG001`).

Fix: drop the `"api"` arms and the `api`/`refresh` parameters (call sites are all internal);
keep `_lb_cache`'s tuple only if tests rely on it, else return the name.

### L3 — Shipped docs pin volatile live counts that have already drifted

The commit "refreshed all stale counts to live values"; one day later the pinned counts are
wrong again (the docs do warn "counts … drift"):

```
README.md:172 / docs/REFERENCE.md:135   "221/221/221/82/220/228 of the 703 variants"
live (aa_benchmarks query=capabilities)  Economics 229 · Engineering 221 · Finance 222 ·
                                         Healthcare 82 · Legal 222 · Strategy 222
README.md:143 / reference 'providers'    "1,199 provider endpoints"   live: "# 1 of 1222 endpoints"
README.md:127 example                     "# 5 of 113 scored by value"  live: "# 3 of 114 scored by value"
README.md:135                            "194/703 variants"            live: "195/703"
```

Fix: describe the shape ("~220 of the 703 variants") or state the exact date and let the
tool's live coverage column be the source of truth; do not pin per-index counts in prose.

### L4 — `docs/INTERFACES.md` body still describes FastMCP, contradicting its own addendum

`:18-21` ("SDK is `mcp` 2.x — NOT FastMCP … `FastMCP` no longer exists") contradicts
`:58` ("official SDK, ships FastMCP"), `:83` ("server.py # FastMCP app") and `:441`
("FastMCP: raise ValueError/…"). Fix: reword the three body references to `MCPServer`.

### L5 — `fields=all` on the index surfaces adds an all-`-` "Precision" column

```
$ eval/client.py call aa_leaderboard '{"sort":"capabilities.legal","fields":"all","top":2}'
— no data for: Precision (shown as -)
| Model | Slug | Creator | … | Precision |     ← every cell "-"
```

Pre-existing (`fields=all` unions every leaderboard column), but it is noise an agent pays
tokens for. Fix: drop columns that are empty for every shown row when `fields=all` (or
exclude the provider-only `Precision` from the leaderboard's `all` set).

### L6 — Weak tests (see the test-quality section below for the list)

### L7 — Without the rich overlay, capability coverage understates AA's real coverage

Offline with only the leaderboard + capability page cached:

```
# 3 of 26 scored (703 tracked) · Cap Legal, active only · aa:rsc + /models/capabilities/legal
— Cap Legal: 26 of 703 tracked variants have a value; …
```

26 is AA's curated chart set, not its real coverage (222). The line says "tracked variants"
with no "in the data available" qualifier. Low impact (the rich overlay is normally
present), but it is the same "coverage is a dataset property" wording trap.

---

## Verified sound (do not re-check)

1. **The keyed backend is gone at the code/import/test level.** `grep -rn
   "AA_API_KEY|AA_SOURCE|AA_API_TTL|aa:api|api/v2|x-api-key|ApiAuthError|fetch_models_free|
   with_licensing|_api_available|api_models_free" src tests scripts README.md
   docs/INTERFACES.md docs/REFERENCE.md` → only the intentional one-time warning
   (`server.py:399,404,423`), its tests (`test_server.py:1806-1824,1985,1999`) and the
   INTERFACES note. `aa_mcp.api` / `aa_mcp.source` / `data_source` appear nowhere.
2. **The env warning behaves**: fired with a raw stdio probe (`AA_API_KEY`+`AA_SOURCE` set,
   two `aa_leaderboard` calls) — the warning appeared **once**, on **stderr**, and stdout
   carried only clean JSON-RPC (`logging.basicConfig(stream=sys.stderr)` at
   `server.py:6054`).
3. **Coverage fix is complete for `aa_leaderboard` and `aa_benchmark_leaderboard`.**
   `sort=capabilities.legal name=claude-sonnet-5-5` → header `# 5 shown of 5 matching (703
   tracked)`, coverage `Cap Legal: 222 of 703 tracked variants have a value (134 active)`,
   and a separate `— 5 of 134 scored models match your filters`. `benchmark=capabilities.legal
   creator=Anthropic` → `35 of 222 scored models match your filters`. A filter that matches
   nothing still prints the dataset coverage. `aa_media`/`aa_providers`/`aa_search`/`aa_agents`
   only ever print match counts ("2 shown of 33 matching"), never a coverage claim.
4. **Index loader degradation is otherwise correct.** Direct probe + loopback server:
   404 → `AAFetchError` naming the URL and cache path; empty array → actionable
   "payload … is unusable — retry with refresh=true"; array present but all values null →
   logged, page treated as absent, ranking continues from the rich dataset; HTML body →
   same; 1-row array → rejected by `_INDEX_MIN_ROWS=2`; unknown capability key →
   `ValueError` listing the six; unknown index key → `([], "", 0)`.
5. **Offline cold start** on every new surface (`aa_leaderboard sort=capabilities.legal`,
   `aa_benchmark_leaderboard benchmark=capabilities.legal`, `aa_model sections=indexes`,
   `aa_benchmarks query=capabilities`, `aa_pareto score=capabilities.legal`,
   `aa_agents board=coding_agents`) → actionable "offline mode … no usable cache for
   <name> — render <url> …" messages, no crash. `refresh=true` and a 10 h-stale capability
   page both behave; a truncated `rich_dataset.json` is re-discovered and rebuilt.
6. **Live values and wording** for the new surfaces: six capability sorts, `openness`
   (326-array), `decisionIndex` (15 of 28 rows), `aa_model sections=indexes` (six scores +
   sub-scores, "no sub-scores for X" stated honestly), `aa_benchmarks query=capabilities`
   (105 rankables, 57 benchmark-kind, coverage column), `aa_agents board=coding_agents`
   (41 rows). No env-var/key wording anywhere; the "paid data API" phrasing is the intended
   one.
7. **Sweep, suite, lint, generator**: see the baseline block above.
8. **Token/latency** of the new surfaces (warm cache, harness-measured): `sort=capabilities.legal`
   top=10 → 428 tok / 431 ms; `sort=openness` → 324 tok / 466 ms; `aa_model sections=indexes`
   → 442 tok / 631 ms; `aa_benchmarks query=capabilities` → 281 tok / 376 ms;
   `aa_agents board=coding_agents` → 359 tok / 69 ms. Nothing wasteful for an agent; `top=134`
   (3150 tok) only when explicitly asked.

## Could not verify

- **Whether AA will ever place a back-ref inside these specific arrays.** Today's cached
  payloads contain **0** non-dict items in the capability (26), openness (326/25) and
  decision (28) arrays, so H1 is latent, not currently firing. I could not force the live
  site to prove it; the repo's own `INDEX_SOURCES.md` says the shape exists.
- **Network-level proof that no paid AA API is contacted** (would need traffic capture).
- **A one-off reading** of the no-rich capability footnote that appeared to print
  `(134 active)` alongside `26 of 703`: not reproducible across 4 re-runs (deterministic
  `26 of 703`), so it is excluded from the findings.
- **Full README numeric audit** (e.g. "9 media arenas", "64 hosts", per-benchmark coverage
  rows in REFERENCE.md) — spot-checked only.

---

## Test quality (item 4)

The suite is genuinely behavioural in the main: the new index/coverage tests patch the data
layer and assert on rendered output (`test_leaderboard_ranks_a_capability_index`,
`test_capability_coverage_survives_a_filter`, `test_capability_coverage_survives_a_filter_that_matches_nothing`,
`test_benchmark_leaderboard_coverage_survives_a_filter`, `test_leaderboard_ranks_the_openness_index_from_its_own_page`,
`test_leaderboard_ranks_the_decision_index`, `test_agents_board_presents_the_coding_agent_index`,
`test_model_section_shows_capability_sub_scores`), and the loader tests pin real fixture
values (`test_capability_page_rows`, `test_index_rows_pick_the_full_array_over_the_chart_set`,
`test_decision_index_rows_keep_their_namespaced_slugs`). Those are not tautological.

**Weak / mirror / incidental tests** (low value; would not catch a behaviour regression):

- `tests/test_server.py:269,276,281` `test_{pareto,compare,benchmarks}_tool_signature_matches_the_brief`
  — assert the exact parameter *names/order*; pure wiring, break on cosmetic reorders.
- `tests/test_server.py:2019` `test_openness_and_decision_index_rankables_are_registered`
  and `:2091` `test_coding_agent_index_rankable_points_at_aa_agents` — assert literal
  registry strings (`rank.how == "aa_agents board=coding_agents"`), i.e. re-pin the table.
- `tests/test_server.py:2176` `test_filter_match_note_is_never_a_coverage_claim` and
  `:2167` `test_dataset_scored_ignores_filters` — mirror one-line helpers' f-strings.
- `tests/test_server.py:513` `test_benchmarks_domain_rows_and_count` — asserts only
  `"of" in header and "rankables" in header`; almost any header passes.
- `tests/test_server.py:1911` `test_capability_index_aliases_resolve_to_the_same_ranking` —
  the `_metric_key(alias) == key` half mirrors the alias table (the ranking half is fine).
- `tests/test_loaders.py:525` `test_index_pages_cover_exactly_the_six_capability_indexes` —
  registry self-consistency, not behaviour.

**Plausible consumer-visible bugs with NO test** (the ones worth writing, not written):

1. Non-dict / string back-reference in a capability or index array → `AttributeError`
   (H1). No test anywhere feeds a mixed array to `parse_capability_index` /
   `parse_index_rows`.
2. `name=` that normalises to zero tokens (non-ASCII/punctuation) silently disabling the
   filter (M1) — `test_filter_name_tokenizes_like_search` only covers ASCII non-matches.
3. The `*` estimated marker on a non-intelligence score (M2).
4. `aa_pareto`'s filtered denominator (M3) — the coverage tests only cover
   `aa_leaderboard` / `aa_benchmark_leaderboard`.
5. Capability page unreadable vs model-not-on-page wording (L1).
6. Capability coverage when the rich overlay is absent (L7).

---

## Blunt verdict

**Is this repo max quality today, for a keyless benchmark MCP?** Very close, and honestly
better than most: the keyless cutover is clean (no live keyed path, env vars inert, warning
correctly on stderr only), the six Capability Indexes plus Openness/Decision/Coding-Agent
surfaces are real, correctly valued, honestly labelled and keyless, the coverage bug is
genuinely fixed for the two tools that had it, degradation on 404/empty/all-null/corrupt
payloads and offline cold start is actionable everywhere I poked, and the whole 630-test
suite + sweep (299 calls, 0 unexpected failures) is green. What is *not* max quality: one
latent crash (H1) where a documented AA payload shape — a string back-reference inside a row
array — takes out five tools at once with a bare `AttributeError` instead of the graceful
degradation the code advertises; the same coverage-defect class survives unfixed in
`aa_pareto` (M3); a `name=` filter can silently return the whole dataset while claiming to
have filtered (M1); the estimated-score legend mislabels real published index values (M2);
and the shipped copy still says "700-row" in seven user-visible strings the doc refresh
missed. Fix H1 + M1 + M3 (a handful of lines) and the "max quality" claim is defensible;
leave them and the next adversarial pass will find them again.

---

**Finding counts:** HIGH 1 · MEDIUM 4 · LOW 7 (12 total).

**Three worst:** (1) H1 — `AttributeError` from a non-dict row breaks `aa_leaderboard`,
`aa_benchmark_leaderboard`, `aa_model`, `aa_pareto`, `aa_compare`; (2) M1 — a non-ASCII
`name=` filter is silently ignored while the header reports it as applied, returning the
wrong result set; (3) M3 — `aa_pareto` reports a post-filter model count next to
"(703 tracked)", the exact defect class this change set out to eliminate.

**Verdict paragraph:** see above.

---

## Round-2 fix log (server.py + select.py + server tests + sweep)

Fixed by the `server.py` owner this round (see the chat hand-off for before/after):

- **M1** — `select.py:130-149`: a `name=` that yields no alphanumeric token is now
  `name_unmatchable` and matches nothing (was: silently disabled the filter).
- **M2** — `server.py` `_benchmark_leaderboard`: `starred = key == "intelligence"` gates
  both the `*` marker and its count; the legend now reads "the model's Intelligence Index
  is AA-estimated …".
- **M3** — `server.py` `_pareto`: the frontier footnote appends " matching your filters"
  when any narrowing filter is present.
- **M4** — eight user-visible "700-row" strings reworded to "leaderboard" /
  "leaderboard snapshot" (server.py + the `aa_compare`/`aa_benchmark_leaderboard`
  docstrings).
- **L1** — `_capability_coverage_note` distinguishes "not on the chart set" from "page
  could not be read this call".
- **L2** — dead keyed-API plumbing removed from `server.py`: the unreachable
  `source_hint == "api"` / `surface == "api"` arms, the unused `_cache_ttl(api)` and
  `_cache_aware(refresh)` parameters, and the vestigial `_lb_cache()` tuple (now returns
  the cache-name string). **Not fixed (not my file):** `catalog.py:933`
  (`_b.source_hint not in ("api", "none")`) still carries an unreachable `"api"` arm —
  hand to the `catalog.py` owner.
- **L5** — `_fields_trim(fields)`: a wildcard `fields=all`/`*` now trims all-null columns
  like the default set (no more all-`-` `Precision` column), while an explicitly named
  column is still rendered with `-`.
- **L6** — deleted the three tool-signature mirrors, the two registry-string mirrors and
  the two helper mirrors; replaced them with behaviour tests (and the sweep gained cases
  for the zero-token filter, the filtered frontier footnote, the Openness estimate marker
  and `fields=all`).
- **H1** was **not** fixed (it belongs to `loaders.py`, owned by the coverage worker):
  `parse_capability_index` / `parse_index_rows` still crash on a non-dict array element.

Also corrected in the sweep: the `hleDiamond` expectation string ("700-row leaderboard"
→ "leaderboard").
