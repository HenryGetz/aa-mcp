# Keyed API removal — inventory & removal plan

Scope: remove the keyed/paid `aa:api` backend entirely, leaving exactly one keyless
source (`aa:rsc`). This document is inventory only — **no code was changed**.

Method: `grep`/`rg` over `src/`, `tests/`, `docs/`, `eval/`, `scripts/`, `README.md`,
`pyproject.toml`, `.github/` (vendored `.venv/`, `.pytest_cache/`, `.ruff_cache/`
excluded). Line numbers are current as of 2026-10-15.

---

## 0. Reference counts per file

Counts are grep hits for the keyed-path symbol set
(`AA_API_KEY|AA_SOURCE|AA_API_TTL|api_key|active_source|probe_api|source_label|
ApiAuthError|fetch_models_free|parse_models_free|parse_model_item|MODELS_FREE_URL|
API_BASE|aa:api|with_licensing|_enrich_licensing|data_source|_source_key|
source_hint|_api_available|api_models_free|x-api-key|api/v2|api only`).

| file | hits | disposition |
|---|---:|---|
| `src/aa_mcp/api.py` | 32 | DELETE whole file |
| `src/aa_mcp/source.py` | 22 | DELETE whole file |
| `src/aa_mcp/loaders.py` | 13 | REWRITE |
| `src/aa_mcp/server.py` | 41 | REWRITE (largest surface) |
| `src/aa_mcp/catalog.py` | 4 | REWRITE (coding/agentic hint) |
| `src/aa_mcp/reference.py` | 3 | DOC-UPDATE (user-facing text) |
| `src/aa_mcp/render.py` | 0 | KEEP (label formatter only) |
| `src/aa_mcp/normalize.py` | 0 | KEEP |
| `src/aa_mcp/select.py` | 0 | KEEP |
| `src/aa_mcp/__init__.py` | 0 | KEEP |
| `tests/test_api.py` | 48 | DELETE whole file |
| `tests/test_source.py` | 48 | DELETE whole file |
| `tests/test_loaders.py` | 9 | REWRITE (3 tests + 2 helpers) |
| `tests/test_server.py` | 8 | REWRITE (monkeypatch targets) |
| `tests/test_catalog.py` | 6 | REWRITE (2 tests) |
| `tests/test_fetch.py` | 3 | REWRITE (cosmetic) |
| `tests/fixtures/api_models_free.json` | — | DELETE |
| `tests/fixtures/openapi.yaml` | — | KEEP (vocabulary) — see ambiguity A5 |
| `README.md` | 7 | DOC-UPDATE |
| `docs/INTERFACES.md` | 6 | DOC-UPDATE |
| `docs/REFERENCE.md` | 5 | DOC-UPDATE (generated) |
| `scripts/surface_sweep.py` | 2 | REWRITE |
| `scripts/gen_reference_md.py` | 0 | KEEP |
| `pyproject.toml` | 0 | KEEP (no change) |
| `.github/workflows/ci.yml` | 0 | KEEP (no `AA_API_KEY`; runs offline) |
| `eval/README.md`, `eval/client.py` | 0 | KEEP |
| `eval/runs/*`, `eval/reports/*`, `docs/process/AUDIT_*` | — | KEEP (historical) — see A6 |
| `~/.omp/agent/mcp.json` | 0 | KEEP (no `AA_API_KEY` env; note only) |

---

## 1. Reference table

### 1.1 `src/aa_mcp/api.py` — DELETE (entire file, 253 lines)

