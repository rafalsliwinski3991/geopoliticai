# Repository AI Tool Inventory

`yes` means the provider has a matching repository-local skill or hook.
Providers are identified by their repository configuration directories:
`.github` (GitHub Copilot), `.opencode` (OpenCode), `.claude` (Claude), and
`.codex` (Codex).

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
| swarm | yes | yes | yes | yes |

## Hooks

The hook table includes executable hook implementations only. The Claude
`.klaussy-version` file is metadata and is therefore excluded.

| Hook | GitHub Copilot | OpenCode | Claude | Codex |
|---|---:|---:|---:|---:|
| dependency_guard.py | no | no | yes | no |
| plan_guidance.py | no | no | yes | no |
| read_injection_guard.py | no | no | yes | no |
| self_review_guard.py | no | no | yes | no |
