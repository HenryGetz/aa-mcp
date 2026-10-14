# Wave B — server-layer hardening (from the independent audits)

Sources of truth (read the cited sections):
- `eval/reports/audit_quality.md` — H1/H2/H3 consumer side, plus M/L items.
- `eval/reports/adversarial.md` — A14, A36, A37, A42 (input/output bounds), A22/A25/A26 (cache
  awareness in messages), A33.

Files you own in this wave: `src/aa_mcp/server.py`, `src/aa_mcp/reference.py`,
`docs/REFERENCE.md` (regenerate via `scripts/gen_reference_md.py`), `docs/INTERFACES.md` (drift).
**Do not edit `fetch.py`, `flight.py`, `loaders.py`, `normalize.py`, `select.py`, `catalog.py`** —
another agent is hardening those in parallel. Where you need something from them, code
defensively and note the required interface in your report (e.g. they are adding
`select.value_pairs()` and making the cache/`fetch.get` reject unsafe names).

## B1 (HIGH) — speech boards crash

`aa_media board=speech_to_text|speech_to_text_streaming|speech_to_speech` raises
`NameError: name 'board_key' is not defined` (`server.py:1660-1661`; the local is `key_name`).
Fix, and add `realtime_voice`/`realtime-voice` as accepted aliases for `speech_to_speech`
(the README and `reference.TOPICS['media']` both call it "realtime voice"). Verify all four
spellings live.

## B2 (HIGH) — benchmark leaderboard ranks lower-is-better metrics backwards

`server.py:1273` sorts descending regardless of `catalog`'s `Metric.better`. Fix so
`omniscienceHallucinationRate`, `cweBenchRefusalRate`, `cybergymE2eRefusalRate`,
`deepsecBenchRefusalRate` rank best-first (lowest value first), and make the header/column note
state the direction (e.g. `lower is better`). Paste before/after for
`aa_benchmark_leaderboard {"benchmark":"omniscienceHallucinationRate","top":3}`.

## B3 (HIGH) — no order dependence

Do not rely on `select.value_rank` mutating shared memoized models (the other agent is making it
functional). Compute the frontier knee from the metric value you actually sorted by, using the
new functional API when available (`getattr(select, "value_pairs", None)`) and a local computation
otherwise. Requirement: `aa_leaderboard mode=frontier` must return the *same* answer before and
after an intervening `aa_leaderboard mode=value sort=omniscience` call. Paste the three-call
repro output.

## B4 (MEDIUM) — `sort=<breakdown benchmark>` raises AttributeError

`server.py:574` does `catalog.metric(sort_key).label`, but `unit == "mixed"` benchmarks are not in
`METRICS`. Either label them from `catalog.BENCHMARKS` or reject them with a clear
`ValueError` listing the sortable names. Cover every key in `catalog.BENCHMARKS` in a loop and
report any other key that still fails.

## B5 (MEDIUM) — `mode=value` labels a `sort`-dependent ratio as `Intel/$`

The value column header must reflect the actual `sort` key (`Intel/$`, `Omniscience/$`,
…), and the header note must name the ratio used.

## B6 (MEDIUM) — `refresh=true` must not download everything

A single `refresh=true` call issued 14 HTTP GETs (audit M). Refresh only the surfaces the call
actually needs: the leaderboard always; the rich dataset only when the call needs it
(chart-only benchmark, capability/Elo sort, `fields` requesting overlay data); media/agents only
for those tools. Paste the observed number of requests before/after (the adversarial report has a
counting-proxy recipe in `/tmp/adv`).

## B7 (HIGH, security) — bound every response and sanitize cell content

- A 2 MB scraped `name` produced a 2,000,447-char (≈500k-token) tool reply (A36). Cap per-cell
  length (e.g. 120 chars, ellipsis), per-column width, and per-response size (e.g. 200 kB; when
  exceeded, truncate rows and add one note). Never echo an unbounded argument back in an error.
- Renderer must neutralize markdown structure inside values (A37): replace `|`, backticks and
  newlines (and `\r`, tabs) so a scraped string cannot forge table rows or inject instruction-like
  markdown; keep numbers untouched.
- Validate inputs at the tool boundary: reject strings containing NUL/control chars or lone
  surrogates with a clear `ValueError` (a lone surrogate currently makes the response vanish with
  no server log — A14); bound string args (e.g. 256 chars for names/queries, 2000 for `fields`);
  reject non-finite floats for numeric filters.

## B8 (MEDIUM) — cache-aware, action-oriented error text

When a fetch or parse fails, the message must name the cache file and tell the caller to retry
with `refresh=true` (or `AA_OFFLINE=1` when a good file exists) — several adversarial findings
(A22/A25/A26) were "the tool says nothing useful about why it is wrong or how to fix it".

## B9 (LOW) — cleanups from the review

- `aa_raw kind=eval` should validate the slug shape and say "kind=eval expects an evaluation
  slug (e.g. gpqa-diamond)" instead of fetching a model slug and returning a 404 (found by
  `scripts/surface_sweep.py`).
- Delete the dead `_UNTRACKED_FALLBACK`; use `catalog.UNTRACKED_BENCHMARKS` only.
- Delete the dead `render.header` usage path or make it the single header renderer (pick one;
  state which).
- `include_estimates`: either render the documented `*` estimate marker or drop the parameter
  from the docstring — do not promise it and not deliver.
- Register the `aa://reference/fields` topic from the same source as the others (no special case).
- Update `docs/INTERFACES.md` to match the shipped surface (tools, resources, filters,
  `refresh`/`include_raw` wording) — it is published in the repo.

## Acceptance (report all of it)

- `uv run pytest -q` green (the other agent adds data-layer tests; your slice should not break them).
- Live repros pasted for B1 (all four spellings), B2 (before/after), B3 (three-call sequence), B4
  (loop over every benchmark key), B5, B6 (request counts), B7 (2 MB name + a name containing
  `|`/newlines/backticks: paste the rendered table and the response size), B8 (a forced failure),
  B9 (the `aa_raw kind=eval` message).
- `.venv/bin/python scripts/surface_sweep.py` final summary line (it must end at 0 unexpected
  failures; the `coding`/`agentic`/`hleDiamond` benchmark-leaderboard errors it reports are
  *expected* — say so explicitly in the sweep output or adjust the sweep's expectations, which
  lives in `scripts/`, not in your slice).