| file:line | symbol / snippet | disposition |
|---|---|---|
| `api.py:1-11` | module docstring ("JSON API … x-api-key … AA_API_TTL") | DELETE |
| `api.py:24` | `API_BASE = os.environ.get("AA_BASE_URL", …) + "/api/v2"` | DELETE |
| `api.py:25` | `MODELS_FREE_URL` | DELETE |
| `api.py:26` | `DEFAULT_API_TTL = 21600` | DELETE |
| `api.py:28` | `_MAX_PAGES` | DELETE |
| `api.py:30-37` | `__all__ = [API_BASE, MODELS_FREE_URL, ApiAuthError, fetch_models_free, parse_model_item, parse_models_free]` | DELETE |
| `api.py:40-46` | `class ApiAuthError(AAFetchError)` | DELETE |
| `api.py:54-57` | `_ttl()` (reads `AA_API_TTL`) | DELETE |
| `api.py:60-62` | `_status_from()` (401/403 regex) | DELETE |
| `api.py:65-72` | `_auth_error()` | DELETE |
| `api.py:75-91` | `_fetch_json_text()` (`x-api-key` header) | DELETE |
| `api.py:96-97` | `_key()` (reads `AA_API_KEY`) | DELETE |
| `api.py:104-116` | `_EVAL_INDEX_MAP` (incl. `artificial_analysis_coding_index` → `coding`, `..._agentic_index` → `agentic`, six `capabilities.*`) | DELETE (re-point source for coding/agentic — see A1) |
| `api.py:119-132` | `_num`, `_nested` | DELETE |
| `api.py:134-207` | `parse_model_item()` | DELETE |
| `api.py:210-217` | `parse_models_free()` | DELETE |
| `api.py:225-253` | `fetch_models_free()` (pagination, `api_models_free` cache names) | DELETE |

### 1.2 `src/aa_mcp/source.py` — DELETE (entire file, 108 lines)

| file:line | symbol / snippet | disposition |
|---|---|---|
| `source.py:1-13` | docstring + `AA_API_KEY`/`AA_SOURCE`/`AA_API_TTL` env docs | DELETE |
| `source.py:25` | `_MODES = ("auto", "api", "rsc")` | DELETE |
| `source.py:28-29` | `_lock`, `_probe_cache`, `_downgrade_logged` | DELETE |
| `source.py:31` | `__all__ = ["active_source", "api_key", "probe_api", "source_label"]` | DELETE |
| `source.py:34-37` | `api_key()` | DELETE |
| `source.py:40-42` | `_mode()` (`AA_SOURCE`) | DELETE |
| `source.py:45-74` | `probe_api()` (`from . import api`; probe/cache/downgrade) | DELETE |
| `source.py:77-83` | `_note_downgrade()` | DELETE |
| `source.py:85-100` | `active_source()` (`AA_SOURCE=api requires an AA_API_KEY`) | DELETE |
| `source.py:104-108` | `source_label()` (`aa:api` / `aa:rsc`) | DELETE → replace with constant `aa:rsc` (see §2 step 1) |

### 1.3 `src/aa_mcp/loaders.py` — REWRITE

| file:line | symbol / snippet | disposition |
|---|---|---|
| `loaders.py:40` | `from . import catalog, fetch, flight, normalize, select, source` | SIMPLIFY (drop `source`) |
| `loaders.py:53` | `"data_source",` in `__all__` | DELETE |
| `loaders.py:782-784` | `data_source() -> source.source_label()` | DELETE (or REWRITE to `return "aa:rsc"`) — see A2 |
| `loaders.py:807-829` | `_enrich_licensing(api_model, rsc_model)` | DELETE |
| `loaders.py:832-862` | `leaderboard(refresh, *, with_licensing=False)` — api branch 840-860 + docstring 833-838 | REWRITE (drop `with_licensing` param and api branch; keep `_leaderboard_rsc` call at 862) |
| `loaders.py:864-899` | `model()` api branch (877-899) + docstring 868-871 | DELETE (keep RSC path from 901) |
| `loaders.py:787` | `_leaderboard_rsc()` | KEEP (becomes the only path) |

### 1.4 `src/aa_mcp/server.py` — REWRITE (biggest surface)

