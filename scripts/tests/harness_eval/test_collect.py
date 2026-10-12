import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from harness_eval import collect

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def _git(ws: Path, *args: str) -> None:
    subprocess.run([*GIT, "-C", str(ws), *args], check=True, capture_output=True)


def test_claude_usage_sums_every_model(tmp_path):
    raw = tmp_path / "r.json"
    raw.write_text(
        json.dumps(
            {
                "total_cost_usd": 1.5,
                "modelUsage": {
                    "a": {
                        "inputTokens": 10,
                        "cacheCreationInputTokens": 5,
                        "cacheReadInputTokens": 100,
                        "outputTokens": 7,
                    },
                    "b": {
                        "inputTokens": 1,
                        "cacheCreationInputTokens": 2,
                        "cacheReadInputTokens": 20,
                        "outputTokens": 3,
                    },
                },
            }
        )
    )
    assert collect.claude_usage(raw) == collect.Usage(18, 120, 10, 1.5)


def test_claude_usage_falls_back_to_usage(tmp_path):
    raw = tmp_path / "r.json"
    raw.write_text(
        json.dumps(
            {
                "total_cost_usd": 0.5,
                "usage": {
                    "input_tokens": 4,
                    "cache_creation_input_tokens": 6,
                    "cache_read_input_tokens": 50,
                    "output_tokens": 9,
                },
            }
        )
    )
    assert collect.claude_usage(raw) == collect.Usage(10, 50, 9, 0.5)


def test_claude_usage_missing_or_truncated_is_null(tmp_path):
    assert collect.claude_usage(tmp_path / "nope.json") == collect.Usage()
    bad = tmp_path / "bad.json"
    bad.write_text('{"type": "res')
    assert collect.claude_usage(bad) == collect.Usage()


