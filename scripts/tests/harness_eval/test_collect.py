import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
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


def _stack(tmp_path: Path, ledger: str) -> tuple[Path, str, Path]:
    """Overlay base on eval-base, fc/01-cost (1 commit), fc/02-bylines (2 commits) checked out."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "eval-base")
    (ws / ".gitignore").write_text("docs/harness_logs/\n")
    _commit_file(ws, "base.txt", "b")
    base = _rev(ws, "HEAD")
    _git(ws, "checkout", "-q", "-b", "fc/01-cost")
    _commit_file(ws, "cost.txt", "cost\n")
    _git(ws, "checkout", "-q", "-b", "fc/02-bylines")
    _commit_file(ws, "by1.txt", "by1\n")
    _commit_file(ws, "by2.txt", "by2\n")
    log = ws / "docs" / "harness_logs" / "p"
    log.mkdir(parents=True)
    (log / "ledger.md").write_text(ledger)
    out = tmp_path / "out"
    out.mkdir()
    return ws, base, out


LEDGER = "Unit 01: complete (commits a..b)\n- **Unit 2** \u2014 complete\n"


def test_split_stack_writes_one_diff_per_unit_branch(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    u1 = (out / "units" / "u01.diff").read_text()
    u2 = (out / "units" / "u02.diff").read_text()
    assert "cost.txt" in u1 and "by1.txt" not in u1 and "by2.txt" not in u1
    assert "by1.txt" in u2 and "by2.txt" in u2 and "cost.txt" not in u2
    assert units == [
        {"unit": "01", "diff": "units/u01.diff", "changed_files": ["cost.txt"], "complete": True},
        {
            "unit": "02",
            "diff": "units/u02.diff",
            "changed_files": ["by1.txt", "by2.txt"],
            "complete": True,
        },
    ]
    assert stack == {
        "units_reached": 2,
        "units_done": 2,
        "chained": True,
        "final_heads": False,
        "head_off_stack": False,
    }


@pytest.mark.parametrize(
    ("ledger", "expected"),
    [
        ("Unit 05: complete (commits `a..b`)", {"05"}),
        ("* Unit 5 - complete", {"05"}),
        ("**Unit 05**: Complete", {"05"}),
        ("Unit 05 complete (commits a...b)", {"05"}),
        ("Unit 05 is complete", {"05"}),
        ("Unit 05 is incomplete", set()),
        ("Unit 05: in progress", set()),
    ],
)
def test_ledger_variants_count_as_complete(ledger, expected):
    # Arrange
    # Act
    done = collect.completed_units(ledger)

    # Assert
    assert done == expected


def test_unit_branch_without_a_complete_line_is_reached_not_done(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, "Unit 01: complete\n")

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert [u["complete"] for u in units] == [True, False]
    assert (stack["units_reached"], stack["units_done"]) == (2, 1)


def test_the_checked_out_unit_includes_uncommitted_work(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)
    (ws / "by1.txt").write_text("edited\n")
    (ws / "new.txt").write_text("fresh\n")
    collect.capture_diff(ws, base, out)

    # Act
    units, _ = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    u1 = (out / "units" / "u01.diff").read_text()
    u2 = (out / "units" / "u02.diff").read_text()
    assert "edited" in u2 and "new.txt" in u2
    assert "edited" not in u1 and "new.txt" not in u1
    assert units[0]["changed_files"] == ["cost.txt"]
    assert units[1]["changed_files"] == ["by1.txt", "by2.txt", "new.txt"]


def test_ending_off_the_stack_is_reported(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)
    _git(ws, "checkout", "-q", "eval-base")

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert stack["head_off_stack"] is True
    u1 = (out / "units" / "u01.diff").read_text()
    u2 = (out / "units" / "u02.diff").read_text()
    assert "+cost" in u1 and "+by1" in u2 and "+by2" in u2
    assert "-cost" not in u1 and "-by1" not in u2
    assert [u["changed_files"] for u in units] == [["cost.txt"], ["by1.txt", "by2.txt"]]


def test_a_rebased_branch_breaks_the_chain(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)
    _git(ws, "checkout", "-q", "eval-base")
    _git(ws, "branch", "-D", "fc/02-bylines")
    _git(ws, "checkout", "-q", "-b", "fc/02-bylines")
    _commit_file(ws, "by1.txt", "by1\n")

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert stack["chained"] is False
    assert (out / "units" / "u01.diff").exists() and (out / "units" / "u02.diff").exists()
    assert len(units) == 2


def test_non_unit_branches_are_ignored(tmp_path):
    # Arrange
    ws, _, _ = _stack(tmp_path, LEDGER)
    _git(ws, "branch", "main")
    _git(ws, "branch", "fc/notes")
    _git(ws, "branch", "fc/03-")
    _git(ws, "branch", "fc/04-slug_x")
    _git(ws, "branch", "fc/05-Upper")

    # Act
    found = collect.unit_branches(ws)

    # Assert
    assert found == {"01": "fc/01-cost", "02": "fc/02-bylines"}


def test_final_heads_line_is_found(tmp_path):
    # Arrange
    ledger = LEDGER + "Final heads: fc/01-cost 1a2b, fc/02-bylines 3c4d\n"
    ws, base, out = _stack(tmp_path, ledger)

    # Act
    _, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert stack["final_heads"] is True


def test_no_unit_branches_means_no_units(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "eval-base")
    _commit_file(ws, "base.txt", "b")
    base = _rev(ws, "HEAD")
    _commit_file(ws, "work.txt", "w\n")
    out = tmp_path / "out"
    out.mkdir()
    collect.capture_diff(ws, base, out)

    # Act
    units, stack = collect.split_stack(ws, base, "", out)

    # Assert
    assert units == []
    assert (stack["units_reached"], stack["chained"], stack["head_off_stack"]) == (0, False, True)
    assert "work.txt" in (out / "candidate.diff").read_text()


def test_a_missing_unit_stops_the_cut_and_breaks_the_chain(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)
    _git(ws, "checkout", "-q", "-b", "fc/04-gap")
    _commit_file(ws, "gap.txt", "g\n")

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert [u["unit"] for u in units] == ["01", "02"]
    assert not (out / "units" / "u04.diff").exists()
    assert (stack["units_reached"], stack["chained"]) == (2, False)


def test_a_run_may_start_at_a_later_unit(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "eval-base")
    _commit_file(ws, "base.txt", "b")
    base = _rev(ws, "HEAD")
    _git(ws, "checkout", "-q", "-b", "fc/05-graph")
    _commit_file(ws, "graph.txt", "g\n")
    out = tmp_path / "out"
    out.mkdir()

    # Act
    from_five, stack = collect.split_stack(ws, base, "Unit 5: complete\n", out, first_unit=5)
    from_one, _ = collect.split_stack(ws, base, "Unit 5: complete\n", tmp_path / "out1")

    # Assert
    assert [(u["unit"], u["complete"]) for u in from_five] == [("05", True)]
    assert (stack["units_reached"], stack["chained"]) == (1, True)
    assert from_one == []


def test_a_unit_branch_without_changes_is_not_reached(tmp_path):
    # Arrange
    ws, base, out = _stack(tmp_path, LEDGER)
    _git(ws, "branch", "fc/03-empty")

    # Act
    units, stack = collect.split_stack(ws, base, collect.read_ledger(ws), out)

    # Assert
    assert [u["unit"] for u in units] == ["01", "02"]
    assert (stack["units_reached"], stack["chained"]) == (2, True)


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
    (out / "units").mkdir(parents=True)
    (out / "harness_logs" / "p").mkdir(parents=True)
    secret = "sk-secret-value-1"
    targets = [out / "raw.json", out / "units" / "u01.diff", out / "harness_logs" / "p" / "ledger.md"]
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
    assert result["units"] == []
    assert result["stack_checks"] is None