| file:line | symbol / snippet | disposition |
|---|---|---|
| `server.py:40` | `source,` in the `from . import (…)` block | SIMPLIFY (drop) |
| `server.py:396-400` | `_api_available()` | DELETE |
| `server.py:403-408` | `_source_key()` (`loaders.data_source().split(":")[-1]`) | REWRITE → `return "rsc"` constant |
| `server.py:410-418` | `_cache_ttl(api)` (`AA_API_TTL` vs `AA_CACHE_TTL`) | SIMPLIFY (drop `api` branch + `AA_API_TTL`) |
| `server.py:420-433` | `_fresh(name, *, api=False)` | SIMPLIFY (drop `api` kwarg if `_cache_ttl` loses it) |
| `server.py:436-439` | `_lb_cache()` → `("api_models_free", True)` when `_source_key()=="api"` | SIMPLIFY → constant `("leaderboard", False)` |
| `server.py:449-450` | `_header(..., api=False, source_label=None)` | SIMPLIFY |
| `server.py:460-469` | `_header` body (`_fresh(name, api=api)`, `source=source_label or _source_key()`) | SIMPLIFY |
| `server.py:957-972` | `_prov_label(rich_used, source_key)` | SIMPLIFY (`base = "rsc"`) |
| `server.py:979-980` | `_is_index_key()` → `("capabilities.", "coding", "agentic")` | KEEP (keys still exist) |
| `server.py:983-995` | `_no_rank_text()` — "…through the JSON API (AA_API_KEY)…" | REWRITE text |
| `server.py:1249-1258` | `_rankable()` "how" — `bench.source_hint == "api"` → `"(needs AA_API_KEY)"` | REWRITE |
| `server.py:1766-1774` | `_pareto` `source_label` join with `_source_key()` | SIMPLIFY |
| `server.py:2033-2038` | `_leaderboard` `_prov_label` + `extra_source` | SIMPLIFY |
| `server.py:2098-2105` | `_model_indices` — `if not _api_available(): … "need AA_API_KEY (JSON API); unavailable on the scrape source"` | REWRITE (drop `_api_available`; honest text pending A1) |
| `server.py:2119-2134` | `_model_capabilities` docstring "(aa:api, …)" + `_api_available` note | REWRITE |
| `server.py:2152-2156` | `_model_chart_evals` skips `bench.source_hint == "api"` | REWRITE (depends on A1) |
| `server.py:2381` | `head += f" · aa:{_source_key()}"` | SIMPLIFY (constant) |
| `server.py:2596-2598` | `_is_chart_rankable` — `bench.source_hint == "api"` guard | REWRITE (depends on A1) |
| `server.py:3542,3548` | `_compare` `_lb_cache()`, `_prov_label` | SIMPLIFY |
| `server.py:3748-3749` | `_rankable_coverage` — `if surface == "api": return "api only (AA_API_KEY)"` | REWRITE |
| `server.py:3894` | `_benchmark_leaderboard` `_lb_cache()` | SIMPLIFY |
| `server.py:4015` | `_providers` `_prov_label` | SIMPLIFY |
| `server.py:4925-4926` | `_surface_note()` — `{"api": "API-only (AA_API_KEY)"}` | REWRITE |
| `server.py:4994,5005` | `aa_search` `_lb_cache()` / `_header(source_label=_source_key())` | SIMPLIFY |
| `server.py:5073-5076` | `aa_reference` — "coding/agentic/capability indexes need AA_API_KEY …" | DELETE |
| `server.py:5124-5125` | `aa_raw kind=leaderboard` `_lb_cache()` | SIMPLIFY |
| `server.py:5672-5675` | `_r_sources` resource → `reference.TOPICS["sources"]` | KEEP (text changes via reference.py) |

### 1.5 `src/aa_mcp/catalog.py` — REWRITE

| file:line | symbol / snippet | disposition |
|---|---|---|
| `catalog.py:57` | `source_hint: str = "leaderboard"  # … "api" …` | SIMPLIFY |
| `catalog.py:70-73` | `("coding", "Coding", None, "index", …)` / `("agentic", "Agentic", None, "index", …)` entries | KEEP (registry rows stay) |
| `catalog.py:233-236` | `_SOURCE_HINTS = {"coding": "api", "agentic": "api"}` | REWRITE → new hint (A1) |
| `catalog.py:802` | `Rankable.surface` docstring `"… "api" …"` | SIMPLIFY |
| `catalog.py:861-866` | `_lb_reachable = (… and _b.source_hint != "api" …)` | REWRITE (depends on A1) |
| `catalog.py:646-649` | `_OPENAPI_ALIASES` (field vocabulary) | KEEP |

### 1.6 `src/aa_mcp/reference.py` — DOC-UPDATE (user-facing shipped text)

