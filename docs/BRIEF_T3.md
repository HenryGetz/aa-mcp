# T3 brief — MCP server + tools (integration point)

Owner of: `src/aa_mcp/server.py` (and nothing else). You may create
`src/aa_mcp/tools_render.py` **only** if `server.py` exceeds ~700 lines; prefer one file.

Read first: `docs/INTERFACES.md` (frozen APIs + **ADDENDUM: SDK is mcp 2.x, `MCPServer`**),
`docs/BRIEF_WAVE1.md`, and skim `docs/BRIEF_T1.md` + `docs/BRIEF_T2.md` for the
module APIs you consume. `fetch`, `flight`, `catalog`, `normalize`, `select`,
`render`, `loaders` are written by other agents against those frozen signatures —
import them, never edit them.

## Entry point

```python
def main() -> None:  # console script target (pyproject: aa-mcp = aa_mcp.server:main)
    ...
if __name__ == "__main__":
    main()
```

`main()` configures `logging` to **stderr** only (level from `AA_LOG_LEVEL`,
default WARNING) and calls `srv.run("stdio")`. Never write to stdout except the
MCP protocol.

## Non-negotiable output rules (token efficiency is a feature)

- Every tool returns compact **markdown text**. No JSON blobs except `aa_raw`.
- Never echo the arguments back. One header line, then the table, then at most one
  footnote line.
- Header shape: `# <n>/<total> <noun> · <what was selected> · <freshness> · aa:rsc`
  e.g. `# 10/700 models · intelligence, active only · 4m ago · aa:rsc`.
  Use `render.header(...)`; freshness from `fetch.cache_age`/`Fetched.fetched_at`
  (a `stale` cache must be labelled `stale: <age>`).
- Tables: default `top=10..15`, never more than 25 rows unless the caller asks.
  Columns: keep ≤ 7 unless `fields` says otherwise. Use `catalog.format_value` /
  `render.*` for every number (no raw floats, no `None`).
- `fields: str = ""` (comma list of friendly names) is supported by every
  table-returning tool; when empty use a sensible default column set.
- When a filter yields 0 rows, say **why** in one line (e.g. `# no models match
  min_intelligence=80 and max_cost_per_task=0.5 — drop one filter`).
- Ambiguity: catch `select.AmbiguousError` and raise `ValueError` whose message is a
  3-column candidate table (name / creator / slug) + the hint to pass a fuller name.
  Never guess silently.
- Missing/unknown benchmark/metric name -> `ValueError` listing the closest 5
  `catalog` matches.
- Any `AAFetchError` propagates with its `.hint` appended (cache path + browser
  fallback), so the agent can self-recover.
- Round-trippable objects: whenever you print a model, include its `slug` (agents
  need it for the next call).

## Tools (exact names + signatures)

```python
aa_leaderboard(mode: str = "rank", sort: str = "intelligence", fields: str = "",
               top: int = 10, creator: str = "", name: str = "",
               open_weights: bool | None = None, reasoning: bool | None = None,
               min_intelligence: float | None = None, max_cost_per_task: float | None = None,
               min_speed: float | None = None, max_ttft: float | None = None,
               min_context: int | None = None, released_after: str = "",
               include_deprecated: bool = False, refresh: bool = False) -> str
```
`mode`: `rank` (default), `value` (intelligence per $/task), `frontier` (Pareto
intelligence-vs-cost; note the "knee" in the footnote when useful).
`sort`: any `catalog.METRICS` key or alias (`intelligence`, `cost_per_task`, `tps`,
`ttft`, `e2e`, `context_tokens`, `price_in`, `price_out`, `params_b`,
`release_date`, `openness`, any benchmark key).
Default columns: Model, Creator, Intel, $/Task, tok/s, TTFT, Ctx (drop Creator when
`top > 15` to save tokens). `mode=value` adds `Intel/$`.

```python
aa_model(query: str, sections: str = "", refresh: bool = False) -> str
```
One model digest. Resolve via `loaders.leaderboard()` + `select.resolve`, then
`loaders.model(slug)` for the rich record and `normalize.merge` with the leaderboard
record (model-page/chart data wins). Default sections:
`identity,indexes,benchmarks,pricing,speed`; available also `cost,openness,modalities,all`.
Layout: facts line (creator · released · params · context · modalities · reasoning
effort · open-weights+license · deprecated), `## Indices`, `## Benchmarks` (only
non-null, one compact table of `Eval | Score`, Elo rows labelled), `## Pricing`
(in/out/cache-read/cache-write $/1M + $/task), `## Speed` (tok/s, TTFT, E2E,
tokens/task), `## Cost per task` (breakdown + per-eval weighted cost when present).
Include `# <name> · <creator> · aa.<slug>` header and the model slug in a footnote.

```python
aa_compare(queries: list[str], metrics: str = "", compact: bool = True,
           refresh: bool = False) -> str
```
2-6 models; metric rows = `metrics` or a default set (Intelligence, $/task, in/out
$/1M, tok/s, TTFT, context, release date, params, open-weights, reasoning effort).
`compact=True` keeps the 6 rows that matter. Columns = model short names; add the
slug row only when two names collide.

```python
aa_benchmarks(query: str = "", verbose: bool = False) -> str
```
Catalog of AA benchmarks: `Benchmark | Slug | Unit | Coverage | Measures`.
Coverage = how many of the 700 tracked model variants have a value (computed from
`loaders.leaderboard()` for leaderboard-family fields, else
`model page only`/`chart set only`). `verbose=True` appends description + tags per
row. `query` filters by substring over key/label/tags.

