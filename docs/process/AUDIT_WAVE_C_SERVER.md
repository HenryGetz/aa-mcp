# Wave C — server capabilities (pareto tool, benchmark search, comparison parity)

Files you own: `src/aa_mcp/server.py`, `src/aa_mcp/reference.py`,
`docs/REFERENCE.md` (regenerate), `docs/INTERFACES.md`, `scripts/surface_sweep.py`,
plus a new `tests/test_server.py` if you have room (the sibling test wave may also
create it — if it exists when you start, extend it; never overwrite it).

The sibling wave is adding this interface to `catalog.py` **in parallel** — code against
it with defensive `getattr(catalog, "rankables", None)` and a `BENCHMARKS`/`METRICS`
fallback so your tools work before and after it lands. Full spec:
`docs/AUDIT_WAVE_C_CATALOG.md`.

```python
catalog.Rankable(key, label, kind, unit, tags, how, surface, desc, aliases)
catalog.RANKABLES: dict[str, Rankable]
catalog.DOMAINS: dict[str, tuple[str, ...]]
catalog.rankable(key_or_alias) -> Rankable | None
catalog.rankables(*, domain="", tag="", query="") -> list[Rankable]
```

## C1 (user: "this one should ALWAYS have a tool") — new tool `aa_pareto`

```python
aa_pareto(score: str = "intelligence", x: str = "cost_per_task", top: int = 15,
          creator: str = "", open_weights: bool | None = None,
          min_intelligence: float | None = None, min_context: int | None = None,
          include_deprecated: bool = False, include_all: bool = False,
          refresh: bool = False) -> str
```

- `score`: any rankable with per-model numbers (intelligence by default, or any
  benchmark/index/capability key, e.g. `cyberIndex`, `terminalBench40`,
  `capabilities.legal`).
- `x`: the trade-off axis — `cost_per_task` (default), `index_total_cost`
  ("Cost to Run the Intelligence Index"), `out_tokens_per_task`, `time_per_task`,
  `context_tokens`, `params_b`, `ttft`, `price_in`, `price_out`.
- Returns the **Pareto frontier** (models where no other model has both lower-or-equal
  x and higher-or-equal score, strictly better in at least one), ordered by x
  ascending, with columns `Model | Slug | Creator | <score> | <x> | <ratio>`; then a
  one-line knee note (last model before the cost/score ratio jumps ≥5×, as the
  reference text already describes) and a coverage line.
- Must state the axis labels and units in the header (`Intel vs $/task (Pareto
  frontier, cost ascending)`), and when the chosen `x` comes from the rich overlay or
  needs `AA_API_KEY`, say so (and explain what is missing) rather than returning an
  empty table.
- `aa_leaderboard(mode="frontier")` must delegate to the same implementation (one code
  path, not two).
- The three site views the user named must be reachable:
  `aa_pareto` (default) = "Intelligence Index vs. Cost per Index Task";
  `aa_pareto x=out_tokens_per_task` = "Intelligence Index vs. Output Tokens per Task";
  `aa_pareto x=index_total_cost` = "Intelligence Index vs. Cost to Run the AA
  Intelligence Index". Mention these three in the docstring and in
  `reference.TOPICS["overview"]`'s routing table.

## C2 (user: "easy way to search ... relevant to whatever task domain") — `aa_benchmarks` becomes the search index

Keep the name and the existing arguments; extend:

```python
aa_benchmarks(query: str = "", domain: str = "", tag: str = "", verbose: bool = False) -> str
```

- Renders `Thing | Kind | Unit | Coverage | How to query` (+ `Measures` when ≤10 rows
  or `verbose`), from `catalog.rankables(...)`.
- `How to query` is `Rankable.how` verbatim — this is the key affordance: an agent that
  finds "Artificial Analysis Speech to Speech Index" must immediately see
  `aa_media board=speech_to_speech`.
- Unknown `domain`/`tag` -> error listing the valid ones from `catalog.DOMAINS`.
- Zero results -> say so and suggest two or three closest labels (never a bare empty
  table). Untracked-name answers keep working (`UNTRACKED_BENCHMARKS`).

## C3 (user: comparison parity) — `aa_compare` upgrades

```python
aa_compare(queries: list[str] = [], metrics: str = "", view: str = "table",
           compact: bool = True, spec: str = "", refresh: bool = False) -> str
```

- **Any number of models** 2..12 (fuzzy names or slugs). For each model use the merged
  dataset; if a model is missing from the rich overlay (older/deprecated variants),
  fetch its own model page once (cached, `loaders.model(slug)`) and merge — mirroring
  what the site's comparison page does. Never silently drop a requested model: if it
  cannot be resolved, error with candidates.
- `metrics`: `""` (sensible default rows), `"all"` (every rankable key that any of the
  selected models has), `"benchmarks"` (benchmark/index kinds only), or an explicit
  comma list of keys/labels/aliases (resolve through `catalog.rankable`, fall back to
  `metric`). Unknown names -> closest-match error.
- `view`: `table` (models as columns) or `diff` (one row per metric, value plus the
  delta vs the best/first model, e.g. `57.6 (+4.9)`), which is what a comparison page
  effectively shows.
- `spec`: accept a **YAML or JSON** document (a YAML subset parser is fine: `models`,
  `metrics`, `view`, optional `filters`) and merge it with the explicit arguments;
  at the end of the output emit a copy-pasteable `spec:` block (YAML) reproducing the
  call, so a comparison is reusable/reproducible. Do not add a YAML dependency — write
  a ~40-line parser for the small mapping/list/scalar subset, or accept JSON only if
  YAML proves unsafe, and say which you did.
- Keep the Wave-B bounds/sanitisation rules (cell caps, response caps, markdown
  escaping) intact; with 12 models and `metrics=all` you must still bound the response
  and note the truncation.

## C4 — resources/prompts/docs

- Resources: `aa://rankables` (JSON list from `catalog.RANKABLES`), `aa://rankables.yaml`
  (same data as YAML), `aa://comparisons/spec` (a YAML template for `aa_compare`'s
  `spec=`). Keep existing URIs working.
- Prompts: update `compare_models` to mention `metrics="all"`, `view="diff"` and the
  spec round-trip; update `best_model_for_task` to route value/trade-off questions to
  `aa_pareto`.
- `reference.TOPICS["overview"]` routing table gains rows for `aa_pareto`,
  `aa_benchmarks` (domain search) and comparison specs; regenerate `docs/REFERENCE.md`.
- `docs/INTERFACES.md`: document the new tools/resources and the `Rankable` interface.
- `scripts/surface_sweep.py`: add cases for `aa_pareto` (each `x` axis, a couple of
  scores), `aa_benchmarks` with `domain=`/`tag=`, and `aa_compare` with 3, 8 and 12
  models, `metrics=all`, `view=diff`, and a YAML `spec`.

## Acceptance (paste evidence)

- `pytest -q` green.
- Live outputs for: `aa_pareto` (default, `x=out_tokens_per_task`, `x=index_total_cost`,
  `score=cyberIndex`), `aa_benchmarks {"domain":"security"}`, `aa_benchmarks
  {"query":"speech"}`, `aa_benchmarks {"query":"Provider Voice Arena Preference Elo"}`,
  `aa_compare` with 4 models `metrics=all view=diff`, the same call via a YAML `spec`,
  and a 12-model `metrics=all` call (paste the truncation note and token count).
- `.venv/bin/python scripts/surface_sweep.py` summary line (0 unexpected failures).
- Token cost of the new tools (harness stderr) — `aa_pareto` should be ≤ ~400 tokens
  for `top=15`.
