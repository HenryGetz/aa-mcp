# aa-mcp interfaces (frozen contract)

## Single keyless source (RSC flight payloads)

One data source: `GET <page>` with the `RSC: 1` header returns the Next.js App
Router flight payload (JSON-ish text), which the loaders parse into the canonical
`Model` records. No API key, no backend selection, no quota, no fallback logic.

Every tool header reports `aa:rsc`: `render.header` renders `aa:{source}` and
`server._source_key()` is the constant `"rsc"`. Nothing in the server reads
`AA_API_KEY` / `AA_SOURCE` / `AA_API_TTL`; if those are set in the environment the
server logs one warning and ignores them.

Anything that once needed a key is either available on a public page (the six
Capability Indexes — see `docs/REFERENCE.md` topic `indexes`) or not published at
all (the model-level Coding Index and Agentic Index).

## ADDENDUM (verified 2026-10-14): SDK is `mcp` 2.x — NOT FastMCP

The installed SDK is `mcp` 2.x: `from mcp.server.mcpserver import MCPServer`
(`FastMCP` no longer exists; do not import `mcp.server.fastmcp`). Verified surface:

```python
srv = MCPServer(name="aa-mcp", version=__version__, instructions="...")

@srv.tool(name="aa_leaderboard", title="...")   # description defaults to the docstring
def aa_leaderboard(...) -> str: ...

@srv.resource("aa://reference/metrics", name="...", mime_type="text/markdown")
def _r() -> str: ...

@srv.prompt("best_model_for_task")
def _p(task: str) -> str: ...

def main() -> None: srv.run("stdio")
```

- Input schema derives from the signature + type hints + docstring (Google-style
  `Args:` sections become parameter descriptions).
- Return `str` → single text content block. Do NOT return dicts/dataclasses
  (that adds `structuredContent` and doubles token cost); use `structured_output=False`.
- Client side (our eval harness): `mcp.client.stdio.stdio_client(StdioServerParameters(...))`
  + `async with ClientSession(r, w) as s: await s.initialize()`, then
  `s.list_tools()`, `s.call_tool(name, args)`, `s.list_resources()`,
  `s.read_resource(uri)`, `s.list_prompts()`, `s.get_prompt(name, args)`.
- Runtime dep: `mcp>=2.0.0` (pyproject is set). `.venv` resolves to Python 3.12 —
  keep 3.10+ syntax.

`aa-mcp` is a Python MCP server exposing live Artificial Analysis (AA) benchmark
data (artificialanalysis.ai) with token-efficient markdown output. No API key
required: data is read from the site's Next.js **RSC flight payloads**.

This file is the coordination contract between modules. **Do not change a
public signature here without telling the orchestrator.**

## Hard rules

- Dependency budget: **`mcp` only** (official SDK, ships FastMCP). No pandas, no
  requests, no bs4, no lxml, no yaml at runtime. `tests/` may use pytest.
- Python >= 3.10 (dev machine has 3.14; target 3.10+ syntax).
- No network at import time. Network only inside loaders.
- Never print to stdout from library code: **stdout is the MCP stdio channel.**
  Diagnostics go to `stderr` via `logging`.
- All user-visible numbers rounded (1 decimal for scores, 2-4 for USD).
- Subagents: do not run linters/formatters/tests-as-gates on the whole repo;
  edit files and report. The orchestrator runs gates once at phase end.

## Repo layout

```
pyproject.toml            # project name "aa-mcp", script aa-mcp = aa_mcp.server:main
README.md
docs/INTERFACES.md        # this file
src/aa_mcp/
  __init__.py             # __version__
  fetch.py                # HTTP + cache
  flight.py               # RSC/HTML payload parsing helpers
  catalog.py              # metric registry + benchmark catalog + formatters
  normalize.py            # raw payload records -> Canonical model record
  select.py               # filter / sort / fuzzy resolve / pareto / value
  render.py               # markdown table + header rendering
  loaders.py              # per-source page loaders (the only network users)
  server.py               # FastMCP app: tools, resources, prompts, main()
tests/
  fixtures/               # real captured payloads (offline tests)
  test_*.py
eval/                     # agent-in-the-loop evaluation harness (not shipped logic)
```

