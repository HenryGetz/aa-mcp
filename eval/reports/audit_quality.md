# Audit A — code quality & correctness review (read-only)

Repo: `aa-mcp` @ `804fcea`. Method: full read of `src/aa_mcp/*` (6186 LOC), fixtures-driven
reproduction with `AA_OFFLINE=1` + `AA_CACHE_DIR` pointing at copies of `tests/fixtures/`, and
measurements of the parse/scan paths on the 3.2 MB / 2.7 MB / 2.0 MB captures. Environment:
`.venv` Python 3.12.14; `pytest -q` = 226 passed, 18.9 s; `scripts/gen_reference_md.py --check`
exits 0. Every finding below was reproduced or is quoted verbatim from the cited lines; the
"not verified" section lists what I could not close.

Ordering: HIGH (5), MEDIUM (8), LOW (7).

---

## HIGH — `aa_media` crashes on all three speech boards (`NameError: board_key`)

- `src/aa_mcp/server.py:1660-1661` (in `_media`, whose local is `key_name`, `server.py:1638`)
- What is wrong:

```python
        note = (f"{board_key} · speech, WER lower is better" if speech != "sts"
                else f"{board_key} · speech, STS index")
```

`board_key` is only ever bound in `_agents` (`server.py:1708`); `grep -n board_key
src/aa_mcp/server.py` returns 1660, 1661, 1708, 1709, 1721, 1722. Both branches of the
conditional reference it, so the f-string raises
`NameError: name 'board_key' is not defined`. Reproduced offline, with `home.rsc` in the cache:

```
$ AA_OFFLINE=1 AA_CACHE_DIR=/tmp/aacache .venv/bin/python -c "import aa_mcp.server as s; s._media('speech_to_text', top=3)"
RAISED NameError name 'board_key' is not defined
$ ... s._media('speech_to_speech', top=3)
RAISED NameError name 'board_key' is not defined
```

