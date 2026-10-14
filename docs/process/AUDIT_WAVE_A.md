# Wave A — data-layer hardening (from the independent audits)

Sources of truth (read the cited sections):
- `eval/reports/audit_quality.md` (code review; findings H2/H3/H4/H5 + M/L items)
- `eval/reports/adversarial.md` (attack report; findings A2/A14/A22/A25/A26/A27/A28/A31/A32/A33/A34/A36)

Files you own in this wave: `src/aa_mcp/fetch.py`, `flight.py`, `loaders.py`, `normalize.py`,
`select.py`, `catalog.py` + their tests + new fixtures. **Do not edit `server.py` or
`reference.py`** — the other agent owns those; where a fix needs both sides, expose a clean
interface and say so in your report.

Everything must stay additive/back-compatible for `server.py`'s current call sites unless the
brief says otherwise. Keep `uv run pytest -q` green at the end (226 tests now).

## A1 (HIGH, security) — cache path sanitization

`aa_raw kind=eval query="../../../../tmp/ESCAPED3"` wrote `/tmp/adv/ESCAPED3.rsc` outside
`AA_CACHE_DIR` (adversarial A42/A43). Every cache entry name is built from user input
(`model_<slug>`, `providers_<slug>`, `eval_<slug>`, `media_<board>`, `agents_<board>`).
`fetch.get(name=…)` must reject names that are not a single safe path segment:
allow only `[a-z0-9._-]` (case-insensitive), length ≤ 120, no leading dot, no `..`, no `/`,
no absolute path, no NUL/newline; raise `ValueError` with the offending name on violation.
Also enforce that the resolved path is inside `cache_dir()` (defence in depth via
`Path.resolve().is_relative_to`). Add tests: `../../x`, `a/b`, `.hidden`, `''`, `a`*200,
`x\x00y`, `%2e%2e%2fx`.

## A2 (HIGH, robustness) — bounded downloads and timeouts

- Decompression cap: a gzip bomb (60 kB → 182 MB RSS, adversarial A28) must be refused.
  Cap the decoded body (`AA_MAX_BYTES`, default 48 MB) while streaming; on breach raise
  `AAFetchError` naming the limit and the URL.
- Timeouts: a never-replying upstream stalled a tool for 121 s (A27) because one 60 s attempt
  is followed by a retry. Add a total deadline (`AA_HTTP_TIMEOUT`, default 30 s per attempt)
  and do **not** retry on timeout/read timeouts; retry only on connect errors and HTTP 5xx,
  at most once, with the global budget for a single `get()` capped at ~45 s.

## A3 (HIGH, correctness) — cache is untrusted input

A single edited field in `rich_dataset.json` made `aa_leaderboard` report Intel 999.0 / $0.01
as #1 with no warning (A32); poisoned/mismatched cache entries never self-heal and no error
mentions the cache or `refresh=true` (A22/A25/A26).

- Add a cache metadata sidecar (or a wrapper envelope): store `{"schema": N, "written": ts, "url": …}`
  next to each payload (e.g. `<name>.meta.json`) and treat a missing/mismatched schema as stale
  (refetch once, then parse the fresh body). A payload whose stored URL differs from the
  requested URL must never be used. Keep this cheap: one small JSON per name.
- Validate plausibility after parsing, before returning data: `Model.intelligence` within
  [-100, 100], `cost_per_task` ≥ 0, `context_tokens` > 0 when present, and at least 50% of
  records carrying `intelligence` for the leaderboard/rich datasets. On failure raise
  `AAFetchError`-style error naming the cache file and suggesting `refresh=true`
  (do not silently drop the offending record).
- Every parse failure must mention the cache path and `refresh=true` in the message.

## A4 (MEDIUM, perf/social) — single-flight per cache name

8 parallel cold calls still fetched the big pages 2-4×, and `refresh=true`/`TTL≤0` downloads each
payload twice (A31/A33). Add an in-process per-name lock (a small `dict[str, threading.Lock]`
guarded by a mutex) so concurrent `get()` calls for the same name share one download; keep the
existing cross-process `flock`. With `refresh=true`, only that name is refetched (no duplicate
second fetch) — verify with a counting HTTP server in a test.

## A5 (HIGH, correctness) — `flight._scan` misses arrays whose first element is a flight ref

