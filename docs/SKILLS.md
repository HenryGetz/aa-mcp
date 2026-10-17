# Skills and MCP install

`aa-mcp` can be reached by an agent in two independent ways, and they are easy to
confuse: a **skill** (markdown instructions the agent reads on demand) and an **MCP
server** (a separate process exposing callable tools). Installing one does not install
the other.

This page documents both, plus the exact commands for this machine (omp
`@oh-my-pi/pi-coding-agent` 18.11.0 on Linux). The omp-side claims come from the
installed package source (`~/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/src/…`)
and were verified on 2026-10-16; see `docs/process/OMP_SKILLS_PATH.md` for the full
reconnaissance.

---

## 1. Skills vs MCP servers

| | **Skill** | **MCP server** |
|---|---|---|
| what it is | markdown instructions (+ optional scripts/assets) in a directory | a separate process that speaks MCP and exposes callable tools |
| how an agent gets it | name + description appear in the system prompt; the body is read on demand with `read skill://<name>` (or `/skill:<name>`) | omp connects at session start; each tool is exposed as `mcp__<server>_<tool>` (the Claude-style `mcp__<server>__<tool>` spelling is also accepted) |
| what it costs | context only when the agent reads it | a running process + the tool schemas in the prompt |
| how you install it | copy a directory (or `npx skills add …`) into a skills root | register a command/URL in `mcp.json` |
| example here | `skills/aa-mcp/SKILL.md` (this repo) | the `aa` server in `~/.omp/agent/mcp.json` |
| refresher | restart the session (discovery runs at session start) | `/mcp reload` — "Force reload MCP runtime tools" |

An MCP install gives an agent *tools*; a skill gives it *instructions*. The `npx skills`
CLI is skills-only — it has no MCP concept (`add`, `use`, `remove`, `list`, `find`,
`update`, `init`, `experimental_install`, `experimental_sync`; no `mcp` subcommand).

---

## 2. Installing skills with `npx skills`

