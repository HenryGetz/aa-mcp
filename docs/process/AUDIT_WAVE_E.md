# Wave E — final gaps from round-5 acceptance (the user's bar)

Report: `eval/runs/round5_f.md`. Four concrete defects; fix all four.

Files you own: `src/aa_mcp/server.py`, `src/aa_mcp/catalog.py` (additive; the catalog
agent is idle), `src/aa_mcp/reference.py`, `docs/REFERENCE.md` (regenerate),
`tests/test_server.py`, `tests/test_catalog.py`.

## E1 — `Rankable.how` hints must be executable

`aa_benchmarks {"query":"Artificial Analysis Cyber Index"}` tells the agent to run
`aa_leaderboard sort=cyberIndex`, which **errors** ("has no values in the 700-row
leaderboard — chart-set / model-page only"). The correct call is
`aa_benchmark_leaderboard benchmark=cyberIndex`. Audit every one of the 99 hints:

- the hint's tool must actually accept the hint's argument (e.g. a key that only has
  chart-set/panel values must point at `aa_benchmark_leaderboard benchmark=<key>`, not at
  `aa_leaderboard sort=<key>`);
- add a **static** test asserting every hint is well-formed and internally consistent:
  tool name in the known tool set; the argument name is valid for that tool; the key
  resolves through `catalog.rankable`/`metric`; and `aa_leaderboard sort=<key>` is only
  suggested for keys whose values come from the leaderboard/rich surfaces (`Rankable.surface`).
  This test must fail on the current cyberIndex hint before your fix.
- also verify the hints for `capabilities.*`, `coding`, `agentic`, the `view` kind and the
  arena entries.

## E2 — breakdown benchmarks must not raise internal errors

`aa_benchmark_leaderboard {"benchmark":"aa3dBreakdown"}` (and `harveyLabBreakdown`) raises
an internal `TypeError`. Mixed/container benchmarks have no scalar values: they must
return an honest, actionable error (or an explanatory one-liner) naming the closest
scalar sibling (e.g. `aa3dElo`, `harveyLab`). Add tests for every `unit` in
{"text", "mixed"} in `catalog.BENCHMARKS`.

## E3 — arena models must be comparable (the round-5 "unanswerable")

`aa_media board=speech_to_speech` publishes `Grok Voice 3.0`, but
`aa_compare {"queries":["Grok Voice 3.0","GPT-Live-1"]}` and `aa_search {"query":"Grok Voice 3.0"}`
both say `no model matches … closest slugs: none`. Media/speech/video/image/music models
are part of AA, so comparison must work for them:

- extend resolution so `aa_search` and `aa_compare` can find arena-board entries by fuzzy
  name across **all** boards in `loaders.MEDIA_BOARDS` + the three speech boards
  (return them with a `board`/`arena` marker so the caller knows which board they came from);
- `aa_compare` renders arena metrics for such models: Elo (with 95% CI when asked),
  appearances, price with its unit, release date, open-weights where published — plus a
  footer naming the board and warning that cross-board Elo is not comparable;
- mixed queries (a language model and an arena model) must produce a clear explanation
  instead of a broken table;
- keep the existing language-model path unchanged, and keep the resolution cached/bounded
  (one board fetch per board at most, reuse the loader memos).

## E4 — missing-metric footer must scale

For the user's 4-model `metrics=all` comparison the footer truncates to `… (+29 more)`,
hiding which model is missing what. Replace the pair listing with a per-model summary
(`— missing on requested metrics: MiMo-V2.6-Pro 29, DeepSeek V4.1 Flash 31, …`) plus, when
only a few cells are missing (say ≤6), the existing per-metric detail. Keep it bounded and
keep the whole-model line (`<model> has no published pricing or speed …`).

## Acceptance (paste evidence)

- Before/after for: `aa_benchmarks {"query":"Artificial Analysis Cyber Index"}` (hint now
  correct and the hinted call succeeds), `aa_benchmark_leaderboard {"benchmark":"aa3dBreakdown"}`
  (honest message, no TypeError), `aa_search {"query":"Grok Voice 3.0"}`,
  `aa_compare {"queries":["Grok Voice 3.0","GPT-Live-1 (Astra, medium)"]}`,
  and the 4-model `metrics=all view=diff` footer.
- `uv run pytest -q` count, `uvx ruff check .` clean, `.venv/bin/python scripts/surface_sweep.py`
  summary line (0 unexpected failures).
- Add the new cases (arena compare, breakdown error, hint audit, footer scaling) to
  `scripts/surface_sweep.py` so they stay covered.
