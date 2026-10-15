# Wave G-B — data provenance (normalize/loaders side)

Sources: `eval/runs/round7_verify.md` (independent verification). Two defects live in your
files. Files you own: `src/aa_mcp/normalize.py`, `src/aa_mcp/loaders.py`,
`src/aa_mcp/reference.py`, `docs/REFERENCE.md`, `tests/test_normalize.py`,
`tests/test_loaders.py`. **Do not touch** `server.py` or `catalog.py` (the sibling agent
owns those for this wave).

## G-B1 — `time_per_task` must be AA's published field, not our mean

Verified: the chart records carry AA's own `intelligenceIndexTimePerTask`, but `normalize`
drops it, so the server recomputes a mean of the 10 per-eval `timePerTask` values —
measured median deviation **−6.7%** across 189 models (e.g. claude-opus-5-5: 697.1s
recomputed vs **797.5s** published), only 6.9% of models within 1%.

Fix: read `intelligenceIndexTimePerTask` in `from_chart` (and legacy if present) into
`speed["time_per_task"]`, and keep the per-eval mean as a **separate, clearly-named**
fallback (`speed["time_per_task_derived"]`) used only when AA's field is absent. Document in
the module docstring which is which. The server will prefer the published one (tell it in
your report).

## G-B2 — disclose the rich overlay's age

Verified: two identical calls 12 minutes apart returned different speed/latency values while
both headers said `3m ago`, because the age label comes from the leaderboard cache while the
values came from the rich overlay, which has its own TTL (`AA_RICH_TTL`, default 6h) and was
never documented. Fix on your side:

- expose the overlay's provenance so the server can label it — e.g. make
  `loaders.rich_dataset()` (or a small helper `loaders.rich_age() -> float | None`) report the
  cache file's age/write time in seconds, plus the seed slug used;
- document `AA_RICH_TTL` (and that the overlay is a separate, longer-lived cache) in the
  reference text topic `sources` (`reference.py` + regenerate `docs/REFERENCE.md`);
- add tests: the helper reports an age for a warm cache and `None` when absent; the dataset
  is not re-fetched inside its TTL; `refresh=True` bypasses it.

## G-B3 — the `sources` topic must name every surface

Extend `reference.TOPICS["sources"]` (and `docs/REFERENCE.md`) to list, per surface, what it
carries and how fresh it is: leaderboard (1h, 700×~50), rich overlay (6h, 700×94 incl.
capability indexes, Elo, per-eval costs), eval chart sets + homepage panels (1h, top ~20-30
per eval), provider board (1h), model providers (1h), media arenas (1h), agents boards (1h),
eval catalog (1h). One line each — this is the text an agent reads when two numbers disagree.

## Acceptance

Paste: `uv run pytest -q` count, `uvx ruff check .` clean,
`.venv/bin/python -c "import aa_mcp.loaders as L; m=L.rich_dataset(); print(len(m), L.rich_age())"`,
and the live comparison for one model where the published vs derived `time_per_task` differ
(show both numbers from the raw payload and from the MCP), plus `gen_reference_md.py --check`.
