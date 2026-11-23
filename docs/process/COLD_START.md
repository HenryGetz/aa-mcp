# Cold start: what an `aa-mcp` / `aa-mcp-cli` call pays before it does any work

Measured 2026-11-23 on the dev box (Python 3.12.14, `mcp` 2.x, load average ~28
from other work on the machine — entries are the **minimum of 5 interleaved
runs**, old and new alternating, so both sides saw the same noise).
`old` = HEAD `c5795ef`; `new` = the deferred-SDK change.

## Where the 3.6 s went

`python -X importtime -c "import aa_mcp.cli"`, cumulative self-costs:

| module | cum | why |
|---|---|---|
| `mcp` (whole SDK) | 3.81 s | `mcp/__init__.py` pulls the **client** (`mcp.client.*`, `httpx2`, `http.cookiejar`) and `mcp.server.mcpserver` pulls the **HTTP server** stack (`starlette`, `uvicorn`, `sse_starlette`) — neither is used by a stdio session |
| `mcp_types._types` / `_v2025_11_25` / `_v2026_07_28` | 1.55 s | generated pydantic protocol models built at import |
| `pydantic` | ~0.4 s | schema engine behind them |
| `aa_mcp.server` | 0.36 s | our module + the 12 `@srv.tool` registrations (`FuncMetadata` pydantic models per tool) |
| `urllib.request` (via `aa_mcp.fetch`) | 0.10–0.15 s | http.client, ssl, socket, email — only a live fetch needs it |
| everything else (`loaders`, `catalog`, `normalize`, stdlib) | ~0.2 s | the actual data layer |

## What changed

- `server.py` registers through a plain local `registry`; `build_server()` replays
  the registrations onto `MCPServer` and is the **only** place `mcp` is imported.
  `server.srv` resolves lazily through module `__getattr__`.
- Tool failures raise `aa_mcp.server.ToolError`; `build_server()` wraps each tool
  so it still reaches the client as the SDK's `ToolError` (`is_error` content,
  same `Error executing tool <name>: <message>` text as before).
- `cli.py` dispatches `call`/`list`/`read`/`prompts`/`prompt` on the plain
  records; only `schema` builds the server, because it prints the SDK's own
  `inputSchema`.
- `fetch._download` imports `urllib.request` locally (warm-cache and offline
  calls never touch the network).

## Before / after (best of 5, warm OS cache)

| path | before | after | |
|---|---|---|---|
| `import aa_mcp.cli` (in-process) | 2.67 s | 0.16 s | 17× |
| `aa-mcp-cli call aa_reference '{"topic":"overview"}'` | 3.24 s | 0.31 s | 10× |
| `aa-mcp-cli call aa_leaderboard '{"top":3}'` (warm cache) | 4.31 s | 0.67 s | 6.4× |
| `aa-mcp --help` | 3.78 s | 0.38 s | 10× |
| `aa-mcp-cli list` | 3.3 s | 0.42 s | 8× |
| `aa-mcp-cli schema aa_pareto` | 3.4 s | 3.4 s | unchanged by design (needs the SDK's schema) |

`aa_mcp.server` import falls from 3.92 s to 0.26 s for the CLI/tool path.

## What remains

A real MCP session (`aa-mcp`, which is what the lazy-tool proxy respawns per
call) still pays the whole `mcp` import before the handshake — **~3.6 s on the
loaded box these numbers came from, ~2.0 s when it is idle** (the CLI's own
0.2–0.3 s disappears under it) — because:

- importing any `mcp.*` submodule runs `mcp/__init__.py`, which imports the
  client (`mcp.client.session*`, `httpx2`, `http.cookiejar`);
- `mcp.server.mcpserver.__init__` imports `mcp.server.streamable_http`, pulling
  `starlette`/`uvicorn`/`sse_starlette`;
- `mcp_types` builds its pydantic protocol models at import (1.55 s).

None of that is ours to defer: the SDK does not offer a stdio-only entry point.
That is also why a lazy-tool `invoke_proxy_tool` round-trip measures 2.3–4.7 s
across loads before and after this change — the per-invoke server respawn is
pure SDK import, so the win there is zero until the proxy holds a session open.
The only remaining lever for the proxy path is to stop respawning the server per
call (a long-lived session), which is a client-side decision, not a server one.
