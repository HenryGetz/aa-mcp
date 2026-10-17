# How omp discovers skills on this machine

Recon date: 2026-10-16 (local, CDT). Host: `wavy@linux 6.8.0-142-generic`.
omp build: `@oh-my-pi/pi-coding-agent` **v18.11.0**, `~/.bun/bin/omp` → `~/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js`.
Below, `$OMP` abbreviates `/home/wavy/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent` (the package ships its `src/`, so all citations are real source lines).

Nothing under `/home/wavy/ai/aa-mcp` was modified except this file; no git state, no omp config file was touched. All probes were created outside the repo and removed (see §6).

---

## 0. Answer in one paragraph (details below)

Put a skill at **`~/.agents/skills/<skill-name>/SKILL.md`** (user-global) or **`<repo>/.agents/skills/<skill-name>/SKILL.md`** (project-local) — both are scanned **by default, with no config change**. `<repo>/.omp/skills/<skill-name>/SKILL.md` also works but *requires* a `description:` in front-matter. Discovery is a plain directory scan performed **at process/session start**; there is **no registration step and no index to rebuild** (`~/.omp/agent/skill-descriptions.db` is only a cache of LLM-compressed description blurbs, not a registry). A skill added to disk is picked up by the **next omp process** — a session that is already running keeps its snapshot (verified: a live session answers `read skill://<new-skill>` with `Unknown skill`). So: copy/clone/symlink the skill dir into place, then **restart the omp session** (or trigger a live refresh — §7). Agents then reference it as `skill://<skill-name>` (and `/skill:<name>`).

---

## 1. Where omp skills live — the working `agent-browser` skill

```console
$ ls -la /home/wavy/.agents/skills/
total 20
drwxrwxr-x 5 wavy wavy 4096 Oct 16 21:16 .
drwxrwxr-x 3 wavy wavy 4096 May 30 10:36 ..
drwxrwxr-x 2 wavy wavy 4096 Jun  2 09:30 agent-browser
drwxrwxr-x 3 wavy wavy 4096 Oct 16 21:14 developing-with-streamlit
drwxrwxr-x 2 wavy wavy 4096 Oct 16 21:06 find-skills

$ ls -la /home/wavy/.agents/skills/agent-browser/
-rw-rw-r-- 1 wavy wavy 3263 Jun  2 09:30 SKILL.md
```

* **Full path of the working skill: `/home/wavy/.agents/skills/agent-browser/SKILL.md`**
* Layout: `<root>/<skill-name>/SKILL.md` — one directory per skill, **not** a flat file, **not** a plugin bundle. (`developing-with-streamlit` additionally has a `scripts/` subdir; assets live next to `SKILL.md` inside the skill dir.)
* Root for all three skills: `/home/wavy/.agents/skills/` (i.e. the **`.agents/skills`** convention, user level).

omp classifies them as `agents:user`, confirmed by a fresh process:

```console
$ cd /tmp && omp skill list --json | python3 -c '...'
count: 3
- agent-browser             | hide= False | src= agents:user | base= /home/wavy/.agents/skills/agent-browser
- developing-with-streamlit | hide= False | src= agents:user | base= /home/wavy/.agents/skills/developing-with-streamlit
- find-skills               | hide= False | src= agents:user | base= /home/wavy/.agents/skills/find-skills
warnings: []
```

### How those files got there: the `npx skills` CLI (not omp)

`/home/wavy/.agents/.skill-lock.json` is the lockfile of the third-party **`npx skills`** CLI (skills.sh). omp does **not** read it (`grep -rn "skill-lock" $OMP/src/` → no matches):

```json
{
  "version": 3,
  "skills": {
    "agent-browser": { "source": "vercel-labs/agent-browser", "sourceType": "github",
      "sourceUrl": "https://github.com/vercel-labs/agent-browser.git",
      "skillPath": "skills/agent-browser/SKILL.md",
      "installedAt": "2026-05-30T15:36:15.650Z", "updatedAt": "2026-06-02T14:30:08.169Z" },
    "developing-with-streamlit": { "source": "streamlit/agent-skills", "sourceType": "github",
      "sourceUrl": "https://github.com/streamlit/agent-skills.git",
      "skillPath": "developing-with-streamlit/SKILL.md",
      "installedAt": "2026-10-17T02:06:42.895Z" },
    "find-skills": { "source": "vercel-labs/skills", "sourceType": "github",
      "sourceUrl": "https://github.com/vercel-labs/skills.git",
      "skillPath": "skills/find-skills/SKILL.md",
      "installedAt": "2026-10-17T02:06:46.502Z" }
  },
  "dismissed": { "findSkillsPrompt": true },
  "lastSelectedAgents": ["amp","cline","codex","cursor","droid","gemini-cli","github-copilot","kilo","kimi-code-cli","opencode","pi","warp","zed"]
}
```

