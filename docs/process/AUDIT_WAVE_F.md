# Wave F — panel/chart-backed indexes must be first-class (user request)

User request (verbatim intent): *the Cyber Index "should be a default one you can
query like intelligence directly that is built in"*.

## Current behaviour (verified)

- `aa_leaderboard {"sort":"cyberIndex"}` **fails**:
  `'AA Cyber Ind' has no values in the 700-row leaderboard — it is chart-set / model-page only.`
- `aa_benchmark_leaderboard {"benchmark":"cyberIndex"}` works (20 scored, "AA chart set").
- `aa_pareto {"score":"cyberIndex"}` works (the pareto path already joins extra scores).
- `aa_compare`/`aa_model` join chart-set/panel scores (added in wave D).

So the score-join machinery exists (`_score_surface` / `_extra_score_models` /
`_model_chart_evals`) but **`aa_leaderboard`'s sort/filter/field path does not use it**.
That inconsistency is the bug: a key that is rankable via one tool must be rankable via
the default leaderboard tool too, with the same ergonomics as `intelligence`.

## Required change

1. **One uniform ranking path.** When `sort` (or `min_intelligence`-style score filters,
   or a requested `fields=` column) names a key whose values live in the eval chart set /
   homepage panel / rich overlay, join those scores onto the leaderboard rows and rank
   normally. `aa_leaderboard {"sort":"cyberIndex","top":10}` must return a ranked table
   exactly like `sort=intelligence`, with `mode=value`/`mode=frontier`/`fields=` working
   for it too.
2. **Union every surface AA publishes for that key**, best-effort, in one pass: the rich
   dataset record (`cyberIndex` is one of the 94 chart keys), the homepage eval panel
   (`eval:artificial-analysis-cyber-index`, ~20 rows, includes `refusalRate` and
   `mitigationStatus`), and the eval page's chart set
   (`/evaluations/artificial-analysis-cyber-index`). Take the richest non-null value per
   model; do not double-count; keep it memoised (the panels/chart sets are already
   memoised — verify no new per-call fetches).
3. **Honest coverage, always.** The header/footnote must state the real coverage and
   source, e.g.
   `# 10 of 24 scored (700 tracked) · AA Cyber Index, chart set + panel · aa:rsc + rich dataset`.
   Never imply a full leaderboard when it is a subset, and never a bare failure.
4. **Companion metrics.** AA publishes `refusalRate` (and a `mitigationStatus`) alongside
   the cyber index. Register them as rankables (`cyberRefusalRate`, `cyberMitigationStatus`
   — choose consistent keys, mark `better="low"` for refusal) with `how` hints that work,
   and make them sortable/usable through the same path (they are part of "the cyber
   index" as the user sees it). Same treatment for the other security panels
   (`cwe-bench-aa`, `deepsecbench-aa`, `cybergym-e2e-aa`) which already have refusal-rate
   companions.
5. **Apply the same fix generally**: audit every rankable whose `surface` is
   `chart`/`panel`/`api` and confirm it is reachable through `aa_leaderboard` when it has
   per-model values (e.g. `cweBench`, `deepsecBench`, `cybergymE2e`, `wildguardtest`,
   `aa3dElo`, `harveyLab`, `globalMmluLiteScore`, `math500`, `when2call`, `frontierCode`,
   `enterpriseOpsGym`, `gdpPdfAllPass`, `mlrcOverall`). Where a key genuinely has no
   per-model values (container/breakdown kinds), keep the honest explanatory error.
   Report the audit table: `key | surfaces with values | aa_leaderboard sort works?`.
6. **Eval catalog completeness.** `loaders.eval_catalog()` returns 33 cards from
   `/evaluations`, but AA also publishes eval pages that the card list omits — verified:
   `artificial-analysis-cyber-index` (and other index/panel evals) is missing, even though
   `/evaluations/artificial-analysis-cyber-index` exists and parses (20 chart models).
   Make the catalog the **union** of the server-rendered cards and the sitemap's
   `/evaluations/*` paths (the sitemap is already fetchable via `loaders.sitemap_paths`),
   so every published eval page is discoverable; keep card metadata (title/description/tags)
   where available and fall back to a label derived from the slug for the rest. Cache it
   under the existing eval-catalog memo. Add a test asserting the cyber index slug is present
   and that the count is ≥ the card count.
7. **Companion metrics from the panel variants.** The cyber index has more than one homepage
   panel (an earlier capture had `refusalRate` and `mitigationStatus` keys). Check every
   `eval:*` panel variant for the security evals and register any companion scalar
   (`refusalRate`, `mitigationStatus`, …) as rankables with working `how` hints, exactly like
   the refusal-rate keys already registered for cwe/cybergym/deepsec.
8. Tests + sweep cases: `aa_leaderboard sort=cyberIndex` (ranked, labelled),
   `mode=value`/`mode=frontier` with a panel-backed score, `fields=` with it, the
   companion refusal-rate key, and one key from each audited group.

## Acceptance (paste evidence)

- Live before/after: `aa_leaderboard {"sort":"cyberIndex","top":5}`,
  `{"mode":"frontier","sort":"cyberIndex"}`,
  `{"sort":"cyberIndex","fields":"cyberIndex,cyberRefusalRate,cyberMitigationStatus"}`,
  `aa_benchmarks {"query":"cyber"}`, `aa_benchmark_leaderboard {"benchmark":"cyberIndex"}`.
- The audit table from item 5.
- `uv run pytest -q` count, `uvx ruff check .` clean, `scripts/surface_sweep.py` summary
  (0 unexpected failures), and `scripts/gen_reference_md.py --check` in sync (update the
  reference text: panel/chart-backed indexes are first-class and their coverage is stated).