| file:line | symbol / snippet | disposition |
|---|---|---|
| `reference.py:10` | `overview`: "Two backends, same records… `aa:api` (requires `AA_API_KEY`)… 100 req/24 h free tier" | DOC-UPDATE |
| `reference.py:11` | `indexes`: "API-only (require `AA_API_KEY`): **Coding Index**, **Agentic Index**, and the six Capability Indexes…" | DOC-UPDATE (critical; see A1) |
| `reference.py:17` | `fields`: lists `coding`, `agentic` aliases | KEEP (aliases still valid once A1 lands) |
| `reference.py:18` | `sources`: "JSON API: …/api/v2 (`x-api-key`)… API TTL `AA_API_TTL`…" | DOC-UPDATE |

### 1.7 `src/aa_mcp/render.py` — KEEP

| file:line | symbol / snippet | disposition |
|---|---|---|
| `render.py:110` | `parts.append(f"aa:{source or 'rsc'}")` | KEEP (works with the constant `"rsc"`) |

### 1.8 `tests/`

| file:line | symbol / snippet | disposition |
|---|---|---|
| `tests/test_api.py:1-235` | whole file (48 refs: envelope, mapping, capability indices, TTL, pagination, auth, `data_source()=="aa:api"`) | DELETE |
| `tests/test_source.py:1-159` | whole file (48 refs: `AA_SOURCE` matrix, probe, downgrade, `aa:api`) | DELETE |
| `tests/test_loaders.py:29-34` | `_isolate` `delenv("AA_API_KEY")`, `delenv("AA_SOURCE")` | SIMPLIFY (drop the two delenv lines; keep others) |
| `tests/test_loaders.py:615-635` | `_api_item`, `_api_envelope`, `_api_source` helpers | DELETE |
| `tests/test_loaders.py:638-646` | `test_api_leaderboard_licensing_is_unknown` | DELETE |
| `tests/test_loaders.py:648-662` | `test_api_leaderboard_with_licensing_enriches_from_rsc` | DELETE |
| `tests/test_loaders.py:664-674` | `test_api_leaderboard_with_licensing_survives_rsc_failure` | DELETE |
| `tests/test_server.py:68,297,1012,1048,1439,1501,1788,1797` | `monkeypatch.setattr(server, "_source_key", lambda: "rsc")` / `_lb_cache` | REWRITE (retarget if symbols removed/renamed) |
| `tests/test_server.py:1567-1576` | `coding/$` ratio test (`indices={"coding": 50.0}`) | KEEP (pure data; no API) |
| `tests/test_catalog.py:206-220` | `test_source_hint_classification` (`"coding": "api"`, `"agentic": "api"`) | REWRITE (A1) |
| `tests/test_catalog.py:223-229` | `test_source_hint_values_are_known_and_counted` (`hints["api"] == 2`) | REWRITE |
| `tests/test_catalog.py:551-553` | `bench.source_hint == "api"` allowance in hint-coverage test | REWRITE |
| `tests/test_catalog.py:91-96` | `test_openapi_fixture_lists_our_keys` (uses `openapi.yaml`) | KEEP (A5) |
| `tests/test_fetch.py:347-358` | header-merge test using `x-api-key` example | REWRITE cosmetic (generic test; keep behaviour) |
| `tests/fixtures/api_models_free.json` | API free-shape fixture | DELETE |
| `tests/fixtures/openapi.yaml` | AA V2 OpenAPI capture | KEEP (A5) |

### 1.9 Docs / scripts / packaging

