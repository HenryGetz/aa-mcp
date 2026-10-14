# T5 brief — dual-source architecture (JSON API primary, RSC fallback)

Owner: `src/aa_mcp/source.py` (new), `src/aa_mcp/api.py` (new),
`tests/test_api.py`, `tests/test_source.py`, edits to **your own** `src/aa_mcp/loaders.py`
and `tests/test_loaders.py`, plus one new fixture `tests/fixtures/api_models_free.json`.
Do not touch fetch.py/flight.py/catalog.py/normalize.py/select.py/render.py/server.py
(the CoreLayer agent owns those; it is adding a `headers=` parameter to `fetch.get`).

## Why

The scraper (RSC flight payload) is the no-key default. AA also exposes a documented
JSON API (`https://artificialanalysis.ai/api/v2`, OpenAPI spec at
`/api/v2/openapi`, public). Its **free tier** endpoint
`GET /api/v2/language/models/free` returns structured JSON for every language model
with headline indices, the six Capability Indexes, the Coding/Agentic indexes,
median performance and input/output/cache pricing — data the scraped payload does
**not** contain. Requirements: header `x-api-key: <key>`, 100 requests/24 h on the
free tier. So: **API when a key is present, RSC otherwise, never hard-fail.**

## Deliverable

`source.py`

```python
def api_key() -> str | None                 # env AA_API_KEY ("" -> None)
def active_source(refresh: bool = False) -> str
    # AA_SOURCE = auto (default) | api | rsc
    #   auto -> "api" if api_key() else "rsc"
    #   api  -> "api" (raises AAFetchError with a clear hint if no key)
    #   rsc  -> "rsc"
    # If api is selected but the last probe failed with 401/403, return "rsc" and
    # log once to stderr (do not spam).
def probe_api() -> tuple[bool, str]         # (usable, reason) — cached per process
def source_label() -> str                   # "aa:api" | "aa:rsc" — used in tool headers
```

`api.py`

```python
API_BASE = "https://artificialanalysis.ai/api/v2"
def parse_models_free(payload: dict) -> list[Model]     # pure, offline-testable
def fetch_models_free(refresh: bool = False) -> list[Model]
def parse_model_item(item: dict) -> Model
```

- Envelope: `{"tier": ..., "pagination": {...}, "data": [<FreeModelData>, ...]}`.
  Verify the exact envelope + field names against `tests/fixtures/openapi.yaml`
  (`LLMModelsFreeResponse`, `FreeModelData`, `FreeEvaluations`, `FreePricing`,
  `FreeModelPerformance`, `FreeIntelligenceIndexCost`) — snake_case fields, `null`
  means not measured.
- Map into the frozen `normalize.Model`: `evals["intelligence"]`-style indices land in
  `Model.indices` (`intelligence`, `coding`, `agentic`, `capabilities.*`), pricing in
  `Model.pricing` (`in`, `out`, `cache_read`, `cache_write`), `Model.speed`
  (`tps`, `ttft`, `ttfa`, `e2e`), `cost_per_task` from
  `artificial_analysis_intelligence_index_cost.cost_per_task.total_cost` when present,
  `release_date`, `creator`/`creator_slug` from `model_creator`, `source="api"`.
- Use `fetch.get(url, name="api_models_free", refresh=refresh, rsc=False,
  headers={"x-api-key": key})` (the CoreLayer agent is adding `headers=`; if it is
  not there yet, keep a 3-line local urllib fallback and note it in your report).
- Cache TTL for API responses must be longer than the scrape TTL: pass
  `ttl=int(os.environ.get("AA_API_TTL", 21600))` (6 h) to respect the 100/day quota.
- 401/403 -> raise `AAFetchError` with hint "set a valid AA_API_KEY or use AA_SOURCE=rsc";
  the caller (`source.active_source`) downgrades to RSC after the first such failure.

`loaders.py` integration (minimal, no signature changes)

- `leaderboard(refresh=False)` -> API models when `active_source() == "api"`, else the
  existing RSC path. Return the same `list[Model]` shape either way.
- `model(slug, ...)` -> when on API source, take the target record from the API list
  and optionally merge the RSC chart set (which has the extra per-eval fields) using
  `normalize.merge(api_record, chart_record)`; if the RSC fetch fails, return the API
  record alone (never fail the whole call).
- Add `def data_source() -> str` returning `source.source_label()` so tools can label
  output provenance.
- Everything else (media/agents/providers) stays on the RSC path — those surfaces are
  not in the free tier; Pro/Commercial endpoints exist but we do not implement them.

`tests/test_api.py`

- Fixture-generating note: `tests/fixtures/api_models_free.json` must be a **static**
  file shaped exactly like the OpenAPI schema (3 models: one full, one all-nulls, one
  open-weights). Generate it once from `tests/fixtures/openapi.yaml` with a throwaway
  script; tests must not import yaml.
- Tests: envelope unwrap -> 3 Models; nulls -> `None` not 0; capability indices land
  under `indices["capabilities.*"]`; cost_per_task from `cost_per_task.total_cost`;
  `source == "api"`.
- HTTP tests with `AA_API_KEY=test` + a monkeypatched `fetch.get` (no network):
  URL/header correctness, 401 -> `AAFetchError` + `active_source()` downgrade to
  `"rsc"` on the next call, `AA_SOURCE=rsc` never touches the API, `AA_SOURCE=api`
  without a key raises with the hint.

`tests/test_source.py`

- `AA_SOURCE` matrix (auto/api/rsc x key/no-key), `source_label()`, probe caching,
  and that a 401 downgrade does not repeat the API call (assert call count).

## Acceptance (self-check; no repo-wide gates)

- `uv run pytest tests/test_api.py tests/test_source.py tests/test_loaders.py -q` passes.
- With `AA_SOURCE=rsc` (default when no key) every existing loader test still passes
  unchanged — the dual source must be invisible without a key.
- No forbidden imports (pandas/requests/bs4/lxml/yaml) in `src/`.
- `AA_OFFLINE=1` still works for every RSC loader.

Report: files changed, test command + result, the exact mapping table you used
(API field -> `Model` field), and what you could **not** verify (no live API key
exists on this machine — say so plainly and state that live auth/envelope is
spec-derived).
