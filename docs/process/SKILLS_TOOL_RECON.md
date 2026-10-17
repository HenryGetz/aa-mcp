# `npx skills` — tool reconnaissance and install trial

Date: 2026-10-16. Host: Linux x64, node v26.0.0, npx 11.15.0, omp 18.11.0 (`/home/wavy/.bun/bin/omp`).

Scope: identify the `npx skills` CLI, determine what `npx skills add streamlit/agent-skills -s developing-with-streamlit -g`
does, prove where it installs, decide whether the **omp** runtime consumes that location, and assess relevance to
`/home/wavy/ai/aa-mcp`.

> Nothing in `/home/wavy/ai/aa-mcp` was modified except this file. The project-scope install trial was run in
> `/tmp/skills-scratch`. No git state was touched.

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Is `npx skills` real and does it work here? | **Yes.** npm package `skills@1.7.2`, published by **Vercel Labs** (`vercel-labs/skills`), MIT. `npx --yes skills --help` exits 0. |
| What does `add <repo> -s <skill> -g` do? | Clones the GitHub repo, finds `SKILL.md` skills, and installs the selected one at **user level** into `~/.agents/skills/<skill>/` (+ symlink into `~/.claude/skills/`). |
| Where does `-g` write? | **`~/.agents/skills/developing-with-streamlit/`** plus `~/.claude/skills/developing-with-streamlit` (symlink) and a lock entry in `~/.agents/.skill-lock.json`. |
| Does omp read that directory? | **Yes.** `realpath skill://agent-browser` → `/home/wavy/.agents/skills/agent-browser`. omp's `agents` provider scans `.agents/skills`. |
| Did the install already happen? | **Yes** — it was already present (installed 2026-10-17T02:06:42Z ≈ 21:06 local today); this recon re-ran it and confirmed. |
| Does the *current* omp session see it? | **No** — `read skill://developing-with-streamlit` → `Unknown skill`. Skills are discovered at session start; a new omp session is required. |
| Right tool for an **MCP server**? | **No.** `skills` is a markdown-skill package manager. MCP servers go in `~/.omp/agent/mcp.json` (or `.omp/mcp.json`). |
| Relevant to `aa-mcp`? | **No** — the skill is for building Streamlit apps; `aa-mcp` has zero Streamlit usage. |

---

## 1. What the tool is

### 1.1 Package identity (`npm view skills`)

```
skills@1.7.2 | MIT | deps: 2 | versions: 100
The open agent skills ecosystem
https://github.com/vercel-labs/skills#readme

keywords: cli, agent-skills, skills, ai-agents, aider-desk, amp, antigravity, ..., claude-code, ...
bin: skills, add-skill
dist
.tarball: https://registry.npmjs.org/skills/-/skills-1.7.2.tgz
.unpackedSize: 596.9 kB

dependencies:
tar: ^7.5.20, yaml: ^2.8.3

maintainers:
- rauchg <rauchg@gmail.com>
- quuu <qual1337@gmail.com>

dist-tags:
latest: 1.7.2
snapshot: 1.5.23-snapshot.2

published a week ago by GitHub Actions <npm-oidc-no-reply@github.com>
```

- **npm package name:** `skills` (unscoped — no `@scope/`). No ambiguity; it resolved on the first attempt, so the
  fallback candidates (`@skills/cli`, `skills-cli`, `@anthropic/skills`, `agent-skills`) were **not needed**.
- **Publisher:** Vercel Labs — repo `https://github.com/vercel-labs/skills`, homepage `https://skills.sh`.
- **Version installed on this run:** `1.7.2` (latest).
- **Bins:** `skills`, `add-skill`.
- **Runtime deps:** only `tar` and `yaml`.

### 1.2 `npx --yes skills --help` (raw, trimmed)

