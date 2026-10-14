# Shared brief (Wave 1)

Goal: `aa-mcp` — production-quality Python MCP server over live artificialanalysis.ai
(AA) data, token-efficient by design. Repo root `/home/wavy/ai/aa-mcp`.

READ FIRST, IN FULL: `/home/wavy/ai/aa-mcp/docs/INTERFACES.md` — it freezes module
APIs, the Canonical `Model` dataclass, the metric/benchmark registry rules, data
source URLs/shapes/traps, build order, and cache conventions. It is authoritative;
do not redesign it. If something in it is factually wrong against the live site,
follow reality and report the discrepancy in your final message.

Environment: python3.14, `uv`, pytest available. Runtime dependency budget is `mcp`
SDK only (FastMCP). No pandas / requests / bs4 / lxml / yaml in `src/`. Tests may
use pytest; fixtures are real payloads in `tests/fixtures/` (see INTERFACES.md).

Rules for this wave:
- Edit only the files listed in your own task slice. Another agent owns other files
  in this repo right now; never edit a file you do not own, never reformat others.
- You MAY run focused python checks / small throwaway scripts (e.g. with `eval` or
  `uv run python -c`) against `tests/fixtures/` to confirm your own parsing works.
  Do NOT run repo-wide pytest, linters, or formatters — the orchestrator owns gates.
- Library code must never print to stdout (stdout is the MCP wire). Use `logging`
  to stderr if needed.
- Everything offline-testable: parsing, normalization, selection, rendering must be
  pure functions over fixture text/files where practical.
- Use `python3` (3.14) for ad-hoc checks; `uv run` works in the repo.
