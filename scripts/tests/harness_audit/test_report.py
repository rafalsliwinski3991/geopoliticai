import json
import subprocess
import sys

import pytest
from harness_audit import report
from harness_audit.findings import Finding


def _finding(kind, file, line):
    return Finding(kind=kind, file=file, line=line, quote="q", problem="p", fix="f")


def test_title():
    # Act
    four = report.title("PR #175", "77e1f02abc", 4)
    one = report.title("PR #175", "77e1f02abc", 1)
    # Assert
    assert four == "Harness audit: PR #175 @ 77e1f02 (4 findings)"
    assert one == "Harness audit: PR #175 @ 77e1f02 (1 finding)"


def test_neutral():
    # Act
    text = report.neutral("ping @alice about #12 and C#")
    # Assert
    assert "@\u200balice" in text
    assert "#\u200b12" in text
    assert "C\u200b#" not in text
    assert "C#" in text


def test_body_neutralises_model_text():
    # Arrange
    found = [Finding(kind=2, file="a.md", line=1, quote="q", problem="@org/team see #5", fix="f")]
    # Act
    text = report.body(found, "PR #9", "77e1f02", "https://run")
    # Assert
    assert "@\u200borg/team" in text
    assert "#\u200b5" in text


def test_body_groups_by_kind_in_order():
    # Arrange
    found = [_finding(5, "b.md", 2), _finding(1, "a.md", 1)]
    # Act
    text = report.body(found, "PR #9", "77e1f02", "https://run")
    # Assert
    assert text.index("## 1.") < text.index("## 5.")
    assert "## 2." not in text
    assert "- [ ] `a.md:1` p" in text
    assert "- [ ] `b.md:2` p" in text


def test_body_renders_multiline_quote_and_fix():
    # Arrange
    found = [Finding(kind=1, file="a.md", line=1, quote="first\nsecond", problem="p", fix="the fix")]
    # Act
    lines = report.body(found, "PR #9", "77e1f02", "https://run").splitlines()
    # Assert
    assert "  > first" in lines
    assert "  > second" in lines
    assert "  Fix: the fix" in lines


