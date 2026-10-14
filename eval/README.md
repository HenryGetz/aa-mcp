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

## Reports

| file | what it is |
|---|---|
| `reports/fidelity.md` | independent field-by-field audit of the parsers against raw payloads (~85 KB, per-field verdict tables) |
| `runs/round1_a.md`, `round1_b.md` | round-1 agent reports (call logs + friction) |
| `runs/round2_a.md`, `round2_b.md` | round-2 agent reports |
| `runs/round3_q.md` | round-3 confirmation report |

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

## Reproducing the measurements quoted in the README

```bash
.venv/bin/python eval/client.py bench        # ≈4.3k tokens for 13 calls, ≈330/call
uv run pytest -q                             # 226 offline tests, no network
```