## Data sources (verified 2026-10-14)

All RSC fetches need header `RSC: 1` + a browser `User-Agent`; server gzips
(`Accept-Encoding: gzip`), so transfer is ~15% of decoded size. Crawling the
plain HTML works too but is ~2x bigger and needs `self.__next_f.push` joining.

| name | URL (add `RSC: 1`) | decoded | shape |
|---|---|---|---|
| leaderboard | `/leaderboards/models` | 1.19 MB | JSON array under `"models":[` (**2nd** occurrence) — 703 model variants x 50 metrics |
| model page | `/models/<slug>` | 0.75-3.2 MB | `"initialModels":[` array (27-32 records x 94 metrics, focused model included, `chartHighlighted:true`) **or**, on legacy/deprecated pages, `"currentModel":{...}` (~80 keys, array may be empty) |
| model providers | `/models/<slug>/providers` | 380 KB | `"hostModels":[{...}]` — per-endpoint pricing/performance, `intelligenceIndexCostPerTask`, `jsonMode`, `functionCalling`; precision from `slug` suffix |
| providers board | `/leaderboards/providers` | 2.7 MB | `"rows":[{...}]` 1199 endpoint rows: host + model (incl. `intelligenceIndex` + per-benchmark scores) + pricing (`cacheHitPrice`/`cacheWritePrice`, **no** `cacheHitDiscountPercent`) + performance + `features` (`contextWindowTokens`, `functionCalling`, `jsonMode`, `openaiCompatible`). No precision tag and no `intelligenceIndexCostPerTask` here — those exist only on `hostModels` |
| homepage | `/` | 1.11 MB | `"sttNonStreaming":{"models":[..]}`, `"sttStreaming":{...}`, `"sts":{...}`; plus `{"evalSlug":..,"models":[{score,costPerTask,..}]}` panels (top 20 per eval: cyber-index, cwe-bench-aa, deepsecbench-aa, cybergym-e2e-aa) |
| media arena | `/image/leaderboard/text-to-image`, `/image/leaderboard/editing`, `/video/leaderboard/text-to-video`, `/video/leaderboard/image-to-video`, `/video/leaderboard/video-editing`, `/text-to-speech/leaderboard/provider-voice`, `/text-to-speech/leaderboard/controlled-voice`, `/music/leaderboard/instrumental`, `/music/leaderboard/vocals` | 1.0-2.0 MB | arrays of `{"formatted":{..},"values":{name,elo,ciLower,ciUpper,appearances,rank,creator:{name},releaseDate,pricePer1kImages|pricePerMinute|pricePer1mCharacters|voiceCount,openWeightsUrl,url}}` — several arrays per page (per-category variants). Selection is **validated** (`loaders._media_arena`): the array must carry the board's expected keys (`name`+`elo`+its price key) and sit in the page's arena slot — the flight main slot (`32:[[null,[…]]]`) or an object-field slot (`"initialData":[`); per-category subsets (`["<label>",[…]]`) never qualify, and the first slot in document order wins. No match ⇒ a clear error instead of a different arena |
| speech | `/speech-to-speech/arena/overview` | - | fall back to homepage boards |
| agents | `/agents/coding-agents`, `/agents/chatbots`, `/agents/search-api` | 0.6 MB | inspect with `flight.find_arrays` (see "unresolved" below) |
| eval page | `/evaluations/<slug>` | 0.35-0.93 MB | `"initialModels":[` array of chart-selected model records (same 94-key shape as model pages); size varies by eval: gpqa 19, livecodebench 5, aa-briefcase / intelligence-index / terminalbench-4-0 32 — i.e. AA's chart selection, **not** a full leaderboard |
| eval catalog | `/evaluations` (plain HTML, no RSC header) | 0.38 MB | server-rendered `<a href="/evaluations/<slug>">` cards with `<h2>/<h3>` title, description text, `<span>` tags (33 cards) |
| sitemap | `/sitemap.xml` | 6 MB | model/eval surface list; use only for diagnostics, not on the hot path |
| capability index | `/models/capabilities/<index>` (`index` = `finance-and-accounting`, `strategy-and-ops`, `legal`, `healthcare-and-medical`, `engineering`, `economics`) | 0.39-0.41 MB | `"initialModels":[` array — 26 records (20 for Healthcare & Medical) with `weightedIndex`/`headlineValue` + `subScores`; the full per-model values (`capabilities.<name>`, 221/221/221/82/220/228 of 703) ride the model-page/rich overlay |

