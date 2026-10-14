# Audit B — adversarial robustness testing (read-only, evidence-driven)

Repo: `/home/wavy/ai/aa-mcp`. You are the hostile user. Your job is to **break the
MCP server** and report exactly how, with repro commands. Do not fix anything and do
not modify files under `src/`, `tests/`, `docs/` — write only your report
`eval/reports/adversarial.md` and scratch files under `/tmp`.

## How to drive it

```bash
cd /home/wavy/ai/aa-mcp
.venv/bin/python eval/client.py tools
.venv/bin/python eval/client.py call <tool> '<json args>'      # exits 1 on tool error
.venv/bin/python eval/client.py read <uri>
.venv/bin/python eval/client.py --env KEY=VALUE call …          # env override for the server
```

Environment knobs the server honours: `AA_CACHE_DIR`, `AA_CACHE_TTL`, `AA_API_TTL`,
`AA_OFFLINE`, `AA_BASE_URL`, `AA_API_KEY`, `AA_SOURCE`, `AA_RICH_TTL`, `AA_LOG_LEVEL`.

## Attack list (do all of these; add your own)

1. **Degenerate inputs on every tool**: empty string, whitespace, `"0"`, very long
   string (10k chars), unicode/emoji/combining marks, SQL/JSON fragments
   (`'; DROP TABLE`, `{"a":1}`), path fragments (`../../etc/passwd`, `aa://sources`),
   newlines inside args. `top` = 0, 1, -1, 10**9, `"abc"`, 1e9 as float; negative
   `min_intelligence`/`max_cost_per_task`/`min_context`; `min_intelligence=NaN`;
   `fields` empty / unknown / duplicated / 200 entries; `queries` with 1 element, 6
   elements, 20 elements, duplicates, empty strings; `metrics` garbage.
2. **Ambiguity and non-existence**: a model name that matches nothing, a name that
   matches many, a slug that 404s, a benchmark name that does not exist, a board that
   does not exist, a resource URI that does not exist, `aa_raw` with every `kind` plus
   a bogus one.
3. **Failure injection** (this is the important part):
   - `AA_OFFLINE=1` with a cold cache (`AA_CACHE_DIR=/tmp/adv-$$`): does every tool
     degrade gracefully with an actionable message, or do some crash?
   - Unwritable cache dir (create it, `chmod 500`): does the server still serve, and
     with what error?
   - **Corrupt cache**: write `tests/fixtures/leaderboard.rsc`'s first 1000 bytes into
     `<cache>/leaderboard.rsc` (truncated payload) and into `rich_dataset.json`, then
     call tools. Truncated/garbled payloads must produce an actionable error, never a
     traceback, never silently wrong output.
   - **Wrong content**: serve a well-formed HTML page (no RSC) as the leaderboard via
     `AA_BASE_URL` pointing at `python3 -m http.server` in a directory with a file
     named `leaderboards/models`… if the path shape makes that hard, instead write a
     10-line `http.server` script that answers any request with chosen bytes. Verify:
     (a) HTML fallback if implemented, (b) error path otherwise, (c) no crash.
   - **Slow/hanging server**: `AA_BASE_URL` pointing at a socket that accepts and never
     replies (a python one-liner with `socket.listen`, no accept). Measure how long a
     tool takes to fail and what the message is (timeout must be bounded).
   - **Redirect/dead host**: `AA_BASE_URL=http://127.0.0.1:1` (connection refused).
4. **Concurrency**: 8 parallel `aa_leaderboard`/`aa_model` calls with a cold cache in a
   private `AA_CACHE_DIR` — any corrupted cache file, exception, partial write, or
   duplicate-fetch storm? (Check the cache dir afterwards for suspiciously many files
   or a `.tmp` left behind.)
5. **Cache poisoning / staleness**: touch a cache file to 10 hours old and confirm the
   header reports staleness; set `AA_CACHE_TTL=0` and confirm refresh behaviour; set
   `AA_CACHE_TTL=-5` and see what happens.
6. **Payload tampering at the data layer**: copy `tests/fixtures/media_t2i.rsc`,
   mutate it (delete the array the parser looks for; change a numeric to a string;
   insert a huge string) and call `loaders.parse_media`/`parse_leaderboard` through
   `AA_BASE_URL` + a static HTTP server. Report which mutations produce: clean error,
   degraded output (empty table without explanation), or crash.
7. **Resource/DoS sanity**: time the worst case for each tool with a warm cache and
   report anything above ~1.5 s; measure memory for `aa_raw kind=leaderboard top=5`
   and `aa_benchmarks` (they may build large intermediates).
8. **Injection surface**: can any scraped string reach output in a form that would
   mislead an LLM consumer — e.g. a model named `Ignore previous instructions…`
   (results from AA are live, so instead check how the server escapes/truncates long
   or newline-containing values: mutate a fixture's `name` to contain newlines, `|`,
   backticks and instruction-like text, then look at the rendered table). Report
   whether markdown-table structure can be broken by data, and whether `aa_raw` output
   is bounded.

## Output format

`eval/reports/adversarial.md`:

```
## A<n> — <short attack name> — <RESULT: clean | degraded | crash | hang | wrong data>
- repro: <exact command(s)>
- observed: <exact output, trimmed to the relevant lines>
- expected: <what a max-quality server should do>
- severity: HIGH|MEDIUM|LOW
```

End with: a table of every attack x result, the 3 worst findings, and an explicit
list of attacks you could not execute (and why). Include timings for anything that
took over a second. Paste raw output — no paraphrase.