| file:line | symbol / snippet | disposition |
|---|---|---|
| `README.md:9-16` | "No API key needed. Two interchangeable data backends…" table (`aa:api`, `AA_API_KEY`, quota) | DOC-UPDATE |
| `README.md:18-19` | "If a key is present the API is tried first… falls back… header shows which backend answered" | DOC-UPDATE |
| `README.md:156` | "- Coding/Agentic indexes need the JSON API (`AA_API_KEY`)." | DOC-UPDATE |
| `README.md:166-170` | env table rows `AA_API_KEY`, `AA_SOURCE`, `AA_API_TTL` | DOC-UPDATE |
| `docs/INTERFACES.md:3` | "## Dual-source architecture (JSON API primary, RSC fallback)" | DOC-UPDATE |
| `docs/INTERFACES.md:9-19` | dual-source table + `active_source`/`source_label` contract + "Implementation lives in `api.py` + `source.py`" | DOC-UPDATE |
| `docs/INTERFACES.md:112` | `openapi` source row | DOC-UPDATE (or KEEP as reference) |
| `docs/INTERFACES.md:466` | fixture list includes `openapi.yaml` | KEEP |
| `docs/REFERENCE.md:11-13` | two-backends section | DOC-UPDATE (regenerate) |
| `docs/REFERENCE.md:125-128` | "API-only (require `AA_API_KEY`)…" | DOC-UPDATE (regenerate) |
| `docs/REFERENCE.md:316-320` | JSON API + `AA_API_TTL` cache lines | DOC-UPDATE (regenerate) |
| `scripts/gen_reference_md.py:24-26` | regenerates `docs/REFERENCE.md` from `reference.py` | KEEP (run after editing reference.py) |
| `scripts/surface_sweep.py:305-309` | coding/agentic expectations: "Coding Index is API-only (AA_API_KEY)…" | REWRITE (after A1) |
| `pyproject.toml` | — | KEEP (no reference) |
| `.github/workflows/ci.yml` | runs offline; no `AA_API_KEY` | KEEP (but will go red until tests are rewritten) |
| `~/.omp/agent/mcp.json` | no `AA_API_KEY` env block | KEEP (note only, do not edit) |
| `eval/runs/*`, `eval/reports/*`, `eval/questions_round7_*`, `docs/process/AUDIT_*` | historical text mentioning `aa:api`/`AA_API_KEY` | KEEP (A6) |

---

## 2. Order of operations (keep the tree green)

Goal: never leave an import of a deleted module or a dangling symbol for long.

1. **Introduce the constant first, delete `source.py` last.**
   Add `_SOURCE_KEY = "rsc"` (or `_source_key() -> "rsc"`), make `_lb_cache()` return
   `("leaderboard", False)`, drop the `api` branch from `_cache_ttl`/`_fresh`, and change
   `loaders.data_source()` to a constant `"aa:rsc"`. Run tests — still green (no
   behaviour change while `AA_SOURCE` defaults to `auto` with no key).
2. **Cut `server.py` off `source`**: delete `_api_available()`, drop the `source` import,
   rewrite the 3 `_api_available` call sites (2099, 2131, 5073) and the `source_hint ==
   "api"` / `surface == "api"` messaging sites. Tests that monkeypatch `_source_key` /
   `_lb_cache` are unaffected if the names are kept.
3. **Cut `loaders.py` off `source`**: delete `_enrich_licensing`, the `with_licensing`
   parameter + api branch in `leaderboard()`, and the api branch in `model()`. Delete
   the 3 `test_loaders.py` api tests and helpers in the same commit.
4. **Delete `tests/test_api.py`, `tests/test_source.py`, `tests/fixtures/api_models_free.json`**
   and rewrite `test_catalog.py` / `test_fetch.py` / `test_server.py` monkeypatch targets.
   This is the commit that makes CI go red→green.
5. **Delete `src/aa_mcp/api.py` and `src/aa_mcp/source.py`** (now unreferenced). `grep -rn
   "import api\|source\." src tests scripts` must be empty.
6. **Catalog/reference/docs pass**: re-point `_SOURCE_HINTS` for coding/agentic (A1),
   rewrite the remaining user-facing strings in `reference.py` + `server.py`, regenerate
   `docs/REFERENCE.md` (`uv run python scripts/gen_reference_md.py`), update `README.md`,
   `docs/INTERFACES.md`, `scripts/surface_sweep.py`.

Ordering rationale: steps 1–3 remove all *runtime* coupling before the files disappear;
step 4 removes the *test* coupling; only then (step 5) do the modules become dead code.
The only transient red window is step 4, which is atomic (tests + deletions in one commit).

---

## 3. Tests: delete vs rewrite vs add