`skills` is Vercel Labs' cross-agent skill installer ([github.com/vercel-labs/skills](https://github.com/vercel-labs/skills),
registry and docs at [skills.sh](https://skills.sh)).

```bash
# one named skill from a GitHub repo, user-level (works in every project)
npx skills add <owner>/<repo> -s <skill> -g

# project-level (the default): installs into the current directory
npx skills add <owner>/<repo> -s <skill>

# see what a repo offers without installing anything
npx skills add <owner>/<repo> -l
```

`-s <skill>` selects one skill from the package (`-s '*'` for all of them); without it
the CLI prompts. `-g` switches from project scope to user scope. Useful extras:
`-a <agents>` (which agent directories get links), `--copy` (copy into agent dirs
instead of symlinking), `-y` (no prompts), `--json` (machine-readable).

### What it writes

| scope | canonical skill directory | lockfile | extra agent links |
|---|---|---|---|
| global (`-g`) | `~/.agents/skills/<skill>/SKILL.md` | `~/.agents/.skill-lock.json` | `~/.claude/skills/<skill>` → `../../.agents/skills/<skill>` (one symlink per selected agent) |
| project (default) | `<project>/.agents/skills/<skill>/SKILL.md` | `<project>/skills-lock.json` | `<project>/.claude/skills/<skill>` symlink when Claude Code is among the detected agents |

Observed on this machine:

```console
$ npx skills list -g
Global Skills
agent-browser             ~/.agents/skills/agent-browser             Source: vercel-labs/agent-browser
developing-with-streamlit ~/.agents/skills/developing-with-streamlit Source: streamlit/agent-skills
find-skills               ~/.agents/skills/find-skills               Source: vercel-labs/skills

$ ls -la ~/.claude/skills/
lrwxrwxrwx developing-with-streamlit -> ../../.agents/skills/developing-with-streamlit

$ npx skills add vercel-labs/skills -s find-skills -y -a codex    # in an empty dir
  ✓ find-skills (copied) → ./.agents/skills/find-skills
$ find . | sort
./.agents/skills/find-skills/SKILL.md
./skills-lock.json
```

Other subcommands:

| command | does |
|---|---|
| `npx skills list` / `ls` (`-g` for global) | list installed skills and their sources |
| `npx skills find [query] [--owner <owner>]` | search the registry interactively |
| `npx skills use <owner>/<repo>@<skill>` | print a ready-made prompt for one skill without installing it |
| `npx skills remove [skills]` (`-g`, `-a`, `-s`, `--all`) | uninstall, cleaning up the agent links |
| `npx skills update [skills…]` (`-g` / `-p`) | update within the recorded source |
| `npx skills init [name]` | scaffold a new `<name>/SKILL.md` |
| `npx skills experimental_install` | restore skills from `skills-lock.json` |

**omp does not need to be a selected agent.** The CLI's canonical store
(`~/.agents/skills/`, `./.agents/skills/`) is already an omp default scan root, so the
skill is discovered whether or not the CLI also created a link for some other agent.

---

## 3. Where omp reads skills

omp scans a fixed set of roots **at session start** and exposes what it finds. The
default-on roots that matter here (full provider list and precedence:
`docs/process/OMP_SKILLS_PATH.md` §2.2):

| root | scope | notes |
|---|---|---|
| `~/.agents/skills/<name>/SKILL.md` | user (all projects) | where `npx skills … -g` installs; `description` optional |
| `<repo>/.agents/skills/<name>/SKILL.md` | project (walk-up from cwd to the git root) | where `npx skills …` (project mode) installs |
| `<repo>/.omp/skills/<name>/SKILL.md` | project | omp-native; **`description` is required** |
| `~/.omp/agent/skills/<name>/SKILL.md` | user | omp-native; `description` required |

Rules the scanner enforces:

* the file must be named exactly `SKILL.md`, **one level deep** — `<root>/<name>/SKILL.md`.
  Nested layouts (`<root>/group/<name>/SKILL.md`) are not discovered, and a flat
  `<root>/SKILL.md` is not read from these roots;
* **symlinked skill directories are followed**, so `ln -s /path/to/clone ~/.agents/skills/<name>`
  works (a *dangling* link is silently ignored);
* front-matter `name` defaults to the directory name and must not contain `/` or `\`;
* `description` is what the prompt shows the model — always write one;
* `enabled: false` skips the skill entirely;
* `hide: true` (or the Agent-Skills spelling `disable-model-invocation: true`) keeps the
  skill out of the prompt's listing but leaves `read skill://<name>` and `/skill:<name>`
  working.

### Restart requirement

Discovery happens once, when the session starts. A skill added to disk afterwards is
**invisible to that session** — `read skill://<name>` answers
`Unknown skill: <name>` while a fresh process finds it. So after installing:

* **restart the session** (`/restart`, or start a new `omp`) — the normal path;
* or, if the skill was installed through omp's own `/skills install …` (the
  `skills.omp.sh` registry, unrelated to this repo) or you changed any `skills.*` setting,
  omp refreshes live and no restart is needed;
* `/reload` is **MCP-only** and does not refresh skills.

### Confirm what omp sees

```bash
omp skill list --json            # what a session in this directory would resolve
omp skill list --json | python3 -c "import json,sys; [print(s['name'], '|', s['source'], '|', s['filePath']) for s in json.load(sys.stdin)['skills']]"
```

---

## 4. Installing the aa-mcp MCP server

This repo is an MCP server. Nothing here is installed by `npx skills` — you run the
server and register it with omp.

```bash
# run it without installing (uv fetches the repo and runs it on stdio)
uvx --from git+https://github.com/HenryGetz/aa-mcp aa-mcp

# or install the executable once
uv tool install --from git+https://github.com/HenryGetz/aa-mcp aa-mcp   # -> ~/.local/bin/aa-mcp
```

Then register it. omp reads MCP config from `<repo>/.omp/mcp.json` (project) and
`~/.omp/agent/mcp.json` (user, per profile); `<repo>/.omp/.mcp.json` and
`~/.omp/agent/.mcp.json` are also accepted. `~/.omp/agent/mcp.json` on this machine
already has the entry:

```json
{
  "mcpServers": {
    "aa": {
      "type": "stdio",
      "command": "/home/wavy/.local/bin/aa-mcp",
      "timeout": 180000,
      "enabled": true
    }
  }
}
```

Swap `command` for a `uvx` launcher if you did not install the executable:

```json
{
  "mcpServers": {
    "aa": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/HenryGetz/aa-mcp", "aa-mcp"],
      "timeout": 180000
    }
  }
}
```

Reload the MCP runtime with `/mcp reload` after editing the file (or restart). The
server's 12 tools then appear as `mcp__aa_aa_leaderboard`, `mcp__aa_aa_compare`, … and
its 15 resources under `aa://…`.

---

## 5. This repo's own skill

