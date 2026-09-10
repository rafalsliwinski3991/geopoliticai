# Repository AI Tool Inventory

All inventory tables in this file must use the same provider-matrix format:
the first column contains the skill, command, plugin, agent, or hook name, and
the remaining columns contain one column per provider (`GitHub Copilot`,
`OpenCode`, `Claude`, and `Codex`). Provider cells must use `yes` or `no`.
Paths, configuration details, and explanatory notes belong below the table.

This is the detailed inventory of the repository's AI harnesses and tools.
Providers are identified by their repository configuration directories:
`.github` (GitHub Copilot and GitHub CLI workflows), `.opencode` (OpenCode),
`.claude` (Claude Code), and `.codex` (Codex).

This file is the single home for detailed repository AI-tool layout facts.
The three codebase guidance files (`AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md`) contain the shared change policy and concise
development workflow; this file contains the detailed inventory.

After any repository change, update `AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md` together. After any addition, removal, rename,
or modification of a provider's skills, hooks, plugins, agents, commands, or
related AI-tool configuration, update this file in the same change.

## Repository Locations

- `.github/skills/` - GitHub Copilot skills with bundled references and
  scripts.
- `.opencode/skills/` - OpenCode-local skill catalog; no repository-local skill
  path is currently configured in `opencode.jsonc`.
- `.codex/skills/` - Codex skill catalog containing shared and project-local
  skills.
- `.codex/config.toml` - project agent, thread, marketplace, and plugin
  settings.
- `.codex/plugins/` and `.codex/.tmp/` - ignored, repository-scoped Codex
  plugin and marketplace caches when Codex runs with `CODEX_HOME=.codex`.
- `.codex/agents/` - four Codex role definitions.
- `.claude/skills/` - Claude skills; `swarm` exists only here. The removed Phoenix
  symlinks are no longer consumers of the deleted `.agents/skills/` catalog.
- `.opencode/commands/` - OpenCode commands: `review`, `plan-review`, and a
  native `rs-implement-plan` variant.
- `.opencode/command/` - OpenCode copies of four Claude `rs-*` commands
  (`rs-brainstorming`, `rs-implement-plan`, `rs-improve-plan`, and
  `rs-plan-from-brainstorm`) with the Claude-only `argument-hint` and
  `allowed-tools` frontmatter keys removed; bodies are otherwise unchanged.
  The two `rs-implement-plan-as-*` Claude commands were not ported because they
  dispatch through Claude Code plugins that do not exist in opencode.
- `.claude/commands/` - Claude Code commands: `rs-plan-from-brainstorm`,
  `rs-improve-plan`, `rs-implement-plan`, `rs-implement-plan-as-codex`,
  `rs-implement-plan-as-opencode`, and `rs-brainstorming`.
- `.github/workflows/` - GitHub Actions workflows, including unit tests; the
  repository also uses the GitHub CLI (`gh`) for permitted repository tasks.
- `.claude/hooks/` and `.codex/hooks/` - contain no active hook
  implementations; the `.claude/hooks/.klaussy-version` file is metadata.
- `docs/brainstorming/` - durable session artifacts written by the
  `rs-brainstorming` command (Claude and OpenCode), not at the repository root.

## Commands

| Command or workflow | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| implement-plan | no | no | no | yes |
| improve-plan | no | no | no | yes |
| plan-from-brainstorm | no | no | no | yes |
| plan-review | no | yes | no | no |
| review | no | yes | no | no |
| rs-implement-plan | no | yes | yes | no |
| rs-implement-plan-as-codex | no | no | yes | no |
| rs-implement-plan-as-opencode | no | no | yes | no |
| rs-improve-plan | no | yes | yes | no |
| rs-plan-from-brainstorm | no | yes | yes | no |
| rs-brainstorming | no | yes | yes | no |

Command locations and implementation details:

- OpenCode commands: `.opencode/commands/review.md`,
  `.opencode/commands/plan-review.md`, and the native
  `.opencode/commands/rs-implement-plan.md`, which sets `agent: build` and
  `model: opencode-go/glm-5.3-flash` and runs TDD with tiered review itself
  rather than delegating to another harness. The `.opencode/command/`
  directory additionally holds direct copies of the Claude `rs-*` commands:
  `rs-brainstorming.md`, `rs-implement-plan.md`, `rs-improve-plan.md`, and
  `rs-plan-from-brainstorm.md`. `rs-implement-plan` therefore has two OpenCode
  definitions — the native variant in `.opencode/commands/` and the Claude
  port in `.opencode/command/`; resolve the duplicate before relying on
  `/rs-implement-plan` in opencode.
