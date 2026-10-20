# Notes

Facts about this repository's AI harnesses that cannot be read off the
filesystem. `make inventory` fails when a Claude command or skill has no
counterpart under OpenCode or Copilot; this file explains the deliberate
exceptions and everything else it cannot check. Keep only what a directory listing cannot tell you: a reason, a
deliberate absence, a launch incantation.

## Guidance files

`CLAUDE.md` is the single source of truth. `AGENTS.md` and
`.github/copilot-instructions.md` are pointers at it, so no harness reads a
second, drifting copy of the repository map.

## Skills

Claude Code's `.claude/skills/` is canonical. `.opencode/skills/` holds
symlinks into it, created by `make link-skills`, so the two cannot drift.
OpenCode-only skills may be added there as real directories and are left
untouched by that target.

`swarm` is excluded from both non-Claude harnesses (`SKIP_SKILLS` in the
`Makefile`, read by `sync-copilot` and `link-skills` alike). It needs the
`@langchain/quickjs` code interpreter and a `swarm_task` PTC tool, which neither
provides; loading it there would offer the model tools that do not exist.
`e2e` is excluded the same way: it drives Claude's `AskUserQuestion` and this
repo's Compose stack, and has no port.

`disable-model-invocation: true` is honoured by Claude Code only. OpenCode
loads every skill it finds and keeps no invocation flag, so the three Python
quickstarts still occupy its context.

The TypeScript quickstarts were deleted from both harnesses: this repository is
Python, and `frontend/chat/` is React without LangChain.

## Commands

OpenCode loads both `.opencode/command/` and `.opencode/commands/`. This
repository uses the singular form only; the plural directory was removed after
two commands existed in both with different bodies and undefined precedence. The
two generic review commands it also held (`review`, `plan-review`) are replaced
by the `rs-code-review` and `rs-improve-plan` ports, not dropped.

OpenCode command copies are the Claude originals with `argument-hint` and
`allowed-tools` (neither of which OpenCode reads) replaced by `agent: build`
and `model: opencode-go/glm-5.3-flash`. Their bodies match apart from the
steps that name a tool, path, or helper only Claude has, which each port
writes for its own harness (the `question` tool, `.opencode/` paths).

`rs-implement-plan` goes further: OpenCode's
version has its own body, which dispatches the `.opencode/agents/` workers
(`plan-implementer`, `plan-retry`, `plan-unit-auditor`, `plan-final-review`),
so its behaviour is kept in step with Claude's by hand.

No port carries a harness note above its body. Where a Claude command
dispatches one of its read-only subagents, the OpenCode and Copilot versions
of `rs-code-review` and `rs-improve-plan`, and Copilot's `rs-implement-plan`,
make that pass themselves, because neither harness has those agents.
`rs-improve-codebase` is the exception: each harness has its own
`architecture-scout` and `structure-scout` (`.claude/agents/`,
`.opencode/agents/`, `.github/agents/`), and its ports dispatch them, OpenCode
with the Task tool and Copilot with its `agent` tool. Its ports also write the
page locally where Claude Code publishes an artifact, as `rs-explain-plan` and
`rs-guidebook` do.

`make inventory` checks only that a port exists under each harness, never
whether its body still matches the Claude original. That match is verified by
hand and by the Harness Audit workflow; a passing check is not evidence of it.
Agents are not checked: each harness keeps a deliberately different set.

## Session artifacts

`rs-brainstorming` writes `docs/brainstorming/<YYYYMonDD>_brainstorm_v<N>_<topic-slug>.md`.
`rs-plan-from-brainstorm` writes `docs/plans/<date>_plan_<topic-slug>_v<N>.md`,
reusing the brainstorm's date with its own topic slug.

## Copilot

`.github/skills/` mirrors `.claude/skills/` as real copies (Copilot does not
read the Claude tree), refreshed by `make sync-copilot`. `swarm` and `e2e` are
excluded for the same reasons as in OpenCode.

Claude commands are ported to `.github/prompts/<name>.prompt.md`, Copilot's
slash-command format: `allowed-tools` becomes `tools` with Copilot tool names,
and `agent: agent` replaces Claude's implicit write access.
Copilot runs helpers as custom agents in `.github/agents/` through its `agent` tool; only
`rs-improve-codebase`'s port uses them so far.

`make sync-copilot` rebuilds `.github/skills/` from scratch rather than copying
over it, so a skill deleted from `.claude/skills/` disappears downstream too.
Anything hand-written under `.github/skills/` is destroyed with it: edit
`.claude/skills/` and re-run the target. `.github/prompts/` is not synced and is
maintained by hand.

`make link-skills` prunes only symlinks, leaving OpenCode-only real directories
in place, and refuses to link a canonical skill whose name is already taken by
one of them. Linking over it would put the symlink inside that directory, where
it dangles and `make inventory` reports the skill as missing.