Cache path convention: `~/.cache/aa-mcp/<name>.rsc` (env `AA_CACHE_DIR`).
Default TTL 3600 s (env `AA_CACHE_TTL`).

### Known traps

- The leaderboard payload contains **two** `"models":[` arrays: `#1` is a 3-key nav
  list (703 items `{name,releaseSlug,slug}`); the metrics array is the one whose
  items contain `intelligenceIndex`. Select by required keys, never by index.
- `intelligenceIndexCostPerTask` is a **float** on leaderboard records but a
  **dict** `{"cost": {...}, "evaluations": [...]}` on model-page/chart records.
  API/OpenAPI calls it `total_cost` (`artificial_analysis_intelligence_index_cost.cost_per_task.total_cost`).
- Effort variants are separate leaderboard rows (`claude-opus-5-5`, `-high`,
  `-xhigh`) and separate slugs; `effort.label` exists only on chart records.
- `omniscience` is roughly -70..+70 (can be negative); it is not a 0-100 index.
- `terminalBench21` (not `terminalbenchV21`), `terminalbenchHard`,
  `terminalBench40`; `hle` vs `hleDiamond`; `omniscienceNonHallucination`
  (leaderboard) vs `omniscienceHallucinationRate` (chart) = 1 - non-hallucination.
- HTML fallback: if the RSC payload has no data array, plain HTML still contains
  a rendered table (`Model|Context|Creator|Intelligence|...`). Only implement this
  for the leaderboard, and only as an error-path fallback.
- Cloudflare: a 403/503/tiny body means bot mitigation. Never retry blindly more
  than once; surface `AAFetchError` with the cache path + the hint "render the URL
  in a browser and save the HTML to <cache path>, then re-run".
- AA redeploys often; chunk paths and payload key order change. Never hardcode
  chunk URLs or build ids.

## Module APIs

### fetch.py

```python
class AAFetchError(RuntimeError): ...        # .hint: str, .url: str, .path: pathlib.Path
@dataclass(slots=True)
class Fetched:
    text: str; path: pathlib.Path; fetched_at: float; cached: bool; stale: bool

def get(url: str, name: str, *, refresh: bool = False, rsc: bool = True,
        ttl: int | None = None, min_bytes: int = 0,
        headers: Mapping[str, str] | None = None) -> Fetched
def cache_dir() -> pathlib.Path
def cache_name(name: str) -> str            # validate/normalise a cache segment (raises ValueError)
def clear_cache() -> tuple[int, int]        # (files_removed, bytes_freed)
def cache_age(name: str) -> float | None    # seconds since mtime (raises ValueError on an unsafe name)
```

- `get` writes atomically (tmp file + `os.replace`), guards concurrent writers
  with `fcntl.flock` on `<path>.lock`, single-flights concurrent same-name
  downloads in-process, and **serves stale cache with `stale=True`** instead of
  raising when the network fails and a cached copy exists (log a warning to
  stderr). Raises `AAFetchError` only when there is no usable cache.
