# Repository AI Tool Inventory

`yes` means the provider has a matching repository-local skill or hook.
Providers are identified by their repository configuration directories:
`.github` (GitHub Copilot), `.opencode` (OpenCode), `.claude` (Claude), and
`.codex` (Codex).

This file is the single home for detailed repository AI-tool layout facts.
The three codebase guidance files (`AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md`) contain only the concise Codex development
workflow.

After any addition, removal, rename, or modification of a provider's skills,
hooks, plugins, agents, commands, or related AI-tool configuration, update
this file to keep it accurate.

## Repository Locations

- `.github/skills/` - GitHub Copilot skills with bundled references and
  scripts.
- `.opencode/skills/` - OpenCode-compatible copy of the same skill bundle.
- `.codex/skills/` - Codex copy of the shared skill bundle.
- `.codex/config.toml` - project agent and thread settings.
- `.codex/agents/` - four Codex role definitions.
- `.claude/skills/` - Claude skills; `swarm` and `grill-me` exist only here.
- `.claude/hooks/` and `.codex/hooks/` - contain no active hook
  implementations; the `.claude/hooks/.klaussy-version` file is metadata.
- `docs/brainstorming/` - durable session artifacts written by the Claude
  `grill-me` skill, not at the repository root.

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
| grill-me | no | no | yes | no |
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

The Claude `grill-me` skill stores its session files under
`docs/brainstorming/`, not at the repository root.

## Agents

| Agent | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| orchestrator | no | no | no | yes |
| explorer | no | no | no | yes |
| builder | no | no | no | yes |
| critic | no | no | no | yes |

The configured Codex defaults are: `orchestrator` uses `gpt-5.6-sol` with
high reasoning and a read-only sandbox; `explorer` uses `gpt-5.6-luna` with
medium reasoning and a read-only sandbox; `builder` uses `gpt-5.6-sol` with
high reasoning and a workspace-write sandbox; and `critic` uses `gpt-5.6-sol`
with high reasoning and a read-only sandbox. These sandbox modes are
configured defaults, and project configuration loads only for trusted
repositories.

The OpenCode slash commands `.opencode/commands/review.md` (`/review`) and
`.opencode/commands/plan-review.md` (`/plan-review`) instruct the current agent
to perform an independent review directly; OpenCode has no dedicated `critic`
subagent. The Codex `critic` agent (`.codex/agents/critic.toml`) is the only
read-only reviewer subagent, and no other provider ships matching commands.

## Hooks

The hook table includes executable hook implementations only. There are
currently no active repository-local hooks or hook configuration for any
provider. The Claude `.claude/hooks/.klaussy-version` file is metadata and is
therefore excluded.

| Hook | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