### Delete outright
- `tests/test_api.py` (entire file) — tests only the deleted module.
- `tests/test_source.py` (entire file) — tests only the deleted selector.
- `tests/test_loaders.py::test_api_leaderboard_licensing_is_unknown` (638)
- `tests/test_loaders.py::test_api_leaderboard_with_licensing_enriches_from_rsc` (648)
- `tests/test_loaders.py::test_api_leaderboard_with_licensing_survives_rsc_failure` (664)
- `tests/test_loaders.py` helpers `_api_item` / `_api_envelope` / `_api_source` (615-635)

### Rewrite
- `tests/test_loaders.py:29-34` — drop `AA_API_KEY`/`AA_SOURCE` delenv (env vars no longer
  read); keep the RSC isolation the fixture already relies on.
- `tests/test_catalog.py:206-229, 551-553` — remove `"coding"/"agentic": "api"` expectations
  and the `hints["api"] == 2` count; assert the new hint (A1) instead.
- `tests/test_server.py:68,297,1012,1048,1439,1501,1788,1797` — retarget monkeypatches if
  `_source_key`/`_lb_cache` are renamed/removed; otherwise keep.
- `tests/test_fetch.py:347-358` — rename the `x-api-key` example header (behaviour is
  generic header merging; keep the assertions).
- `scripts/surface_sweep.py:305-309` — update the coding/agentic expectations once A1 lands.

### New tests to add (cover the replacement behaviour)
1. **Single keyless source label** — `render.header(...)` / `server._source_key()` always
   produce `aa:rsc` (never `aa:api`), with `AA_API_KEY`/`AA_SOURCE` set to arbitrary values
   (assert they are ignored, or that a warning is emitted — see A4).
2. **One leaderboard path** — `loaders.leaderboard()` ignores `with_licensing` (parameter
   gone) and returns the RSC rows; `loaders.model(slug)` returns the RSC chart-set record.
3. **No keyed cache artefacts** — `server._lb_cache() == ("leaderboard", False)` and
   `_cache_ttl()` never reads `AA_API_TTL`; cache names never become `api_models_free`.
4. **Keyless coding/agentic ranking** (once the new extraction lands) — `aa_leaderboard
   sort=coding` / `aa_benchmark_leaderboard benchmark=coding` rank real values and no
   message mentions `AA_API_KEY`; `aa_model` shows Coding/Agentic with no "needs API key"
   footnote.
5. **Honest degradation** (if extraction is not yet available) — `aa_benchmarks` /
   `aa_model` state the gap without naming an API key or a backend choice.
6. **No dangling references** — a repo-level assertion (or CI grep) that `AA_API_KEY`,
   `AA_SOURCE`, `AA_API_TTL`, `aa:api`, `ApiAuthError`, `fetch_models_free` appear nowhere
   in `src/` or `tests/`.

---

## 4. Ambiguities — need a decision (do not guess)

**A1. What replaces `source_hint == "api"` for `coding` / `agentic`?**
Today `catalog._SOURCE_HINTS["coding"|"agentic"] = "api"` and `server.py` keys ~8 branches
off `source_hint == "api"` (1250/1257, 2153, 2597, 3748-3749, 4925-4926, and
`_no_rank_text` 983-995). The keyless extraction does not exist yet. Options: (a) new hint
value (e.g. `"page"`/`"rsc"`) with its own messaging, (b) map to `"rich"` once the model-page
extraction lands, (c) leave `"api"` semantics but rename. This blocks the catalog, server
messaging, `reference.py:11`, `surface_sweep.py`, and the new tests — **pick one before the
catalog pass.**

**A2. Keep `loaders.data_source()` or delete it?**
Only caller is `server._source_key()` (which is then monkeypatched in tests). Minimal
replacement: delete `data_source()`, make `_source_key()` a literal `"rsc"`. Alternative:
keep `data_source() -> "aa:rsc"` for symmetry with `render.header`'s `aa:` prefix. Affects
8 test monkeypatch sites.

**A3. Is `AA_BASE_URL` still needed?**
`api.py:24` builds `API_BASE` from it, but `fetch.py` also uses `AA_BASE_URL` for RSC
fetches and `tests/test_loaders.py:32` deletes it. Keep it (RSC still needs it) — confirm no
other intent.