Note the happy accident that makes this work: the `npx skills` CLI's canonical install root (`~/.agents/skills/`) happens to be exactly one of omp's default scan roots. `skillPath` in the lockfile (`developing-with-streamlit/SKILL.md`) is the path *inside the upstream repo*; on disk the skill dir is copied to `~/.agents/skills/developing-with-streamlit/`.

A filesystem-wide sweep found no other omp-relevant skill root in use on this machine:

```console
$ find ~ -name 'SKILL.md' -not -path '*/node_modules/*' 2>/dev/null
/home/wavy/.agents/skills/agent-browser/SKILL.md
/home/wavy/.agents/skills/find-skills/SKILL.md
/home/wavy/.agents/skills/developing-with-streamlit/SKILL.md
… plus unrelated vendored copies inside Python site-packages
  (fastapi, typer, sqlmodel, playwright), ~/.claude/plugins/marketplaces/…,
  ~/.codex/plugins/cache/…, and ~/code-src-20260224/… (codex source tree).
```

Directories omp *could* use but that **do not exist** here: `~/.omp/skills`, `~/.omp/agent/skills`, `~/.omp/agent/skills.json`, `~/.omp/agent/skills.lock.json`.

---

## 2. omp's actual skill search paths (evidence: source + config + DB)

### 2.1 The config is silent — everything is default

`~/.omp/agent/config.yml` (complete file, 636 bytes, verbatim) contains **no `skills.*` key at all**:

```yaml
symbolPreset: nerd
theme:
  dark: titanium
  light: light
setupVersion: 2
modelRoles:
  default: opencode-go/deepseek-v4.1-flash
  smol: opencode-go/deepseek-v4.1-flash
  task: opencode-go/deepseek-v4.1-flash
  plan: opencode-go/deepseek-v4.1-flash
  slow: opencode-go/deepseek-v4.1-flash
  advisor: antigravity/gemini-3.8-flash
cycleOrder:
  - default
dev:
  autoqaConsent: granted
advisor:
  enabled: false
  subagents: false
task:
  maxConcurrency: 2
  softRequestBudget: 0
  agentIdleTtlMs: 120000
  agentModelOverrides:
    default: opencode-go/deepseek-v4.1-flash
tools:
  virtualize:
    - xd://lsp
    - xd://dap
    - xd://mcp
```

There is no `~/.omp/config.json`; the other `~/.omp/agent/*.json` files are MCP/model/routing state, not skills. So **all skill settings are at their code defaults**, which are:

```ts
// $OMP/src/extensibility/settings.ts
:29  cfgSkillsEnabled            "skills.enabled"            default true
:43  cfgSkillsEnableCodexUser    "skills.enableCodexUser"    default false
:45  cfgSkillsEnableClaudeUser   "skills.enableClaudeUser"   default false
:48  cfgSkillsEnableClaudeProject"skills.enableClaudeProject"default true
:53  cfgSkillsEnablePiUser       "skills.enablePiUser"       default true   // native ~/.omp/agent
:55  cfgSkillsEnablePiProject    "skills.enablePiProject"    default true   // <ancestor>/.omp/skills
:57  cfgSkillsEnableAgentsUser   "skills.enableAgentsUser"   default true   // ~/.agent[s]/skills  ← agent-browser
:60  cfgSkillsEnableAgentsProject"skills.enableAgentsProject"default true   // <ancestor>/.agent[s]/skills
:66  cfgSkillsCustomDirectories  "skills.customDirectories"  default []
:72  cfgSkillsIgnoredSkills      "skills.ignoredSkills"      default []
:78  cfgSkillsIncludeSkills      "skills.includeSkills"      default []
```

### 2.2 Provider table (paths are exact, from source)

