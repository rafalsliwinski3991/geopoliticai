from pathlib import Path

from harness_integrity import ai_tools_inventory


def _touch(root: Path, *paths: str) -> None:
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")


def _complete_tree(root: Path) -> None:
    _touch(
        root,
        ".claude/commands/rs-foo.md",
        ".opencode/command/rs-foo.md",
        ".github/prompts/rs-foo.prompt.md",
        ".agents/skills/rs-foo/SKILL.md",
        ".claude/skills/bar/SKILL.md",
        ".github/skills/bar/SKILL.md",
    )
    (root / ".opencode/skills").mkdir(parents=True)
    (root / ".opencode/skills/bar").symlink_to("../../.claude/skills/bar")
    (root / ".agents/skills").mkdir(parents=True, exist_ok=True)
    (root / ".agents/skills/bar").symlink_to("../../.claude/skills/bar")


def test_complete_tree_has_nothing_missing(tmp_path):
    """A tree with every command port and skill copy/link reports nothing missing."""
    # Arrange
    _complete_tree(tmp_path)

    # Act
    missing = ai_tools_inventory.find_missing(tmp_path, set())

    # Assert
    assert missing == []


def test_missing_command_port_is_reported(tmp_path):
    """A command missing from any non-Claude harness is returned by path."""
    # Arrange
    _complete_tree(tmp_path)
    (tmp_path / ".github/prompts/rs-foo.prompt.md").unlink()
    (tmp_path / ".agents/skills/rs-foo/SKILL.md").unlink()

    # Act
    missing = ai_tools_inventory.find_missing(tmp_path, set())

    # Assert
    assert missing == [
        ".github/prompts/rs-foo.prompt.md",
        ".agents/skills/rs-foo/SKILL.md",
    ]


def test_dangling_skill_link_is_reported(tmp_path):
    """A broken symlink under .opencode/skills or .agents/skills counts as missing."""
    # Arrange
    _complete_tree(tmp_path)
    (tmp_path / ".opencode/skills/bar").unlink()
    (tmp_path / ".opencode/skills/bar").symlink_to("../../.claude/skills/gone")
    (tmp_path / ".agents/skills/bar").unlink()
    (tmp_path / ".agents/skills/bar").symlink_to("../../.claude/skills/gone")

    # Act
    missing = ai_tools_inventory.find_missing(tmp_path, set())

    # Assert
    assert missing == [".opencode/skills/bar", ".agents/skills/bar"]


def test_skipped_skill_needs_no_copies(tmp_path):
    """A skill in skipped_skills is exempt from non-Claude copies and links."""
    # Arrange
    _complete_tree(tmp_path)
    _touch(tmp_path, ".claude/skills/swarm/SKILL.md")

    # Act
    missing_when_skipped = ai_tools_inventory.find_missing(tmp_path, {"swarm"})
    missing_when_included = ai_tools_inventory.find_missing(tmp_path, set())

    # Assert
    assert missing_when_skipped == []
    assert missing_when_included == [
        ".opencode/skills/swarm",
        ".github/skills/swarm",
        ".agents/skills/swarm",
    ]