```
Usage: skills <command> [options]

Manage Skills:
  add <package>        Add a skill package (alias: a)
                       e.g. vercel-labs/agent-skills
                            notion
                            https://notion.so/<skill-page>
                            https://github.com/vercel-labs/agent-skills
  use <package>@<skill>   Generate a prompt for using one skill without installing it
  remove [skills]      Remove installed skills
  list, ls             List installed skills
  find [query]         Search for skills interactively

Updates:
  update [skills...]   Update skills to latest versions (alias: upgrade)

Project:
  experimental_install Restore skills from skills-lock.json
  init [name]          Initialize a skill (creates <name>/SKILL.md or ./SKILL.md)
  experimental_sync    Sync skills from node_modules into agent directories

Add Options:
  -g, --global           Install skill globally (user-level) instead of project-level
  -a, --agent <agents>   Specify agents to install to (use '*' for all agents)
  -s, --skill <skills>   Specify skill names to install (use '*' for all skills)
  -l, --list             List available skills in the repository without installing
  -y, --yes              Skip confirmation prompts
  --copy                 Copy files instead of symlinking to agent directories
  --metadata <json>      Attach valid JSON to the install telemetry event
  --subagent <names>     Install to Eve subagents (use 'root' for the root agent)
  --all                  Shorthand for --skill '*' --agent '*' -y
  --full-depth           Search all subdirectories even when a root SKILL.md exists
  --json                 Output results as JSON (machine-readable, no ANSI codes)
```

`npx --yes skills add --help` prints the **same** top-level usage block (the `add` subcommand has no separate
help screen); `npx --yes skills --version` → `1.7.2`. All three exit 0, in ~8–16 s (npx download + node start).

**Subcommands:** `add`/`a`, `use`, `remove`, `list`/`ls`, `find`, `update`/`upgrade`, `init`,
`experimental_install`, `experimental_sync`. Options exist for `add`, `use`, `remove`, `update`, `find`
(`--owner`), and `experimental_sync` (`-a`, `-y`, `--copy`).

---

## 2. What `add <repo> -s <skill> -g` means

From the help text plus the two empirical runs (§3):

| Token | Meaning |
|---|---|
| `add <package>` | Source of skills. Accepts a GitHub `owner/repo` shorthand (what we used), a bare name resolved against a registry, a full URL, or a docs page. The CLI **clones the repo** (observed: `◇ Cloning repository… / Repository cloned`) and scans it for `SKILL.md` files. |
| `-s, --skill <name>` | Selects which skill(s) inside that repo to install (`*` = all). Without `-s`, the CLI prompts; with `-l/--list` it only lists. The streamlit repo contains exactly one skill, so `-s` was unambiguous. |
| `-g, --global` | Install at **user level** instead of project level. Without `-g`, the skill is installed into the *current directory's* agent folders. |

### Exact write targets (verified)

**Global (`-g`):**
- `~/.agents/skills/<skill>/` — the "universal" directory (copy, not symlink).
- `~/.claude/skills/<skill>` → symlink to `../../.agents/skills/<skill>` (Claude Code is detected).
- Lock file: `~/.agents/.skill-lock.json`.

**Project-local (no `-g`, run in cwd):**
- `./.agents/skills/<skill>/` — universal.
- `./.claude/skills/<skill>` → symlink to `../../.agents/skills/<skill>`.
- Lock file: `./skills-lock.json`.

### Config / manifest files

- `~/.agents/.skill-lock.json` (global lock, `"version": 3`) and `<cwd>/skills-lock.json` (project lock,
  `"version": 1`). These record `source`, `skillPath`, hashes and timestamps — they are the tool's own bookkeeping,
  not something omp reads.
- `~/.agents/.skill-lock.json` also carries `dismissed.findSkillsPrompt` and `lastSelectedAgents`.
- **No `AGENTS.md` edits, no `.skillsrc`, no `~/.config/skills`** were created or modified. (`~/.config/skills`
  does not exist; `~/.codex/skills` and `~/.config/opencode/skills` were untouched by this install.)

---

## 3. Install trial

### 3.1 It was already installed

The global install had already been performed before this recon (lock timestamp `2026-10-17T02:06:42.895Z`
≈ 21:06 local). Re-running the exact command reproduced it cleanly.

### 3.2 `npx --yes skills add streamlit/agent-skills -s developing-with-streamlit -g` (raw, trimmed)

