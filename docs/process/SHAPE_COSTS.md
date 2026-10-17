# Shape costs: skill vs MCP server vs bundled-CLI-with-skill

Fixed-cost and operational analysis for "should `aa-mcp` be a **skill**, an **MCP
server**, or a **skill + bundled CLI**?" — measured on this machine on 2026-10-16.
Everything here is independent of asking an agent questions; the *actively-used*
head-to-head (answer quality, tokens per answer) is measured by the sibling A/B run.

Token estimates are `chars ÷ 4`, the convention `eval/client.py` itself uses
(`_tokens()` = `math.ceil(len(text)/4)`). Byte counts come from `wc -c`; the
per-tool numbers come from the real MCP wire payload, not a re-serialisation.

Machine: `wavy@linux 6.8.0-142-generic`, omp `18.11.0`, Claude Code `2.1.73`,
codex-cli `0.99.0`. Repo at `/home/wavy/ai/aa-mcp`.

---

## 1. Fixed context cost per shape

"Fixed cost" = what the model pays **before it does anything**: the tool
definitions, resource listings and prompt listings a client injects at session
start, or the skill index entry a client injects at session start.

### 1.1 MCP server — the full tool list as the client sees it

`eval/client.py schema` pretty-prints with `indent=1` and renames `input_schema`;
that is **not** what goes over the wire. The wire payload was dumped with a
throwaway script (`/tmp/wire_dump.py`) that calls `list_tools()` and serialises
each `Tool` with `model_dump(by_alias=True, exclude_none=True)` — i.e. exactly the
JSON-RPC result an MCP client receives:

```console
$ cd /home/wavy/ai/aa-mcp && timeout 120 .venv/bin/python eval/client.py schema > /tmp/aa_schema.json
$ wc -c /tmp/aa_schema.json
24620 /tmp/aa_schema.json

$ timeout 120 .venv/bin/python eval/client.py tools > /tmp/aa_tools.txt
$ wc -c /tmp/aa_tools.txt
1880 /tmp/aa_tools.txt

$ timeout 120 .venv/bin/python /tmp/wire_dump.py
tools: 12
wire bytes: 21385
wire tokens (chars/4): 5346.25
resources: 15 bytes: 2386 tok: 596.5
prompts: 2 bytes: 341 tok: 85.25
```

| MCP surface | bytes | tokens (`÷4`) | when paid |
|---|---:|---:|---|
| `tools/list` (12 tools, name + title + description + inputSchema) | **21,385** | **5,346** | every session start |
| `resources/list` (15 resources, uri + name + mime only) | 2,386 | 597 | only if the client injects resource listings |
| `prompts/list` (2 prompts, name + description) | 341 | 85 | only if the client injects prompt listings |
| all three | 24,112 | 6,028 | |
| `eval/client.py schema` output (pretty, harness form) | 24,620 | 6,155 | n/a — harness display only |
| `eval/client.py tools` output (one-liner form) | 1,880 | 470 | n/a — harness display only |

**Per-tool breakdown** (wire bytes, from `/tmp/wire_tools.json`):

| tool | bytes | tokens | title | description | inputSchema |
|---|---:|---:|---:|---:|---:|
| `aa_compare` | 3,504 | 876 | 14 | 2,854 | 496 |
| `aa_leaderboard` | 3,503 | 876 | 17 | 1,984 | 1,377 |
| `aa_pareto` | 2,552 | 638 | 25 | 1,599 | 823 |
| `aa_providers` | 2,054 | 514 | 18 | 1,279 | 663 |
| `aa_media` | 1,866 | 466 | 18 | 1,249 | 511 |
| `aa_benchmark_leaderboard` | 1,771 | 443 | 21 | 927 | 726 |
| `aa_search` | 1,483 | 371 | 17 | 980 | 390 |
| `aa_benchmarks` | 1,467 | 367 | 31 | 1,048 | 291 |
| `aa_model` | 1,047 | 262 | 12 | 659 | 302 |
| `aa_raw` | 1,030 | 258 | 21 | 527 | 399 |
| `aa_agents` | 564 | 141 | 18 | 233 | 244 |
| `aa_reference` | 531 | 133 | 22 | 309 | 127 |
| **TOTAL** | **21,372** | **5,343** | 234 | **13,648** | 6,349 |

