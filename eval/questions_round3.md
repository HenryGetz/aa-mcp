# Round 3 — spot check (post-fix confirmation)

Same harness rules (`.venv/bin/python eval/client.py` only; no curl, no web search, no
reading `src/`). Write to `eval/runs/round3_<yourname>.md`.

This round deliberately re-tests things that failed in rounds 1-2, plus internal
consistency. Report *any* remaining confusion, plus a one-line verdict per question:
CLEAN / FRICTION.

1. Who leads LiveCodeBench, and where does `mistral-large-4` rank? Is the answer a full
   leaderboard or a subset — and does the tool say which?
2. Rank the models on the Legal capability index (top 5). Then give `gemini-4-argon`'s
   six capability-index scores and its AA-Briefcase Elo.
3. Resolve "opus max". Then answer: what does BFCL score look like for the frontier
   models, and does AA track MathVista?
4. For `kimi-k3`: how many endpoints exist, which is cheapest, which has the best
   time-to-first-token, what quantization does each report, and what context window
   applies? (State explicitly whether the context figure is per-endpoint or model-level.)
5. Consistency: pull `claude-opus-5-5` from `aa_leaderboard`, `aa_model` and
   `aa_compare`. Tabulate intelligence, $/task, tok/s, TTFT, context and cache-read
   price across the three tools and flag every value that differs by more than
   rounding, with your explanation of which number you would trust and why.
6. Report the exact token cost (the harness prints it) of each call you made, the
   total, and which single call was the worst value for the question it answered.