```
●   claude  Agent detected — installing non-interactively
◇  Source: https://github.com/streamlit/agent-skills.git
◒  Cloning repository…
◇  Repository cloned
◇  Found 1 skill
●  Selected 1 skill: developing-with-streamlit

◇  Installation Summary ──────────────────────────────────────────────────╮
│  ~/.agents/skills/developing-with-streamlit                             │
│    universal: Amp, Antigravity, Antigravity CLI, Cline, Codex +16 more  │
│    symlink → Claude Code                                                │
│    overwrites: Cline, Codex, Dexto, Kimi Code CLI, Loaf +4 more         │
├─────────────────────────────────────────────────────────────────────────╯

◇  Security Risk Assessments ───────────────────────────────────────────────╮
│                             Gen               Socket            Snyk      │
│  developing-with-streamlit  Safe              0 alerts          Low Risk  │
│  Details: https://skills.sh/streamlit/agent-skills                        │
├───────────────────────────────────────────────────────────────────────────╯

◒  Installing skills…
◇  Installation complete

◇  Installed 1 skill ─────────────────────────────────────────────────────╮
│  ✓ ~/.agents/skills/developing-with-streamlit                           │
│    universal: Amp, Antigravity, Antigravity CLI, Cline, Codex +16 more  │
│    symlinked: Claude Code                                               │
├─────────────────────────────────────────────────────────────────────────╯

■  Failed to install 1
│    ✗ developing-with-streamlit → PromptScript: PromptScript does not support global skill installation
└  Done!  Review skills before use; they run with full agent permissions.
```

(The `PromptScript` line is a benign per-agent limitation, not an error affecting the universal install.)

### 3.3 Project-local trial in `/tmp/skills-scratch`

```
npx --yes skills add streamlit/agent-skills -s developing-with-streamlit

◇  Installation Summary ──────────────────────────────────────────────────╮
│  ./.agents/skills/developing-with-streamlit                             │
│    universal: Amp, Antigravity, Antigravity CLI, Cline, Codex +16 more  │
│    symlink → Claude Code                                                │
├─────────────────────────────────────────────────────────────────────────╯
◇  Installed 1 skill → ./.agents/skills/developing-with-streamlit
```

Resulting tree:

```
/tmp/skills-scratch/skills-lock.json
/tmp/skills-scratch/.agents/skills/developing-with-streamlit/SKILL.md
/tmp/skills-scratch/.agents/skills/developing-with-streamlit/scripts/discover.py
/tmp/skills-scratch/.claude/skills/developing-with-streamlit -> ../../.agents/skills/developing-with-streamlit
```

`/tmp/skills-scratch/skills-lock.json`:

```json
{
  "version": 1,
  "skills": {
    "developing-with-streamlit": {
      "source": "streamlit/agent-skills",
      "sourceType": "github",
      "skillPath": "developing-with-streamlit/SKILL.md",
      "computedHash": "9f8006c37398b5c6a27043bdfe3a25d4aafdfb53413618c88d2c978932f9d08e"
    }
  }
}
```

### 3.4 What actually landed on disk (global)

```
$ ls -la ~/.agents/skills/
drwxrwxr-x  agent-browser
drwxrwxr-x  developing-with-streamlit
drwxrwxr-x  find-skills

$ ls -la ~/.agents/skills/developing-with-streamlit/
-rw-rw-r--  SKILL.md            (1650 bytes)
drwxrwxr-x  scripts/
-rwxrwxr-x  scripts/discover.py (10463 bytes)

$ ls -la ~/.claude/skills/
developing-with-streamlit -> ../../.agents/skills/developing-with-streamlit
```

`~/.agents/.skill-lock.json` (global):

```json
{
  "version": 3,
  "skills": {
    "agent-browser": { "source": "vercel-labs/agent-browser", ... "installedAt": "2026-05-30T15:36:15.650Z" },
    "developing-with-streamlit": {
      "source": "streamlit/agent-skills",
      "sourceType": "github",
      "sourceUrl": "https://github.com/streamlit/agent-skills.git",
      "skillPath": "developing-with-streamlit/SKILL.md",
      "skillFolderHash": "11e6c906e0bb9619a4965895aad28400d2f11c8b",
      "installedAt": "2026-10-17T02:06:42.895Z",
      "updatedAt": "2026-10-17T02:06:42.895Z"
    },
    "find-skills": { "source": "vercel-labs/skills", ... }
  },
  "dismissed": { "findSkillsPrompt": true },
  "lastSelectedAgents": ["amp","cline","codex","cursor","droid","gemini-cli","github-copilot",
                         "kilo","kimi-code-cli","opencode","pi","warp","zed"]
}
```

`npx skills list -g` confirms all three are registered globally:

```
Global Skills

agent-browser             ~/.agents/skills/agent-browser
  Agents: Antigravity, Antigravity CLI, Codex, Gemini CLI, GitHub Copilot +3 more  Source: vercel-labs/agent-browser
developing-with-streamlit ~/.agents/skills/developing-with-streamlit
  Agents: Antigravity, Antigravity CLI, Codex, Gemini CLI, GitHub Copilot +3 more  Source: streamlit/agent-skills
find-skills               ~/.agents/skills/find-skills
  Agents: Antigravity, Antigravity CLI, Codex, Gemini CLI, GitHub Copilot +3 more  Source: vercel-labs/skills
adeu-redlining            ~/.config/opencode/skills/adeu-redlining   ...  Source: local
(plus clonedeps, codemap, loop-engineering, reflect, simplify — all OpenCode-local, not from this tool)
```

### 3.5 Installed `SKILL.md` (excerpt)

```markdown
---
name: developing-with-streamlit
description: "Use for ALL Streamlit tasks: creating, editing, debugging, beautifying, styling, theming,
optimizing, or deploying Streamlit apps. Also custom components, st.components.v2, HTML/JS/CSS work.
Discovers and loads version-matched reference docs from the user's installed Streamlit (>=1.57).
Triggers: streamlit, st., dashboard, app.py, beautify, style, CSS, color, background, theme, button,
widget styling, custom component, st.components, CCv2, session state, performance, cache, fragment,
slow rerun, deploy."
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/scripts/discover.py:*) Bash(python3 ...)
---

# Developing with Streamlit

Streamlit (>=1.57) ships detailed reference documentation for building Streamlit apps inside its pip
package. The bundled skill is a routing `SKILL.md` plus a `references/` folder of topic-specific
reference docs (dashboards, themes, layouts, session state, custom components, etc.).

## Usage

Run the discovery script with the user's project directory:

    python <SKILL_DIR>/scripts/discover.py --project-dir <USER_PROJECT_DIR>
...
```

`scripts/discover.py` is a ~10 KB local helper that locates the active interpreter (venv/conda/pipenv/poetry/pdm/uv),
finds the installed Streamlit package, and prints the path to Streamlit's *bundled* `SKILL.md`. Exit codes:
`1` Streamlit not installed, `2` Streamlit predates bundled skills, `3` no interpreter, `4` upstream restructured.

---

## 4. Does omp see it?

### 4.1 Where omp looks for skills

From `omp://skills.md` (authoritative runtime doc): skills are discovered per-provider; the relevant provider is

> `agents` (priority 70) — `agents` provider (`.agent[s]/skills`)

and the provider list includes `native` (`.omp` user/project), `skillshare`, `omp-plugins`, `claude`,
`agent-plugins`, `claude-plugins`, `agents`, `codex`, `opencode`, `github`, `omp-managed`.

Corroborated by strings in the omp binary itself:

```
$ strings -a /home/wavy/.bun/bin/omp | grep -o '\.agents/skills[^"]\{0,30\}'
.agents/skills (project walk-up + user home)

$ strings -a /home/wavy/.bun/bin/omp | grep -o 'skill-descriptions[^"]\{0,40\}'
skill-descriptions
skill-descriptions-db
skill-descriptions.db
```

### 4.2 Ground truth: where the working `agent-browser` skill lives

```
$ realpath skill://agent-browser
/home/wavy/.agents/skills/agent-browser

$ ls -la /home/wavy/.agents/skills/agent-browser/
-rw-rw-r--  SKILL.md   (3263 bytes)
```

`~/.agents/skills/agent-browser/SKILL.md` is a plain directory (no symlink), and omp resolves
`skill://agent-browser` straight to it. **`~/.agents/skills/` is the directory omp reads** — and it is exactly the
directory `npx skills … -g` writes to. So the answer is yes: the global install target **is** an omp-read location.

