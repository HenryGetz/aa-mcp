# Round 2 — agent-in-the-loop evaluation (harder)

Same harness rules as round 1 (`eval/client.py` only, no curl, no web search).
Write answers + friction to `eval/runs/round2_<yourname>.md`.

Questions:

1. "what about opus max?" — resolve what model that actually is and give its
   intelligence, price and speed. (Deliberately ambiguous.)
2. Which model was released most recently, and what is its intelligence score?
3. Who leads **AA-Briefcase**, and by how many Elo points over second place? Does AA
   consider it a full leaderboard or a chart subset?
4. How does MathVista look for the current frontier models?
5. Estimate the daily cost of running 5M input tokens + 1M output tokens per day on
   the three best-value frontier models (use raw $/1M rates, state the assumption).
6. Which providers serve Kimi K3, what does each charge, and which one has the best
   time-to-first-token?
7. Compare the top 3 of the video-editing board against the top 3 of text-to-video:
   which is the better pick for editing fan footage, and on what basis?
8. Who leads AA's coding agent leaderboard, what model powers it, and what does it
   cost per task?
9. For the best intelligence-per-dollar model above Intelligence 30, which provider
   is cheapest and what context window does that endpoint offer?
10. I have a 400k-token document corpus and cache-heavy re-ingestion. Which models
    support ≥400k context, and among them which has the cheapest cache-read price?
11. What is the difference between the Intelligence Index and AA-Briefcase, and is
    AA-Briefcase included in the index?
12. My team must choose between three options: (a) smartest overall, (b) best value
    above Intelligence 45, (c) fastest above Intelligence 45. Name each pick with
    its numbers in one table.

Deliverable: `eval/runs/round2_<yourname>.md` with, per question: the answer, exact
calls used, call count, and friction notes.