- `name` must be one safe path segment (`[A-Za-z0-9._-]`, ≤120, no leading dot,
  no `..`, no `/`): a user-controlled slug that reaches a cache name is rejected
  with `ValueError` **before** any filesystem access (adversarial A42/A43).
- `min_bytes` guards truncated bodies (leaderboard: 200_000).
- Each entry has a `<entry>.meta.json` sidecar `{schema, written, url}`: a
  mismatched stored URL is never used, and a missing/old schema triggers one
  refetch (still usable offline / on network failure). A poisoned entry
  therefore self-heals instead of persisting until the TTL expires (A22/A26/A32).
- Bounds: `AA_MAX_BYTES` (default 48 MB) caps the decoded body (gzip bombs are
  refused, A28); `AA_HTTP_TIMEOUT` (30 s per attempt) and `AA_HTTP_DEADLINE`
  (45 s total) bound one `get()`; timeouts are not retried (only connect errors
  and 5xx, at most once) (A27).

### flight.py

```python
def payload(text: str) -> str
    # HTML -> concatenated self.__next_f.push chunks; raw RSC -> text unchanged
def find_array(payload: str, required: Iterable[str], *, min_len: int = 1,
               start: int = 0, last: bool = False) -> list[dict]
    # first (or last) JSON array whose first *dict* element contains all
    # `required` keys; raises LookupError if absent
def find_arrays(payload: str, required: Iterable[str], *, min_len: int = 1) -> list[list[dict]]
def find_arrays_at(payload: str, required: Iterable[str], *, min_len: int = 1) -> list[tuple[int, list[dict]]]
    # every match with its byte offset (media-arena selection uses the offset)
def keyed_object(payload: str, key: str) -> dict | None
def jsonld(text: str) -> list[dict]
def text_strip_tags(text: str) -> str
```

`find_array` must be robust to arrays nested inside flight rows, and must not
parse the whole 3 MB file repeatedly at O(n^2): a single left-to-right scan with
`json.JSONDecoder.raw_decode` per `[` candidate, short-circuiting on the first
match, is what ships. Anchors may be `[{` **or** `["` — model pages embed
`"initialModels":["<flight ref>", …]` and the 703-item pool those refs index
leads with a string, so the probe item is the first *dict* element (probe bounded
to a 32 KB slice / 32 elements) and the array is decoded in full only once the
probe carries every required key (audit H4). Measured: full-file scan of the
3.2 MB legacy page ≈ 0.06-0.25 s.

### catalog.py

```python
@dataclass(frozen=True, slots=True)
class Metric:
    key: str            # canonical field name in Canonical.evals / .indices / .pricing
    label: str          # short column header, <= 12 chars where possible
    kind: str           # "pct"|"index"|"elo"|"usd"|"tps"|"sec"|"tokens"|"int"|"bool"|"date"|"str"
    group: str          # "index"|"eval"|"pricing"|"speed"|"identity"|"agentic"|"media"
    desc: str           # one line, from metrics reference/OpenAPI descriptions
    better: str | None  # "high"|"low"|None

@dataclass(frozen=True, slots=True)
class Benchmark:
    key: str            # canonical metric key
    label: str          # "GPQA Diamond"
    slug: str | None    # AA eval page slug ("gpqa-diamond")
    unit: str           # "%"|"Elo"|"index"|"USD/task"|"s"|"tok/s"
    desc: str
    tags: tuple[str, ...]
    index_member: bool  # contributes to Intelligence Index v4.3.2

BENCHMARKS: dict[str, Benchmark]        # key -> Benchmark (all ~40 AA benchmarks)
METRICS: dict[str, Metric]              # every knowable field
FIELD_ALIASES: dict[str, str]           # "gpqa"/"GPQA Diamond"/"gpqa-diamond" -> key
def metric(key_or_alias: str) -> Metric | None
def benchmark(key_or_alias: str) -> Benchmark | None
def format_value(key: str, value) -> str   # "-" for None; pct*100; elo rounded; usd
def field_names() -> list[str]             # alias list for --fields help
```