(For completeness, other candidate homes were checked and are *not* used by omp for these skills:
`~/.omp/agent/skills` and `~/.omp/skills` do not exist; `~/.omp/agent/managed-skills` does not exist;
`~/.codex/skills` contains only Codex's own `.system` skills; `~/.gemini/skills`, `~/.pi/skills` do not exist.)

### 4.3 Did omp actually pick it up?

`~/.omp/agent/skill-descriptions.db` already contains a row for the new skill:

```
$ sqlite3 ~/.omp/agent/skill-descriptions.db 'select * from skill_descriptions'
2d3024243fb7e7f7ac61da5c592dbf9204497f496d9d2cc99ed30c83fb98f8e4
  |Use to interact with websites, automate browser tasks, or test web apps.
47be5f4cf4312a5c1e28fa8b7ab6f6f328136d070001a8474cd6bc96de89ff1c
  |Streamlit apps: build, edit, debug, style, theme, deploy, components, session state.
dc2e4ed71f8fc223d1d5e8edd421fd37eabc7904e5da52043d5d7d24c1663c94:opencode-go/deepseek-v4.1-flash
  |Helps users discover and install agent skills when they ask questions like "how do I do X", "find…
```

The third key is model-scoped to `opencode-go/deepseek-v4.1-flash` (omp's configured default model), which confirms
this DB is omp's own description index. Its WAL was written at 21:07, one minute after the 21:06 install — omp's
indexer saw the new skill file.

### 4.4 …but the *current* session cannot read it

```
$ read skill://developing-with-streamlit
Unknown skill: developing-with-streamlit
Available: agent-browser
```

omp discovers skills **at session start** (`omp://skills.md`: "file-backed capability packs discovered at startup").
This session began before/around the install, so its live skill set is still just `agent-browser`. The file is in the
right place and the index knows about it — a **new omp session / restart is required** for
`skill://developing-with-streamlit` to resolve.

> **Cannot be determined from inside this session:** whether a restarted omp lists the skill in the system prompt.
> The evidence (file in an omp-read directory + entry in omp's description index + `realpath` proof that omp maps
> `skill://agent-browser` to that same directory) makes it near-certain, but the runtime cannot be restarted from
> within an agent session, so this is stated as [INFERENCE] rather than observed.

---

## 5. The verdict

### (a) Installing *agent skills* — `npx skills add … -g` is correct ✅

It is the right move **for skills**. It works on this machine, it installs into `~/.agents/skills/<skill>/`, and that
is a directory omp's `agents` provider scans. Concretely, for this environment:

```bash
npx skills add <owner>/<repo> -s <skill-name> -g     # user-level, visible to omp after a restart
npx skills add <owner>/<repo> -s <skill-name>        # project-level → ./.agents/skills/ (repo-local)
npx skills list -g                                   # what is installed globally
npx skills remove <skill-name> -g                    # uninstall
```

### (b) Installing an *MCP server* — `npx skills` is the wrong tool ❌

`skills` is a **markdown-skill package manager**. It has no MCP concept anywhere in its help, subcommands, lock
format, or output. Do not use it to add an MCP server.

- **Skill** = a `SKILL.md` (plus optional scripts/references) that the agent reads into context on demand via
  `skill://<name>`. No process, no tool schema; it is *instructions*.
- **MCP server** = a separate process (stdio or HTTP) that exposes *callable tools* (they surface in omp as
  `mcp__<server>__<tool>`). It must be registered with the runtime that will spawn it.

In **omp**, MCP servers are declared in `~/.omp/agent/mcp.json` (user) or `.omp/mcp.json` (project) — per
`omp://mcp-config.md`. This is already how the repo's own server is wired up:

```jsonc
// ~/.omp/agent/mcp.json (existing, abridged)
{
  "$schema": "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json",
  "mcpServers": {
    "aa": { "type": "stdio", "command": "/home/wavy/.local/bin/aa-mcp", "timeout": 180000, "enabled": true },
    "excel": { "type": "stdio", "command": "/home/wavy/opt/excel-mcp/.venv/bin/excel-mcp", "enabled": false },
    ...
  }
}
```

Correct paths for an MCP server here: edit `~/.omp/agent/mcp.json` (or project `.omp/mcp.json`), or use omp's
interactive `/mcp add`. `npx skills` plays no part.

---

## 6. Relevance check — `streamlit/agent-skills`

Fetched `https://github.com/streamlit/agent-skills` (224 stars, 23 forks, Apache-2.0, Python). Repo contents:

```
AGENTS.md  CLAUDE.md  CONTRIBUTING.md  LICENSE  README.md
.github/instructions/reviewing-skills.instructions.md
.github/workflows/test-discovery.yml
developing-with-streamlit/SKILL.md
developing-with-streamlit/scripts/discover.py
tests/discovery/{README.md,conftest.py,run-local.sh,test_discovery.py}
```

**What it is:** a *single* meta-skill, `developing-with-streamlit`. It is **not** a library of Streamlit knowledge.
It is a routing stub plus `discover.py`: the script detects the active Python interpreter, locates the installed
Streamlit package, and points the agent at the reference docs that **Streamlit itself bundles** in the pip package
(`lib/streamlit/.agents/meta-skill/…`, Streamlit ≥1.57, moved into `streamlit/streamlit` as of 1.60). If Streamlit
is old or absent, it falls back to the online docs.

**Repo status — important:** the README opens with a deprecation notice:

> **This repository is deprecated and is being archived.** The `developing-with-streamlit` meta-skill now lives in
> and ships with Streamlit itself … As of Streamlit **1.60+** the meta-skill is bundled in the pip package …
> `streamlit skills` installs it from your local install — no download from this repo.

It recommends `pip install --upgrade streamlit` then `streamlit skills`. Existing `npx skills` installs keep
working (the `v1` tag is preserved).

**What it is for:** only Streamlit app work — creating/editing/debugging/styling/theming/deploying Streamlit apps,
`st.*` widgets, session state, custom components. It is useless unless a Streamlit app is actually being built, and
it needs **Streamlit ≥1.57 installed in the active interpreter** to resolve anything.

**Relevance to `/home/wavy/ai/aa-mcp`:** **none.**
- `aa-mcp` is a Python **MCP server** for `artificialanalysis.ai` (`pyproject.toml`: *"MCP server for
  artificialanalysis.ai — live AI model benchmarks, pricing, speed and provider data, token-efficient by design"*,
  deps `mcp>=2.0.0`). It has **zero** references to Streamlit (`grep -ril streamlit` → no matches).
- Streamlit is **not installed** in this environment (`python3 -c "import streamlit"` → `ModuleNotFoundError`).
- The skill would only make sense if the user wants to build a **Streamlit UI** (e.g. a front-end over the MCP
  server's data), which is not what this repo is.

It is currently installed globally and is harmless — it costs one line in the skill list — but it adds no
capability for `aa-mcp`.

---

## What to do next

**If you want omp to actually use the skill:** restart omp / start a new session. The file is already in
`~/.agents/skills/`, which omp reads, so no re-install is needed. (Cannot be done from inside this session.)

**If you want the Streamlit skill properly (and its docs):**
```bash
pip install --upgrade "streamlit>=1.60"   # or uv add streamlit
streamlit skills                          # installs from your local Streamlit package
```

**If you don't want it** (recommended for `aa-mcp`):
```bash
npx skills remove developing-with-streamlit -g
```

**If the real goal is an MCP server:** do not use `npx skills`. Register it in omp:
```bash
# either edit the file directly…
$EDITOR ~/.omp/agent/mcp.json          # add an entry under "mcpServers"
# …or run /mcp add inside an omp session
```

---

## Final answer

- **Does the tool work here?** Yes — `npx skills@1.7.2` (Vercel Labs, `vercel-labs/skills`, MIT) runs fine on
  node v26.0.0 / npx 11.15.0; help, list, and add all succeed.
- **Where does it install?** `-g` → `~/.agents/skills/<skill>/` (plus a `~/.claude/skills/<skill>` symlink and
  `~/.agents/.skill-lock.json`). Project mode → `./.agents/skills/<skill>/` + `./.claude/skills/<skill>` +
  `./skills-lock.json`. Verified on disk.
- **Does omp consume that location?** Yes. `realpath skill://agent-browser` resolves to
  `/home/wavy/.agents/skills/agent-browser`, and omp's binary contains `.agents/skills (project walk-up + user
  home)`. `npx skills -g` writes exactly there. The current session does not see the new skill because skills load
  at startup; a restart is required (unverifiable from inside this session → [INFERENCE]).
- **Recommendation:** For **agent skills**, `npx skills add … -g` is the correct and working path in this
  environment. For an **MCP server**, it is the wrong tool — use `~/.omp/agent/mcp.json`. And
  `streamlit/agent-skills` is **not relevant to `aa-mcp`** (no Streamlit app, no Streamlit installed); remove it
  unless a Streamlit UI is the goal.