| # | Provider id (priority) | User-level (`~/`) path | Project-level path | Default on? |
|---|---|---|---|---|
| 1 | `native` (100) | `~/.omp/agent/skills/<name>/SKILL.md` | `<ancestor>/.omp/skills/<name>/SKILL.md` (walk-up cwd→repoRoot) | yes (`enablePiUser`/`enablePiProject`) |
| 2 | `skillshare` (95) | pins in `~/.omp/agent/skills.lock.json`, unpacked at `~/.omp/skillshare/@scope/<name>/<version>/SKILL.md` | `<ancestor>/.omp/skills.lock.json` | yes (only if a lockfile exists) |
| 3 | `omp-plugins` (90) | `~/.omp/plugins/node_modules/<pkg>/skills/<name>/SKILL.md` | plugin roots from `extensions:` | yes |
| 4 | `claude` (80) | `~/.claude/skills/<name>/SKILL.md` | `<ancestor>/.claude/skills/…` | user **off**, project on |
| 5 | `agent-plugins` (75) | plugin packages (`plugin.json` + `skills/`) | same | yes |
| 6 | `claude-plugins` (70) | `~/.claude/plugins/**` (opt-in) | — | opt-in |
| 7 | **`agents` (70)** | **`~/.agent/skills/<name>/SKILL.md` and `~/.agents/skills/<name>/SKILL.md`** | **`<ancestor>/.agent[s]/skills/…`** | **yes (both levels)** |
| 8 | `codex` (70) | `~/.codex/skills/…` | `<cwd>/.codex/skills/…` | user **off** |
| 9 | `opencode` (55) | `~/.config/opencode/skills/…` | `<cwd>/.opencode/skills/…` | opt-in (user) |
| 10 | `github` (30) | — | `<cwd>/.github/skills/<name>/SKILL.md` | yes |
| 11 | `omp-managed` (5) | `~/.omp/agent/managed-skills/<name>/SKILL.md` | — | yes (auto-learn output) |

Plus `skills.customDirectories` (provider id `custom`), which scans each configured dir non-recursively as `*/SKILL.md`.

Evidence for the two rows that matter here:

```ts
// $OMP/src/discovery/agents.ts — the provider that owns agent-browser
:158 async function loadSkills(ctx: LoadContext): Promise<LoadResult<Skill>> {
:159   const projectScans = getProjectPathCandidates(ctx, "skills").map(dir =>
:160     scanSkillsFromDir(ctx, { dir, providerId: PROVIDER_ID, level: "project" }),
:162   const userScans = getUserPathCandidates(ctx, "skills").map(dir =>
:163     scanSkillsFromDir(ctx, { dir, providerId: PROVIDER_ID, level: "user" }),
:177   description: "Load skills from .agent/skills and .agents/skills (project walk-up + user home)",
```
```ts
// $OMP/src/discovery/agents.ts
:29 const AGENT_DIR_CANDIDATES = [".agent", ".agents"] as const;
:141 export function getUserPathCandidates(ctx, ...segments) {
:142   return getUserHomeCandidates(ctx).flatMap(home =>
:143     AGENT_DIR_CANDIDATES.map(baseDir => path.join(home, baseDir, ...segments)));
// getProjectPathCandidates walks cwd → repoRoot, emitting <ancestor>/.agent/<seg> and
// <ancestor>/.agents/<seg> at each level, skipping $HOME (user level is enumerated separately).
```
```ts
// $OMP/src/discovery/builtin.ts — native (.omp)
:309 async function loadSkills(ctx: LoadContext) {
:316       dir: path.join(dir, PATHS.projectDir, "skills"),   // <ancestor>/.omp/skills
:319       requireDescription: true,
:326   dir: path.join(getAgentDir(), "skills"),               // ~/.omp/agent/skills
:329   requireDescription: true,
```
```ts
// $OMP/src/capability/index.ts:51-60 — only these are opt-in foreign roots
const FOREIGN_USER_PROVIDERS = { cursor, codex, claude, "claude-plugins", gemini, opencode, windsurf, github };
// :358 comment: "Native (.omp) and .agents directories are enabled by default."
```

Official doc agrees (`omp://skills.md`): *"Skills are file-backed capability packs discovered at startup"*; provider list matches the table above; *"For conventional provider roots (native/Claude/Codex/Agents/plugins), skills are discovered as one level under `skills/`: `<skills-root>/<skill-name>/SKILL.md` … Nested patterns like `<skills-root>/group/<skill>/SKILL.md` are not discovered recursively."*

