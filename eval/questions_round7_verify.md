# Round 7 — independent correctness cross-check (no API key)

You are a verifier. Another agent is separately judging *usability*; your job is
**correctness**: prove or disprove that the MCP's comparison output matches the raw
artificialanalysis.ai data, with **no API key** involved.

You may use `curl` to fetch raw payloads yourself (that is the point) and the MCP through
its harness. Do **not** edit anything except your report `eval/runs/round7_verify.md`.

## Method

1. `AA_API_KEY` must be unset for the MCP calls (verify and report).
2. Fetch the raw sources yourself with
   `curl -sfL -H "User-Agent: Mozilla/5.0" --compressed -H "RSC: 1" <url> -o /tmp/r7/<name>`
   for: `/leaderboards/models`, `/models/<slug>` (3 models), `/models/<slug>/providers`
   (2 models), one media arena page, and `/evaluations/<slug>` for one benchmark.
3. Parse the raw JSON yourself (independent code — do not import `aa_mcp`) and extract, for
   **6 models spanning different classes** (a frontier model, an effort variant, an
   open-weights model, a cheap model, a deprecated model, a model with sparse data):
   `intelligenceIndex`, `intelligenceIndexIsEstimated`, `price1mInputTokens`,
   `price1mOutputTokens`, `cacheHitPrice`, `contextWindowTokens`, `medianOutputTokensPerSecond`,
   `medianTimeToFirstTokenSeconds`, `intelligenceIndexCostPerTask`, `isOpenWeights`,
   `deprecated`, plus `gpqa`, `hle`, `scicode`, `terminalBench21`, `terminalBench40`,
   `tauBanking`, `lcr`, `ifbench`, `critpt`, `mmmuPro`, `gdpvalNormalized`.
4. Get the same values through the MCP (`aa_compare` with `metrics=all`, `aa_model`,
   `aa_leaderboard sort=...`, `aa_benchmark_leaderboard`, `aa_providers`, `aa_media`).
5. Compare value by value. Report a table per model: `field | raw | MCP | verdict`, and a
   mismatch list (or an explicit "no mismatches").
6. Specifically check the **comparison path**: does `aa_compare` on the 6 models return the
   same numbers as the raw payload for every field both know about? Does `aa_compare
   metrics=all` include the chart-set/panel metrics (e.g. cyber, AA-Briefcase, AIME) for
   models the raw leaderboard does not carry? Does anything come back silently blank that
   the raw payload does have?
7. Check provider prices/quantization for the 2 models: raw `hostModels` vs `aa_providers`.
8. Check one media arena: raw `elo` for the top 3 vs `aa_media` output.

## Report

`eval/runs/round7_verify.md`: method + commands, per-model verdict tables, the mismatch list
(or explicit absence), the comparison-path findings, and a final section
"what a no-key user cannot verify / cannot get" (be concrete: which fields require an API
key, and whether the MCP says so).