`BENCHMARKS` coverage summary (verified from live data): 17 per-benchmark fields
exist in the 703-row leaderboard array (gpqa, hle, scicode, terminalBench21,
terminalBench40, terminalbenchHard, tau2, tauBanking, lcr, ifbench, critpt,
mmmuPro, gdpvalNormalized, analystAgent, apexAgents, itbenchSre,
omniscience*); ~30 more exist only on model pages / eval-page chart records
(aime25, livecodebench, hleDiamond, terminalBenchScience, frontierCode,
cweBench, cybergymE2e, deepsecBench, cyberIndex, aa3dElo, briefcaseElo,
automationBenchPartialScore, enterpriseOpsGym, gdpPdfAllPass, mlcrOverall,
harveyLab, globalMmluLiteScore, mmluPro, math500, when2call, wildguardtest,
aa3dBreakdown, automationBenchBreakdown, gdpvalBreakdown, harveyLabBreakdown,
gdpPdfBreakdown, briefcaseBreakdown, enterpriseOpsGymSuccessRateByDomain,
omniscienceAccuracy, omniscienceHallucinationRate, capabilities.* — plus the
Intelligence Index v4.3.2 member list: AA-Briefcase v1.1, GDPval-AA v2.1,
AutomationBench-AA, Terminal-Bench 4.0, SciCode, AA-LCR v1.1, AA-Omniscience,
HLE, GDP.pdf, CritPt).

### normalize.py

```python
@dataclass(slots=True)
class Model:
    slug: str; name: str; short_name: str; creator: str | None; creator_slug: str | None
    release_date: str | None; deprecated: bool; deprecated_to: str | None
    is_reasoning: bool; is_open_weights: bool; effort: str | None
    params_b: float | None; active_params_b: float | None; context_tokens: int | None
    license: str | None; license_url: str | None; weights_url: str | None
    knowledge_cutoff: str | None; size_class: str | None
    modalities_in: tuple[str, ...]; modalities_out: tuple[str, ...]
    intelligence: float | None; estimated: bool
    indices: dict[str, float | None]     # omniscience, coding, agentic, openness, capabilities.*
    evals: dict[str, float | None]       # benchmark key -> raw value (fraction or Elo)
    pricing: dict[str, float | None]     # in, out, cache_read, cache_write, cache_hit_discount, blended_*
    speed: dict[str, float | None]       # tps, ttft, ttfa, e2e, reasoning_s, out_tokens_per_task
    cost_per_task: float | None
    cost_breakdown: dict[str, float] | None
    per_eval_cost: list[dict] | None     # [{slug, weighted_cost_per_task}]
    source: str                          # "leaderboard"|"model_page"|"chart"|"legacy"
def from_leaderboard(rec: dict) -> Model
def from_chart(rec: dict) -> Model
def from_legacy(rec: dict) -> Model       # "currentModel" shape
def merge(*models: Model) -> Model        # left-to-right, non-None wins; evals/pricing/speed update
```

### select.py

```python
def filter_models(models, *, creator=None, name=None, open_weights=None,
                  reasoning=None, min_intelligence=None, max_cost_per_task=None,
                  min_speed=None, max_ttft=None, min_context=None,
                  released_after=None, exclude_deprecated=True, min_score=None,
                  score_key=None) -> list[Model]
def sort_models(models, key: str, *, desc: bool | None = None) -> list[Model]
def better_desc(key: str) -> bool                                    # True when higher is better
def value_pairs(models, *, score_key="intelligence",
                cost_key="cost_per_task") -> list[tuple[Model, float]]
    # functional score/cost pairs; only usable pairs, never mutates the inputs
def value_rank(models, *, score_key="intelligence") -> list[Model]   # NEW list of replace(m, value=v) copies
def pareto(models, *, score_key="intelligence", cost_key="cost_per_task") -> list[Model]
def search(models, query: str, limit: int = 20) -> list[Model]       # fuzzy, ranked
def resolve(models, query: str) -> Model                              # raises AmbiguousError(candidates)
class AmbiguousError(LookupError): .candidates: list[Model]
```