`skills/aa-mcp/SKILL.md` is the skill that tells an agent how to work with this server
(which tool answers which question, the token discipline, the `aa:rsc` provenance
header). It is plain markdown with front-matter (`name: aa-mcp`, plus a `description`),
so it installs like any other skill:

```bash
# project-local discovery without the CLI (works today)
mkdir -p .agents/skills && cp -r skills/aa-mcp .agents/skills/aa-mcp

# user-level, straight from GitHub — once the skill is pushed
npx skills add HenryGetz/aa-mcp -s aa-mcp -g
```

The copy path is verified: with `skills/aa-mcp` copied to `.agents/skills/aa-mcp`,
`omp skill list --json` reports `aa-mcp | agents:project`. The `npx skills` path is not
usable yet — as of 2026-10-16 the pushed upstream repo does not contain the skill
(`npx skills add HenryGetz/aa-mcp -l` → *"No skills found"*); it will resolve once
`skills/aa-mcp/SKILL.md` is on GitHub, since the CLI discovers `skills/<name>/SKILL.md`
(that is how `vercel-labs/skills` installs `skills/find-skills/SKILL.md`).

Either way the agent then reads it as `skill://aa-mcp`. The skill only carries
instructions — the tools it describes still come from the MCP registration in §4, so
install both if you want an agent to be able to *act* on it.

---

## 6. The Streamlit case (`npx skills add streamlit/agent-skills …`)

```bash
npx skills add streamlit/agent-skills -s developing-with-streamlit -g
```

is a valid **skill** install and it works on this machine: it is already installed
globally at `~/.agents/skills/developing-with-streamlit/SKILL.md` (with the usual
`~/.claude/skills/developing-with-streamlit` symlink and a row in
`~/.agents/.skill-lock.json`). Like any skill installed out-of-band it is invisible to
an already-running omp session until restart. It is **not** an MCP install and adds no
tools.

Two caveats:

* **That upstream repo is deprecated.** Its README says so: *"This repository is
  deprecated and is being archived. The `developing-with-streamlit` meta-skill now lives
  in and ships with Streamlit itself — `streamlit/streamlit` is the canonical source of
  truth"*, bundled in the pip package at `lib/streamlit/.agents/meta-skill/developing-with-streamlit`
  as of Streamlit 1.60+, installed with `streamlit skills`. Existing installs keep
  working (`discover.py` runs locally), but new fixes land in `streamlit/streamlit`.
* **It is irrelevant to this repo** unless you actually want a Streamlit UI — aa-mcp is
  a stdio MCP server, not a Streamlit app.

---

## 7. Troubleshooting

| symptom | cause / fix |
|---|---|
| installed a skill, agent says `Unknown skill: <name>` | the session started before the install — restart (`/restart`). Discovery runs once per session. Confirm with `omp skill list --json` from the project directory. |
| `omp skill list --json` finds it, the session does not | same: `skill list` is a fresh process. |
| symlinked skill never appears | a dangling symlink is skipped silently (`existsSync` on `<link>/SKILL.md`); check `ls -l` and that the target has `SKILL.md`. |
| skill in `<repo>/.omp/skills/<name>/` is ignored | omp's native provider requires front-matter `description`; the `.agents/skills` root does not. Add one. |
| skill present but not listed in the prompt | `hide: true` / `disable-model-invocation: true` de-lists it (still readable via `skill://`); `enabled: false` disables it outright. Also, a same-named skill from a higher-precedence provider wins the bare name — the other one is reachable as `skill://<namespace>/<name>`. |
| copied the repo root instead of the skill dir | the layout must be `<root>/<name>/SKILL.md`; `cp -r agent-skills ~/.agents/skills/` gives `<root>/agent-skills/developing-with-streamlit/SKILL.md` — one level too deep. |
| project install shows up as `claude:project` | project-mode `npx skills add` writes both `./.agents/skills/<name>/` and a `./.claude/skills/<name>` symlink; both are default-on and the higher-priority claude provider wins the name. Harmless; use `-a <agent>` (or copy manually) to avoid the `.claude` link. |
| is `~/.omp/agent/skill-descriptions.db` a registry? | no. It is only a cache of LLM-compressed description blurbs (table `skill_descriptions(key, description)`, keyed by a hash of prompt+name+description), regenerated lazily at prompt-render time. A skill needs no row to be discovered or used. |
| edited `SKILL.md` but the agent still sees the old text | the body is snapshotted at session start — restart. |