### 2.3 `skill-descriptions.db` is a **cache**, not a registry

```console
$ python3 -c "sqlite3 read-only: list tables, schema, rows"
TABLE: skill_descriptions
  cols: ['key', 'description']      count: 3
  ROW: ('2d3024243fb7e7f7…', 'Use to interact with websites, automate browser tasks, or test web apps.')
  ROW: ('47be5f4cf4312a5c…', 'Streamlit apps: build, edit, debug, style, theme, deploy, components, session state.')
  ROW: ('dc2e4ed71f8fc223…:opencode-go/deepseek-v4.1-flash', 'Helps users discover and install agent skills when they ask questions like "how do I do X", "find…')
```

Schema/code (`$OMP/src/extensibility/skill-descriptions.ts`):

```ts
:224 CREATE TABLE IF NOT EXISTS skill_descriptions (key TEXT PRIMARY KEY, description TEXT NOT NULL)
:98  function keyFor(skill) { return sha256(compressDescriptionPrompt + "\0" + skill.name + "\0" + skill.description) }
:120 export function previewSkillDescription(description) { …100-char truncation… }   // MAX_PREVIEW_CHARS = 100
:32  const MAX_COMPRESSED_CHARS = 160; const MAX_COMPRESSED_WORDS = 12;
:245 * "A `<key>:<provider/id>` row records that model's unusable answer, so it is not asked again…"
:328 render(skills) { … store.get(key) ?? previewSkillDescription(skill.description); if missing → #schedule(store,key,skill) }
```

So: at **system-prompt render time** omp tries to compress each skill's front-matter `description` into ≤160 chars/≤12 words using the `smol` role model and caches the result here. The keys are content hashes (not skill names), so rows say nothing about what is discoverable. Row 3's `:opencode-go/deepseek-v4.1-flash` suffix means "compression was unusable for that model; keep the preview". That is corroborated by the log of the process that rendered the post-install list:

```console
$ cat ~/.omp/logs/omp.2026-10-16.1659891.log
{"timestamp":"2026-10-16T21:07:33.743-05:00","level":"warn","pid":1659891,
 "message":"Skill description compression unusable; keeping the preview for this model",
 "skill":"find-skills","model":"opencode-go/deepseek-v4.1-flash"}
```

Rows 1 and 2 are successful compressions (row 2 is exactly 12 words). **No DB entry is needed for a skill to be discovered or usable** — confirmed by the probe in §5: `zz-probe-skill` was discovered with the DB still holding 3 rows. The DB lives at `~/.omp/agent/skill-descriptions.db` and is only touched by prompt rendering (`omp skill list` did not add rows).

---

## 3. What makes a skill discoverable

Scanner (`$OMP/src/discovery/helpers.ts:463-534`), which every conventional provider funnels through:

```ts
:473  entries = await fs.promises.readdir(dir, { withFileTypes: true });   // ENOENT → empty, no warning
:485  if (frontmatter.enabled === false) return;                            // opt-out
:488  if (requireDescription && !frontmatter.description) return;           // per-provider requirement
:491  const skillDirName = path.basename(path.dirname(skillPath));
:493  const name = typeof rawName === "string" ? rawName.trim() || skillDirName : skillDirName;
:496  if (/[\\/]/.test(name)) { warnings.push(`Skill name "…" contains a path separator, skipping`); return; }
:520  for (const entry of entries) {
:521    if (entry.name.startsWith(".")) continue;                            // dot-dirs skipped
:522    if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;      // ← SYMLINKS ARE FOLLOWED
:523    const skillPath = path.join(dir, entry.name, "SKILL.md");           // existsSync follows links
:524    if (fs.existsSync(skillPath)) work.push(loadSkill(skillPath));
```

Facts established:

1. **File name is exactly `SKILL.md`**, one directory under the root: `<root>/<skill-name>/SKILL.md`. Flat `<root>/SKILL.md` is only read when a provider passes `includeSelf` (plugin packages), never for `.agent[s]`/`.omp` roots.
2. **Non-recursive**: `<root>/group/<skill>/SKILL.md` is invisible; the `skills.customDirectories` scan has the same one-level rule (per `omp://skills.md`).
3. **Symlinked skill directories are followed** (`isSymbolicLink()` passes the filter; `existsSync` resolves the target). Verified empirically (§5).
4. **`name`** comes from front-matter, falling back to the directory name; a name containing `/` or `\` is rejected.
5. **`description` is required only for** `native` (`.omp`), `omp-plugins`, `github`, and `skills.customDirectories`. The `agents` provider does **not** require it (verified: a description-less `.agents/skills` skill is discovered) — but without a description the system-prompt hint degrades to the name, so always write one.
6. **`enabled: false` skips** the skill entirely.
7. **`hide: true`** (or the Agent-Skills spelling `disable-model-invocation: true`) does *not* disable it: it stays loadable via `skill://<name>` and `/skill:<name>` but is dropped from the prompt's `<skills>` list (`$OMP/src/system-prompt.ts:938`: `skills.filter(skill => skill.hide !== true)`). Verified: both probe variants reported `hide= True`.
8. **Exposure to a model requires a tool declaring `readsSkillUris`** (the `read` tool does; `$OMP/src/system-prompt.ts:919-931`). Subagents get the **session's** skill list — `omp://skills.md`: *"Task tool subagents receive the session's discovered/provided skills list via normal session creation; there is no per-task skill pinning override."*
9. **Scan happens at session/process start.** There is no watcher and no index. (See §7.)

### Front-matter shape (canonical example: the working skill)

```markdown
---
name: agent-browser
description: Browser automation CLI for AI agents. Use when the user needs to interact with websites, …
allowed-tools: Bash(agent-browser:*), Bash(npx agent-browser:*)
hidden: true
---

# agent-browser
… body …
```

Supported fields (`$OMP/src/capability/skill.ts:11-36`): `name?`, `description?`, `globs?`, `alwaysApply?`, `hide?`, `disableModelInvocation?` (normalized from kebab-case `disable-model-invocation`), plus arbitrary extra keys (preserved as unknown metadata). Also honored by the scanner: `enabled: false`.

Two notes on that file: `allowed-tools` is a Claude-Code field that omp preserves but does **not** enforce for `.agents` skills, and **`hidden: true` is a typo-ish no-op** — omp's field is `hide`, so `agent-browser` is in fact listed in the prompt (as observed). Skills invoked via `/skill:<name>` get `[Skill directory: <baseDir>]` appended so relative script paths resolve; the `${CLAUDE_SKILL_DIR}` placeholder used by `developing-with-streamlit`'s `allowed-tools` is Claude-specific and not expanded by omp — that skill's own `SKILL.md` instructs `<SKILL_DIR>` resolution in prose, which does work.

---

## 4. `skill://` resolution

* `skill://<name>` → that skill's `SKILL.md`; `skill://<name>/<relative-path>` → a file inside the skill dir (absolute paths and `..` rejected).
* Resolution is against the **session's loaded skill set**, so an unknown name errors with the available list:
  ```console
  $ read skill://find-skills          # inside the live session (started Oct 14)
  Unknown skill: find-skills
  Available: agent-browser
  ```
* Name collisions are resolved by provider priority; the loser gets a `<namespace>/<name>` alias (e.g. `skill://streamlit/developing-with-streamlit`). See `omp://skills.md` §"Collision and duplicate handling".

---

## 5. Empirical probe (harmless, outside the repo)

Created under `~/.agents/skills/` and a scratch dir, never inside `/home/wavy/ai/aa-mcp`.

```console
$ mkdir -p ~/.agents/skills/zz-probe-skill && cat > …/SKILL.md <<'EOF'
---
name: zz-probe-skill
description: Probe skill used to verify omp skill discovery. Delete me.
---
EOF
$ mkdir -p /tmp/zz-src-skill && … SKILL.md (name: zz-probe-symlink)
$ ln -sfn /tmp/zz-src-skill ~/.agents/skills/zz-probe-symlink          # symlinked dir
$ mkdir -p /tmp/zz-probe-proj/.agents/skills/zz-proj-agents-skill      # project-level
$ mkdir -p /tmp/zz-probe-proj/.omp/skills/zz-proj-native-withdesc      # native project, w/ description
$ mkdir -p /tmp/zz-probe-proj/.omp/skills/zz-proj-native-nodesc        # native project, NO description
```