Two things dominate, and neither is the schema:

* **Docstrings are 64 % of the fixed cost** (13,648 of 21,385 bytes). `aa_compare`
  and `aa_leaderboard` alone are 7,007 bytes / 1,752 tok — a third of the list.
  The `Args:` blocks in `src/aa_mcp/server.py` are what an agent pays for at every
  session start, whether or not it ever calls the tool.
* **Input schemas are 30 %** (6,349 bytes). `aa_leaderboard`'s schema is the
  largest (1,377 bytes) because it exposes 17 typed filter parameters.

*Caveat, verified:* the wire payload is what the *server* sends. How much of it
reaches the model is client policy. omp registers MCP tools as top-level custom
tools named `mcp__<server>_<tool>` (evidence: session logs on this machine such as
`…/602.mcp__win_ghidra_mcp_decompile_function.log`, and omp's own
`omp://mcp-runtime-lifecycle.md`: *"Connected manager tools become enabled
immediately"* → *"wrapped and added to the runtime tool registry with names like
`mcp__<server>_<tool>`"*). omp's system prompt puts those definitions either in the
provider-native `tools` array or inlined in the prompt (`src/system-prompt.ts:886`
`const toolListMode = !inlineToolDescriptors && nativeTools`); either way the same
tokens are paid. **Unverified:** omp's `mcp-runtime-lifecycle.md` also says *"tools
may be mounted under `xd://` rather than exposed as top-level function definitions"*,
and this machine's `~/.omp/agent/config.yml` carries `tools.virtualize: [xd://lsp,
xd://dap, xd://mcp]` — but `virtualize` appears nowhere in omp 18.11.0's `src/` or
`dist/cli.js`, so a "virtualized, one-line-per-tool" MCP listing was **not**
observed and should not be assumed.

Resources and prompts are **not** injected into omp's system prompt: omp resolves
MCP-advertised custom schemes lazily through the `read` tool
(`src/tools/read.ts:1730` *"Handle native OMP URLs and custom-scheme resources
advertised by MCP servers"*). So in omp the MCP fixed cost is the 5,346 tok of
tools; the 597 + 85 tok listings are a Claude-Code-style client's extra.

### 1.2 Skill — what is paid before the body is read

```console
$ cd /home/wavy/ai/aa-mcp && wc -c skills/aa-mcp/SKILL.md
7095 skills/aa-mcp/SKILL.md
```

| artifact | bytes | tokens | when paid |
|---|---:|---:|---|
| `skills/aa-mcp/SKILL.md` full body | 7,095 | **1,774** | only when the agent reads `skill://aa-mcp` |
| YAML front-matter (whole block) | 357 | 89 | — |
| `description:` value alone | 331 | 83 | session start (naive: full description) |
| name | 6 | 2 | session start |

The "if it lists skills at all" question has a concrete answer on this machine:
**omp compresses the description** before putting it in the prompt —
`$OMP/src/extensibility/skill-descriptions.ts:32` `MAX_COMPRESSED_CHARS = 160;
MAX_COMPRESSED_WORDS = 12`, cached in `~/.omp/agent/skill-descriptions.db`, with a
100-char fallback preview (`previewSkillDescription`, `MAX_PREVIEW_CHARS = 100`).
So omp's real per-skill fixed cost is **≤160 chars ≈ ≤40 tok**, not the 331-char
description. **Codex CLI is explicit about the same shape**: its binary contains the
literal prompt text *"### Available skills … Each entry includes a name, description,
and file path so you can open the source for full instructions when using a specific
skill"* (`core/src/skills/loader.rs`), and `~/.codex/skills/.system/` is populated on
this machine — so Codex pays name + description + path, then reads the body on
demand.

### 1.3 CLI-with-bundled-script shape (the zip)

Extracted to `/tmp` only:

```console
$ cd /tmp && mkdir aazip && cd aazip && unzip -o -q /home/wavy/ai/aa-mcp/artificial-analysis-skill.zip
$ find . -type f -not -path './__MACOSX/*' -exec wc -c {} \;
 7203 ./artificial-analysis-skill/SKILL.md
 7439 ./artificial-analysis-skill/references/metrics.md
39101 ./artificial-analysis-skill/scripts/aa.py
 6148 ./artificial-analysis-skill/.DS_Store

$ cd /tmp/aazip/artificial-analysis-skill && timeout 60 python3 scripts/aa.py --help > /tmp/aa_cli_help.txt
$ wc -c /tmp/aa_cli_help.txt
962 /tmp/aa_cli_help.txt            # 240 tok
$ timeout 60 python3 scripts/aa.py leaderboard --help | wc -c
1534                                # 384 tok
$ timeout 60 python3 scripts/aa.py model --help | wc -c
141                                 # 35 tok
$ timeout 60 python3 scripts/aa.py search --help | wc -c
382                                 # 96 tok
```

| artifact | bytes | tokens | when paid |
|---|---:|---:|---|
| bundled `SKILL.md` full | 7,203 | **1,801** | when the agent reads it |
| bundled `SKILL.md` front-matter | 878 | 220 | — |
| bundled `SKILL.md` `description:` alone | 839 | 210 | session start |
| `scripts/aa.py --help` | 962 | 240 | when the agent runs `--help` |
| `scripts/aa.py` source | 39,101 | — | never in context (it is executed, not read) |

Note the bundled `description` is **839 chars — 2.5× the repo skill's 331** — so the
zip's skill is the most expensive of the three to merely *list*, and it is the one
that gets compressed by omp (839 → ≤160 chars).

### 1.4 Comparison

| shape | available but unused | actively used (static floor) |
|---|---:|---:|
| **MCP server** | **5,346 tok** (tools) [+597 +85 in some clients] | 5,346 + per-call result |
| **Pure skill** | **≤40 tok** in omp (≤160-char compressed blurb); 83 tok naive; 210 tok for the zip's verbose description | ≤40 + 1,774 (body) + per-answer text |
| **Skill + bundled CLI** | **≤40 tok** (omp-compressed; 210 naive) — the 39 KB script costs nothing until run | ≤40 + 1,801 (SKILL.md) + 240 (`--help`) + stdout |

**Cheapest to have available but unused: the skill shape, by ~130×** (≤40 vs 5,346
tok) — and that gap is structural, not tunable: the MCP server's own docstrings are
two thirds of its bill and are paid at every session start regardless of use.
**Cheapest when actively used** is the sibling A/B run's to determine; the static
floor here says the skill pays ~1,800 tok once to learn the conventions and then
only answer text, while MCP pays 5,346 every session plus answer text.

---

## 2. Install / wiring matrix

Legend: **[V]** verified on this machine in this session; **[D]** read from
vendor docs/source but not exercised here; **[U]** unverified (client not installed
here).

### 2.1 MCP registration

| client | where it goes | command | reload | |
|---|---|---|---|---|
| **omp** | `~/.omp/agent/mcp.json` (user, per profile) or `<repo>/.omp/mcp.json` (project); `<repo>/.omp/.mcp.json` and `~/.omp/agent/.mcp.json` also accepted | edit JSON by hand: `{"mcpServers":{"aa":{"type":"stdio","command":"/home/wavy/.local/bin/aa-mcp","timeout":180000,"enabled":true}}}` | `/mcp reload` (MCP-only; `/reload` does **not** refresh skills) | **[V]** file exists with the `aa` entry; paths + `/mcp reload` from `docs/SKILLS.md` and `omp://mcp-runtime-lifecycle.md` **[D]** |
| **Claude Code** | `claude mcp add -s local` → `~/.claude.json` (per project); `-s user` → `~/.claude.json` (global); `-s project` → `<repo>/.mcp.json` (committed) | `claude mcp add aa -s user -- /home/USER/.local/bin/aa-mcp` | restart the session | **[V]** `claude mcp add --help` shows `-s local\|user\|project` (default `local`); `~/.claude.json` exists and has a top-level `mcpServers` key (holds `excel`). Exact scope→path mapping **[D]** |
| **Codex CLI** | `~/.codex/config.toml`, table `[mcp_servers.<name>]` | `codex mcp add aa -- /home/USER/.local/bin/aa-mcp` (writes the TOML) | new session | **[V]** `codex mcp add --help` and `codex mcp list`; `~/.codex/config.toml` carries 8 `[mcp_servers.*]` tables on this machine |
| **Cursor** | `~/.cursor/mcp.json` (global) or `<repo>/.cursor/mcp.json` (project) | edit JSON | reload window | **[U]** — Cursor is not installed here (`~/.cursor` absent); paths from docs |
| **plain chat / LLM API, no tool support** | — | **not installable.** An MCP server cannot be reached: there is no `tools/list`, no function calling. Only the *skill text* can be pasted. | — | **[V]** structural |

### 2.2 Skill installation

| client | where it goes | command | reload | |
|---|---|---|---|---|
| **omp** | `~/.agents/skills/<name>/SKILL.md` (user, all projects) or `<repo>/.agents/skills/<name>/SKILL.md` (project); native alt `~/.omp/agent/skills/`, `<repo>/.omp/skills/` (**description required**); also `~/.claude/skills`, `~/.codex/skills` | `mkdir -p .agents/skills && cp -r skills/aa-mcp .agents/skills/aa-mcp`, or `npx skills add <owner>/<repo> -s aa-mcp -g` | **restart** — discovery is a start-of-session scan, no watcher, no registry | **[V]** `~/.agents/skills/aa-mcp` exists; `<repo>/.agents/skills/aa-mcp` is a symlink to `../../skills/aa-mcp`; `~/.claude/skills/aa-mcp` → `../../.agents/skills/aa-mcp`. Full provider table + restart evidence in `docs/process/OMP_SKILLS_PATH.md` |
| **Claude Code** | `~/.claude/skills/<name>/SKILL.md` (user) or `<repo>/.claude/skills/` (project) | copy the skill dir, or `npx skills add … -g` (the CLI creates the `.claude` symlink itself) | new session | **[V]** `~/.claude/skills/` exists and contains symlinks (`aa-mcp`, `developing-with-streamlit`) |
| **Codex CLI** | `~/.codex/skills/<name>/SKILL.md` | copy the skill dir | new session | **[V]** `~/.codex/skills/.system/{skill-installer,skill-creator}/SKILL.md` present; binary carries the skills loader + prompt text |
| **Cursor** | `.cursor/rules/*.mdc` (rules, not Agent Skills) | copy/convert | reload | **[U]** — not installed here |
| **plain chat / LLM API, no tool support** | the conversation | paste `SKILL.md` (or its front-matter + relevant sections) into the system prompt | — | **[V]** structural — this is the *only* shape that works with zero tool support |

### 2.3 Friction ranking (fewest steps, least to go wrong)

1. **Skill into an existing skills root** — one `cp -r` (or `npx skills add`), no
   config file, no daemon, no restart of anything but the session. Works with a
   plain chat client by pasting the text.
2. **MCP into omp / Codex / Claude** — one CLI command or one JSON/TOML block; but
   it starts a **process**, has a startup timeout, and needs a reload
   (`/mcp reload` in omp) plus a restart in Claude/Codex.
3. **Skill + bundled CLI** — same as (1) plus the script must be executable and
   findable; the bundled `aa.py` is stdlib-only (`argparse, json, os, re,
   subprocess, sys, time`) so there is no `pip install` step, which is its one real
   advantage.
4. **MCP in a plain chat/API client** — impossible; you must fall back to pasting
   text (i.e. to shape 1).

---

## 3. Runtime / ops properties

| property | MCP server (this repo) | Skill + bundled CLI (`aa.py`) | Pure skill (no data path) |
|---|---|---|---|
| **deterministic output** | Yes — one code path per question; ties broken by a named secondary key and footnoted; every response header reads `aa:rsc` (`server.py` `_source_key()`) | Mostly — but it re-derives tables itself, so rounding/column choices can differ from the MCP for the same question | n/a — the model writes the answer; determinism is the model's, not the tool's |
| **caching across questions** | Yes: one shared on-disk cache in `~/.cache/aa-mcp` (`AA_CACHE_DIR`), `_DEFAULT_TTL = 3600` s (`fetch.py:48`), `AA_CACHE_TTL` override, plus an in-process decoded-text LRU memo keyed on `(path, mtime_ns, size)` and a single-flight lock so concurrent calls share one download. **Every tool and every question reuse it.** | Yes, but a **separate** cache: `CACHE = "/tmp/aa_cache"`, `TTL = 3600` (`scripts/aa.py:48-52`). Two shapes ⇒ two caches ⇒ the same payload downloaded twice, and `/tmp` is wiped on reboot. | None — no data path at all |
| **offline mode** | `AA_OFFLINE=1` → cache-only; a missing entry raises `AAFetchError` with a hint (`fetch.py:166`, `get()` docstring). CI runs the whole suite this way. | No offline switch (no `AA_OFFLINE` in `aa.py`) | n/a |
| **rate-limit / bot mitigation** | Handled once, centrally: browser UA, `Accept-Encoding: gzip`, `RSC: 1`; a body shorter than `min_bytes` is treated as bot mitigation (`_TooSmall`) and retried once after `_BACKOFF = 0.7` s; `_is_transient` gates the retry; a hard deadline (`_DEADLINE = 45` s) bounds the whole attempt; on failure a stale cache is served with `stale=True` rather than erroring. | Hand-rolled: `min_bytes=500_000` heuristic, own UA string (`…Macintosh…`, different from the repo's Linux UA), no backoff, no deadline, no stale-serve | n/a |
| **secrets handling** | **None required — verified.** Grepping `src/` for key/secret/auth usage returns exactly one hit, and it is a warning that the keyed backend is gone: `server.py:428` *"One-time notice that `AA_API_KEY`/`AA_SOURCE` are no longer read."* The only env vars read are `AA_BASE_URL`, `AA_CACHE_DIR`, `AA_CACHE_TTL`, `AA_LOG_LEVEL`, `AA_MAX_BYTES`, `AA_OFFLINE`, `AA_RICH_TTL` — no credential. `fetch.py` sends no `Authorization` header (a `headers=` param exists for callers, but the server passes none). | None required — same keyless RSC source | None |
| **failure when AA changes its payload** | One place to fix: the parse layer. `loaders.py` has an explicit `_validate()`/`_implausible()` guard and a `_parse_error` → `AAFetchError` path with a hint, so a shape change surfaces as a legible error, and the 523-test fixture suite (30 fixtures, 17 MB, incl. `rich_dataset.json.gz`, `leaderboard.rsc`, `model_page_legacy.rsc`) catches it offline. | Same breakage, second implementation: `aa.py`'s own `find_array`/`extract_keyed_object`/`rsc_payload` must be patched separately, with no fixtures and no tests shipped in the zip. | n/a |
| **testability / CI offline** | Yes. `.github/workflows/ci.yml:20` runs *"Tests (offline, fixture-backed)"* with `AA_OFFLINE: "1"`; 523 test functions across 8 modules. | No tests, no fixtures, no CI in the zip. | n/a |
| **blast radius of a bug** | One shared data layer: a fix or a regression lands once, for every consumer and every question. | N implementations of the same parse/format logic: a bug in the bundled CLI affects only its users but is invisible to the repo's tests, and vice versa. | The model's judgement is the whole system: a wrong answer has no tool to blame. |

---

## 4. Divergence risk

The repo today has **one** data layer. `src/aa_mcp/` is 13,366 lines; the modules a
second implementation would have to duplicate are:

| module | lines | bytes | what it owns |
|---|---:|---:|---|
| `loaders.py` | 2,703 | 105,361 | RSC parsing, model/provider/media/agent/Speech adapters, `_validate`/`_implausible` plausibility guards |
| `catalog.py` | 1,854 | 91,781 | the benchmark/rankable catalog (what is rankable, units, coverage) |
| `normalize.py` | 789 | 32,199 | field normalisation to the internal `Model` shape |
| `fetch.py` | 646 | 21,477 | HTTP, cache, TTL, provenance sidecar, retry/backoff, offline, single-flight |
| `flight.py` | 456 | 16,447 | Next.js RSC flight-payload decoding |
| `select.py` | 357 | 11,527 | fuzzy name→slug resolution + ambiguity errors |
| `render.py` | 156 | 4,648 | table rendering primitives |
| **total** | **6,961** | **283,440** | |

`loaders.py` alone is **103 top-level functions + 3 classes in 2,703 lines** — a
single module, so a single place to change.

**The bundled CLI already is the duplication.** `artificial-analysis-skill.zip`'s
`scripts/aa.py` is **824 lines / 39 top-level functions / 39,101 bytes** and
re-implements, in parallel and in miniature, the whole spine: `fetch`/`fresh`/
`cached` (fetch.py), `rsc_payload`/`find_array`/`extract_keyed_object` (flight.py),
`load_models`/`load_model_page` (loaders.py), `norm`/`find_models`/`resolve`
(select.py), `f1`/`f0`/`pct`/`money`/`num`/`yn`/`md_table` (render.py), plus
`cmd_*` renderers. It is a **separate lineage**, not an import of this repo: its
user agent is the macOS one while `fetch.py` uses the Linux one, and it caches to
`/tmp/aa_cache` while the MCP caches to `~/.cache/aa-mcp`. It has no `catalog.py`
equivalent, no `_validate`/`_implausible` guards, no provenance sidecar, no
offline switch, and ships no tests or fixtures.

Quantified: **~824 lines (12 % of the repo's data layer) already duplicated**, and
it is a *stale* snapshot — the zip is dated 2026-09-06, the repo's loaders were
touched 2026-10-16. When AA changes a payload shape:

* **today** — one patch to `loaders.py`/`flight.py`, guarded by 523 tests and 30
  fixtures, and every consumer (all 12 tools) is fixed at once;
* **with a bundled CLI as a second data path** — the same patch must be found and
  reapplied in `aa.py`'s own parsers, with no fixtures to prove it, and any
  divergence between the two is invisible until a user notices the two shapes
  disagree on the same question. The failure mode is *two answers to one question*,
  which is worse than either being wrong alone.

---

## 5. Where each shape structurally wins

**Only a skill can:**

* carry **conventions** ("always state the source and coverage; never present an
  estimate as measured") that no schema can encode;
* carry **judgment about the data** — which index means what, when a difference is
  noise, when a lower-is-better metric inverts the reading;
* express **multi-step procedures** ("resolve the name, then compare, then check
  providers, then report") and *when to stop*;
* tell the agent to **refuse to answer** — "AA does not publish this; say so rather
  than interpolating";
* **steer tool choice** ("call `aa_search` first whenever a name is uncertain"),
  which is exactly what `skills/aa-mcp/SKILL.md` already does;
* be **edited by a human in one minute** without touching code or tests;
* reach a **client with no tool support at all** (paste the text);
* cost ~40 tok to sit unused.

**Only an MCP server can:**

* expose **typed arguments** — 17 filter params on `aa_leaderboard` with a schema
  the client validates, instead of string parsing;
* **cache** across questions (one 1 h disk cache in `~/.cache/aa-mcp`, shared by
  all 12 tools and all sessions);
* produce **deterministic, bounded tables** — same input, same bytes, tie-break
  rules footnoted;
* be **discovered by a client** — it appears in the tool list automatically, with
  no user action;
* carry **honest coverage labels** (`aa:rsc`, "AA estimate", `—` for no data) as
  part of the response contract, not as advice the model may skip;
* be **tested offline in CI** (523 tests, 30 fixtures, `AA_OFFLINE=1`), and fixed
  in one place when AA moves;
* survive **one server, many clients** — omp, Claude Code, Codex, Cursor all get
  the identical implementation.

---

## 6. Recommendation for this capability

**Data access → MCP server (keep it); conventions → skill (keep it); and ship a
thin CLI over the same tool functions so skill-only clients get the verified data
without a second implementation.**

The numbers behind it:

* **Fixed cost:** MCP costs **5,346 tok every session** to sit unused (64 % of it
  docstrings, 30 % schemas); the skill costs **≤40 tok** (omp compresses the
  description to ≤160 chars) and **1,774 tok** only when read. A skill-only
  deployment is ~130× cheaper to keep available. That is the honest case for the
  skill shape.
* **But the skill cannot fetch.** Pure-skill means the model pastes numbers it
  recalls, which is exactly the failure this repo exists to prevent. The only
  data-bearing shape a skill-only client can use today is the zip's `aa.py`, and
  that is **824 lines of duplicate parser** on a **stale snapshot**, caching to
  `/tmp/aa_cache`, with **no tests** and **no offline mode** — i.e. a second answer
  to every question the MCP already answers.
* **The CLI is cheap because the tools are already plain functions.** Every
  `@srv.tool` function is an ordinary Python function returning a markdown string,
  callable directly — verified:

  ```console
  $ cd /home/wavy/ai/aa-mcp && timeout 60 .venv/bin/python -c "
  from aa_mcp.server import aa_leaderboard, ToolError
  try:
      aa_leaderboard(bogus=1)
  except ToolError as e:
      print('ToolError OK ->', str(e)[:60])"
  ToolError OK -> aa_leaderboard failed: TypeError: aa_leaderboard() got an unexpe
  ```

  So `python -m aa_mcp.cli <tool> '<json>'` is a **dispatch table over 12 existing
  functions + a `ToolError` → exit-code catch — roughly 60–90 lines, no new parsing,
  no new cache, no new dependency** (stdlib `argparse`/`json` only; the package
  already depends on `mcp`). It buys the skill/plain-chat shape the same
  `~/.cache/aa-mcp` cache, the same `_validate` guards, the same `aa:rsc` coverage
  labels and the same 523 offline tests — one data layer, two front doors.

Two sentences: **Keep the MCP server as the data layer and the skill as the
conventions layer — they cost 5,346 tok and ≤40 tok respectively to have available,
and they do different jobs — but do not let a skill-shaped client reach AA through
the zip's parallel `aa.py`.** Add a ~60–90-line `python -m aa_mcp.cli <tool>
'<json>'` shim that calls the existing tool functions and point
`skills/aa-mcp/SKILL.md` at it, so the cheap-to-list shape and the verified-data
shape become the same shape, and delete `artificial-analysis-skill.zip`'s duplicate
parser rather than maintaining it.

---

### Bottom line

| question | answer |
|---|---|
| **fixed-context token cost per shape** | MCP **5,346 tok** (tools; +597 resources, +85 prompts in clients that inject those listings); pure skill **≤40 tok** in omp / 83 naive / 210 for the zip's description, +1,774 when the body is read; skill + bundled CLI **≤40 tok** unused, +1,801 (SKILL.md) +240 (`--help`) when used |
| **install friction ranking** | 1. skill into an existing skills root (one `cp -r`, no config, works with a plain chat client by pasting) → 2. MCP into omp/Codex/Claude (one CLI/JSON block, but a process + reload + restart) → 3. skill + bundled CLI (same as 1 plus a script that must stay in sync) → 4. MCP into a plain chat/API client (**impossible**) |
| **recommendation** | MCP for data, skill for conventions, plus a ~60–90-line `python -m aa_mcp.cli <tool> '<json>'` over the same tool functions so skill-only clients get the verified data without a second implementation; retire the zip's duplicate `aa.py`. |
