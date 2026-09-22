# Notes

Facts about this repository's AI harnesses that cannot be read off the
filesystem. `make inventory` appends this file verbatim to the generated
inventory. Keep only what a directory listing cannot tell you: a reason, a
deliberate absence, a launch incantation.

## Guidance files

`CLAUDE.md` is the single source of truth. `AGENTS.md` points at it.
`.github/copilot-instructions.md` is still an independent copy and drifts;
collapsing it into a pointer is outstanding work.

## Skills

Claude Code's `.claude/skills/` is canonical. `.opencode/skills/` holds
symlinks into it, created by `make link-skills`, so the two cannot drift.
OpenCode-only skills may be added there as real directories and are left
untouched by that target.

`swarm` is excluded from OpenCode (`OPENCODE_SKIP_SKILLS` in the `Makefile`).
It needs the `@langchain/quickjs` code interpreter and a `swarm_task` PTC tool,
which OpenCode does not provide; loading it there would offer the model tools
that do not exist.

`disable-model-invocation: true` is honoured by Claude Code only. OpenCode
loads every skill it finds and keeps no invocation flag, so the three Python
quickstarts still occupy its context.

The TypeScript quickstarts were deleted from both harnesses: this repository is
Python, and `frontend/chat/` is React without LangChain.

## Commands

OpenCode loads both `.opencode/command/` and `.opencode/commands/`. This
repository uses the singular form only; the plural directory was removed after
two commands existed in both with different bodies and undefined precedence.

`rs-implement-plan-as-codex` and `rs-implement-plan-as-opencode` are Claude
Code only. They dispatch through Claude Code plugins that no other harness has.

OpenCode command copies keep `agent: build` and
`model: opencode-go/glm-5.3-flash`; their bodies otherwise match the Claude
originals.

## Session artifacts

`rs-brainstorming` writes `docs/brainstorming/<YYYYMonDD>_brainstorm_v<N>_<topic-slug>.md`.
`rs-plan-from-brainstorm` writes `docs/plans/<date>_plan_<topic-slug>_v<N>.md`,
reusing the brainstorm's date with its own topic slug.

## Copilot

`.github/skills/` mirrors `.claude/skills/` as real copies (Copilot does not
read the Claude tree), refreshed by `make sync-copilot`. `swarm` is excluded for
the same runtime reason as OpenCode.

Claude commands are ported to `.github/prompts/<name>.prompt.md`, Copilot's
slash-command format: `allowed-tools` becomes `tools` with Copilot tool names,
and `agent: agent` replaces Claude's implicit write access. Ports that reference
Claude's read-only subagents carry a harness note telling Copilot to perform
those roles itself, because it cannot spawn them.

`rs-implement-plan-as-codex` and `rs-implement-plan-as-opencode` are not ported.
They delegate every worker call through Claude Code plugins, so a port would be
a command that cannot run.

Copilot also reads root `CLAUDE.md` directly, which is why
`.github/copilot-instructions.md` can eventually become a pointer or be dropped.