Results (`omp skill list --json`, a **fresh** process — `$OMP/src/cli/skill-list.ts:29` documents it as *"Discover skills for a directory exactly as a session would and report them"*):

```console
$ cd /tmp && omp skill list --json
count: 5
 - agent-browser       | src= agents:user | /home/wavy/.agents/skills/agent-browser/SKILL.md
 - developing-with-streamlit | src= agents:user | …
 - find-skills         | src= agents:user | …
 - zz-probe-skill      | src= agents:user | /home/wavy/.agents/skills/zz-probe-skill/SKILL.md
 - zz-probe-symlink    | src= agents:user | /home/wavy/.agents/skills/zz-probe-symlink/SKILL.md   ← symlink followed
warnings: []

$ cd /tmp/zz-probe-proj && omp skill list --json
count: 7
 - … (5 above) …
 - zz-proj-agents-skill     | src= agents:project | /tmp/zz-probe-proj/.agents/skills/zz-proj-agents-skill/SKILL.md
 - zz-proj-native-withdesc  | src= native:project | /tmp/zz-probe-proj/.omp/skills/zz-proj-native-withdesc/SKILL.md
   (zz-proj-native-nodesc is ABSENT → native requires `description`)

$ cd /tmp && omp skill list --json     # front-matter edge cases
count: 8
 - zz-probe-dmi      | hide= True    # disable-model-invocation: true
 - zz-probe-hidden   | hide= True    # hide: true
 - zz-probe-nodesc   | hide= False   # no description → still discovered (agents provider)
 - zz-probe-skill    | hide= False
 - zz-probe-symlink  | hide= False
   (zz-probe-disabled with `enabled: false` is ABSENT)

$ read skill://zz-probe-skill          # inside the ALREADY-RUNNING session
Unknown skill: zz-probe-skill
Available: agent-browser

$ sqlite3 skill-descriptions.db → still 3 rows (probe added none)
```

**Probe result: discovery works exactly as the code predicts** — new user-level and project-level skills are picked up by a fresh process immediately, symlinked skill dirs are followed, `description` is mandatory only for `.omp`, `enabled: false` hides, `hide`/`disable-model-invocation` only de-lists from the prompt. **A new skill is *not* visible to an already-running session** (§7). No restart of the runtime was needed to validate the probe; `omp skill list` is a fresh process.

**Cleanup (done):** removed `~/.agents/skills/zz-probe-{skill,nodesc,hidden,dmi,disabled,symlink}`, `/tmp/zz-src-skill`, `/tmp/zz-probe-proj`. Post-cleanup `omp skill list --json` reports the original 3 skills and `ls ~/.agents/skills/` shows only `agent-browser`, `developing-with-streamlit`, `find-skills`.

---

## 6. Why the *live* session can't see the new skills (restart requirement)

* My session runs in omp **pid 2310857, started Wed Oct 14 08:47:43 2026**, cwd `/home/wavy/ai/aa-mcp`, session id `01a13aab-a22f-720b-aadd-d07750386de0`:
  ```console
  $ for p in <omp pids>; do echo "$p | $(readlink /proc/$p/cwd) | $(ps -o lstart= -p $p)"; done | grep aa-mcp
  2310857 | /home/wavy/ai/aa-mcp | Wed Oct 14 08:47:43 2026
  ```
* `developing-with-streamlit` and `find-skills` were installed **2026-10-17T02:06Z = Oct 16 21:06 local** — *after* that process started. Its skill snapshot therefore contains only `agent-browser` (installed 2026-05-30), which is exactly what the prompt `<skills>` block and `read skill://…` report.
* A fresh process started 21:07 (`pid 1659891`) did discover them — hence the DB rows and the `find-skills` log line.

**Conclusion: discovery is a start-of-session scan. Anything added to disk afterwards is invisible until a refresh or restart.**

### Live refresh triggers (no restart needed, in principle)