def test_clip_does_not_exceed_the_byte_budget():
    # Act
    short = report.clip("short")
    long_body = "x" * (report.MAX_BODY_BYTES + 100)
    clipped = report.clip(long_body)
    multibyte = report.clip("é" * (report.MAX_BODY_BYTES // 2))
    # Assert
    assert short == "short"
    assert clipped.endswith(report.TRUNCATED)
    assert len(clipped.encode()) <= report.MAX_BODY_BYTES + len(report.TRUNCATED.encode())
    assert multibyte.encode("utf-8").decode("utf-8") == multibyte
    assert len(multibyte.encode()) <= report.MAX_BODY_BYTES + len(report.TRUNCATED.encode())


def test_decide():
    # Arrange
    open_issues = [
        {"number": 5, "title": "Harness audit: PR #175 @ a (3 findings)"},
        {"number": 6, "title": "Harness audit: PR #17 @ b (1 finding)"},
        {"number": 7, "title": "Harness audit: main @ c (2 findings)"},
    ]
    found = [_finding(1, "a.md", 1)]
    # Act
    with_findings = report.decide(open_issues, "PR #175", found)
    without_findings = report.decide(open_issues, "PR #175", [])
    nothing_yet = report.decide([], "PR #175", [])
    # Assert
    assert with_findings == report.Actions(create=True, close=(5,))
    assert without_findings == report.Actions(create=False, close=(5,))
    assert nothing_yet == report.Actions(create=False, close=())


class _FakeGh:
    """Records gh calls; `issue list` finds issue #5, `issue create` mints #9."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, stdin=None):
        self.calls.append(tuple(args))
        if "issue" in args and "list" in args:
            return '[{"number": 5, "title": "Harness audit: PR #175 @ a (3 findings)"}]'
        if "issue" in args and "create" in args:
            return "https://github.com/o/r/issues/9\n"
        return ""


def _run_report(monkeypatch, tmp_path, fake, findings_document, summary):
    monkeypatch.setattr(report, "gh", fake)
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(findings_document))
    monkeypatch.setattr(
        sys, "argv",
        ["report.py", "--findings", str(findings_path), "--target", "PR #175",
         "--sha", "77e1f02abc", "--run-url", "https://run", "--summary", str(summary)],
    )


def test_main_supersedes_the_previous_issue(tmp_path, monkeypatch):
    # Arrange
    fake = _FakeGh()
    summary = tmp_path / "summary.md"
    _run_report(
        monkeypatch, tmp_path, fake,
        {
            "findings": [{"kind": 2, "file": "a.md", "line": 1, "quote": "q", "problem": "p", "fix": "f"}],
            "dropped": [{"kind": 1, "file": "b.md", "line": 2, "quote": "q", "problem": "p", "fix": "f",
                         "reason": "not a tracked file"}],
        },
        summary,
    )
    # Act
    report.main()
    # Assert
    create_calls = [c for c in fake.calls if c[0] == "issue" and c[1] == "create"]
    close_calls = [c for c in fake.calls if c[0] == "issue" and c[1] == "close"]
    assert create_calls, fake.calls
    assert len(close_calls) == 1
    label_calls = [c for c in fake.calls if c[0] == "label"]
    list_calls = [c for c in fake.calls if c[0] == "issue" and c[1] == "list"]
    assert label_calls[0][-1] == "--force"
    assert list_calls[0][-1] == "number,title"
    order = {call: i for i, call in enumerate(fake.calls)}
    assert order[label_calls[0]] < order[list_calls[0]] < order[create_calls[0]] < order[close_calls[0]]
    create = create_calls[0]
    assert "--body-file" in create and create[create.index("--body-file") + 1] == "-"
    assert "Harness audit: PR #175 @ 77e1f02 (1 finding)" in " ".join(create)
    assert "Superseded by https://github.com/o/r/issues/9." in " ".join(close_calls[0])
    text = summary.read_text()
    assert "## Harness audit" in text
    assert "Dropped" in text
    assert "`b.md:2` (not a tracked file)" in text


def test_main_writes_the_summary_before_gh_fails(tmp_path, monkeypatch):
    # Arrange
    summary = tmp_path / "summary.md"

    def failing_gh(*args, stdin=None):
        raise subprocess.CalledProcessError(1, "gh", stderr="no auth")

    _run_report(
        monkeypatch, tmp_path, failing_gh,
        {"findings": [{"kind": 2, "file": "a.md", "line": 1, "quote": "q", "problem": "p", "fix": "f"}],
         "dropped": []},
        summary,
    )
    # Act / Assert
    with pytest.raises(subprocess.CalledProcessError):
        report.main()

    assert "## Harness audit" in summary.read_text()


def test_main_reports_every_close_failure(tmp_path, monkeypatch):
    # Arrange
    summary = tmp_path / "summary.md"

    class CloseFailGh:
        def __init__(self):
            self.calls = []
            self.closed = []

        def __call__(self, *args, stdin=None):
            self.calls.append(tuple(args))
            if "list" in args:
                return json.dumps([
                    {"number": 5, "title": "Harness audit: PR #175 @ a (1 finding)"},
                    {"number": 6, "title": "Harness audit: PR #175 @ b (1 finding)"},
                ])
            if "close" in args:
                number = args[2]
                if number == "5" and number not in self.closed:
                    raise subprocess.CalledProcessError(1, "gh", stderr="nope")
                self.closed.append(number)
                return ""
            return ""

    fake = CloseFailGh()
    _run_report(monkeypatch, tmp_path, fake, {"findings": [], "dropped": []}, summary)
    # Act / Assert
    with pytest.raises(SystemExit) as excinfo:
        report.main()

    assert "#5" in str(excinfo.value)
    assert fake.closed == ["6"]
    assert "## Harness audit" in summary.read_text()


def test_main_with_no_findings_resolves(tmp_path, monkeypatch):
    # Arrange
    fake = _FakeGh()
    summary = tmp_path / "summary.md"
    _run_report(monkeypatch, tmp_path, fake, {"findings": [], "dropped": []}, summary)
    # Act
    report.main()
    # Assert
    assert not any(c[0] == "issue" and c[1] == "create" for c in fake.calls)
    close_calls = [c for c in fake.calls if c[0] == "issue" and c[1] == "close"]
    assert close_calls
    assert "Resolved in `77e1f02`" in " ".join(close_calls[0])
    assert "No findings." in summary.read_text()