`better_desc(key)` is the single source of truth for ranking direction
(`False` for `catalog.metric(key).better == "low"`). `value_rank` is a
back-compatible wrapper that returns copies — callers **must not** rely on it
writing `.value` onto the objects they passed (the server computes its value
column from `value_pairs`; audit H3). `filter_models` raises `ValueError` for
non-finite numeric filters instead of silently disabling them (A2).

Fuzzy matching normalizes to `[a-z0-9]` and matches exact slug / release slug /
short name / name, then substring, ranking by intelligence desc. `resolve` raises
`AmbiguousError` (server turns it into a helpful "re-run with fuller name" error
containing up to 8 candidates) when >1 candidate remains after exact matching.

### render.py

```python
def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str
def header(total: int | None, shown: int, *, note: str = "", source: str = "",
           as_of: float | None = None) -> str
def note(lines: Sequence[str]) -> str          # trailing "— note" line(s)
def num(v, digits=1) -> str; usd(v, digits=2) -> str; pct(v, digits=1) -> str
def ctx(v) -> str                              # 128000 -> "128k", 1000000 -> "1.0M"
def ago(ts: float) -> str                      # "12m ago"
```

Header style (keep it ONE short line, no param echo):
`# 42 of 703 models · Intel/Cost frontier · data 3m ago · aa:rsc`

### loaders.py

```python
def leaderboard(refresh=False) -> list[Model]              # 703 variants (from_leaderboard)
def model(slug: str, refresh=False) -> dict[str, Model]     # slug -> Model (chart set incl. target; legacy fallback)
def provider_endpoints(slug, refresh=False) -> list[Endpoint]
def provider_board(refresh=False) -> list[Endpoint]
def home_boards(refresh=False) -> dict[str, list[dict]]     # "stt","stt_streaming","sts","eval:<slug>"
def media(board: str, refresh=False) -> list[dict]          # board in MEDIA_BOARDS
def agents(board: str, refresh=False) -> list[dict]
def open_weights_flag(row: dict) -> bool | None             # public normalizer for speech/agent/media rows
def eval_models(slug: str, refresh=False) -> list[Model]    # top-N chart set for one eval page
def eval_catalog(refresh=False) -> list[dict]               # {slug,title,description,tags}
def sitemap_paths(refresh=False) -> list[str]
```

`open_weights_flag(row)` is the single reader for the several open-weights
spellings AA ships (`openWeights`, `isOpenWeights`, `openWeightsUrl`,
`modelWeightsSourceUrl`, incl. `{"values": {…}}` wrappers); it returns `None`
when the row carries no flag at all, which is how `aa_media`'s speech boards know
to refuse the filter instead of returning an empty board (audit H5).

```python
@dataclass(slots=True)
class Endpoint:
    model_slug: str; model_name: str; host: str; host_slug: str | None
    precision: str | None; price_in: float | None; price_out: float | None
    cache_read: float | None; cache_write: float | None; cache_hit_discount: float | None
    cost_per_task: float | None; tps: float | None; ttft: float | None; e2e: float | None
    function_calling: bool; json_mode: bool; openai_compatible: bool | None
    context_tokens: int | None; intelligence: float | None; source: str
```

`MEDIA_BOARDS` keys: `text_to_image`, `image_editing`, `text_to_video`,
`image_to_video`, `video_editing`, `text_to_speech`, `text_to_speech_controlled`,
`music_instrumental`, `music_with_vocals`. `agents()` boards:
`coding_agents`, `chatbots`, `search_api` (resolve payload shape during
implementation; if a board has no usable structured data, raise a clear
`AAFetchError`/`ValueError` explaining the fallback URL rather than returning []).

