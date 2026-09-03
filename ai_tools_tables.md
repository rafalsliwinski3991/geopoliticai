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
- `.opencode/skills/` - OpenCode-local skill catalog; `opencode.jsonc` currently
  points at the missing `.agents/skills` path instead.
- `.codex/skills/` - Codex skill catalog containing shared and project-local
  skills.
- `.codex/config.toml` - project agent and thread settings.
- `.codex/agents/` - four Codex role definitions.
- `.claude/skills/` - Claude skills; `swarm` exists only here.
- `.opencode/oh-my-opencode-slim.jsonc` - OpenCode plugin presets and agent
  roles; the active plugin is `oh-my-opencode-slim@latest`.
- `.opencode/commands/` - OpenCode commands: `review`, `plan-review`, and
  `implement-plan`.
- `.claude/commands/` - Claude Code commands: `rs-plan-from-brainstorm`,
  `rs-improve-plan`, `rs-implement-plan`, and `rs-implement-plan-as-codex`.
- `.github/workflows/` - GitHub Actions workflows, including unit tests; the
  repository also uses the GitHub CLI (`gh`) for permitted repository tasks.
- `.claude/hooks/` and `.codex/hooks/` - contain no active hook
  implementations; the `.claude/hooks/.klaussy-version` file is metadata.
- `docs/brainstorming/` - durable session artifacts written by the Claude
  `rs-brainstorming` skill, not at the repository root.

## Commands

| Command or workflow | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| implement-plan | no | yes | no | yes |
| improve-plan | no | no | no | yes |
| plan-from-brainstorm | no | no | no | yes |
| plan-review | no | yes | no | no |
| review | no | yes | no | no |
| rs-implement-plan | no | no | yes | no |
| rs-implement-plan-as-codex | no | no | yes | no |
| rs-improve-plan | no | no | yes | no |
| rs-plan-from-brainstorm | no | no | yes | no |
| rs-brainstorming | no | no | yes | no |

Command locations and implementation details:

- OpenCode commands: `.opencode/commands/implement-plan.md`,
  `.opencode/commands/plan-review.md`, and `.opencode/commands/review.md`.
- Claude Code commands: `.claude/commands/rs-implement-plan.md`,
  `.claude/commands/rs-implement-plan-as-codex.md`,
  `.claude/commands/rs-improve-plan.md`, and
  `.claude/commands/rs-plan-from-brainstorm.md`, plus
  `.claude/commands/rs-brainstorming.md`. The Codex variant delegates all worker
  calls through `codex@openai-codex` as `/codex:rescue --wait --fresh --model
  gpt-5.6-terra --effort high`.
- Codex workflows are skills under `.codex/skills/`; there is no
  `.codex/commands/` directory.

GitHub Actions workflows are stored in `.github/workflows/` and
`app/.github/workflows/`; they are CI automation rather than interactive
harness commands. The GitHub CLI (`gh`) is used through permitted shell
commands and has no repository-local command definition.

## Plugins

| Plugin | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| oh-my-opencode-slim@latest | no | yes | no | no |
| context7@claude-plugins-official | no | no | yes | no |
| codex@openai-codex | no | no | yes | no |

Plugin configuration details:

- `oh-my-opencode-slim@latest` is configured in `opencode.jsonc`; its
  `opencode-go` presets are defined in `.opencode/oh-my-opencode-slim.jsonc`.
- `context7@claude-plugins-official` and `codex@openai-codex` are enabled in
  `.claude/settings.local.json`.
- No repository-local plugin configuration is present for GitHub Copilot or
  Codex.

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

The Claude `rs-brainstorming` command stores its session files under
`docs/brainstorming/`, not at the repository root, named
`<YYYYMonDD>_brainstorm_v<N>_<topic-slug>.md`. The Claude
`rs-plan-from-brainstorm` command writes to `docs/plans/` as
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
