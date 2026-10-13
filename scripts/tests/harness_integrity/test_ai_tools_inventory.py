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
        ".claude/skills/bar/SKILL.md",
        ".github/skills/bar/SKILL.md",
    )
    (root / ".opencode/skills").mkdir(parents=True)
    (root / ".opencode/skills/bar").symlink_to("../../.claude/skills/bar")


def test_complete_tree_has_nothing_missing(tmp_path):
    _complete_tree(tmp_path)
    assert ai_tools_inventory.find_missing(tmp_path, set()) == []


def test_missing_command_port_is_reported(tmp_path):
    _complete_tree(tmp_path)
    (tmp_path / ".github/prompts/rs-foo.prompt.md").unlink()
    assert ai_tools_inventory.find_missing(tmp_path, set()) == [".github/prompts/rs-foo.prompt.md"]


def test_dangling_skill_link_is_reported(tmp_path):
    _complete_tree(tmp_path)
    (tmp_path / ".opencode/skills/bar").unlink()
    (tmp_path / ".opencode/skills/bar").symlink_to("../../.claude/skills/gone")
    assert ai_tools_inventory.find_missing(tmp_path, set()) == [".opencode/skills/bar"]


def test_skipped_skill_needs_no_copies(tmp_path):
    _complete_tree(tmp_path)
    _touch(tmp_path, ".claude/skills/swarm/SKILL.md")
    assert ai_tools_inventory.find_missing(tmp_path, {"swarm"}) == []
    assert ai_tools_inventory.find_missing(tmp_path, set()) == [
        ".opencode/skills/swarm",
        ".github/skills/swarm",
    ]