```python
aa_benchmark_leaderboard(benchmark: str, top: int = 15, fields: str = "",
                         creator: str = "", open_weights: bool | None = None,
                         min_intelligence: float | None = None,
                         include_estimates: bool = True, refresh: bool = False) -> str
```
Rank models on one benchmark. Source selection, in order:
1. field present in the 700-row leaderboard -> full ranking;
2. else `loaders.eval_models(eval_slug)` chart set (AA's own top-N, ~32 models);
3. else homepage `eval:<slug>` panel (top 20) for the cyber/security boards.
State the source + coverage in the header footnote, e.g.
`# GPQA Diamond · 512/700 models scored (leaderboard)` or
`# AA-Briefcase · AA chart set (32 models) — not a full leaderboard`.
Columns: Model, Creator, Score (+ Intel, $/Task when the source provides them).

```python
aa_providers(model: str = "", host: str = "", top: int = 15,
             sort: str = "cost_per_task", fields: str = "",
             open_weights: bool | None = None, min_context: int | None = None,
             refresh: bool = False) -> str
```
- `model` non-empty -> `loaders.provider_endpoints(slug)` (precision, per-endpoint
  in/out/cache-read $/1M + discount, $/task, tok/s, TTFT, E2E, FnCall, JSON).
- else -> `loaders.provider_board()` filtered by `host`/`open_weights`/`min_context`
  and sorted by `sort` (`cost_per_task`, `price_in`, `price_out`, `tps`, `ttft`,
  `intelligence`, `context_tokens`).
At least one of `model`/`host` should be given; if both empty, return the cheapest
N globally and say so in the header.

```python
aa_media(board: str, top: int = 15, fields: str = "", open_weights: bool | None = None,
         refresh: bool = False) -> str
```
`board` = any `loaders.MEDIA_BOARDS` key **or** the speech/homepage boards
(`speech_to_text`, `speech_to_text_streaming`, `speech_to_speech`) resolved through
`loaders.home_boards()`. Unknown board -> `ValueError` listing valid keys.
Columns: Rank, Model, Creator, Elo (+95% CI when `fields` asks), Appearances,
Price (with unit), Release. Speech: WER % (lower better) or STS index.

```python
aa_agents(board: str = "coding_agents", top: int = 15, refresh: bool = False) -> str
```
AA agent leaderboards (`coding_agents`, `chatbots`, `search_api`; see
`loaders.AGENT_BOARDS`). If `loaders.agents()` raises for a board, let the error
through unchanged.

```python
aa_search(query: str = "", creator: str = "", open_weights: bool | None = None,
          top: int = 15, refresh: bool = False) -> str
```
Cheap name->slug resolver: `Model | Creator | Intel | $/Task | slug`. Always include
slug. Used before every other call when the name is uncertain.

```python
aa_reference(topic: str = "overview") -> str
```
Static text from `catalog` (no network): topics `overview` (what this server has,
source provenance, freshness semantics, tool routing table, the "trust these facts"
rules: cost-per-task is cache-aware and must not be recomputed, TTFT != throughput,
effort variants are separate rows, estimates marked `*`, `-` = not measured, AA does
not track MathVista/DocVQA/BFCL), `indexes`, `benchmarks`, `pricing`, `speed`,
`providers`, `media`, `fields` (alias list), `sources`. Unknown topic -> list topics.

```python
aa_raw(kind: str, query: str = "", fields: str = "", top: int = 1,
       refresh: bool = False) -> str
```
Escape hatch returning JSON (`json.dumps(..., indent=1, default=str)`), filtered by
`fields`. `kind`: `model`, `leaderboard`, `providers`, `providers_board`, `media`,
`agents`, `home`, `eval`, `catalog`. Cap `top` at 5 and warn in the header that this
is token-expensive; prefer the table tools.

## Resources (must not load data at import time)

- `aa://reference/metrics` (markdown, the metric/eval definitions + methodology notes)
- `aa://reference/fields` (plain list of field aliases)
- `aa://benchmarks` (JSON catalog from `catalog.BENCHMARKS`)
- `aa://sources` (URLs, cache paths, TTL, offline mode, Cloudflare recovery)

## Prompts

- `best_model_for_task(task: str, budget: str = "", open_weights: str = "")` ->
  instructs the model to call `aa_leaderboard` (+ `aa_search` first if names are
  uncertain) and answer with a recommendation + 2 alternates + the knee of the curve.
- `compare_models(models: str)` -> instructs `aa_compare` (+ `aa_providers` when price
  or provider choice matters).

## Acceptance (self-check; do not run repo-wide gates)

- `.venv/bin/python -c "import aa_mcp.server"` succeeds with no stdout output.
- `.venv/bin/python eval/client.py tools` lists all 11 tools with non-empty one-line
  descriptions and correct params (the harness already exists at `eval/client.py`).
- `.venv/bin/python eval/client.py call aa_leaderboard '{"top":3}'` returns a
  markdown table with a header line and no parameter echo.
- `.venv/bin/python eval/client.py call aa_model '{"query":"claude-opus-5-5","sections":"indexes"}'`
  returns only identity+indices sections.
- Error paths produce actionable messages: unknown benchmark, ambiguous model name,
  unknown media board, fetch failure with cache fallback hint.
- No tool returns anything on stdout other than the MCP protocol; logging only stderr.

Report: tools implemented, exact harness commands run + observed output sizes
(chars/tokens), anything in the frozen interfaces you had to work around.