```ts
// $OMP/src/session/agent-session.ts:6378-6401 — refreshSkillsAndCommands(): resetCapabilities() →
//   reload slash commands → tools.refreshSkills() → rebuild prompt → notify command-metadata listeners
// $OMP/src/sdk.ts:4896 — cfgSkillsAndCommandsDiscovery.listen(session, () => session.refreshSkillsAndCommands());
//   watched settings: skills.*, commands*.enable*, enabledProviders/disabledProviders  (sdk.ts:408-417)
// $OMP/src/slash-commands/builtin-skills.ts:55-61 — /skills install|update → reportChanges() → ctx.refreshSkillState()
// $OMP/src/modes/interactive-mode.ts:2637 — refreshSkillState() → session.refreshSkills()
// also triggered on workspace/cwd switch (interactive-mode.ts:2778-2804) and plugin reload
// $OMP/src/slash-commands/builtin-lifecycle.ts:839 — slash command `/restart`
//   "Restart omp with the same launch flags, resuming this session"
```

Practically: a skill dropped in out-of-band (git clone, `npx skills add`, unzip) is **not** auto-detected. Refresh it by any of: `/skills install …` (registry path), toggling any `skills.*` setting in the settings UI (fires the listener), switching workspace, or `/restart`. `/reload` is MCP-only. The safest, most predictable instruction is **restart the session** (`/restart` or a new `omp`).

---

## 7. Install recipe for a skill distributed as a GitHub repo

Reference case: `streamlit/agent-skills` → `developing-with-streamlit/SKILL.md` (already present here, see §1); and this repo's own `artificial-analysis-skill.zip`:

```console
$ unzip -l /home/wavy/ai/aa-mcp/artificial-analysis-skill.zip
        0  … artificial-analysis-skill/
     7203  … artificial-analysis-skill/SKILL.md
     7439  … artificial-analysis-skill/references/metrics.md
    39102  … artificial-analysis-skill/scripts/aa.py
```

The upstream repo's **skill directory** (the one containing `SKILL.md`) is what gets installed; its parent (`skills/` in `vercel-labs/agent-browser`, the repo root in `streamlit/agent-skills`) is just packaging.

### A. User-global (all projects on this machine) — recommended default

```bash
# pick the skill dir out of the upstream repo (clone shallow, or use npx skills)
git clone --depth 1 https://github.com/streamlit/agent-skills /tmp/agent-skills
cp -r /tmp/agent-skills/developing-with-streamlit ~/.agents/skills/developing-with-streamlit
#   → ~/.agents/skills/developing-with-streamlit/SKILL.md   ✅ discovered, no config change
```

