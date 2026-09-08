# .hermes — repo-local Hermes parity with .claude

Local-only mirror. Nothing here touches the global profile (`~/.hermes/`).
Hermes loads these skills for sessions started inside this repo after trust:

  hermes skills trust             # run once from this repo root
  hermes skills trust /home/rafal/repos/geopoliticai   # explicit path variant

Verify:

  hermes chat -q "/rs-brainstorming" --help  # slash commands auto-register per skill
  # or in-session: /reload-skills, then /rs-plan-from-brainstorm, /preflight-scout, ...

## What is mirrored

| .claude source | .hermes mirror | Notes |
|---|---|---|
| `skills/*` (22 dirs) | `skills/*` verbatim copies | Same SKILL.md + references/scripts. Re-sync on .claude updates (command below). Includes `swarm`, which `.opencode/skills` lacks. |
| `commands/rs-*.md` (6) | `skills/rs-*/SKILL.md` | Hermes registers every skill as `/<name>`, so `/rs-brainstorming` etc. work. `name:` added from filename; `allowed-tools` kept as a hint only — Hermes grants tools per session, not per skill. |
| `agents/*.md` (5) | `skills/<agent>/SKILL.md` | Hermes has no repo-local agents dir; roles are ported as skills. Load via `skill_view("<name>")` and run via `delegate_task`, or `/<name>`. All five are read-only by contract. |
| `CLAUDE.md` / `AGENTS.md` | (no copy) | Hermes already injects `AGENTS.md` (cwd) automatically. Deliberately no `.hermes.md` here — it would outrank and shadow `AGENTS.md` (first-match-wins). |
| `hooks/` | (empty upstream) | Nothing to port. Repo-local hooks live under `.hermes/hooks/`; project plugins under `.hermes/plugins/` (require `HERMES_ENABLE_PROJECT_PLUGINS=1`). |

## Intentionally NOT ported (global-only in Hermes)

- `.claude/settings.json` permissions (allow Read/Edit/Write/Glob/Grep, `Bash(git/gh/make *)`; deny `.env` reads/edits).
  Hermes equivalent is global: `approvals` / `command_allowlist` in `~/.hermes/config.yaml`.
  Kept out on purpose per "local only" — if you want it, run e.g.
  `hermes config set approvals.mode smart` (global, affects all repos).
- `.claude/settings.local.json` (`enabledPlugins`, per-skill `skillOverrides` off-list).
  No repo-local equivalent; manage via `hermes plugins` / `hermes skills config` (global).
- `.mcp.json` (`context7` via npx). Hermes MCP servers are global config.
  To enable globally: `hermes mcp add context7 --command npx --args -y @upstash/context7-mcp` (not run — would leave repo scope).

## Re-sync after .claude changes

  cd /home/rafal/repos/geopoliticai
  rm -rf .hermes/skills && mkdir -p .hermes/skills
  cp -r .claude/skills/. .hermes/skills/
  for f in .claude/commands/*.md; do n=$(basename $f .md); mkdir -p .hermes/skills/$n; cp $f .hermes/skills/$n/SKILL.md; done
  for f in .claude/agents/*.md; do n=$(basename $f .md); mkdir -p .hermes/skills/$n; cp $f .hermes/skills/$n/SKILL.md; done
  # then add `name: <dir>` as the first frontmatter line in each
  # .hermes/skills/rs-*/SKILL.md (agents already carry `name:`)
  hermes skills trust

Trust is stored globally as a path entry (`skills.trusted_project_dirs` in
`~/.hermes/config.yaml`) but grants nothing outside this repo path.
Scans are content-hash cached under `~/.hermes/cache/project_skill_scans/`, never in the repo.
