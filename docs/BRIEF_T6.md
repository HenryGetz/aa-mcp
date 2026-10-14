# T6 brief — fidelity fixes (from the independent FidelityCheck report)

Source of truth: `eval/reports/fidelity.md` (independent verification against raw
payloads). Files you own for this task: `src/aa_mcp/loaders.py`,
`src/aa_mcp/normalize.py`, `src/aa_mcp/catalog.py`, `tests/test_loaders.py`,
`tests/test_normalize.py`, `tests/test_catalog.py`, `tests/fixtures/*` (add captures if
needed). Do **not** touch `server.py` (being written right now) and keep every change
**additive** — no renames, no signature changes, so concurrent work stays compatible.

## Fix 1 (critical) — provider endpoint cost/task

`loaders.provider_endpoints()` returns `cost_per_task=None` for every live endpoint,
because `performance.intelligenceIndexCostPerTask` is *flat* on that surface:
`{"total": 5.98, ...}` (verified live for claude-opus-5-5 x4 and claude-opus-5 x3).
`_cost_per_task` only handles a float and the chart shape `{"cost": {"total": …}}`.
Handle all three shapes (`float`, flat `{"total": …}`, nested `{"cost": {"total": …}}`)
in one shared helper and use it for both surfaces. Add a fixture that actually
contains the flat shape (capture `/models/claude-opus-5-5/providers` into
`tests/fixtures/providers_model_flat.rsc`, or extend the existing fixture capture) and
a test asserting a live-observed value: claude-opus-5-5 anthropic endpoint
`cost_per_task ≈ 5.98` (use the exact value you capture), plus that the endpoint list
is sorted by it.

## Fix 2 — dead benchmark claim

`enterpriseOpsGym` (+ `enterpriseOpsGymSuccessRateByDomain`) exists in
`catalog.BENCHMARKS` and has real chart values (10/27 records non-null in the fable
chart fixture) but is missing from `normalize._CHART_EVAL_KEYS`, so no surface can
read it. Add it (and audit the other chart keys against `catalog.BENCHMARKS` so no
other entry is unreachable — list what you checked).

## Fix 3 — leaderboard `release_date` (currently None for all 700 rows)

The same leaderboard payload carries a 506-item array of
`{slug, name, releaseDate, deprecated, creator{slug,name,logo}}` where `slug` is the
*release* slug (e.g. `claude-opus-5-5`) while leaderboard rows are *variant* slugs
(e.g. `claude-opus-5-5-high`). Join them inside `parse_leaderboard` and populate
`Model.release_date` and `Model.creator_slug`. Matching order:
1. exact slug; 2. longest release slug that is a prefix of the variant slug
(`-high`/`-xhigh`/`-low`/`-max`/`-medium` effort suffixes) — require a `-` boundary;
3. no match -> keep `None`. Add a test asserting e.g. `claude-opus-5-5-xhigh` and
`claude-opus-5-5` both get the same non-null `release_date`, and that a random
unmatched slug stays `None` (no false positives).

## Fix 4 — keep the distribution data the leaderboard already provides

`from_leaderboard` should keep the variance/percentile fields instead of dropping
them: `speed["tps_p05"|"tps_q25"|"tps_q75"|"tps_p95"]`,
`speed["ttft_p05"|"ttft_q25"|"ttft_q75"|"ttft_p95"]`, `speed["ttfa"]`,
`speed["reasoning_s"]` (null-tolerant). Then register matching `catalog.METRICS`
entries (`kind="tps"` / `kind="sec"`, `group="speed"`, `better="high"` for tps and
`"low"` for latency, one-line descriptions) so they are usable in `fields=`/`sort=`.
Do not invent values for rows that lack them.

## Fix 5 — chart records: keep the per-evaluation intelligence data

Add a `per_eval: list[dict] | None = None` field to `Model` (additive, default None)
filled from the chart record's `intelligenceIndexEvaluations`
(`[{slug, score, outputTokensPerTask, costPerTask, timePerTask}, …]`) by
`from_chart`, and keep `intelligenceIndexCost` (total cost of the whole index run) as
`cost_breakdown["index_total"]` when present. Also carry `reasoningTokens`
(`speed["reasoning_tokens"]`) and `briefcaseTotalCost`
(`cost_breakdown["briefcase_total"]`). `merge()` must prefer the first non-empty
value for `per_eval`. Tests: fable fixture yields 10 per-eval rows with
`slug="aa-briefcase"` first, `cost_breakdown["index_total"] ≈ 13128.86`.

## Acceptance (self-check; no repo-wide gates, no formatters)

- `uv run pytest tests/test_loaders.py tests/test_normalize.py tests/test_catalog.py -q` passes.
- Live check (paste the output in your report):
  `.venv/bin/python -c "from aa_mcp import loaders as L; m=L.leaderboard(); print(sum(1 for x in m if x.release_date), [ (x.slug,x.release_date) for x in m if x.slug.startswith('claude-opus-5-5')]); e=L.provider_endpoints('claude-opus-5-5'); print([(x.host,x.cost_per_task) for x in e])"`
  Expect a non-zero release_date count, effort variants sharing one date, and non-null
  cost_per_task values sorted ascending.
- Report which of the FidelityCheck findings you fixed, which you deliberately left,
  and every new fixture you added.