## Tool surface (server.py)

Tools (all return compact markdown text). `refresh: bool = False` is accepted by
every data-reading tool: `aa_leaderboard`, `aa_model`, `aa_pareto`, `aa_compare`,
`aa_benchmark_leaderboard`, `aa_providers`, `aa_media`, `aa_agents`, `aa_search`,
`aa_raw`. `aa_benchmarks` and `aa_reference` read static/memoised registry data
and take **no** `refresh` (the benchmark catalog is refreshed by the tools that
fetch live coverage: `aa_benchmark_leaderboard`, `aa_leaderboard`, `aa_pareto`).

1. `aa_leaderboard` — rank/filter model variants.
   `mode: rank|value|frontier`, `sort`, `fields`, `top=10`, filters
   (`creator`, `name`, `open_weights`, `reasoning`, `min_intelligence`,
   `max_cost_per_task`, `min_speed`, `max_ttft`, `min_context`, `released_after`),
   `include_deprecated=False`, `refresh=False`. `mode=value` labels the ratio
   column after `sort` (e.g. `Omniscience/$`); `mode=frontier` **delegates to
   `aa_pareto`** (`x=cost_per_task`) so both surfaces share one frontier + knee
   implementation.
2. `aa_model` — one model digest. `query`, `sections` (subset of
   `identity,indexes,benchmarks,pricing,speed,cost,openness,modalities`),
   `refresh=False` (there is no `include_raw`; use `aa_raw kind=model`).