or the ecosystem CLI (what was used for the existing three; `installedAt` in the lockfile matches the on-disk mtimes to the second, so the CLI's canonical install root on this machine is `~/.agents/skills/` — `[INFERENCE]` from the lockfile plus the resulting directory layout, the CLI itself was not re-run):

```bash
npx skills add streamlit/agent-skills        # → ~/.agents/skills/<skill>/ + ~/.agents/.skill-lock.json
```

then **restart the omp session**. Agents then use `read skill://developing-with-streamlit` (and `/skill:developing-with-streamlit`).

### B. Project-local (this repo only) — the user's "set this repo up" case

Two supported roots, both scanned by walk-up from the session cwd to the git root:

```bash
mkdir -p <repo>/.agents/skills
cp -r /tmp/agent-skills/developing-with-streamlit <repo>/.agents/skills/     # agents provider: description optional
#   → <repo>/.agents/skills/developing-with-streamlit/SKILL.md   ✅ (src= agents:project)

# or the native root (description REQUIRED):
mkdir -p <repo>/.omp/skills
cp -r … <repo>/.omp/skills/developing-with-streamlit
#   → <repo>/.omp/skills/developing-with-streamlit/SKILL.md      ✅ (src= native:project)
```

Precedence if both exist: `native` (priority 100) beats `agents` (70), so a same-named `.omp/skills` copy wins the bare `skill://<name>`; the other is reachable under a `<namespace>/<name>` alias. Project skills also apply to subagents spawned with that cwd. Verified with the scratch dir in §5 (`agents:project` and `native:project` both discovered from a plain, non-git directory).

### Copy vs symlink vs git submodule

| Approach | How | Pros | Cons |
|---|---|---|---|
| **Copy** (`cp -r`) | `<root>/<skill-name>/` is a real dir | Simplest; self-contained; no dangling links; works with `npx skills update` | Snapshot — upstream changes need a re-copy; content duplicated (and, for project installs, either committed to this repo or untracked) |
| **Symlink** (`ln -s`) | `<root>/<skill-name>` → your clone | Single source of truth; update with `git pull` in the clone | Verified: discovery **does follow symlinked skill dirs**. But a dangling link is silently invisible (scan is `existsSync`-based), it isn't portable across machines/checkouts, and a `git`-tracked project symlink points outside the repo |
| **git submodule** | clone upstream as a submodule, point omp at it | Reproducible pin, no duplication | Layout mismatch: a submodule of the *repo* lands as `<dir>/<skill-name>/SKILL.md` — one level too deep for the non-recursive scan. You must either check out only the skill dir (sparse-checkout) so it *is* `<root>/<skill-name>/`, or add `skills.customDirectories: ["<abs-or-~/path/to/submodule-parent>"]` to `~/.omp/agent/config.yml` (custom dirs scan one level as `*/SKILL.md` and require `description`) |

`skills.customDirectories` (config change — **described, not applied**; `~/.omp/agent/config.yml` was left untouched):

```yaml
skills:
  customDirectories:
    - /home/wavy/ai/aa-mcp/vendor/agent-skills     # scans vendor/agent-skills/*/SKILL.md
```

Use an absolute path (or `~/…`); relative entries are resolved against the inspected directory by `omp skill list` and are ambiguous for a session. Changing this setting in a live session fires the discovery listener and refreshes immediately (`$OMP/src/sdk.ts:4896`).

### Restart requirements — summary

| What you did | Refresh needed |
|---|---|
| `cp`/clone/symlink/unzip a skill into `.agents/skills` or `.omp/skills` | **New omp process** (`/restart`, or start a new session). A live session keeps its snapshot (verified). |
| `omp skill install` / `/skills install` (Skillshare registry, `skills.omp.sh`) | No — `reportChanges()` → `refreshSkillState()` reloads in-session |
| Toggled any `skills.*` setting / `enabledProviders` in the settings UI | No — settings listener calls `refreshSkillsAndCommands()` |
| Edited `skills.customDirectories` in `config.yml` by hand | Yes, restart (file edit doesn't fire the in-memory listener) |
| Deleted/edited the `SKILL.md` of an existing skill | Restart — the body is snapshotted at session start |

---

## 8. Gotchas observed

* The upstream repo's *packaging* dir must not be copied wholesale: copying the `streamlit/agent-skills` repo root into `~/.agents/skills/` would yield `~/.agents/skills/agent-skills/developing-with-streamlit/SKILL.md` — not discovered (non-recursive). Copy the skill dir itself.
* Front-matter `hidden: true` (as in `agent-browser`) is a **no-op** in omp; the field is `hide`.
* `description` is mandatory for `.omp/skills` but not for `.agents/skills` — keep it mandatory in practice, since it is the routing hint in the prompt and the source of the cached compressed blurb.
* A skill whose front-matter `name` contains `/` or `\` is skipped with a warning.
* `omp skill list [dir] --json` is the read-only way to see exactly what a session in `dir` would resolve (`name`, `description`, `filePath`, `baseDir`, `source`, `hide`, plus `warnings`) — ideal for verifying an install before restarting.
* `~/.agents/.skill-lock.json` belongs to the third-party `npx skills` CLI; omp ignores it, so deleting it does not affect omp (it only breaks `npx skills update`).

---

## 9. Direct answer

**Where do I put a skill so omp agents can use it, and does anything need to be refreshed?**
Put the skill's own directory — the one containing `SKILL.md` — at `<skill-name>/` under a skills root: **`~/.agents/skills/`** for all projects on this machine, or **`<repo>/.agents/skills/`** (or `<repo>/.omp/skills/`, which additionally requires a `description:` in front-matter) for just this repository; the root must already exist or be created, the file must be named exactly `SKILL.md`, and the layout must not be nested deeper. No config change is required on this machine (the relevant settings are unset and default to enabled) and there is no registry or index to update — `~/.omp/agent/skill-descriptions.db` is only a cache of compressed description blurbs regenerated lazily at prompt render time. The one thing that *does* need refreshing is the running session: skill discovery happens once at process/session start, so a skill copied/cloned/symlinked/unzipped into place is invisible to an already-running session (proved: the live session answers `Unknown skill` while a fresh `omp skill list` finds it) — restart the session (`/restart` or a new `omp`) after installing, unless you install through the in-session `/skills install` path or change a `skills.*` setting, both of which trigger a live reload. Afterwards agents reference the skill as `skill://<skill-name>` and `/skill:<skill-name>`.
