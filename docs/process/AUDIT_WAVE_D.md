# Wave D — comparison completeness (round-4 agent findings)

Round-4 evaluation report: `eval/runs/round4_e.md` (read it). The user's bar is
"no model-comparison question is impossible". These are the concrete gaps it found.

Files you own for this wave: `src/aa_mcp/server.py`, `src/aa_mcp/catalog.py`
(the catalog agent is idle; keep changes additive), `src/aa_mcp/reference.py`,
`docs/REFERENCE.md` (regenerate), plus `tests/test_server.py` / `tests/test_catalog.py`.
Do **not** touch `loaders.py` (another agent is adding memos there right now).

## D1 — `aa_compare` must mark missing cells and state coverage

Findings: three metrics came back blank for one model with no explanation, and a model
with no published pricing/speed produced an all-`-` comparison with **no coverage
wording at all** (only `aa_leaderboard` explains missing data).

- Render `-` for a missing value (as now) but add, per metric row, nothing extra; instead
  add **one footer block** when any cell is missing:
  `— missing: Harvey LAB-AA (MiMo-V2.6-Pro), ITBench-AA SRE (MiMo-V2.6-Pro), MMMU-Pro (MiMo-V2.6-Pro)`
  (grouped by model, truncated sensibly) and, when a whole model has no values on the
  requested metrics, say so explicitly: `— Muse Wonder Full has no published pricing or
  speed on AA; 0/6 requested metrics available`.
- Keep the existing `— no data for: <columns>` style used elsewhere for consistency.

## D2 — join chart-set / homepage-panel scores into comparisons

Finding: comparing `mimo-v2-6-pro` vs `deepseek-v4-1-flash` on cyber/CWE returned all `-`
even though both scores are published and retrievable via `aa_benchmark_leaderboard`
(they live in AA's eval chart set / homepage panel, not in the model records the compare
path reads). `aa_pareto` already solves this with `_extra_score_models` — reuse that
mechanism for `aa_compare` (and for `aa_model`'s benchmark section if it has the same
hole), so any metric AA publishes for a selected model is available. State the source in
the footer when a row came from a panel/chart set (`— Cyber Index from AA's eval chart set
(top ~20 models)`).

## D3 — `aa_benchmarks` query must not be too literal for domain words

Finding: `aa_benchmarks {"query":"security"}` returned 1 of 8 matching rankables while
`domain="security"` returns 8. Fix the search semantics in `catalog.rankables()` so a
single-word query that matches a known **domain name** expands to that domain (and say so
in the header, e.g. `query=security (domain match)`), while multi-word queries keep the
tokenised AND behaviour. Keep `domain=`/`tag=` semantics unchanged.

## D4 — AA-3D coverage label

Finding: `aa_benchmarks` labelled AA-3D as "not fetched" although the leaderboard/rich
dataset fetches it live. Correct the `surface`/coverage classification for `aa3dElo` (and
audit the other rankables whose label says `chart set only (not fetched)` — several are
now covered by the rich dataset). The label must be computed from the same live coverage
logic the tool already uses, not a static guess.

## D5 — spec echo completeness

Finding: the echoed spec dropped keys that were defaulted, and `compact` was silently
ignored whenever `metrics` was given. Fix: the echoed spec must reproduce the call
byte-for-byte in behaviour (include the effective values, including `view`/`metrics`/
`compact`), and `compact` must either apply when `metrics` is given or be documented as
ignored in the output footer — do not silently ignore a parameter.

## D6 — tests

Add/extend offline tests for D1-D5 (missing-cell footer, panel join, domain-word query,
coverage label, spec echo completeness), and for the round-3/4 regression set that is
still uncovered in `tests/test_server.py`:
- `aa_media` speech boards end-to-end (`speech_to_text`, `speech_to_text_streaming`,
  `speech_to_speech`, and the `realtime_voice` alias) — the NameError regression;
- `aa_benchmark_leaderboard` direction for a `better="low"` metric (lowest first) and its
  `lower is better` header;
- frontier knee order-independence (same answer before/after `mode="value"` with a
  different `sort`);
- the response/cell caps and markdown escaping: a model whose scraped `name` contains
  `|`, newlines, backticks, a lone surrogate or a 10k-char string must not be able to
  break the table or inflate the response beyond the cap (sanitize surrogates to U+FFFD);
- input validation errors: NaN/inf filters, over-long `fields`, unknown domain/tag.

## Acceptance (paste evidence)

- `uv run pytest -q` green (record the count) and `uvx ruff check .` clean.
- Live before/after for: the round-4 pairwise call (`aa_compare` on the two models,
  `metrics=all view=diff`) showing the new missing/coverage footers and the cyber row
  populated; `aa_benchmarks {"query":"security"}`; `aa_benchmarks {"query":"AA-3D"}`;
  a spec round-trip showing the echo now includes every effective key.
- `.venv/bin/python scripts/surface_sweep.py` summary line (0 unexpected failures).
