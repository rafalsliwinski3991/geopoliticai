import json
import subprocess
import sys

import pytest
from harness_audit import report
from harness_audit.findings import Finding


def _finding(kind, file, line):
    return Finding(kind=kind, file=file, line=line, quote="q", problem="p", fix="f")


def test_title():
    # Arrange
    # Act
    four = report.title("PR #175", "77e1f02abc", 4)
    one = report.title("PR #175", "77e1f02abc", 1)
    # Assert
    assert four == "Harness audit: PR #175 @ 77e1f02 (4 findings)"
    assert one == "Harness audit: PR #175 @ 77e1f02 (1 finding)"


def test_neutral():
    # Arrange
    text = "ping @alice about #12 and C#"
    url = "see https://github.com/o/r/issues/123 and [x](https://github.com/o/r/pull/45)"
    # Act
    neutralised = report.neutral(text)
    neutralised_url = report.neutral(url)
    # Assert
    assert "@\u200balice" in neutralised
    assert "#\u200b12" in neutralised
    assert "C\u200b#" not in neutralised
    assert "C#" in neutralised
    # The URL path is broken, so neither the bare nor the bracketed link works.
    for form in ("issues/\u200b123", "pull/\u200b45"):
        assert form in neutralised_url
    assert "/issues/123" not in neutralised_url
    assert "/pull/45" not in neutralised_url


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


def test_body_collapses_newlines_in_problem_and_fix():
    # Arrange
    found = [
        Finding(
            kind=3, file="a.md", line=1, quote="q",
            problem="line one\n## forged heading\n- [x] injected",
            fix="fix one\n### another forged heading",
        )
    ]
    # Act
    lines = report.body(found, "PR #9", "77e1f02", "https://run").splitlines()
    # Assert
    # The kind heading is the only line starting with a Markdown heading marker.
    assert [line for line in lines if line.startswith("#")] == ["## 3. A contradiction"]
    assert "- [ ] `a.md:1` line one ## forged heading - [x] injected" in lines
    assert "  Fix: fix one ### another forged heading" in lines


def test_dropped_note_neutralises_the_model_chosen_path():
    # Arrange
    dropped = [
        {"kind": 1, "file": "b`md\n## forged", "line": 2, "quote": "q", "problem": "p", "fix": "f",
         "reason": "not a tracked file"},
    ]
    # Act
    note = report.dropped_note(dropped)
    # Assert
    assert "- `b'md ## forged:2` (not a tracked file)" in note
    # The only backticks left are the code span around the sanitised path.
    assert note.count("`") == 2
    assert "\n## forged" not in note


def test_clip_does_not_exceed_the_byte_budget():
    # Arrange
    long_body = "x" * (report.MAX_BODY_BYTES + 100)
    at_budget = "é" * (report.MAX_BODY_BYTES // 2)
    over_budget = "é" * (report.MAX_BODY_BYTES // 2 + 10)
    # Act
    short = report.clip("short")
    clipped = report.clip(long_body)
    clipped_multibyte = report.clip(over_budget)
    # Assert
    assert short == "short"
    assert at_budget == report.clip(at_budget)
    assert clipped.endswith(report.TRUNCATED)
    assert len(clipped.encode()) <= report.MAX_BODY_BYTES + len(report.TRUNCATED.encode())
    assert clipped_multibyte.endswith(report.TRUNCATED)
    # The cut never splits a multibyte character into mojibake.
    assert clipped_multibyte.encode("utf-8").decode("utf-8") == clipped_multibyte
    assert len(clipped_multibyte.encode()) <= report.MAX_BODY_BYTES + len(report.TRUNCATED.encode())


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
    # Act
    with pytest.raises(subprocess.CalledProcessError):
        report.main()

    # Assert
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
    # Act
    with pytest.raises(SystemExit) as excinfo:
        report.main()

    # Assert
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
    assert "Resolved in `77e1f02`: no confirmed findings." in " ".join(close_calls[0])
    assert "No findings." in summary.read_text()


def test_main_with_only_dropped_findings_says_how_many(tmp_path, monkeypatch):
    # Arrange
    fake = _FakeGh()
    summary = tmp_path / "summary.md"
    _run_report(
        monkeypatch, tmp_path, fake,
        {"findings": [], "dropped": [{"kind": 1, "file": "b.md", "line": 2, "quote": "q",
                                      "problem": "p", "fix": "f", "reason": "not a tracked file"}]},
        summary,
    )
    # Act
    report.main()
    # Assert
    close_calls = [c for c in fake.calls if c[0] == "issue" and c[1] == "close"]
    assert close_calls
    assert "no confirmed findings (1 dropped)" in " ".join(close_calls[0])
    assert "the audit found nothing" not in " ".join(close_calls[0])


def test_gh_logs_the_stderr_and_reraises(tmp_path, monkeypatch, capsys):
    # Arrange
    def failing_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "gh", stderr="boom\n")

    monkeypatch.setattr(report.subprocess, "run", failing_run)
    # Act
    with pytest.raises(subprocess.CalledProcessError):
        report.gh("label", "create", "x")
    # Assert
    assert "gh label create failed: boom" in capsys.readouterr().err