- Claude Code commands: `.claude/commands/rs-implement-plan.md`,
  `.claude/commands/rs-implement-plan-as-codex.md`,
  `.claude/commands/rs-implement-plan-as-opencode.md`,
  `.claude/commands/rs-improve-plan.md`, and
  `.claude/commands/rs-plan-from-brainstorm.md`, plus
  `.claude/commands/rs-brainstorming.md`. The Codex variant delegates all worker
  calls through `codex@openai-codex` as `/codex:rescue --wait --fresh --model
  gpt-5.6-terra --effort high`. The OpenCode variant delegates all worker calls
  through `opencode@tasict-opencode-plugin-cc` as `/opencode:rescue --wait
  --fresh --model gpt-5.6-luna`, with `--agent build` for implementers and
  `--agent plan` for read-only scouts/auditors/reviewers.
- Codex workflows are skills under `.codex/skills/`; there is no
  `.codex/commands/` directory.

GitHub Actions workflows are stored in `.github/workflows/` and
`app/.github/workflows/`; they are CI automation rather than interactive
harness commands. The GitHub CLI (`gh`) is used through permitted shell
commands and has no repository-local command definition.

## Plugins

| Plugin | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| context7@claude-plugins-official | no | no | yes | no |
| codex@openai-codex | no | no | yes | no |
| opencode@tasict-opencode-plugin-cc | no | no | yes | no |
| ponytail@ponytail | no | no | no | yes |

Plugin configuration details:

- `context7@claude-plugins-official`, `codex@openai-codex`, and
  `opencode@tasict-opencode-plugin-cc` are enabled in
  `.claude/settings.local.json`.
- `ponytail@ponytail` version 4.9.0 is enabled only for this repository in
  `.codex/config.toml`. Launch it with `CODEX_HOME="$PWD/.codex" codex` so
  Codex uses the repository-local marketplace and plugin cache; do not add it
  to `~/.codex`. In a new Codex thread, use `/hooks` to review and explicitly
  trust Ponytail's two lifecycle hooks.
- Context7 provides `resolve-library-id` and `query-docs` MCP tools for
  version-specific external library documentation; Claude workflows use them when
  current external APIs affect a decision.
- No repository-local plugin configuration is present for GitHub Copilot.

## Skills

| Skill | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| deep-agents-core | yes | yes | yes | yes |
| deep-agents-memory | yes | yes | yes | yes |
| deep-agents-orchestration | yes | yes | yes | yes |
| deepagents-python-quickstart | yes | yes | yes | yes |
| deepagents-typescript-quickstart | yes | yes | yes | yes |
| ecosystem-primer | yes | yes | yes | yes |
| eval-engineering | yes | yes | yes | yes |
| rs-brainstorming | no | no | no | yes |
| langchain-dependencies | yes | yes | yes | yes |
| langchain-fundamentals | yes | yes | yes | yes |
| langchain-middleware | yes | yes | yes | yes |
| langchain-python-quickstart | yes | yes | yes | yes |
| langchain-rag | yes | yes | yes | yes |
| langchain-typescript-quickstart | yes | yes | yes | yes |
| langgraph-cli | yes | yes | yes | yes |
| langgraph-fundamentals | yes | yes | yes | yes |
| langgraph-human-in-the-loop | yes | yes | yes | yes |
| langgraph-persistence | yes | yes | yes | yes |
| langgraph-python-quickstart | yes | yes | yes | yes |
| langgraph-typescript-quickstart | yes | yes | yes | yes |
| langsmith-online-eval-engineering | yes | yes | yes | yes |
| managed-deep-agents | yes | yes | yes | yes |
| swarm | no | no | yes | no |

The `rs-brainstorming` command (Claude and OpenCode) stores its session files
under `docs/brainstorming/`, not at the repository root, named
`<YYYYMonDD>_brainstorm_v<N>_<topic-slug>.md`. The `rs-plan-from-brainstorm`
command (Claude and OpenCode) writes to `docs/plans/` as
`<date>_plan_<topic-slug>_v<N>.md`, reusing the brainstorm's date but
deriving its own 1-3-word topic slug from what the plan implements rather
than copying the brainstorm's slug verbatim.

All four repository skill catalogs contain no directories whose names begin
with `python-`. Python-related framework quickstarts with names such as
`deepagents-python-quickstart`, `langchain-python-quickstart`, and
`langgraph-python-quickstart` are distinct names and remain present.

## Agents

| Agent | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| orchestrator | no | no | no | yes |
| explorer | no | no | no | yes |
| builder | no | no | no | yes |
| critic | no | no | no | yes |

Codex has agents enabled with up to six concurrent session threads. Its four
role definitions are `orchestrator`, `explorer`, `builder`, and `critic`; the
current model, reasoning, and sandbox settings are maintained in
`.codex/agents/*.toml` and `.codex/config.toml`.

The OpenCode slash commands listed above instruct the current agent to perform
repository workflows directly; OpenCode has no dedicated `critic` subagent.
The Codex `critic` agent (`.codex/agents/critic.toml`) is the only read-only
reviewer subagent, and no other provider ships matching agents.

## Hooks

The hook table includes executable hook implementations only. There are
currently no active repository-local hooks or hook configuration for any
provider. The Claude `.claude/hooks/.klaussy-version` file is metadata and is
therefore excluded.

| Hook | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
