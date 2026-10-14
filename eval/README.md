# Evaluating and iterating on aa-mcp

The server was developed against its own users: agents answered realistic
Artificial-Analysis questions through the real MCP stdio server and reported
friction, which drove the fix rounds.

## Harness

`eval/client.py` is a thin stdio MCP client (spawns the server exactly as an MCP
client does):

```bash
.venv/bin/python eval/client.py tools                  # tool inventory + params
.venv/bin/python eval/client.py schema                 # full input schemas
.venv/bin/python eval/client.py call aa_model '{"query":"gpt-6-luna"}'
.venv/bin/python eval/client.py read aa://reference/indexes
.venv/bin/python eval/client.py prompts
.venv/bin/python eval/client.py bench                  # 13-call panel, tokens per call
AA_MCP_CMD=/path/to/aa-mcp .venv/bin/python eval/client.py tools   # test an installed build
```

Every `call`/`bench` appends an NDJSON record (tool, args, latency, chars, estimated
tokens, error flag) to `eval/runs/live.ndjson` — that log is the measurement source
for token efficiency.

## Question sets

- `questions_round1.md` — everyday questions across the whole surface (12).
- `questions_round2.md` — adversarial: ambiguous names, missing data, cross-source
  contradictions, cost/cache reasoning (12).
- `questions_round3.md` — post-fix confirmation + cross-tool consistency (6).
- `questions_round4.md` — comparison parity: the site's comparison pages, Pareto views,
  domain search, YAML spec round-trip, and an attempt to find an unanswerable question (6).
- `questions_round5.md` — final acceptance: the user's own list of 16 named benchmarks/views
  plus comparison-URL parity and the completeness bar (20).

## Reports

| file | what it is |
|---|---|
| `reports/fidelity.md` | independent field-by-field audit of the parsers against raw payloads (~85 KB, per-field verdict tables) |
| `reports/audit_quality.md` | read-only code review: 20 prioritized findings with file:line, evidence and smallest fix |
| `reports/adversarial.md` | hostile-usage report: 44 attacks (degenerate input, corrupt cache, gzip bomb, hanging upstream, concurrency, payload tampering) with repro commands and severities |
| `runs/round1_a.md`, `round1_b.md` | round-1 agent reports (call logs + friction) |
| `runs/round2_a.md`, `round2_b.md` | round-2 agent reports |
| `runs/round3_q.md` | round-3 confirmation report |
| `runs/round4_e.md` | round-4 comparison-parity report |
| `runs/round5_f.md` | round-5 final acceptance report |

## Issues found and fixed through this loop

| round | finding | fix |
|---|---|---|
| fidelity | provider endpoints reported `cost_per_task = None` for every live endpoint (flat `{"total": …}` shape unhandled) | one cost-shape helper for all three payload shapes + flat-shape fixture |
| fidelity | `release_date` null for all 700 leaderboard rows | join the payload's sibling release array (exact, then longest release-slug prefix) — 677/700 populated |
| fidelity | `enterpriseOpsGym` + 8 other benchmarks catalogued but unreachable | extended the chart-key maps, added an audited reachability table |
| 1 | `aa_model` crashed with a raw traceback on several model pages (flight reference strings inside the dataset array) | reference resolution/skip in every parser; `ValueError` instead of `AttributeError`; tool boundary converts any surprise into a readable `ToolError` |
| 1 | `aa_agents` crashed on every board (`creator` is a string) | shape-tolerant row extraction + recursive ref resolution; no `$…` literal can reach output |
| 1 | explicit `fields=` columns vanished when all-null | identity columns always render; requested columns render with `-`; only default columns are trimmed |
| 1 | `sort`/`fields` silently ignored unknown names | alias resolution (capability/Elo/pricing/speed) + closest-match error |
| 1-2 | capability indexes unrankable | rich 699-model dataset discovery gives cross-model capability rankings without a key |
| 2 | `aa_media fields=` dropped the model name | identity columns are never user-selectable |
| 2 | header counts read as matches but showed rows | headers now state shown/matching/tracked |
| 2 | `board=video` silently resolved to `text_to_video` | ambiguous aliases removed; unknown board errors with the valid list |
| 3 | `aa_search "opus max"` returned nothing | tokenized AND matching in `select.search`/`filter_models` |
| 3 | `aa_benchmarks {"query":"BFCL"}` returned fuzzy near-matches | explicit "AA does not track …" answers for 11 untracked benchmarks |
| 3 | coverage labelled `chart set only` where 343 models are scored | live coverage labels driven by each benchmark's best surface |
| quality audit | `aa_media` speech boards raised `NameError`; lower-is-better benchmarks ranked backwards; `value_rank` mutated shared models; the flight scan missed arrays starting with a reference; speech `open_weights` read a non-existent key | all fixed + regression tests (`tests/test_server.py`, `tests/test_flight.py`) |
| adversarial | path traversal via `aa_raw kind=eval` wrote outside the cache dir; a 2 MB scraped name produced a ~500k-token reply; unbounded gzip decode; 121 s hang on a dead upstream; cache trusted blindly; 8 parallel cold calls fetched 2-4× | cache-name sanitisation + path containment; per-cell/response caps and markdown escaping; `AA_MAX_BYTES` decode cap; bounded timeouts without retry storms; cache metadata + plausibility validation; in-process single-flight |
| 4 | comparison returned blank cells with no explanation and could not see chart-set scores (cyber/CWE) | per-cell missing footer, per-model coverage line, chart/panel score join in `aa_compare` and `aa_model` |
| 5 | `Rankable.how` hints could be wrong (cyber index pointed at a call that errors); breakdown benchmarks raised `TypeError`; media/speech models were uncomparable | hints audited + static consistency test; honest error for container benchmarks; arena models resolvable and comparable |

## Reproducing the measurements quoted in the README

```bash
.venv/bin/python eval/client.py bench        # per-call token cost for the whole surface
.venv/bin/python scripts/surface_sweep.py    # ~220 live calls, every tool × every enum
uv run pytest -q                             # offline tests, no network
uvx ruff check .                             # lint (CI runs this)
```