- Why it matters: `aa_media board=speech_to_text|speech_to_text_streaming|speech_to_speech`
  is documented in the tool docstring, the README ("speech-to-text / streaming / realtime
  voice") and `reference.TOPICS['media']`, and it is one of the product's headline surfaces.
  The client only sees `_tool`'s generic branch (`server.py:247-251`):
  `aa_media failed: NameError: name 'board_key' is not defined`. CI cannot catch it: there is no
  `tests/test_server.py`, and `scripts/surface_sweep.py` (which does cover the speech boards,
  `surface_sweep.py:97-100`) is untracked and network-gated.
- Suggested fix: use `key_name` in both f-strings.

```python
        note = (f"{key_name} · speech, WER lower is better" if speech != "sts"
                else f"{key_name} · speech, STS index")
```

---

## HIGH — `aa_benchmark_leaderboard` ranks lower-is-better benchmarks backwards

- `src/aa_mcp/server.py:1273` (and the same shape at `src/aa_mcp/loaders.py:1332-1337`)
- What is wrong: the ranking sort ignores the metric direction that `catalog` already models
  (`catalog.py:380-385`: `_LOWER_IS_BETTER = {omniscienceHallucinationRate, cweBenchRefusalRate,
  cybergymE2eRefusalRate, deepsecBenchRefusalRate}` → `Metric.better == "low"`):

```python
    pairs.sort(key=lambda t: t[1], reverse=True)
```

  `select.sort_models` (`select.py:113-116`) and `_endpoint_sort` (`server.py:1437-1441`) honour
  `better`, this one does not. Reproduced against the shipped rich-dataset fixture:

```
$ aa mcp _benchmark_leaderboard('omniscienceHallucinationRate', top=3)
| Model | Slug | Creator | Omni Halluc | Intel |
| Qwen3.5 0.8B (Non-reasoning) | qwen3-5-0-8b-non-reasoning | Alibaba | 98.5% | 5.4 |
| Qwen3.5 9B (Non-reasoning)  | qwen3-5-9b-non-reasoning  | Alibaba | 98.4% | 13.3 |
| Gemma 3 4B Instruct         | gemma-3-4b                | Google  | 98.2% | 4.8 |
```

- Why it matters: the tool's contract is "who leads a given benchmark"; for
  `omniscienceHallucinationRate` (573 of 699 rich models scored) it names the *worst*
  hallucinators as the leaders, and the four refusal-rate keys are affected in the same way.
  `aa_benchmark_leaderboard` was verified end-to-end here; the chart-set path inherits the same
  direction bug through `loaders.eval_models` ("best first" sort, `loaders.py:1332-1337`).
- Suggested fix:

```python
    _m = catalog.metric(key)
    pairs.sort(key=lambda t: t[1], reverse=not (_m is not None and _m.better == "low"))
```

---

## HIGH — `select.value_rank` mutates memoized `Model` objects; the frontier "knee" reads the stale value

- `src/aa_mcp/select.py:165-174` (write) and `src/aa_mcp/server.py:609-611` (read before recompute)
- What is wrong: `value_rank` writes the derived `value` onto the caller's objects, and the
  server hands it the *shared* memo list (`server._MODELS_MEMO` → `_models_state`, reused by
  every tool call for the process lifetime):

```python
        if score is not None and cost is not None and cost > 0:
            m.value = score / cost          # select.py:172
```

  `mode="frontier"` then picks the knee **before** `value_rank` runs (server.py:609-611):

```python
        knee = max(frontier, key=lambda m: (m.value if m.value is not None
                                            else (m.intelligence or 0) / (m.cost_per_task or 1)))
        select.value_rank(frontier, score_key=sort_key)
```

  Reproduced: the identical call returns different knees depending on a previous call.

```
1st run  aa_leaderboard(mode='frontier', sort='intelligence')
         — knee ≈ GPT-6 Luna (High): $0.03/task, intel 32.9
then     aa_leaderboard(mode='value', sort='omniscience')
3rd run  aa_leaderboard(mode='frontier', sort='intelligence')   # same args as run 1
         — knee ≈ GPT-6.1 Sol (Low): $0.13/task, intel 42.1
```

- Why it matters: tool output is order-dependent (and thread-racy — the MCP server runs sync
  tools on a pool, so two concurrent requests can interleave `.value` writes across
  `sort` keys the caller never asked about). An agent caching or comparing two leaderboard
  answers gets contradictory "best trade-off" points from the same arguments.
- Suggested fix: stop storing derived values on shared objects — compute the knee from
  `select.lookup(m, sort_key)` and have `value_rank` return `(model, value)` pairs (or
  `dataclasses.replace(m, value=...)`).

---

## HIGH — `flight._scan` requires the array's first element to be a dict, so real chart/rich arrays are invisible

- `src/aa_mcp/flight.py:77-89` (guard at `:86`), consumed by `loaders._rich_records`
  (`loaders.py:345-355`) and `loaders.parse_chart` (`loaders.py:384-402`)
- What is wrong: the scan mutates the "first item contains all required keys" rule into
  "`value[0]` must be a dict", and the anchor test one line earlier (`text[k] == "{"`) rejects
  arrays that start with a string:

```python
        if k < n and payload_text[k] == "{":          # flight.py:77
            ...
            if (isinstance(value, list) and len(value) >= min_len and value
                and isinstance(value[0], dict)        # flight.py:86
                and required <= value[0].keys()):     # flight.py:87
                yield value
```

  The captured legacy page embeds exactly that shape — `tests/fixtures/model_page_legacy.rsc`:
  `"initialModels":[ "...:props:currentModel", "...:props:models:35", ... ]` (28 refs, 27 of them
  `models:<N>`) and the pool they index is `"models":[ "$e:...", {…92 keys, has 'capabilities'…}, … ]`
  — 700 items, first element a string. Measured:

```
flight.find_arrays(payload, ("chartDefaultSelected","releaseDate","suffix"))  ->  0 arrays (0.06 s)
loaders.parse_chart(model_page_legacy.rsc)                                     ->  1 model
loaders.parse_rich_dataset(model_page_legacy.rsc)                              ->  0 models
# with the anchor/first-element check relaxed to "first *dict* element":
relaxed scan on the same payload ->  1 array of 700 items (2.0-2.6 s)
```

- Why it matters: on such a page `_resolve_refs` (`loaders.py:357-381`) gets `pool=None` and
  silently drops all 27 `:models:<N>` references — the page's chart set collapses to the single
  `currentModel` record (27 sibling records lost, no error, no log), and `rich_dataset()`
  (`loaders.py:556-589`) can never discover the ~700-record dataset from it, so the
  `aa:rsc + rich dataset` overlay (capability indexes, Elo, licences, effort labels — the
  README's "700 × 94 dataset") stays off for the whole process. The repo's own test sidesteps
  this: `_rich_page()` (`tests/test_loaders.py:544-550`, used by `test_parse_chart_resolves_refs_to_chart_set` at `:559`) hand-builds the pool as
  `{"props": {"models": records}}` where `records[0]` *is* a dict, so
  `test_parse_chart_resolves_refs_to_chart_set` passes while the real capture degrades.
- Suggested fix: locate the probe item as the first *dict* element and let the anchor test accept
  a `["` start; keep it cheap by only decoding after the anchor (the naive relaxation costs
  ~2.6 s on the 3.2 MB page, so short-circuit once `min_len`/required keys are satisfied):

```python
        if k < n and payload_text[k] == "{":
            ...
                first = next((x for x in value if isinstance(x, dict)), None)
                if first is not None and required <= first.keys():
                    yield value
```

  (plus allowing `["` at `:77`, or anchoring on `":"models":["` for the rich-pool lookup).

---

## HIGH — speech-board `open_weights` filter reads a key that does not exist, silently emptying the board

- `src/aa_mcp/server.py:1643-1646`
- What is wrong:

```python
        rows = loaders.home_boards(refresh=refresh).get(speech) or []
        if open_weights is not None:
            rows = [r for r in rows if r.get("openWeights") == open_weights]
        if not rows:
            return f"# no rows for speech board {board!r} in the homepage payload"
```

  `parse_home_boards` returns the homepage rows verbatim (`loaders.py:909-924`), and those rows
  carry no open-weights flag. Verified: `grep -c openWeights tests/fixtures/home.rsc` → 0, while
  the STT row keys are `['color','creatorName','id','isDefault','isFallbackDefault','logo','name',
  'timeToFinalTranscriptSeconds','url','werIndex']` (15 rows) and the STS rows have no `openWeights`
  either. The arena path uses a normalization helper for exactly this reason
  (`loaders._media_open_weights`, `loaders.py:947-952`, which also handles `openWeightsUrl`).
- Why it matters: `aa_media board=speech_to_text open_weights=false` (or `true`) answers
  "no rows for speech board 'speech_to_text' in the homepage payload" although 15 rows exist —
  a wrong empty result presented as a payload problem, on a documented parameter.
- Suggested fix: filter with the shared normalizer, or drop the parameter for speech boards with
  an explicit note:

```python
        if open_weights is not None:
            rows = [r for r in rows if loaders._media_open_weights(r) == open_weights]
```

---

## MEDIUM — `aa_leaderboard(sort=<breakdown benchmark>)` raises `AttributeError`

- `src/aa_mcp/server.py:574`
- What is wrong: `_metric_key` accepts any `catalog.BENCHMARKS` key (`server.py:193-208`), but
  `unit == "mixed"` benchmarks are deliberately kept out of `METRICS` (`catalog.py:386-388`), so
  `catalog.metric(sort_key)` is `None`:

```python
    label = catalog.metric(sort_key).label
```

```
$ .venv/bin/python -c "import aa_mcp.server as s; s._leaderboard(sort='briefcaseBreakdown', top=2)"
AttributeError: 'NoneType' object has no attribute 'label'
```

- Why it matters: `sort="briefcaseBreakdown"` (also `automationBenchBreakdown`, `gdpvalBreakdown`,
  `harveyLabBreakdown`, `gdpPdfBreakdown`, `aa3dBreakdown`,
  `enterpriseOpsGymSuccessRateByDomain`) — all advertised by `aa_benchmarks`/`aa_reference` — fails
  in every mode with a generic `aa_leaderboard failed: AttributeError: …` instead of an actionable
  message.
- Suggested fix: `label = (catalog.metric(sort_key) or catalog.BENCHMARKS[sort_key]).label`
  (or reject mixed-unit keys in `_metric_key` with a `ValueError`).

---

## MEDIUM — `mode="value"` labels a `sort`-dependent ratio as `Intel/$`

- `src/aa_mcp/server.py:601`
- What is wrong: the column header is hard-coded while the value is `lookup(sort_key)/cost`:

```python
        cols = _cols(_LB_COLS + [("value", "Intel/$")], fields, _LB_EXTRA, _LB_IDENTITY)
```

  Reproduced with `sort=omniscience`: the header line says `value = Omniscience per $/task` but the
  column is `Intel/$`, and the row `GPT-6.1 Sol (Low)` shows `Intel 42.1 · $/Task $0.13 ·
  Intel/$ 287.8` — 287.8 ≈ omniscience 37.6 / 0.13, whereas the labelled quantity would be ≈ 324.
- Why it matters: the number column contradicts its own header, so an agent reading the table (and
  not the note) attributes the value to the wrong metric.
- Suggested fix: use the resolved label, e.g.
  `_cols(_LB_COLS + [("value", f"{label}/$")], ...)`.

---

## MEDIUM — `refresh=True` bypasses the memos and issues 14 HTTP GETs for one tool call

- `src/aa_mcp/server.py:438-451` (`memo is not None and not refresh`),
  `src/aa_mcp/loaders.py:535` (same for `_RICH_MEMO`)
- What is wrong: `_models()` and `_models_rich()` each call `_models_state(refresh)`, and with
  `refresh=True` the memo is skipped on every call, so the leaderboard is re-fetched and the rich
  seed re-probed per call site. Measured with `fetch.get` instrumented (network failing so the
  stale-cache path is used):

```
aa_leaderboard(refresh=True)          -> 14 fetch.get calls: 2 x leaderboard, 2 x each of 6 rich seed probes
aa_benchmark_leaderboard(refresh=True) ->  3 fetch.get calls: 3 x leaderboard
```

- Why it matters: `refresh=true` is the documented way to see "released today" models, but it
  multiplies load, latency and (for the API backend) quota by 2-3x; each rich probe downloads and
  parses a 0.75-3.2 MB model page. One `aa_model` call reads and
  re-scans its page twice (`loaders.model` plus `_prompt_speed`, which issues its own
  `fetch.get`, `server.py:784-790`), and `aa_benchmark_leaderboard` fetches the page a
  third time for CI/fallback enrichment (`server.py:1327-1331`, `1358-1362`).
- Suggested fix: resolve `_models_state(refresh)` once per tool call and pass `(models, rich_used)`
  down, or have `_models_state` store the refreshed tuple and let `_models`/`_models_rich` read it.

---

## MEDIUM — `rich_dataset` memo ignores `AA_RICH_TTL` and caches a failed discovery forever

- `src/aa_mcp/loaders.py:535-536` and `:587-589`
- What is wrong: the memo key is the cache path only, and the TTL check lives on the cold path, so
  after the first load the age is never consulted again:

```python
    if _RICH_MEMO is not None and _RICH_MEMO[0] == str(path) and not refresh:
        return _RICH_MEMO[1]                     # loaders.py:535
    ...
        if _offline() or age <= _rich_ttl():     # :549 — only reached on a cold memo
    ...
    log.warning("rich dataset not found in %d probe(s)", _RICH_PROBES)
    _RICH_MEMO = (str(path), [])                 # :588 — empty result pinned for the process
```

  The leaderboard memo does it correctly by keying on `(path, fetched_at)` (`loaders.py:620`).
- Why it matters: a long-lived stdio server never picks up a refreshed rich dataset (the overlay
  is what supplies capability indexes, Elo, licences and effort for 699 models), and one transient
  network failure permanently disables the overlay for the process — `_discover_rich_seed` is never
  retried.
- Suggested fix: key the memo on `(str(path), mtime)` (or re-check `age <= _rich_ttl()` before
  returning) and do not memoize `[]`.

---

## MEDIUM — `aa_reference topic=fields` advertises field names that `fields=` rejects

- `src/aa_mcp/reference.py:17` (served by `aa_reference topic=fields` and `aa://reference/fields`),
  resolving in `src/aa_mcp/server.py:193-208`
- What is wrong: the reference text lists `reasoning_time`, `weights_url`, `modalities_in`,
  `modalities_out` and `$/task` as accepted names, but none resolve. Measured by feeding every
  token of that text through `server._metric_key(name, "field")`:

```
documented-but-unresolvable: ['reasoning_time', 'modalities_in', 'modalities_out', 'weights_url', 'task' ($/task)]
$ catalog.metric('reasoning_time') -> None ; catalog.metric('modalities_in') -> None
```

  `reasoning_time` (the metric is `reasoning_s`), `modalities_in`/`modalities_out`/`weights_url`
  (Model fields that were never registered in `catalog.METRICS`) and `$/task` (only a display
  label) are all rejected with `unknown field …`.
- Why it matters: the reference text is the *authoritative* doc agents are told to consult
  ("aa_reference topic=fields lists every accepted name"), so following it produces an error
  instead of a table — e.g. `aa_leaderboard fields=reasoning_time`.
- Suggested fix: register the four names in `catalog.METRICS` (or add them to `FIELD_ALIASES`),
  and either accept `$/task` or drop it from the reference text.

---

## MEDIUM — `docs/INTERFACES.md` has drifted from the shipped tool surface

- `docs/INTERFACES.md:330` ("all accept `refresh: bool = False`"), `:338` (`include_raw=False`),
  `:343` ("filters as in (1)"), `:355-356` (resource list)
- What is wrong (all verified against `server.py`):
  - `aa_benchmarks` (`server.py:1985`) and `aa_reference` (`server.py:2121`) take no `refresh`;
    `aa_benchmarks` does load data, so the doc's claim is not merely cosmetic.
  - `aa_model` (`server.py:1950`) has no `include_raw` parameter.
  - `aa_benchmark_leaderboard` (`server.py:1999-2008`) implements only `creator`, `open_weights`,
    `min_intelligence` — not "filters as in (1)".
  - `:355` lists 4 resources; the app registers 12 (4 explicit + the `reference.TOPICS` loop,
    `server.py:2137-2224`), which README also states. Tool/prompt counts (11/2) do match.
- Why it matters: the file is declared the "frozen contract" between modules and the first thing a
  contributor or client author reads; each item above is a call that fails schema validation.
- Suggested fix: update the four spots (or add the parameters) — they are documentation-only.

---

## MEDIUM — the 226 tests never touch `server.py`

- `tests/` (no `test_server.py`; `pytest -q` → 226 passed)
- What is wrong: `src/aa_mcp/server.py` is 2289 LOC (37 % of the package) and holds the whole
  user-visible surface — every tool entry point, header/coverage/footnote text, the estimate
  marker, the value/frontier modes, prompts and resources. It has zero offline tests; CI runs only
  `pytest`, an import check and `eval/client.py tools` (`list_tools`, no calls)
  (`.github/workflows/ci.yml`). Consequently the HIGH findings above (the speech `NameError`, the
  inverted refusal sort, the stale `.value` knee) all ship green.
- Also weak: `tests/test_loaders.py:370-373` is named
  `test_leaderboard_memo_is_keyed_by_fetch_time` but only asserts `leaderboard() is first`, i.e. a
  memo *hit*; nothing exercises invalidation when the fetch time changes.
- Plausible consumer-visible bugs currently uncovered (name only, not written):
  1. every speech-board call (the `board_key` crash);
  2. `mode="frontier"` knee after any prior `mode="value"` call, and value/frontier under two
     concurrent calls on one process;
  3. `sort=`/`benchmark=` for the four lower-is-better keys (`omniscienceHallucinationRate`,
     `cweBenchRefusalRate`, `cybergymE2eRefusalRate`, `deepsecBenchRefusalRate`);
  4. `sort=` for a mixed-unit breakdown key (`briefcaseBreakdown` …);
  5. `fields=` with any documented-but-unregistered name (`reasoning_time`, `modalities_in`);
  6. chart-set resolution on a page whose pool array leads with a flight reference (the real
     `model_page_legacy.rsc`, rather than the synthetic `_rich_page()`);
  7. `open_weights` on speech boards, and `released_after` dropping rows with no `release_date`
     (no `_missing_notes` entry, `server.py:581-587`);
  8. `top=0`/`top=-3` silently becoming 10/15 (no error, no note).
- Suggested fix: add a fixture-backed `tests/test_server.py` that calls the tool functions
  directly under `AA_OFFLINE=1` (the pattern used by `tests/test_api.py:192-234`), starting with
  items 1-4.

---

## MEDIUM — `_media_row` assumes `values`/`formatted` are mappings

- `src/aa_mcp/loaders.py:956-958`
- What is wrong:

```python
def _media_row(item: dict) -> dict:
    values = item.get("values") or {}
    formatted = item.get("formatted") or {}
    creator = values.get("creator")
```

  the `or {}` guard only replaces *falsy* values, so a truthy non-mapping (`"values": [...]`) gives
  `AttributeError: 'list' object has no attribute 'get'` out of `parse_media` (`loaders.py:999`),
  reaching the client as `aa_media failed: AttributeError: …`. `find_arrays` validates only
  `value[0]` (`flight.py:86-87`), so items 2..N are unvalidated, and `formatted.get("rank")`,
  `formatted.get("name")`, `formatted.get("released")` (`loaders.py:962-971`) have the same shape
  of exposure. Not triggered by any captured fixture.
- Why it matters: AA ships `values` in two shapes already (arena dicts vs the agent wrapper that
  `_unwrap_row` exists to unwrap, `loaders.py:1022-1029`); one page-shape change turns a whole
  media board into a generic error instead of a row-skipping parse.
- Suggested fix: `values = item.get("values"); values = values if isinstance(values, dict) else {}`
  (same for `formatted`).

---

## LOW — `_UNTRACKED_FALLBACK` is dead and its wording has diverged

- `src/aa_mcp/server.py:1059-1065`, consumed at `:1071-1075`
- What is wrong: `_untracked` only falls back when `catalog.UNTRACKED_BENCHMARKS` is empty, and that
  dict is a non-empty module constant (`catalog.py:280-291`, 11 entries), so the server copy is
  unreachable — and it has already drifted textually (catalog suggests "MMMU-Pro plus the
  per-model image/video input modality flags"; the server copy suggests "MATH-500 or AIME 2025").
- Why it matters: two answers to "does AA track MathVista?" — the visible one is the catalog's.
- Suggested fix: delete `_UNTRACKED_FALLBACK` and use `catalog.UNTRACKED_BENCHMARKS` directly.

---

## LOW — two header renderers; `render.header` is production-dead

- `src/aa_mcp/render.py:42-62` vs `src/aa_mcp/server.py:125-151`
- What is wrong: `render.header` is exported (`render.__all__`) and referenced only by
  `tests/test_render.py:21-28`; every tool uses `server._header`, which re-implements the same
  `# … · ago · aa:<source>` shape plus the `stale:` logic. `grep -rn "render.header" src/` → no hits.
- Why it matters: the frozen-contract header API is bypassed in production, so the doc and the code
  disagree about who owns the header format (and the duplicated logic will drift).
- Suggested fix: have `_header` delegate to `render.header` (passing `count`/`note`/`as_of`/
  `source_label`), or delete `render.header` and its test.

---

## LOW — `include_estimates` promises a `*` marker that is never rendered

- `src/aa_mcp/server.py:2024-2025` (docstring) vs `:1300-1301` (rendering)
- What is wrong: the docstring says "estimates are marked with *", but the benchmark-leaderboard
  cell is `cells.append(_fmt(key, value))` with no `m.estimated` check; the marker only exists in
  `_model_indices` (`server.py:710`). `grep -n estimat src/aa_mcp/server.py` shows the only uses are
  the filter (`:1201`) and the marker in the digest.
- Why it matters: an agent told that estimates are flagged may treat an AA-estimated benchmark
  score as measured; `include_estimates=False` still filters correctly.
- Suggested fix: append `"*"` when `m.estimated` in the `score` branch, or drop the doc claim.

---

## LOW — duplicated labels/formatting between `server.py` and `catalog.py`

- `src/aa_mcp/server.py:514-518, 601, 981-989, 1405-1408, 1568-1578, 1626`;
  `src/aa_mcp/catalog.py:335, 341-342`
- What is wrong (all confirmed by inspection; the last one changes output):
  - `_LB_COLS` labels `cost_per_task` as `"$/Task"` while `catalog.METRICS["cost_per_task"].label`
    is `"Cost"` — the same key has two names in one product, and `_cols` derives labels from
    `catalog` (`server.py:271-273`) while the defaults do not.
  - `_media_cell` formats arena Elo via `_fmt("briefcaseElo", row.get("elo"))` — arena Elo is
    coupled to an unrelated benchmark key purely to borrow `kind == "elo"`.
  - `_CAP_LABELS` (`server.py:726-732`) renames `capabilities.*` ("Finance & Accounting") while
    `catalog.BENCHMARKS` labels them "Cap Finance" — `aa_model` and `aa_benchmarks` name the same
    metric differently.
  - Benchmark-derived `Metric.label`s are truncated with `_b.label[:12]` (`catalog.py:392`), so
    `fields=terminalBench21` renders the column `Terminal-Ben` and `fields=cweBenchRefusalRate`
    renders `CWE Refusal` — legitimate but worth knowing before it lands in a snapshot test.
  - `_EXTRA_ALIASES` (`server.py:161-185`) largely restates aliases that `catalog._ALIAS_NORM`
    already resolves from benchmark labels (`catalog.metric("caplegal")` is non-`None`); only the
    `*index` spellings (`legalindex`, …) are load-bearing.
- Why it matters: the metric registry is documented as "the single source of truth for
  formatting"; each duplicate is a place a fix lands in only one tool.
- Suggested fix: build the server's column tables as `(key, catalog.metric(key).label)` lists and
  move the residual aliases into `catalog`.

---

## LOW — unused/dead API surface and noise in `loaders.py` / `flight.py`

- `loaders.py:65` (`rich_models` in `__all__`, defined `:592-600`, no caller in `src|scripts|eval|tests`),
  `flight.py:17-25` (`jsonld`, `text_strip_tags`, `find_objects` used only by tests),
  `loaders.py:347-350` and `:1236-1239` (`except LookupError` around `find_arrays`, which cannot
  raise — only `find_array` does), `loaders.py:1444-1449` (`sitemap_paths` logs then re-raises),
  `SOURCE_URLS["media"]`/`["agents"]` (`loaders.py:99-100`, callers use the dedicated dicts)
- What is wrong: dead weight that the interface doc still presents as API.
- Why it matters: each piece is maintenance surface with no consumer; `sitemap_paths`'s
  warning-then-raise double-reports the same failure.
- Suggested fix: delete `rich_models` and the unused `SOURCE_URLS` entries; drop the dead
  `except LookupError`; make `sitemap_paths` either return `[]` or just let the caller handle it.

---

## LOW — eval-page chart records lose identity fields (`aa_raw kind=eval`)

- `src/aa_mcp/normalize.py:90-98` (`_modalities`), `:342-350` (`active_params_b`), `:326-360`
- What is wrong: the eval-page schema (`tests/fixtures/eval_page.rsc`) has no `inputModalityText`
  (0 occurrences; `inputModalityImage` present) and no `inferenceParametersActiveBillions`, so the
  parsed records report `modalities_in=('image',)`, `modalities_out=()` and `active_params_b=None`:

```
parse_chart(eval_page.rsc) -> 19 models; claude-fable-5-1 in=('image',) out=() params=None active=None
```

  (The page does carry `parameters`/`activeParams` — `params_b` also reads `None` here per the
  captured record.) These models only reach the user through `aa_raw kind=eval`, so the blast
  radius is small.
- Why it matters: raw output for the eval surface claims a text-capable model is image-only, and
  drops parameter counts that the payload actually has.
- Suggested fix: add the eval-page spellings (`activeParams`, `medianCanonicalAnswerOutputSpeed`)
  and treat a missing `*ModalityText` as "text" (AA's default), or omit modalities when no flag
  exists.

---

## LOW — smaller correctness/robustness nits

- `src/aa_mcp/loaders.py:811-815`: `bool(rec.get("functionCalling", features.get("functionCalling")))`
  reports "unknown" (`None`) as `False`, while the sibling `openai_compatible` uses `_opt_bool`;
  both live shapes exist (`providers_model.rsc` top-level, `providers_board.rsc` under `features`).
- `src/aa_mcp/server.py:549, 1191, 1479, 1638, 1707, 1736`: `n = top if isinstance(top, int) and top > 0
  else <default>` makes `top=0`/`top=-3` silently return the default instead of erroring.
- `src/aa_mcp/server.py:581-587`: `released_after` drops every row with `release_date is None` and
  is the one filter with no `_missing_notes` entry, so the README's "warn when a filter dropped
  rows that simply have no measurement" does not hold for it (same for `_search`'s `creator`,
  `server.py:1743-1747`).
- `src/aa_mcp/server.py:1645, 1686`: the speech branch numbers rows with `str(i)` and ignores the
  row's own `rank`, unlike `_media_cell` (`:1624`).
- `src/aa_mcp/loaders.py:833-843`: the endpoint tiebreaker `e.price_in or 0.0` sorts "no price"
  before a real `$0.001`; `(e.price_in is None, e.price_in or 0.0)` is the same shape used for
  `cost_per_task` one line above.
- `src/aa_mcp/render.py:6` + `render.pct` vs `server._discount` (`server.py:71-77`): the same
  `cache_hit_discount` field is rendered by two different scalers; fixtures store a fraction
  (0.8166, 0.9) so both agree today, but `format_value` would print `8166.7%` on a 0-100 source
  while `_discount` prints `82%`.

---

## What I verified as sound (do not re-check)

- **`fetch.py` cache semantics**: TTL/`AA_OFFLINE`/stale-serving/`min_bytes`/atomic
  write+`flock` all behave as `INTERFACES.md` describes; the lock is held only across the tmp
  write (`fetch.py:178-198`), readers are lock-free by design, there is no reentrancy path that can
  deadlock, and `clear_cache()` removes `.lock`/`.tmp` leftovers. Lock files are never unlinked,
  which is what makes the flock sound on Linux.
- **Exception boundary**: all 11 tools are wrapped by `@_tool` (`server.py:1893-2134`), whose
  last-resort `except Exception` (`:247-251`) means no raw traceback can reach a client; every
  tool returns an explanatory string rather than a bare empty table (`_table_block`
  `server.py:309-331`, plus per-tool "no models match"/"no endpoints" messages).
- **`None`-last ordering**: `select.sort_models` (`select.py:104-116`) and
  `server._endpoint_sort` (`server.py:1437-1441`) both keep missing values last in either
  direction.
- **Scale/percentage handling**: `cacheHitDiscountPercent` is a fraction in the fixtures (0.8166,
  0.9) and `catalog` kinds it `pct` → `×100` is right; `werIndex` (0.0172) → `1.7%`; agents
  `indexScore` (0.6836) → `68.4%`; `omniscience` (-70..+70) is `index`, never scaled; `_evals`
  stores raw fractions/Elo and only `format_value` scales. No fraction-vs-percent confusion found
  in the normalized layer.
- **`cost_per_task` shape handling**: `loaders._cost_per_task` handles float, flat `{"total": …}`
  and nested `{"cost": {"total": …}}`; `normalize._cost_fields` handles the dict form and folds
  `intelligenceIndexCost`/`briefcaseTotalCost`; the leaderboard float path is separate
  (`normalize.py:267`). Consistent.
- **Leaderboard array selection** by required keys (never by index) correctly rejects the 3-key nav
  array (`loaders.py:269`, `flight.find_array`).
- **Parse cost on the real captures** (measured, `.venv` Python 3.12): `flight.payload` ≈ 0.00-0.01 s;
  `find_arrays(chart keys)` ≤ 0.25 s on the 3.2 MB legacy, 2.7 MB providers, 2.0 MB TTS, 0.8 MB
  chart and 0.6 MB eval pages; `parse_chart` ≤ 0.13 s on each. `_scan` is linear (one `raw_decode`
  per `[` anchor, monotonic advance) — no quadratic or catastrophic-regex path found. The rich
  dataset (700 records) is built once per discovery, not per tool call.
- **Tool/resource/prompt inventory**: 11 tools, 12 resources, 2 prompts, names matching README and
  `INTERFACES.md`'s tool list; `reference.TOPICS` has 9 topics and the registration loop skips only
  `fields`, which is registered explicitly.
- **Docs in sync**: `scripts/gen_reference_md.py --check` → "docs/REFERENCE.md is up to date
  (11091 chars)", exit 0.
- **Memos are not torn**: `_LEADERBOARD_MEMO`, `_RICH_MEMO`, `_MODELS_MEMO` are all published by
  single tuple rebinding; the defect is object mutation (H3), not the memo swap.
- **`merge()`** unions the four dict fields exactly as documented and never resurrects `None`s
  (checked against `test_merge_later_non_none_wins`); `from_leaderboard`/`from_chart`/`from_legacy`
  raise `ValueError` on non-mappings as documented.
- **No 3.11+/3.12-only syntax** in `src/` (no `match` classes, `tomllib`, `batched`, `StrEnum`,
  `TaskGroup`, PEP-701 f-strings), consistent with `requires-python = ">=3.10"`; `pyproject.toml`'s
  entry point (`aa_mcp.server:main`) and wheel package mapping are correct.

## Not verified / out of scope

- **Anything requiring the live network**: Cloudflare behaviour, API quota, and whether today's
  payloads still match the 2026-10-14 captures. All measurements are offline against
  `tests/fixtures/` (+ the rich-dataset fixture) and `/tmp/probe` copies.
- **Whether MCP 2.x actually runs these sync tools on a thread pool** — I did not inspect the SDK
  in `.venv`. It does not change H3: the stale-`.value` knee reproduces sequentially.
- **Whether AA's live pages ever lead the rich-dataset array with a flight-reference string**: I
  verified it on the captured `model_page_legacy.rsc` only, and did not test the end-to-end
  `rich_dataset()` discovery against a live page.
- **Whether label-first precision detection (`loaders.py:222-241`) is intended** — the fixtures
  assert it (`test_precision_from_host_label_and_model_label`), `INTERFACES.md` says "from the slug
  suffix", so only a maintainer can resolve the intent.
- **The full key set of an eval-page chart record** — I confirmed the *absences* used above
  (`inputModalityText`, `inferenceParametersActiveBillions`) by grep and spot-parsed fields, not by
  enumerating all ~40 keys.
- **`aa_agents` score scale for the `chatbots`/`search_api` boards** (only `coding_agents` was
  checked: fraction → `pct` is right), and the 0-100 form of `cache_hit_discount` (absent from the
  fixtures).
