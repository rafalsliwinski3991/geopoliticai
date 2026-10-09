import json
import subprocess
import sys
from pathlib import Path

import pytest
from harness_audit import findings
from harness_audit.findings import Finding

SCRIPTS_DIR = Path(findings.__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent


def test_load_returns_sorted_findings(tmp_path):
    # Arrange
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            {
                "subtype": "success",
                "structured_output": {
                    "findings": [
                        {"kind": 5, "file": "b.md", "line": 3, "quote": "one", "problem": "p", "fix": "f"},
                        {"kind": 2, "file": "a.md", "line": 9, "quote": "two", "problem": "p", "fix": "f"},
                    ]
                },
            }
        )
    )
    # Act
    loaded = findings.load(raw)
    # Assert
    assert [f.kind for f in loaded] == [2, 5]
    assert all(isinstance(f, Finding) for f in loaded)


def test_an_empty_list_is_valid(tmp_path):
    # Arrange
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"subtype": "success", "structured_output": {"findings": []}}))
    # Act
    loaded = findings.load(raw)
    # Assert
    assert loaded == []


@pytest.mark.parametrize(
    "raw_text",
    [
        json.dumps({"subtype": "error_max_structured_output_retries", "structured_output": {"findings": []}}),
        json.dumps({"subtype": "success"}),
        json.dumps({"subtype": "success", "structured_output": {"no_findings": 1}}),
        "not json at all",
    ],
)
def test_failed_runs_raise(tmp_path, raw_text):
    # Arrange
    raw = tmp_path / "raw.json"
    raw.write_text(raw_text)
    # Act / Assert
    with pytest.raises(findings.AuditFailed):
        findings.load(raw)


def test_a_missing_file_raises(tmp_path):
    # Act / Assert
    with pytest.raises(findings.AuditFailed):
        findings.load(tmp_path / "absent.json")


def test_a_top_level_json_list_raises(tmp_path):
    # Arrange
    raw = tmp_path / "raw.json"
    raw.write_text("[]")
    # Act / Assert
    with pytest.raises(findings.AuditFailed):
        findings.load(raw)


def _finding(**overrides):
    return {"kind": 2, "file": "a.md", "line": 3, "quote": "q", "problem": "p", "fix": "f"} | overrides


@pytest.mark.parametrize(
    "item",
    [
        _finding(kind=0),
        _finding(kind=7),
        _finding(kind=True),
        _finding(kind="2"),
        _finding(line=0),
        _finding(quote=""),
        _finding(fix="   "),
        {"kind": 2, "file": "a.md", "line": 3, "quote": "q", "problem": "p"},
        {"kind": 2, "file": "a.md", "line": 3, "quote": "q", "problem": "p", "fix": "f", "extra": 1},
    ],
)
def test_bad_findings_raise(item):
    # Act / Assert
    with pytest.raises(findings.AuditFailed):
        findings.parse(item)


def test_schema_matches_the_code():
    # Arrange
    schema = json.loads((Path(findings.__file__).parent / "findings.schema.json").read_text())
    item = schema["properties"]["findings"]["items"]
    # Act
    properties = item["properties"]
    from harness_audit import report

    # Assert
    assert set(item["required"]) == set(findings.FIELDS)
    assert properties["kind"]["maximum"] == max(findings.KINDS)
    for name in findings.TEXT_FIELDS:
        assert properties[name]["pattern"] == r"\S"
        assert properties[name]["minLength"] == 1
    assert sorted(report.KIND_TITLES) == [1, 2, 3, 4, 5, 6]


def test_prompt_names_every_kind():
    # Arrange
    prompt = (Path(findings.__file__).parent / "prompt.md").read_text()
    collapsed = " ".join(prompt.split())
    # Act / Assert
    for marker in ("1. **", "2. **", "3. **", "4. **", "5. **", "6. **"):
        assert marker in collapsed
    assert "Read shared skills only under `.claude/skills/`" in collapsed
    assert "is still a finding" in collapsed
    assert "`subagent_type`, so that is not a finding" in collapsed


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "real").mkdir(parents=True)
    (repo / "a.md").write_text("alpha\nbeta\ngamma\n")
    (repo / "real" / "s.md").write_text("skill text\n")
    (repo / "link").symlink_to("real", target_is_directory=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    return repo


def test_verify_keeps_confirmed_findings(tmp_path):
    # Arrange
    repo = _init_repo(tmp_path)
    confirmed = [
        Finding(kind=2, file="a.md", line=2, quote="beta", problem="p", fix="f"),
        Finding(kind=2, file="link/s.md", line=1, quote="skill text", problem="p", fix="f"),
    ]
    # Act
    kept, dropped = findings.verify(confirmed, repo)
    # Assert
    assert kept == confirmed
    assert dropped == []


@pytest.mark.parametrize(
    "spec, reason",
    [
        ({"file": "../x.md", "line": 1, "quote": "q"}, "path leaves the repository"),
        ({"file": "untracked.md", "line": 1, "quote": "q"}, "not a tracked file"),
        ({"file": "a.md", "line": 9, "quote": "q"}, "line 9 is past the end (3 lines)"),
        ({"file": "a.md", "line": 1, "quote": "beta"}, "the quote is not on that line"),
    ],
)
def test_verify_drops_unconfirmed_findings(tmp_path, spec, reason):
    # Arrange
    repo = _init_repo(tmp_path)
    candidate = Finding(kind=2, problem="p", fix="f", **spec)
    # Act
    kept, dropped = findings.verify([candidate], repo)
    # Assert
    assert kept == []
    assert dropped == [
        {
            "kind": 2,
            "file": spec["file"],
            "line": spec["line"],
            "quote": spec["quote"],
            "problem": "p",
            "fix": "f",
            "reason": reason,
        }
    ]


def test_main_writes_findings_and_fails_loudly(tmp_path):
    # Arrange
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            {
                "subtype": "success",
                "structured_output": {
                    "findings": [
                        {"kind": 2, "file": "a.md", "line": 1, "quote": "q", "problem": "p", "fix": "f"}
                    ]
                },
            }
        )
    )

    # a.md does not exist in this repository, so the one finding lands in
    # "dropped"; the run still succeeds and writes the output file.
    out = tmp_path / "out.json"

    # Act
    result = subprocess.run(
        [sys.executable, "-m", "harness_audit.findings", "--raw", str(raw),
         "--repo", str(REPO_ROOT), "--out", str(out)],
        cwd=str(SCRIPTS_DIR), capture_output=True, text=True, check=False,
    )
    # Assert
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["findings"] == []
    assert len(data["dropped"]) == 1
    assert "0 findings, 1 dropped" in result.stdout

    # Arrange
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"subtype": "success"}))
    absent = tmp_path / "absent.json"
    # Act
    result = subprocess.run(
        [sys.executable, "-m", "harness_audit.findings", "--raw", str(bad),
         "--repo", str(REPO_ROOT), "--out", str(absent)],
        cwd=str(SCRIPTS_DIR), capture_output=True, text=True, check=False,
    )
    # Assert
    assert result.returncode != 0
    assert "harness audit failed" in result.stderr
    assert not absent.exists()