3. `aa_pareto` — the always-available trade-off frontier: `score` (any rankable
   with per-model numbers; default `intelligence`) vs `x`
   (`cost_per_task` default, `index_total_cost`, `out_tokens_per_task`,
   `time_per_task`, `context_tokens`, `params_b`, `ttft`, `price_in`, `price_out`),
   `top=15`, `creator`, `open_weights`, `min_intelligence`, `min_context`,
   `include_deprecated=False`, `include_all=False`, `refresh=False`.
   Columns `Model | Slug | Creator | <score> | <x> | <ratio>`, ordered by `x`
   ascending, with the axis labels/units, a coverage line and the knee (the last
   frontier point before the cost/score ratio passes 5× the cheapest point's).
   `index_total_cost` / `time_per_task` are model-page fields (rich overlay);
   a benchmark AA publishes only on an eval chart / homepage panel is joined onto
   the leaderboard rows by slug, and the header says so.
4. `aa_compare` — `queries` (2-12), `metrics` (`""` default rows | `all` |
   `benchmarks` | a comma list of keys/labels/aliases), `view: table|diff`,
   `compact=True`, `spec` (YAML or JSON: `models`/`metrics`/`view`/`compact`/
   `filters`), `refresh=False`. `view=diff` prints each metric's value plus its
   delta vs the first model; the reply ends with a copy-pasteable `spec:` block.
   A model missing from the rich overlay gets its own model page fetched once and
   merged; the reply is bounded (~6 kB) with an explicit truncation note.
5. `aa_benchmarks` — the search index over everything rankable
   (`catalog.rankables`): `query` (tokenised AND-match), `domain` (expands through
   `catalog.DOMAINS`), `tag`, `verbose=False`. Columns
   `Thing | Kind | Unit | Coverage | How to query` (+ `Measures` at ≤10 rows or
   `verbose`); `How to query` is the exact tool call for that thing. Unknown
   `domain`/`tag` error with the valid list; zero hits suggest the closest labels.
6. `aa_benchmark_leaderboard` — rank models on one benchmark. `benchmark`,
   `top=15`, `fields`, `creator`, `open_weights`, `min_intelligence`,
   `include_estimates=True`, `refresh=False`; auto-selects
   source (leaderboard array > eval page chart set > homepage panel) and states
   coverage honestly. Lower-is-better metrics (refusal/hallucination rates) rank
   lowest-first and the header note says `lower is better`.
7. `aa_providers` — `model` (endpoint detail) OR board filters
   (`host`, `model`, `open_weights`, `min_context`, `sort`, `top=15`),
   `fields`, `refresh=False`.
8. `aa_media` — `board`, `top=15`, `open_weights=None`, `fields`, `refresh=False`.
   Speech boards are `speech_to_text`, `speech_to_text_streaming`,
   `speech_to_speech` (aliases: `realtime_voice`, `realtime-voice`, `realtime voice`);
   their `open_weights` filter is refused when the panel carries no such flag.
9. `aa_agents` — `board`, `top=15`, `refresh=False`.
10. `aa_search` — `query`, `creator=None`, `open_weights=None`, `top=15`,
    `refresh=False` → name/creator/slug/intel/cost.
11. `aa_reference` — `topic: overview|indexes|benchmarks|pricing|speed|providers|media|fields|sources|all`.
12. `aa_raw` — `kind: model|leaderboard|providers|providers_board|media|agents|home|eval|catalog`,
    `query=None`, `fields=None`, `top=1` (capped at 5), `refresh=False` → raw JSON
    (token-expensive escape hatch). `kind=eval` validates `query` as an evaluation
    slug (rejects a model slug with the expected `gpqa-diamond` shape).

Resources (15): `aa://benchmarks` (JSON registry), `aa://rankables` (every
rankable thing as JSON), `aa://rankables.yaml` (the same index as YAML),
`aa://comparisons/spec` (a YAML template for `aa_compare spec=`), `aa://sources`
(provenance/cache), `aa://reference/metrics` (indexes+benchmarks+pricing+speed
combined), plus one per `reference.TOPICS` entry — `aa://reference/overview`,
`indexes`, `benchmarks`, `pricing`, `speed`, `providers`, `media`, `fields`,
`sources`. Each is generated from `reference.py` / `catalog.py` / the server's own
spec template, the same sources the tools serve.
Prompts (2): `best_model_for_task` (routes value/trade-off questions to
`aa_pareto`), `compare_models` (mentions `metrics=all`, `view=diff` and the
`spec=` round-trip).

Every tool must raise `ToolError`-equivalent (FastMCP: raise `ValueError`/
`RuntimeError` with actionable text) on bad input, never return a bare empty table
without explanation.

Boundary rules (server.py: `_tool` wrapper):

- arguments are validated before the tool runs: control characters and lone
  surrogates are rejected with a `ValueError` naming the argument, strings are
  capped (256 chars; 2000 for `fields`/`sections`/`metrics`) and non-finite
  floats (NaN/Infinity) are rejected for numeric filters;
- every reply is bounded: table cells are sanitized (markdown metacharacters
  neutralized, 120 chars each), oversized tables drop rows with one note, and
  every reply is capped at 200 kB;
- error text never echoes more than 60 chars of a caller-supplied value, and a
  parse/load failure names the cache file and suggests `refresh=true`
  (or `AA_OFFLINE=1` with a good copy).

## Fixtures (offline tests)

`tests/fixtures/`: `leaderboard.rsc`, `model_page_chart.rsc`,
`model_page_legacy.rsc`, `providers_model.rsc`, `providers_board.rsc`, `home.rsc`,
`media_t2i.rsc`, `media_t2v.rsc`, `media_tts.rsc`, `eval_page.rsc`,
`eval_index.html`, `agents_coding.rsc`, `eval_catalog.json`.
These are real 2026-10-14 captures; treat them as ground truth for parsing tests.
`/tmp/probe/*.rsc` additionally holds `eval_gpqa_param.rsc`,
`ev_*.rsc` (intelligence-index, aa-briefcase, terminalbench-4-0, livecodebench
eval pages), `prov_claude-opus-5-5.rsc`, `dataapi.html`, `sitemap.xml`, `sm.xml`.
