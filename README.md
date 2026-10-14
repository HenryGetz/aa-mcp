# aa-mcp

MCP server for [artificialanalysis.ai](https://artificialanalysis.ai) — live AI model
benchmarks, pricing, speed, context/parameter specs, provider endpoints and the
image/video/speech/music arenas — shaped for agents that pay per token.

No API key needed. Two interchangeable data backends, same records out:

| | `aa:rsc` (default) | `aa:api` (optional) |
|---|---|---|
| source | the site's Next.js RSC payloads | `GET /api/v2/language/models/free` |
| needs | nothing | `AA_API_KEY` (free tier is enough) |
| adds | ~50 metrics per model incl. 17 cross-model benchmarks, pricing, speed, per-model cost-per-task breakdown, provider endpoints, media boards | six Capability Indexes + Coding/Agentic indexes (not in the scrape) |
| quota | none | 100 req/24 h → cached 6 h by default |

If a key is present the API is tried first and the server falls back to scraping on
401/403 rather than failing. Every response header shows which backend answered.

## Install

One line, no clone (uv fetches and runs it for you):

```bash
uvx --from git+https://github.com/HenryGetz/aa-mcp aa-mcp
```

Or install the `aa-mcp` executable once:

```bash
uv tool install --from git+https://github.com/HenryGetz/aa-mcp aa-mcp   # -> ~/.local/bin/aa-mcp
```

Local checkout / development:

```bash
git clone <this repo> && cd aa-mcp
uv sync                      # creates .venv with the mcp SDK
uv run aa-mcp                # serve on stdio
```

Register with an MCP client (omp, Claude Code, Codex, …):

```json
{
  "mcpServers": {
    "aa": {
      "type": "stdio",
      "command": "/home/USER/.local/bin/aa-mcp",
      "timeout": 120000
    }
  }
}
```

## Tools

| tool | answers |
|---|---|
| `aa_leaderboard` | smartest / best / cheapest / fastest models, best value, Pareto frontier, budget and capability filters |
| `aa_model` | everything AA knows about one model: indices, benchmark scores, pricing incl. cache, speed, cost-per-task breakdown, license, modalities, cutoff |
| `aa_compare` | 2-6 models side by side on the metrics you care about |
| `aa_benchmarks` | the benchmark catalog: what each one measures, its unit, and how many of the tracked models have a score |
| `aa_benchmark_leaderboard` | who leads a given benchmark (full leaderboard when AA publishes one, otherwise AA's chart set — stated in the header) |
| `aa_providers` | which provider serves a model, at what price, quantization, TTFT and feature support; or the whole provider × model board |
| `aa_media` | text-to-image, image-editing, text-to-video, image-to-video, video-editing, TTS, music, speech-to-text, realtime voice |
| `aa_agents` | AA's coding-agent, chatbot and search-API leaderboards |
| `aa_search` | resolve a fuzzy model name to real names + slugs (use it before guessing) |
| `aa_reference` | metric definitions, index composition, field names, provenance |
| `aa_raw` | raw JSON escape hatch for anything the tables do not cover |

Resources: `aa://reference/metrics`, `aa://reference/fields`, `aa://benchmarks`,
`aa://sources`. Prompts: `best_model_for_task`, `compare_models`.

### Token discipline

- Tables, not JSON — rounded values, one header line, no argument echo.
- Default 10-15 rows; every table tool accepts `top` and `fields`.
- Long-form documentation lives in resources/reference, so it never costs context
  unless the agent asks for it.
- `aa_raw` warns when used.

Example (real output):

```text
<!-- filled from the live smoke test -->
```

## Environment

| variable | default | meaning |
|---|---|---|
| `AA_API_KEY` | unset | AA JSON API key; enables the `aa:api` backend |
| `AA_SOURCE` | `auto` | `auto` \| `api` \| `rsc` — backend selection |
| `AA_CACHE_DIR` | `~/.cache/aa-mcp` | payload cache |
| `AA_CACHE_TTL` | `3600` | scrape cache TTL (seconds) |
| `AA_API_TTL` | `21600` | API cache TTL (seconds) |
| `AA_OFFLINE` | unset | `1` — serve from cache only, never touch the network |
| `AA_BASE_URL` | `https://artificialanalysis.ai` | override host (tests/mirrors) |
| `AA_LOG_LEVEL` | `WARNING` | stderr log level |

## Behaviour worth knowing

- **Freshness is labelled.** Payloads are cached for an hour; the header shows the
  age and says `stale` when a network failure forced a cached copy. Pass
  `refresh=true` for freshly released models.
- **Coverage is labelled.** AA scores a benchmark on a subset of models; tables state
  how many of the 700 tracked variants carry a value, and warn when a filter dropped
  rows that simply have no measurement.
- **Cost per task is cache-aware** and must not be recomputed from $/1M rates; raw
  rates are separate fields.
- Effort variants (`-low` … `-xhigh`) are separate rows — always name the effort.
- AA does not track MathVista, DocVQA or BFCL; the server says so instead of inventing.

## Troubleshooting

- **Cloudflare / bot challenge** (403/503 or a tiny body): the error names the exact
  cache path. Render the URL in a browser, save the HTML there, re-run — or set
  `AA_OFFLINE=1` to keep working from the last good capture.
- **Site structure change**: the error says which array was missing; the parsers live
  in `src/aa_mcp/loaders.py` (`flight.py` finds the arrays).
- **AA redeploys often** — never hardcode chunk or build-id URLs; the client always
  re-parses freshly fetched payloads.

## Development

```bash
uv run pytest -q                 # offline: fixtures in tests/fixtures (real payloads)
.venv/bin/python eval/client.py tools
.venv/bin/python eval/client.py call aa_leaderboard '{"top":5}'
.venv/bin/python eval/client.py bench      # per-call chars/tokens report
```

`docs/REFERENCE.md` is generated from `src/aa_mcp/reference.py`
(`scripts/gen_reference_md.py`); `docs/INTERFACES.md` documents the internal data
model; `eval/reports/fidelity.md` records an independent field-by-field audit of the
parsers against raw payloads.
