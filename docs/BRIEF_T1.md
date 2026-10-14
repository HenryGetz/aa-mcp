# T1 brief — core data layer

Owner of these files (create them):
`src/aa_mcp/fetch.py`, `src/aa_mcp/flight.py`, `src/aa_mcp/catalog.py`,
`src/aa_mcp/normalize.py`, `src/aa_mcp/select.py`, `src/aa_mcp/render.py`,
plus tests: `tests/test_fetch.py`, `tests/test_flight.py`, `tests/test_catalog.py`,
`tests/test_normalize.py`, `tests/test_select.py`, `tests/test_render.py`.

Exact signatures/semantics: `docs/INTERFACES.md` sections "Module APIs" for
fetch.py, flight.py, catalog.py, normalize.py, select.py, render.py.

## Requirements beyond the signatures

fetch.py
- stdlib `urllib.request` only; headers: browser UA + `Accept-Encoding: gzip`
  (+ `RSC: 1` when `rsc=True`); transparent gzip decode; 60 s timeout; 1 retry on
  transient (5xx/URLError) with 0.7 s backoff.
- Atomic cache write (`.tmp` + `os.replace`), `fcntl.flock` guard, TTL default from
  `AA_CACHE_TTL` else 3600 s, dir from `AA_CACHE_DIR` else `~/.cache/aa-mcp`.
- Serve stale cache when the network fails and a cache file exists (`stale=True`,
  log warning to stderr). Raise `AAFetchError` with `.url/.path/.hint` when there is
  no cache. Hint must tell the operator to render the URL in a browser and save the
  HTML at `.path`, then retry.
- `AA_OFFLINE=1` forces cache-only mode (never touches the network). This is used by
  tests and by the eval harness. In offline mode with no cache file -> `AAFetchError`.
- `min_bytes` check on the decoded body.

flight.py
- Must handle both raw RSC payloads (fixture `leaderboard.rsc` starts with
  `1:"$Sreact.fragment"`) and full HTML (join `self.__next_f.push([1,"..."])` chunks
  by JSON-decoding each string). Detect via `self.__next_f.push` presence.
- `find_array` selects an array of dicts whose **first** item contains every
  `required` key; `last=True` picks the last match; must skip arrays that fail
  `min_len`. Must decode arrays that are embedded inside larger flight structures
  (the media pages put them inside `32:[[null,[{...}]]]`).
- Performance guard: scanning `providers_board.rsc` (2.6 MB) and
  `model_page_legacy.rsc` (3.1 MB) with `find_array` must not exceed ~1.5 s each.
  Avoid re-decoding from every candidate when cheap pruning is possible (e.g. binary
  search for the required key string before attempting decode).
- `keyed_object(payload, key)` finds `"key":{` (used for legacy `currentModel`).
  It must not false-positive on `"key"` occurrences inside unrelated strings — decode
  from the nearest following `{` and accept the decoded dict (raw_decode handles this).

catalog.py
- Build from the live vocabulary in `tests/fixtures/openapi.yaml` (authoritative
  field names + one-line descriptions, Pro `Evaluations` schema), `metrics.md`
  knowledge in INTERFACES.md, and the fixture payload keys. `openapi.yaml` is a test
  fixture only — parse it in tests if useful, do not depend on it at runtime; the
  registry must be plain Python data in `catalog.py`.
- `BENCHMARKS` must contain an entry for every benchmark reachable from AA's
  `/evaluations` surface that maps to a field in our data (see INTERFACES.md list),
  each with `slug` (AA eval page slug where one exists), `unit`, `desc`, `tags`,
  `index_member`. Benchmarks that exist on the site but have no known data field must
  still be listed with `key` == their canonical snake_case name and `desc` noting the
  source, or be omitted if genuinely unknowable — no invented numbers.
- `format_value` is the single source of truth for user-visible formatting: `None ->
  "-"`; `pct` -> `%` with 1 decimal; `elo` -> integer with no unit; `index` -> 1
  decimal; `usd` -> `$` + 2 decimals (4 for per-task costs under $0.01); `tps` -> 1
  decimal; `sec` -> 1 decimal + `s`; `tokens` -> compact (`78k`); `int` -> thousands
  separators; `bool` -> `yes`/`no`; `date` -> as-is.
