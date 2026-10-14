# Round 5 — final acceptance check (the user's own list)

Same harness rules (`.venv/bin/python eval/client.py` only; no curl, no web search, no
reading `src/`; write only `eval/runs/round5_<yourname>.md`).

## Part A — the user's named items must each be findable AND usable

For each item below, (1) find it through the search tool without knowing its internal
key, (2) say what the tool tells you to call, (3) actually make that call and report the
top 3 (or the single-model value when it is a per-model metric):

1. Artificial Analysis Intelligence Index
2. Speed
3. Cost per Task
4. Artificial Analysis Cyber Index
5. AA-3D
6. Provider Voice Arena Preference Elo
7. Artificial Analysis Speech to Speech Index
8. Terminal-Bench 4.0
9. Terminal-Bench-Science 0.1
10. FrontierCode 1.1
11. ITBench-AA
12. AA-Omniscience Index
13. Openness Index
14. Output Tokens per Intelligence Index Task
15. Intelligence Index vs. Output Tokens per Intelligence Index Task
16. Intelligence Index vs. Cost to Run Artificial Analysis Intelligence Index

Report a table: `item | found via | how-to-query hint | call made | top result`.
Flag anything that needed guessing, a second call to discover the right argument, or that
returned an empty/misleading table.

## Part B — the user's comparison URLs

17. Reproduce `.../models/comparisons/mimo-v2-6-pro-vs-deepseek-v4-1-flash` and state the
    winner per domain (coding, science, agentic, security, cost, speed, context).
18. Reproduce `.../models/comparisons?compare=mimo-v2-6-pro,deepseek-v4-1-flash,gpt-6-luna-xhigh,muse-wonder-full`
    with every metric, deltas, and an explicit note of which metrics are missing for
    which model.
19. Pareto: give the Intelligence-vs-Cost-per-task frontier with the knee, then the same
    for the whole-index-cost axis and the output-tokens axis.

## Part C — the bar

20. Try hard to find a model-comparison question the server cannot answer from AA's
    published data. Report the exact question, the calls you tried, and what the server
    said (quote its coverage wording). If you find none, say what the closest call was.

Deliverable: per-item results, exact calls, call counts, harness token costs, a
CLEAN/FRICTION verdict per item, and a closing list of the top 3 things you would still
change in the server.