def test_opencode_usage_sums_assistant_messages(tmp_path):
    db = tmp_path / "o.db"
    con = sqlite3.connect(db)
    con.execute("create table message (id text, session_id text, data text)")
    msgs = [
        ("m1", "parent", {"role": "assistant", "cost": 0.25,
         "tokens": {"input": 10, "output": 5, "reasoning": 2, "cache": {"read": 100, "write": 3}}}),
        ("m2", "child", {"role": "assistant", "cost": 0.5,
         "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 10, "write": 0}}}),
        ("m3", "parent", {"role": "user"}),
    ]
    for mid, sid, data in msgs:
        con.execute("insert into message values (?, ?, ?)", (mid, sid, json.dumps(data)))
    con.commit()
    con.close()
    assert collect.opencode_usage(db) == collect.Usage(14, 110, 8, 0.75)


def test_opencode_usage_without_db_is_null(tmp_path):
    assert collect.opencode_usage(tmp_path / "none.db") == collect.Usage()


def test_capture_diff_includes_untracked_excludes_ignored(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q")
    (ws / ".gitignore").write_text("ignored.txt\n")
    (ws / "base.txt").write_text("b")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (ws / "committed.txt").write_text("c")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "work")
    (ws / "untracked.txt").write_text("u")
    (ws / "ignored.txt").write_text("i")
    out = tmp_path / "out"
    out.mkdir()
    changed = collect.capture_diff(ws, base, out)
    assert sorted(changed) == ["committed.txt", "untracked.txt"]
    assert "ignored.txt" not in (out / "candidate.diff").read_text()


def test_capture_diff_lists_rename_both_ways_and_odd_names_whole(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q")
    (ws / "old.py").write_text("print('some content to keep the rename similar')\n")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _git(ws, "mv", "old.py", "new name.py")
    (ws / "é.py").write_text("x")
    out = tmp_path / "out"
    out.mkdir()
    changed = collect.capture_diff(ws, base, out)
    assert sorted(changed) == ["new name.py", "old.py", "é.py"]


def test_timing_marks_timeout():
    assert collect.timing(0, 2690, 2700) == (44.8, True)
    assert collect.timing(0, 600, 2700) == (10.0, False)
    assert collect.timing(None, 600, 2700) == (None, False)


def test_parse_checks():
    assert collect.parse_checks("0,1,0") == {"tests_before": 0, "tests_after": 1, "lint": 0}
    assert collect.parse_checks(",,") is None
    assert collect.parse_checks("") is None
    assert collect.parse_checks("0,x,1") is None


def _run_main(
    tmp_path: Path,
    outcome: str,
    seconds: int,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    plan_text: str | None = None,
) -> dict:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    if plan_text is not None:
        (ws / "plan.md").write_text(plan_text)
    (tmp_path / "start").write_text("1000")
    (tmp_path / "end").write_text(str(1000 + seconds))
    out = tmp_path / "out"
    scripts = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable, "-m", "harness_eval.collect",
            "--subject", "plan-x", "--kind", "plan", "--repeat", "1",
            "--harness", "claude", "--model", "m", "--ws", str(ws), "--base", "x",
            "--output", "plan.md",
            "--started-file", str(tmp_path / "start"), "--ended-file", str(tmp_path / "end"),
            "--step-timeout-s", "2700", "--agent-outcome", outcome, "--out", str(out),
            *(extra_args or []),
        ],
        cwd=scripts, check=True, capture_output=True, env={**os.environ, **(env or {})},
    )
    return json.loads((out / "result.json").read_text())


def test_main_marks_crash_not_timeout(tmp_path):
    crash = _run_main(tmp_path / "a", "failure", 300)
    assert (crash["agent_failed"], crash["timed_out"]) == (True, False)
    timeout = _run_main(tmp_path / "b", "failure", 2690)
    assert (timeout["agent_failed"], timeout["timed_out"]) == (False, True)


def _rev(ws: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ws), "rev-parse", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit_file(ws: Path, name: str, text: str) -> None:
    (ws / name).write_text(text)
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", name)


def test_an_implement_run_collects_one_diff_and_no_unit_split(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "eval-base")
    _commit_file(ws, "base.txt", "b")
    base = _rev(ws, "HEAD")
    _git(ws, "checkout", "-q", "-b", "fc/05-graph")
    _commit_file(ws, "graph.txt", "g\n")
    (ws / "extra.txt").write_text("x\n")
    (tmp_path / "start").write_text("1000")
    (tmp_path / "end").write_text("1300")
    out = tmp_path / "out"
    scripts = Path(__file__).resolve().parents[2]

    # Act
    subprocess.run(
        [
            sys.executable, "-m", "harness_eval.collect",
            "--subject", "impl-x", "--kind", "implement", "--repeat", "1",
            "--harness", "claude", "--model", "m", "--ws", str(ws), "--base", base,
            "--started-file", str(tmp_path / "start"), "--ended-file", str(tmp_path / "end"),
            "--step-timeout-s", "2700", "--agent-outcome", "success", "--out", str(out),
        ],
        cwd=scripts, check=True, capture_output=True,
    )
    result = json.loads((out / "result.json").read_text())

    # Assert
    diff = (out / "candidate.diff").read_text()
    assert "graph.txt" in diff and "extra.txt" in diff
    assert sorted(result["changed_files"]) == ["extra.txt", "graph.txt"]
    assert "units" not in result and "stack_checks" not in result
    assert not (out / "units").exists()


def test_redact_scrubs_the_longer_secret_first(tmp_path):
    # Arrange
    out = tmp_path / "out"
    out.mkdir()
    (out / "raw.json").write_text("key prefix12345678 and 12345678")

    # Act
    collect.redact(out, ["12345678", "prefix12345678"])

    # Assert
    assert (out / "raw.json").read_text() == "key [REDACTED] and [REDACTED]"


def test_redact_scrubs_every_file(tmp_path):
    # Arrange
    out = tmp_path / "out"
    out.mkdir()
    (out / "harness_logs" / "p").mkdir(parents=True)
    secret = "sk-secret-value-1"
    targets = [out / "raw.json", out / "candidate.diff", out / "harness_logs" / "p" / "ledger.md"]
    for t in targets:
        t.write_text(f"a {secret} b short12 c")
    clean = out / "clean.txt"
    clean.write_text("nothing here")
    os.utime(clean, (1000, 1000))

    # Act
    collect.redact(out, [secret, "short"])

    # Assert
    for t in targets:
        assert t.read_text() == "a [REDACTED] b short12 c"
    assert clean.read_bytes() == b"nothing here"
    assert clean.stat().st_mtime == 1000


def test_main_redacts_named_env(tmp_path):
    # Arrange
    secret = "secretvalue123"

    # Act
    result = _run_main(
        tmp_path,
        "success",
        300,
        extra_args=["--redact-env", "K"],
        env={"K": secret},
        plan_text=f"the key is {secret}",
    )

    # Assert
    assert (tmp_path / "out" / "candidate.md").read_text() == "the key is [REDACTED]"
    assert "units" not in result
