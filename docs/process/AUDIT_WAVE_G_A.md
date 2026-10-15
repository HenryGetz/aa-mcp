# Wave G-A — comparison trustworthiness (server side)

Sources: `eval/runs/round7_verify.md` (independent raw-payload verification) and
`eval/runs/round7_cold.md` (cold-start usability). Zero value mismatches were found; these
are the *trust* and *ease* defects that remain.

Files: `src/aa_mcp/server.py`, `src/aa_mcp/catalog.py` (additive; you own both),
`src/aa_mcp/reference.py`, `docs/REFERENCE.md`, `tests/test_server.py`,
`tests/test_catalog.py`, `scripts/surface_sweep.py`.
**Do not touch** `loaders.py`, `normalize.py`, `fetch.py`, `flight.py`, `select.py`
(the sibling agent owns those for this wave).

## G1 — one metric must never mean two numbers (highest priority)

Verified: `aa_compare {"metrics":"ttft"}` → 679.2s (leaderboard snapshot) while
`{"metrics":"time_to_first_token"}` → 661.2s (model page); asking for a rich-only alias
silently re-sources the *whole reply* (`tps` flips 95.7 → 95.2). Rules:

- Canonical, deterministic choice per metric: prefer the **first-party model-page/rich
  value** when it exists, else the leaderboard snapshot — the same rule regardless of which
  alias the caller used.
- When the two sources differ by more than 2%, add one footer line naming both
  (`— speed: model page 661.2s vs leaderboard snapshot 679.2s (using the model page)`).
- The existing TTFT footer ("TTFT is AA's long-prompt median") must only appear when the
  shown value actually is that median; fix the case where it is wrong.
- Same treatment for `tps`, `e2e`, `ttfa`.

## G2 — identity fields always resolve in `fields=`

Verified: `aa_providers {"model":"x","fields":"model,price_in"}` blanks the Model column and
claims `no data for: Model`, although `hostModels` carries `model.slug` on every endpoint.
Identity fields (`model`, `host`, `name`, `slug`, `benchmark`, `creator`) must resolve from
the record whenever the record has them, in every tool that takes `fields=`, and must never
be reported as "no data".

## G3 — `aa_providers` on a model with no endpoints

Cold-start finding: a model AA lists no API endpoints for produces a hard error. It must
instead explain: `— AA lists no API providers for <model>; it has no published pricing or
endpoint measurements (see aa_model for what AA does publish)`.

## G4 — `metrics=all` must include the derived rows

Verified inconsistency: `Intel/$` appears in the default comparison view but **not** in
`metrics=all`. `all` must include every rankable row the models have, including the derived
ratios the default view uses (`Intel/$`, and the same for a non-default score axis), plus
`$/task`, prices, speed, context, params, release and the chart/panel joins. Keep the
existing response caps and truncation note.

## G5 — announce fuzzy resolution (trust)

Two cold-start friction points: a fuzzy name silently became a slug, and a bare model name
silently became one reasoning-effort variant. Required:

- when a query resolves fuzzily (not an exact slug/name), say so in the header or a footnote:
  `— matched 'opus max' → claude-opus-5-5 (exact slug for that name)`; if several candidates
  were close, name the best two.
- when a bare family name resolves to an effort variant, say which and list the siblings:
  `— matched the Max variant; siblings: gpt-6-luna-high, -xhigh, -low, -non-reasoning`.

## G6 — partial metric requests must not abort

Cold-start friction: one unknown name in a 20-item `metrics=` list aborts the whole call.
Rule: for **list-valued** requests (`metrics=`, `fields=`) render everything that resolves and
add one footnote naming the unresolved entries with their closest matches
(`— unknown, ignored: swe-bench-verified (closest: …)`). Keep hard errors for single-purpose
arguments (`sort=`, `benchmark=`, `board=`, `domain=`).

## G7 — label ties

Cold-start friction: two models tied at `$0.13/task` with no way to see the tie. When the
top rows of a ranked table share the sort value, add one line naming the secondary ordering
and the next distinguishing column (`— 2 models tie at $0.13/task; ordered by intelligence
(46.3 vs 41.0)`).

## G8 — task-domain words AA does not cover

Cold-start: "best model for classification" dead-ended because AA has no classification
benchmark. Add a small, factual task-domain map (extend `catalog.UNTRACKED_BENCHMARKS` or add
`TASK_DOMAINS`) so a *task word* answer names the closest AA measures, e.g.
`classification` → IFBench (instruction following) / MMLU-Pro-style knowledge;
`summarization` → GDP.pdf / AA-LCR; `translation` → Global-MMLU-Lite (multilingual);
`retrieval`/`RAG` → AA-LCR; `SQL`/`data analysis` → AA-AnalystAgent; `tool calling` →
τ²-Bench / τ³-Banking + the provider FnCall/JSON flags. Wording must stay "AA does not
measure X; closest AA measures are …". Wire it into `aa_search` (no model matched) and
`aa_benchmarks` (no rankable matched).

## G9 — rounding-to-zero note

When a cost or price rounds to `$0.00`, say it is below the display precision
(`— $0.00 = measured under $0.005/task`) instead of leaving a bare zero.

## Acceptance

Paste live before/after for: `aa_compare {"metrics":"ttft"}` vs `{"metrics":"time_to_first_token"}`
(values now equal or explicitly footnoted), `aa_compare {"metrics":"all"}` (derived rows
present), `aa_providers {"model":"<a model with no endpoints>","fields":"model,price_in"}`,
`aa_search {"query":"opus max"}`, `aa_search {"query":"best model for classification"}`,
`aa_compare` with one bad metric name in the list, and a tie case. Then `uv run pytest -q`,
`uvx ruff check .`, `scripts/surface_sweep.py` summary (0 unexpected), `gen_reference_md.py --check`.
