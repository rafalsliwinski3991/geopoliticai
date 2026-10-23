import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "harness_eval" / "prepare.sh"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
HARNESS = [
    ".claude/commands/x.md",
    ".opencode/x.md",
    ".agents/skills/x/SKILL.md",
    ".github/prompts/x.md",
    "AGENTS.md",
    "opencode.jsonc",
    "scripts/log_metrics.py",
    "docs/harness_logs/TEMPLATE.md",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [*GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


@pytest.fixture
def src(tmp_path):
    repo = tmp_path / "src"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "app.py", "a")
    _write(repo, ".gitignore", "docs/plans/\n")
    for rel in HARNESS:
        _write(repo, rel, "old")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    a = _git(repo, "rev-parse", "HEAD")
    _write(repo, "answer.py", "the answer")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B")
    b = _git(repo, "rev-parse", "HEAD")
    _write(repo, ".claude/commands/x.md", "new")
    _write(repo, "fixture.md", "the plan")
    return repo, a, b


def _prepare(src, start, tmp_path):
    ws = tmp_path / "ws"
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(src), start, "fixture.md", "docs/plans/p.md", str(ws)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, ws


def test_workspace_holds_no_later_commit(src, tmp_path):
    repo, a, b = src
    proc, ws = _prepare(repo, a, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert subprocess.run(["git", "-C", str(ws), "cat-file", "-e", b], check=False).returncode != 0
    listed = _git(ws, "log", "--all", "--format=%H").split()
    assert len(listed) == 2
    assert a in listed
    assert proc.stdout.strip() in listed


def test_current_harness_is_overlaid_and_committed(src, tmp_path):
    repo, a, _ = src
    proc, ws = _prepare(repo, a, tmp_path)
    assert (ws / ".claude/commands/x.md").read_text() == "new"
    assert _git(ws, "status", "--porcelain") == ""
    assert proc.stdout.strip() == _git(ws, "rev-parse", "HEAD")
    assert _git(ws, "log", "-1", "--format=%s") == "eval: overlay the current harness"


def test_input_is_placed_and_ignored(src, tmp_path):
    repo, a, _ = src
    _, ws = _prepare(repo, a, tmp_path)
    assert (ws / "docs/plans/p.md").read_text() == "the plan"
    assert _git(ws, "status", "--porcelain") == ""


def test_source_repo_refs_are_left_alone(src, tmp_path):
    repo, a, _ = src
    before = _git(repo, "for-each-ref")
    _prepare(repo, a, tmp_path)
    assert _git(repo, "for-each-ref") == before


def test_run_logs_are_excluded(src, tmp_path):
    repo, a, _ = src
    _, ws = _prepare(repo, a, tmp_path)
    _write(ws, "docs/harness_logs/x/ledger.md", "log")
    assert _git(ws, "status", "--porcelain") == ""


def test_missing_harness_path_fails_loudly(src, tmp_path):
    repo, a, _ = src
    (repo / "AGENTS.md").unlink()
    proc, _ = _prepare(repo, a, tmp_path)
    assert proc.returncode != 0
    assert "AGENTS.md" in proc.stderr
