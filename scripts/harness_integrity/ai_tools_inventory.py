"""Fail when a Claude command or skill has no counterpart in another harness.

Claude Code's tree is canonical. Every command in `.claude/commands/` needs a
port under OpenCode and Copilot, and every skill in `.claude/skills/` needs a
copy or link under both, except the skills named on the command line (the
Makefile's SKIP_SKILLS). Only existence is checked: whether a port's body still
matches the original is reviewed by hand and by the harness audit. Agents are
left out because each harness keeps a deliberately different set.

Run from the repository root: `make inventory`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMAND_PORTS = [".opencode/command/{name}.md", ".github/prompts/{name}.prompt.md"]
SKILL_COPIES = [".opencode/skills/{name}", ".github/skills/{name}"]


def find_missing(root: Path, skipped_skills: set[str]) -> list[str]:
    """Return every expected port or skill path that does not exist under root."""
    expected = [
        port.format(name=command.stem)
        for command in sorted((root / ".claude/commands").glob("*.md"))
        for port in COMMAND_PORTS
    ]
    expected += [
        copy.format(name=skill.name)
        for skill in sorted((root / ".claude/skills").iterdir())
        if skill.is_dir() and skill.name not in skipped_skills
        for copy in SKILL_COPIES
    ]
    # exists() follows symlinks, so a dangling OpenCode link counts as missing.
    return [path for path in expected if not (root / path).exists()]


def main() -> None:
    missing = find_missing(ROOT, set(sys.argv[1:]))
    for path in missing:
        print(f"missing: {path}", file=sys.stderr)
    if missing:
        sys.exit(1)
    print("every Claude command and skill exists in OpenCode and Copilot")


if __name__ == "__main__":
    main()
