# Round 7 — "super easy comparison, no API key" (cold start)

You are a **new** agent. You know only this: a local MCP server called `aa-mcp` exposes
live artificialanalysis.ai data, and you drive it through its stdio client:

```bash
cd /home/wavy/ai/aa-mcp
.venv/bin/python eval/client.py tools                 # tool names + parameters
.venv/bin/python eval/client.py schema aa_compare    # one tool's full schema
.venv/bin/python eval/client.py call <tool> '<json>'  # make a call
.venv/bin/python eval/client.py read <uri>            # resources, if you need them
```

Rules: `AA_API_KEY` is **unset** (verify that yourself and report it). Use only
`eval/client.py`; no curl to artificialanalysis.ai, no web search, and **do not read
`src/` or `docs/`** — the whole point is to find out whether the tool surface alone is
enough. Write only `eval/runs/round7_cold.md`.

## The questions (answer them as a user would want, with numbers)

1. I'm choosing between Claude Opus 5.5 and GPT-6 Astra for a long-context agentic coding
   assistant. Which should I pick, and why? Give me the numbers behind the call.
2. Is Muse Wonder Full actually better than Claude Sonnet 5.5, or just newer?
3. Compare the three cheapest models above Intelligence 40 on coding benchmarks.
4. Best value model for high-volume classification, and what's the runner-up?
5. My team does security work — compare the top models on cyber benchmarks.
6. One table comparing `mimo-v2-6-pro`, `deepseek-v4-1-flash`, `gpt-6-luna-xhigh`,
   `muse-wonder-full`, plus which has the best price/performance.

## What to report

- For each question: the answer (with slugs), the exact calls, the **number of calls**, the
  harness-reported token cost of each call, and whether the first tool you chose was right.
- A "was it easy?" verdict per question: `1 call, obvious` / `needed N calls` /
  `had to guess X` / `could not answer`.
- Every moment you had to guess a parameter name, a slug, a metric key or a board name —
  and what the error message told you (quote it).
- Every answer where data was missing, contradictory between two tools, or where you could
  not tell whether something was "not published" versus "you asked wrongly".
- Anything you could not do **because there is no API key** — and whether the tools said so
  clearly.
- A closing list of the top 3 things that would make comparison *easier* or *better*.
