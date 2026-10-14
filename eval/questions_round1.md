# Round 1 — agent-in-the-loop evaluation questions

Answer **only** with `aa-mcp`, driven through the stdio harness:

```bash
cd /home/wavy/ai/aa-mcp
.venv/bin/python eval/client.py tools                       # tool inventory
.venv/bin/python eval/client.py call aa_leaderboard '{"top":5}'
.venv/bin/python eval/client.py read aa://reference/metrics  # metric definitions
```

Rules for the evaluating agent:
- Use `eval/client.py` for every data lookup. Do **not** curl artificialanalysis.ai,
  do not use web search, do not read the repo source to answer a question.
- Prefer the fewest calls and the smallest outputs that answer the question.
- If a call errors, read the error text — it should tell you how to recover.
- Record every answer + the calls you used + any friction in
  `eval/runs/round1_<yourname>.md` (create it). Friction = wrong/ambiguous tool
  choice, output too large, missing field, confusing name, had to guess a slug, etc.

Questions:

1. What is the smartest model available right now, what does it cost per task, and
   what effort setting is it?
2. I run a bulk summarization pipeline. What is the cheapest model above
   Intelligence 40, and separately, which model generates output fastest?
3. Compare Claude Opus 5.5 and GPT-6 Astra on intelligence, price, speed and
   context window. Which is better value?
4. Which API provider serves DeepSeek V4.1 Flash cheapest, and at what quantization?
5. I'm building a streaming chat UI. Which models feel snappiest (lowest time to
   first token) without falling below Intelligence 45?
6. Give me an open-weights model that beats a proprietary mid-tier model on GPQA
   Diamond, and tell me its license and context window.
7. Who leads text-to-image generation right now, and what does it cost per 1000
   images?
8. What does the SciCode benchmark measure, and which models are best at it?
9. Which model leads on legal / healthcare-and-medical capability indexes?
10. How much do cached-input tokens cost on Claude Opus 5.5 vs GPT-6 Astra, and
    what's the cache discount?
11. Which models use Terminal-Bench 4.0, and who leads it?
12. What does an AA-Briefcase Elo score look like for the top 5 models?

Deliverable: `eval/runs/round1_<yourname>.md` containing, per question: the answer,
the exact harness calls (tool + args), the number of calls, and the friction notes.
