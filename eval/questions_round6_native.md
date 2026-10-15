# Round 6 — native MCP test (tools in the agent's own tool list)

Goal: verify `aa-mcp` works when it is exposed as a **native MCP server to an agent**
(not only through the `eval/client.py` stdio harness), and measure token cost from the
agent's side.

## Protocol

1. First, report whether you can see `aa_*` MCP tools in your own tool list (e.g.
   `aa_leaderboard`, `aa_model`, `aa_compare`, `aa_pareto`, `aa_search`, `aa_benchmarks`,
   `aa_providers`, `aa_media`, `aa_agents`, `aa_reference`, `aa_raw`). State **exactly**
   what you see. This is the primary result of this round.
2. If they are present: answer the questions below using **only** those native tools.
   Do not use `eval/client.py`, curl, web search, or the source code.
3. If they are **not** present: say so explicitly (that is a valid finding — it means the
   registration in `~/.omp/agent/mcp.json` is not reaching subagents), then answer the
   questions through the harness `.venv/bin/python eval/client.py call <tool> '<json>'`
   and say which path you used.
4. For every question report: the exact calls (tool + arguments), the number of calls, the
   **approximate size of each tool result** (characters, or tokens ≈ chars/4), and whether
   the tool you picked first was the right one.

## Questions — set A (comparison and trade-offs)

A1. Which model is the best value above Intelligence 45, and where is the knee of the
    intelligence-vs-cost frontier? Give the frontier models.
A2. Compare `mimo-v2-6-pro` and `deepseek-v4-1-flash` on cyber metrics, coding metrics and
    cost, with deltas. Which wins each, and what does the answer cost you in tokens?
A3. Which API provider serves `kimi-k3` cheapest, at what price, and which has the best
    time-to-first-token?

## Questions — set B (search and benchmarks)

B1. You need a benchmark for security work. Find the right one through search (you do not
    know its key), then give the top 3 models on it.
B2. Give the top 5 models on the Legal capability index, and say how you found the metric.
B3. Compare the four models in this URL's query string on every metric AA publishes:
    `mimo-v2-6-pro, deepseek-v4-1-flash, gpt-6-luna-xhigh, muse-wonder-full`. Report the
    number of metric rows, the missing-data summary, and the token cost of the answer.

## Deliverable

`eval/runs/round6_<yourname>.md` containing: the native-tool finding (step 1), per-question
answers with call logs and result sizes, a token-cost table, and a blunt friction list —
especially: any output you found too large, any tool you had to guess at, any answer you
could not get, and whether the tool descriptions were enough to route you correctly on the
first try.