- `FIELD_ALIASES` must accept: canonical key, human label (`GPQA Diamond`),
  eval-page slug (`gpqa-diamond`), lowercase/underscore/hyphen variants, and common
  shorthands (`intel` -> intelligence, `cost` -> cost_per_task, `ttft`, `tps`,
  `ctx` -> context_tokens, `params`, `open` -> is_open_weights, `n` -> name).

normalize.py
- `from_leaderboard` handles `intelligenceIndexCostPerTask` as a plain float.
- `from_chart` handles it as `{"cost": {"total": ...}, "evaluations": [...]}`, plus
  `capabilities` (6 capability indexes -> `indices["capabilities.<key>"]`),
  `briefcaseBreakdown.overall.elo` -> `evals["briefcaseElo"]`, `effort.label`,
  `release.deprecatedTo`, `parameters`/`inferenceParametersActiveBillions`,
  `knowledgeCutoffDate`, `licenseName`/`licenseUrl`/`modelWeightsSourceUrl`,
  `omniscienceHallucinationRate`, `price1mBlended*`, `cacheHitDiscountPercent`.
- `from_legacy` handles the `currentModel` shape (see fixture
  `model_page_legacy.rsc`): `openness.opennessIndex`, `timescaleData`,
  `endToEndResponseTime.total`, `timeToFirstAnswerToken.total`, `parameters`,
  `inferenceParametersActiveBillions`, `input/outputModality*`, `briefcaseBreakdown`.
- Elo-valued evals must not be divided by 100 anywhere; percentages stay fractions
  in `Model.evals` (formatting layer scales them). Document this in a comment.
- `source` values exactly: `"leaderboard"`, `"chart"`, `"legacy"`.

select.py
- `sort_models` accepts a metric key (any `METRICS` key) or a `Model` attribute name;
  missing values always sort last regardless of direction.
- `value_rank` sets `model.value = score / cost_per_task` (skip cost<=0 or None).
- `pareto` keeps the cost-ascending frontier of non-dominated `(cost, score)`.
- `resolve` must prefer an exact slug/release-slug match, then exact normalized
  `short_name`/`name`, then unique substring match; only then raise
  `AmbiguousError` with `.candidates` (max 8, intel-sorted) — ambiguity must never
  be silent.

render.py
- `table` renders a GitHub markdown table with a `|---|---|` separator; empty rows ->
  return an empty string (caller decides how to explain). Keep it cheap: `str.join`.
- `header` returns one line like `# 42/700 models · sorted by intelligence · 3m ago · aa:rsc`
  (no parameter echo). `ago` supports s/m/h/d.

## Acceptance (self-check with fixtures, do not run repo-wide gates)

- `AA_OFFLINE=1` + fixture paths: reading `tests/fixtures/leaderboard.rsc` through
  `flight.payload` + `find_array(["intelligenceIndex"])` yields exactly 700 dicts
  whose `from_leaderboard` conversion gives 700 `Model` objects; at least 180 have
  `cost_per_task`; slug `claude-opus-5-5` resolves to intelligence > 50.
- `model_page_chart.rsc`: `find_array(["intelligenceIndexCostPerTask"])` yields 27
  records; `from_chart` on the `claude-fable-5-1` record gives
  `cost_per_task ≈ 7.63`, `indices["capabilities.legal"] ≈ 60.49`,
  `evals["briefcaseElo"] ≈ 1673.52`, `effort == "max"`, `pricing["in"] == 10`.
- `model_page_legacy.rsc`: `keyed_object(payload, "currentModel")` yields a dict with
  `slug == "glm-4-5v"`; `from_legacy` gives `context_tokens == 64000`, `license == "MIT"`.
- Your own offline unit tests pass via `uv run pytest tests/test_flight.py tests/test_catalog.py tests/test_normalize.py tests/test_select.py tests/test_render.py`.
- No file in `src/` imports pandas/requests/bs4/yaml.

Report in your final message: files created, exact pytest command + result, any
INTERFACES.md discrepancy, anything you could not verify offline.
