# Round 4 — comparison-parity evaluation (the user's acceptance bar)

The user's bar: *"so high-quality that there is no question that is impossible for an
AI agent to answer when comparing models specifically with artificial analysis."*

Drive the server only through the stdio harness:

```bash
cd /home/wavy/ai/aa-mcp
.venv/bin/python eval/client.py tools
.venv/bin/python eval/client.py call <tool> '<json args>'
.venv/bin/python eval/client.py read aa://rankables.yaml | aa://comparisons/spec | aa://benchmarks
```

Rules: `eval/client.py` only; no curl to artificialanalysis.ai; no web search; do not
read `src/` to answer a question; do not modify `src/`, `tests/`, `docs/` — write only
`eval/runs/round4_<yourname>.md`.

1. **Comparison-page parity (pairwise).** Reproduce what
   `https://artificialanalysis.ai/models/comparisons/mimo-v2-6-pro-vs-deepseek-v4-1-flash`
   shows: compare those two models on every benchmark/metric you can get, and state who
   wins each domain (coding, science, agentic/tool-use, cost, speed, context).
2. **Comparison-page parity (multi-model).** For
   `mimo-v2-6-pro, deepseek-v4-1-flash, gpt-6-luna-xhigh, muse-wonder-full` (the user's
   own URL), produce the full metric matrix with deltas, then answer: best coding,
   best security/cyber, cheapest per task, and which one you would pick for a
   cost-sensitive agentic coding workload — with the numbers.
3. **Pareto line.** Give the models on the Intelligence-vs-Cost-per-task Pareto line
   with the knee. Then do the same for *Intelligence vs cost to run the whole
   Intelligence Index* and *Intelligence vs output tokens per task*. Are the knees the
   same model? Explain any difference in one sentence each.
4. **Domain search.** Using only the search tool, find the right thing to rank for:
   (a) security/cyber work, (b) speech/voice, (c) legal work, (d) 3D. For two of them,
   actually run the ranking and report the top 3.
5. **Spec round-trip.** Build a comparison of your choice as a YAML spec, run it, then
   re-run the spec echoed in the output and confirm the tables are identical. Report
   the spec text.
6. **The bar.** Try to construct a model-comparison question that the server *cannot*
   answer with the data AA publishes. If you find one, report the exact question, the
   calls you tried, and what was missing. If you cannot find one, say what the closest
   call was and what the server said about coverage/limits.

Deliverable: `eval/runs/round4_<yourname>.md` with per-item answers, exact calls, call
counts, harness token costs, a one-line CLEAN/FRICTION verdict per item, and a closing
list of anything you would still change.