`tests/fixtures/model_page_legacy.rsc` embeds `"initialModels":[ "<ref>", "<ref>", … ]` and a
700-item pool whose first element is `"$e:…"`; today `find_arrays` returns 0 for both, so
`parse_chart` yields 1 model instead of 28 and `parse_rich_dataset` yields 0 (audit H4). Fix the
scan to (a) accept `["` as an anchor start and (b) select the probe item as the first *dict*
element; keep the cost bounded — short-circuit as soon as a candidate satisfies `min_len` and the
required keys, and confirm the whole-file scan stays under ~1 s on the 3.2 MB legacy page.
Then verify end-to-end on the real fixture: `parse_chart(model_page_legacy.rsc)` ≥ 27 models with
the requested slug present, `parse_rich_dataset(model_page_legacy.rsc)` ≥ 600 models. Fix the
test that hand-builds an artificial pool so it exercises the real shape (read the fixture).

## A6 (HIGH, correctness) — ranking direction for lower-is-better benchmarks

`loaders.eval_models` sorts "best first" unconditionally, so `omniscienceHallucinationRate`,
`cweBenchRefusalRate`, `cybergymE2eRefusalRate`, `deepsecBenchRefusalRate` rank the *worst*
models first (audit H2, shared with the server). Use `catalog.metric(key).better` (already
modelled) to choose the direction. Expose whatever the server needs (`server.py` will call
`loaders.eval_models` / rich-set ranking); if the fix is purely in `loaders`, say so.

## A7 (HIGH, correctness) — `select.value_rank` must not mutate shared models

`value_rank` writes `m.value` onto memoized objects shared across calls and threads, making the
frontier "knee" order-dependent (audit H3). Replace the mutation with a functional API:
`def value_pairs(models, *, score_key="intelligence", cost_key="cost_per_task") -> list[tuple[Model, float]]`
and keep `value_rank` as a thin back-compatible wrapper that returns a **new** list of
`dataclasses.replace(m, value=v)` copies (never touching the inputs). Document in the docstring
that callers must not rely on mutation. Add a test asserting the input objects are unchanged
after a call and that two identical `value_pairs` calls give identical results after an
intervening call with a different `score_key`.

## A8 (MEDIUM) — media array selection must not silently swap arenas

A corrupted payload made the media parser fall back to a *different* 92-row arena (A34).
Selection must validate that the chosen array actually belongs to the requested board: require
the items to carry the board's expected identity/score keys (per `MEDIA_BOARDS` entry) and raise
a clear error when nothing matches, instead of returning a plausible-but-wrong table.

## A9 (MEDIUM) — smaller correctness items from the audits

- `_media_row` assumes `values`/`formatted` are mappings — make it tolerant of non-mappings
  (audit M) and of `values` entries that are refs.
- Expose a public open-weights normalizer for speech/agent rows (`server.py` needs
  `_media_open_weights`-equivalent behaviour for homepage rows whose keys differ; audit H5).
- Reject non-finite floats (`NaN`/`inf`) in numeric filters with a `ValueError` instead of
  treating them as a no-op (A2); the server will call through your API.
- `catalog`: keep `better` authoritative for every metric that can be ranked (verify the set of
  `_LOWER_IS_BETTER` keys is complete against `BENCHMARKS`/`METRICS`).
- Remove now-dead code found by the review (`flight`/`loaders` unused helpers, unsorted `__all__`
  per ruff RUF022) and make `ruff check src/` clean for the files you own (the repo has no ruff
  config; use defaults, and do not reformat unrelated code).

## Acceptance (report all of it)

- `uv run pytest -q` green; paste the new/changed test count.
- `.venv/bin/python -c "import aa_mcp.loaders as L; print(len(L.parse_chart(open('tests/fixtures/model_page_legacy.rsc').read())), len(L.parse_rich_dataset(open('tests/fixtures/model_page_legacy.rsc').read())))"` -> expect ≥27 and ≥600.
- Path traversal repro (`aa_raw kind=eval query="../../../../tmp/ESCAPED"`) must now fail with a
  `ValueError` **before** touching the filesystem, and leave the cache dir unchanged (paste the
  command + `ls` of the cache dir + `ls /tmp/ESCAPED*`).
- Gzip-bomb + hang repros from `eval/reports/adversarial.md` (A28, A27): paste the new
  error/timing (bounded RSS, ≤ ~45 s and no retry storm).
- `uvx ruff check src/` for your files: paste remaining findings if any.
- Live sanity: `scripts/surface_sweep.py` (already in the repo) — paste the final summary line.
