# T2 brief — loaders (all AA surfaces)

Owner of these files (create them):
`src/aa_mcp/loaders.py`, `tests/test_loaders.py`.
You may also add extra *fixtures* under `tests/fixtures/` if a surface needs one
(fetch them with curl; see INTERFACES.md for headers) — fixtures only, nothing else.

Exact signatures/semantics: `docs/INTERFACES.md` sections "Data sources (verified
2026-10-14)", "Known traps", "Module APIs -> loaders.py".

You import from `aa_mcp.fetch`, `aa_mcp.flight`, `aa_mcp.normalize`, `aa_mcp.catalog`
(another agent is writing them right now against the frozen signatures). Do not edit
those modules. If you need an API they do not provide, work around it locally in
`loaders.py` and report the gap.

## Deliverable

`MEDIA_BOARDS`, `AGENT_BOARDS`, `SOURCE_URLS` registries plus these functions
(exact names per INTERFACES.md): `leaderboard`, `model`, `provider_endpoints`,
`provider_board`, `home_boards`, `media`, `agents`, `eval_models`, `eval_catalog`,
`sitemap_paths`, and the `Endpoint` dataclass.

## Requirements

1. Each loader: fetch via `fetch.get(url, name, refresh=..., rsc=...)` with a stable
   cache `name` (e.g. `leaderboard`, `model_<slug>`, `providers_<slug>`,
   `providers_board`, `home`, `media_<board>`, `agents_<board>`, `eval_<slug>`,
   `eval_catalog`, `sitemap`), parse with `flight`, normalize with `normalize`, and
   return canonical objects. Loaders must be usable offline: `fetch.get` honours
   `AA_OFFLINE=1`, and parser functions must be split out as
   `parse_*(text) -> ...` pure functions so tests never touch the network.
2. `model(slug)` returns a dict `slug -> Model` covering the whole chart set embedded
   in `/models/<slug>` (27-32 records, 94 metrics each) so callers can answer
   cross-model questions from one fetch. The requested slug MUST be a key of the
   result. Legacy/deprecated pages: if `initialModels` is empty, return
   `{requested_slug: from_legacy(currentModel)}`. If neither exists, raise
   `AAFetchError` (or `ValueError`) naming the URL and what was missing.
3. `media(board)`: several candidate arrays exist per page; choose the **longest
   array whose items contain `values` and `formatted`**, then normalize each item to
   a flat dict: `name, creator, elo, ci_lower, ci_upper, appearances, rank,
   release_date, price (raw numeric), price_unit, open_weights (bool|None), url,
   extra (board-specific: voiceCount etc.)`. Boards with prices: images ->
   `pricePer1kImages` ($/1k images), video -> `pricePerMinute` ($/min), tts ->
   `pricePer1mCharacters` ($/1M chars). Sort by elo desc. Verify against the live
   page HTML today: the top text-to-image entry must be `GPT Image 2.5 Sunburst (max)`
   with elo ≈ 1217 (the page's own JSON-LD `mainEntity.acceptedAnswer` states the
   leader and its Elo — use that as a fixture-backed assertion in your test).
4. `home_boards()`: return `{"stt": [...], "stt_streaming": [...], "sts": [...],
   "eval:<slug>": [...]}` from the homepage payload (`"sttNonStreaming"`,
   `"sttStreaming"`, `"sts"`; plus every `{"evalSlug":...,"models":[...]}` panel).
   The three speech boards must be sorted best-first (WER ascending for stt,
   `stsIndex` descending for sts).
5. `agents(board)`: implement for `/agents/coding-agents` at minimum. Inspect the
   payload (`tests/fixtures/agents_coding.rsc`) and normalize whatever table data it
   embeds into flat dicts (`name, creator, rank, score(s), cost_per_task, ...`).
   If a board genuinely has no structured payload, raise `ValueError` explaining the
   URL and that the surface is client-rendered — never return `[]` silently.
6. `eval_models(slug)`: parse `"initialModels"` from `/evaluations/<slug>` into
   `list[Model]` (chart set, i.e. AA's own top-N for that eval). Sort descending by
   the eval's own metric when it maps to a known field (use `catalog.benchmark`),
   else keep payload order.
7. `eval_catalog()`: parse `/evaluations` **plain HTML** (no RSC header) into
   `{"slug","title","description","tags"}` records. The page is server-rendered
   cards: `<a class="..." href="/evaluations/<slug>"> … <h2|h3>title</h2|3> …
   description … <span>tag</span> … </a>`. Expect 33 cards; the reference parse is
   stored at `tests/fixtures/eval_catalog.json` — your parser must reproduce it
   (titles, descriptions with whitespace collapsed and HTML entities unescaped, tag
   lists). Do not depend on the JSON fixture at runtime.
8. `provider_endpoints(slug)`: `hostModels` array -> `Endpoint` list, cheapest
   `cost_per_task` first (None last). Precision tag from the endpoint slug suffix
   (`fp4|fp8|fp16|bf16|int4|int8|awq|gptq`, else None). Per-endpoint
   `performance.intelligenceIndexCostPerTask` may be a float or `{"cost":{"total":..}}`.
9. `provider_board()`: 1201 rows -> `Endpoint` list; `host.label`, `model.slug`,
   `model.intelligenceIndex`, `pricing.*`, `performance.*`, `features.*`.
10. All loaders must be safe to call concurrently from a threadpool (MCP server) —
    no module-level mutable state other than the metric registries; pass
    `refresh` through; never cache results in memory beyond the on-disk cache (a
    small per-process memo of the 700-row leaderboard keyed by cache mtime is
    acceptable and encouraged for latency).

## Acceptance (self-check with fixtures; do not run repo-wide gates)

- Offline (`AA_OFFLINE=1` + pre-seeded cache files copied from `tests/fixtures/`)
  each `parse_*` function returns correct counts:
  leaderboard 700, `model_page_chart.rsc` -> 27 models incl. `claude-fable-5-1`,
  `providers_model.rsc` -> 1 endpoint (host `Novita`, precision None,
  price_in 0.6), `providers_board.rsc` -> 1201 endpoints (453 models, 64 hosts),
  `home.rsc` -> stt 15 / stt_streaming 28 / sts 15 (+ eval panels),
  `media_t2i.rsc` -> 102 rows with leader `GPT Image 2.5 Sunburst (max)` elo≈1217,
  `media_t2v.rsc` -> 32 rows leader `Wan 3.0`, `media_tts.rsc` -> 97 rows,
  `eval_page.rsc` (gpqa) -> 32 models, `eval_index.html` -> 33 catalog cards
  matching `tests/fixtures/eval_catalog.json`.
- Your offline test file passes: `uv run pytest tests/test_loaders.py`.
- No `src/` import of pandas/requests/bs4/lxml/yaml.

Report in your final message: files created, exact test command + result, per-surface
counts observed, any structure you found that INTERFACES.md describes wrongly, and
anything client-rendered that could not be extracted.