**A4. What should happen if `AA_API_KEY` / `AA_SOURCE` are set after removal?**
Silently ignore (env vars simply unread) vs. log a one-line stderr warning ("ignored; keyed
backend removed"). Affects README env table wording and a new test.

**A5. `tests/fixtures/openapi.yaml` — keep or delete?**
It documents the paid V2 API but is currently used as a *field-vocabulary* source by
`test_catalog.py:91-96` (`_OPENAPI_ALIASES`, catalog.py:646-649). Recommended: KEEP the
fixture and the vocabulary aliasing (they also name RSC fields); decide whether the
`docs/INTERFACES.md:112` openapi row stays.

**A6. Historical artefacts (`eval/runs/*`, `eval/reports/*`, `eval/questions_round7_*`,
`docs/process/AUDIT_*`).**
They contain `aa:api` / `AA_API_KEY` quotes as evidence of past runs. Recommended: leave
them untouched as a historical record (they are not shipped text and not executed by CI);
confirm rather than mass-scrubbing.

**A7. `with_licensing` has no production caller.**
`loaders.leaderboard(with_licensing=…)` is called only from the 3 tests being deleted
(`test_loaders.py:653,671`) — no tool passes it. Recommended: delete the parameter entirely
rather than keep a no-op. Confirm.

---

## 5. Top 5 riskiest removal points

1. **`catalog._SOURCE_HINTS` coding/agentic + the `source_hint == "api"` branches in
   `server.py` (1250/1257, 2153, 2597, 3748-3749, 4925-4926).** If `"api"` is naively
   remapped to `"leaderboard"`, `aa_leaderboard sort=coding` is advertised as a real path
   with no data → the silent no-op the round-1/round-4 audits already complained about.
   This is exactly the "re-point at the new keyless extraction later" seam (A1).
2. **The `_source_key()` → `data_source()` → `source.source_label()` → `_lb_cache()` →
   `_cache_ttl()` chain.** Deleting `source.py` breaks `server._lb_cache` (cache name
   `api_models_free`), `_cache_ttl` (`AA_API_TTL`), the header label, and 8 test
   monkeypatch sites; must land as one change (steps 1–2 of §2).
3. **User-facing availability claims** in `server._model_indices` (2098-2105),
   `_model_capabilities` (2131-2133), `aa_reference` note (5073-5076), and
   `reference.py:11`. If these keep mentioning `AA_API_KEY`, or silently drop the
   "unavailable" note before the extraction exists, the agent gets a wrong answer.
4. **`loaders.leaderboard()` / `loaders.model()` api branches** (832-862, 877-899) plus
   `_enrich_licensing` (807-829): removing them must leave the RSC paths byte-identical;
   `with_licensing` also has to go from the signature and docstrings (A7).
5. **`render.header`'s `aa:{source}` label + `_source_key()` consumers.** The label is
   produced in two places (`render.py:110` and `server.py:2381`) and read by tests; a
   constant must be threaded so no path can ever emit `aa:api` (new test §3.1).

---

## 6. Status (2026-10-15)

### Done

- **Steps 1–2 (`server.py`)** — `_api_available()` deleted; `_source_key()` is the
  literal `"rsc"` (name kept so the 8 test monkeypatches still work); `_lb_cache()`
  returns `("leaderboard", False)`; `_cache_ttl()` reads only `AA_CACHE_TTL` (the
  `AA_API_TTL` read is gone); `_fresh(name, *, api=False)` keeps its signature for the
  monkeypatches; `source` dropped from the import block and docstring; a one-time
  `_warn_keyed_env_once()` WARNING added for A4.
- **Step 3 (`loaders.py`)** — `source` import dropped; `data_source()` and its `__all__`
  entry deleted; `_enrich_licensing()` deleted; `leaderboard()` lost `with_licensing` and
  its API branch; `model()` lost its API branch; the now-unused `dataclasses.replace`
  import removed.
- **Step 4 (tests)** — deleted `tests/test_api.py`, `tests/test_source.py`,
  `tests/fixtures/api_models_free.json`, `tests/fixtures/openapi.yaml`; deleted the 3
  `test_loaders.py` API tests plus `_api_item`/`_api_envelope`/`_api_source`/`_faked_fetch`;
  the RSC fixture no longer delenvs `AA_API_KEY`/`AA_SOURCE`; `test_openapi_fixture_lists_our_keys`
  became `test_live_payload_fixtures_list_fields_we_map` (asserts `leaderboard.rsc` +
  `model_page_chart.rsc` carry `intelligenceIndex`/`gpqa`/`mmmuPro`/`terminalBench21`/
  `gdpvalNormalized`/`releaseDate`); the `x-api-key` example in `test_fetch.py` renamed to
  `X-Custom-Token`.
- **Step 5** — `src/aa_mcp/api.py` and `src/aa_mcp/source.py` deleted.
- **New tests** — `test_source_key_is_always_rsc_and_warns_once`,
  `test_lb_cache_and_cache_ttl_ignore_api_settings`.
- **Docs/text pass** — `reference.py` `overview`/`indexes`/`sources` rewritten keyless
  (six capability indexes with coverage + sub-score keys, openness/decision/cyber, the
  agent-level coding index, and the honest coding/agentic gap); `docs/REFERENCE.md`
  regenerated (`gen_reference_md.py --check` passes); `README.md` two-backend table and
  API env rows replaced by the single keyless story plus an "Indexes" subsection;
  `docs/INTERFACES.md` dual-source section replaced by a single-source note and its
  fixture/sources tables updated; `scripts/surface_sweep.py` coding/agentic expectations
  reworded (no key).

### Landed by the `index-recon` pass

The API-era messaging is gone: `server.py` no longer names `AA_API_KEY` anywhere
(`_no_rank_text`, the rankable `how` hints, the pareto note, the former
`_api_available()` note blocks, `_rankable_coverage`, `_surface_note` and the
`aa_reference` note were all reworded), and `catalog._SOURCE_HINTS` no longer maps
`coding`/`agentic` to `"api"`. The free index keys (`decisionIndex`, `cyberIndex`,
`codingAgentIndex`, `capabilities.*`, `openness`) now resolve as rankables, with tests
asserting no reply mentions `AA_API_KEY` or `JSON API`.

### Remaining

- Capability-index sweep cases in `scripts/surface_sweep.py` — deliberately deferred
  until the implementation landed; the coding/agentic expectations are already reworded
  to the honest (keyless) wording.

### Final reference counts

`grep -rn "AA_API_KEY\|AA_SOURCE\|AA_API_TTL\|aa:api" src tests scripts README.md docs/INTERFACES.md`
on the finished tree:

| file | hits | what |
|---|---:|---|
| `src/aa_mcp/server.py` | 3 | the A4 warning only (399 docstring, 404 tuple, 423 comment) |
| `tests/test_server.py` | 10 | the two keyless tests plus two absence assertions |
| `docs/INTERFACES.md` | 1 | line 11 — states the vars are set-but-ignored |
| `src/aa_mcp/reference.py`, `README.md`, `docs/REFERENCE.md`, `catalog.py`, `loaders.py`, `scripts/surface_sweep.py` | 0 | clean |

Deleted files: `src/aa_mcp/api.py`, `src/aa_mcp/source.py`, `tests/test_api.py`,
`tests/test_source.py`, `tests/fixtures/api_models_free.json`, `tests/fixtures/openapi.yaml`.

### Verifier findings (`docs/process/VERIFY_KEYLESS.md`, check 6)

Independent verification flagged stale counts in the shipped text: the rankable index
(95 entries / 67 benchmarks → **105 / 57**), the tracked-variant count (700 → **703**),
cost-per-task coverage (186/700 → **194/703**), provider endpoints (1,201 → **1,199**),
the README example block, and the per-benchmark coverage figures in the `benchmarks`
topic. All were re-measured live on 2026-10-15 and refreshed in `README.md`,
`src/aa_mcp/reference.py` (plus the regenerated `docs/REFERENCE.md`) and
`docs/INTERFACES.md`, with a single drift caveat added to the reference preamble and
the README coverage section. The verifier's other two findings — the filter-narrowed
coverage footnote in `server.py` and the stale `openapi.yaml` provenance comments in
`catalog.py` — are code defects outside this document and remain with their owners.
