# Audit A — code quality & correctness review (read-only)

Repo: `/home/wavy/ai/aa-mcp` — public at github.com/HenryGetz/aa-mcp. A Python MCP
server (`aa-mcp`) exposing live artificialanalysis.ai benchmark data over stdio.
11 tools, 12 resources, 2 prompts. `src/aa_mcp/` is ~6.2k LOC; 226 offline tests;
CI green. Python 3.10+ target, single runtime dependency (`mcp>=2.0`).

Modules: `fetch.py` (HTTP + on-disk cache), `flight.py` (Next.js RSC flight payload
parsing), `loaders.py` (per-surface extraction), `normalize.py` (raw records →
canonical `Model` dataclass), `catalog.py` (metric/benchmark registry + value
formatters), `select.py` (filter/sort/fuzzy resolve/pareto/value), `render.py`
(markdown tables + headers), `api.py` + `source.py` (optional JSON-API backend),
`server.py` (MCPServer app: tools/resources/prompts), `reference.py` (shipped
reference text), `scripts/gen_reference_md.py`, `eval/client.py` (stdio test client).

Read `README.md` and `docs/INTERFACES.md` first for the intended design.

## Your job (read-only)

Produce a **prioritized** quality review. You may read anything and run read-only
commands (`grep`, `pytest`, `uv run python -c …`), but **do not modify any file**
except your report: `eval/reports/audit_quality.md`.

Look specifically for:

1. **Correctness bugs**: wrong arithmetic/rounding, off-by-one, sorting that puts
   missing values in the wrong place, percentage/scale confusion (fractions vs %),
   `None` vs `0` vs `-` handling, timezone/TTL mistakes in the cache, hash/memo
   invalidation that can serve stale objects, `dict.get` chains that mask data.
2. **Robustness**: any code path that can raise an unhandled exception out of a tool
   (the boundary is `server.py` `_tool`); parsers that assume a key exists; loops over
   payload data that could be quadratic on a 3 MB payload (measure the worst case);
   unbounded memory (do we ever build a 700-model list per call?); regex catastrophic
   backtracking.
3. **Concurrency**: the MCP server calls tools from a thread pool. Are module-level
   caches (`_LEADERBOARD_MEMO`, server `_models_state`) race-safe? Is the file lock in
   `fetch.py` correct (lock scope, stale lock files, no-deadlock on reentrancy)?
4. **Duplication / dead weight**: the same mapping or formatting logic implemented
   twice (e.g. server-side coverage/labels vs `catalog`), unused helpers, unused
   `__all__` entries, fields on `Model`/`Endpoint` never read anywhere, docstrings
   that contradict behaviour, `docs/INTERFACES.md` drifting from the code.
5. **Typing/API hygiene**: public functions without type hints, `Any` leaks, mutable
   default arguments, dataclasses with inconsistent defaults, functions with 10+
   positional parameters that should be a small config object (only where it clearly
   improves the code — do not propose churn).
6. **Tests**: are the 226 tests actually asserting behaviour, or are any tautological
   (mirror-implementation, asserting wiring, re-pinning incidental output)? Which
   *plausible* consumer-visible bugs are NOT covered? Name the missing cases, do not
   write the tests.
7. **Packaging/docs**: `pyproject.toml` correctness (entry point, wheel contents,
   python floor vs syntax used), anything a new user would trip over in `README.md`.

## Output format

`eval/reports/audit_quality.md`, ordered by severity:

```
## <severity: HIGH|MEDIUM|LOW> — <one-line summary>
- file:line
- what is wrong (with the evidence: code/docstring/command output)
- why it matters (concrete failure scenario a user/agent would hit)
- suggested fix (smallest correct change)
```

Then a short "what I verified as sound" list (so the orchestrator knows what not to
re-check), and a "not verified / out of scope" note. No praise, no summary padding.
