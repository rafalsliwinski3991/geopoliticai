import json

from harness_eval import history


def _judged(**over):
    base = {
        "subject": "plan-opus",
        "repeat": 1,
        "model": "m",
        "overall": 3.0,
        "criteria": [{"name": "units", "reasoning": "r", "score": 3, "cap": None}],
        "hard_checks": {},
        "tokens_in": 1_500_000,
        "tokens_cached": 400_000,
        "tokens_out": 100_000,
        "est_cost_usd": 1.0,
        "minutes": 10.0,
        "timed_out": False,
        "agent_failed": False,
    }
    return {**base, **over}


def _row(run_id="r1", subject="plan-opus", repeat=1, **over):
    base = {
        "run_id": run_id,
        "date": "2026-10-04",
        "sha": "abc",
        "note": "",
        "judge_version": "v1",
        "subject": subject,
        "repeat": repeat,
        "overall": 3.0,
        "tokens_total": 2_000_000,
        "est_cost_usd": 1.0,
        "minutes": 10.0,
        "quality_per_mtok": 1.5,
        "timed_out": False,
        "agent_failed": False,
    }
    return {**base, **over}


def _build(**kw):
    return history.row(_judged(**kw), run_id="r", date="d", sha="s", note="n", judge_version="v")


def test_row_totals_and_quality_per_mtok():
    r = _build()
    assert r["tokens_total"] == 2_000_000
    assert r["quality_per_mtok"] == 1.5
    assert r["scores"] == {"units": 3}
    r = _build(tokens_cached=None)
    assert r["tokens_total"] is None
    assert r["quality_per_mtok"] is None


def test_runs_average_repeats():
    rows = [_row(repeat=1, overall=3.0), _row(repeat=2, overall=3.5)]
    (entry,) = history.runs(rows, "plan-opus")
    assert entry["overall"] == 3.25
    assert entry["n"] == 2


def test_append_skips_recorded_rows(tmp_path):
    path = tmp_path / "h.jsonl"
    history.append(path, [_row()])
    history.append(path, [_row()])
    assert len(path.read_text().splitlines()) == 1
    assert json.loads(path.read_text())["run_id"] == "r1"
    assert history.load(tmp_path / "missing.jsonl") == []


def test_append_dedupes_by_key_and_within_one_call(tmp_path):
    path = tmp_path / "h.jsonl"
    history.append(path, [_row(repeat=1)])
    history.append(path, [_row(repeat=1), _row(repeat=2), _row(repeat=2)])
    assert [r["repeat"] for r in history.load(path)] == [1, 2]


def test_render_marks_deltas_and_noise():
    rows = [
        _row("r1", overall=3.0, tokens_total=2_000_000),
        _row("r2", overall=3.1, tokens_total=1_500_000),
        _row("r3", overall=3.5, tokens_total=1_500_000),
    ]
    out = history.render(rows)
    assert "3.10 ≈" in out
    assert "3.50 ▲0.40" in out
    assert "1.50M ▼0.50M" in out


def test_render_divides_at_judge_change():
    rows = [
        _row("r1", overall=3.0),
        _row("r2", overall=2.0, judge_version="v2"),
        _row("r3", overall=3.5, judge_version="v2"),
    ]
    lines = history.render(rows).splitlines()
    divider = next(i for i, line in enumerate(lines) if "judge changed → v2" in line)
    assert "▲" not in lines[divider + 1] and "▼" not in lines[divider + 1]
    assert "2.00" in lines[divider + 1]
    assert "3.50 ▲1.50" in lines[divider + 2]


def test_render_keeps_last_ten_runs():
    rows = [_row(f"run{i:02d}") for i in range(12)]
    out = history.render(rows)
    assert "run00" not in out and "run01" not in out
    assert "run02" in out and "run11" in out


def test_render_marks_missing_timeout_and_crash():
    # Arrange
    rows = [_row(est_cost_usd=None, timed_out=True, agent_failed=True)]

    # Act
    out = history.render(rows)

    # Assert
    assert "| — | 10m |" in out
    assert "⏱" in out
    assert "✗" in out


def test_render_reasoning_escapes_pipes():
    judged = _judged(
        summary="s",
        criteria=[{"name": "units", "reasoning": "a | b\nc", "score": 2, "cap": 2}],
    )
    out = history.render_reasoning([judged])
    assert "a \\| b c" in out
    assert "(capped at 2)" in out


def test_render_reasoning_escapes_html_so_a_verdict_cannot_close_its_block():
    # Arrange
    judged = _judged(
        summary="done </details> & <b>more</b>",
        criteria=[{"name": "units", "reasoning": "x </details> | y", "score": 2, "cap": None}],
    )

    # Act
    out = history.render_reasoning([judged])

    # Assert
    assert out.count("</details>") == 1
    assert "done &lt;/details&gt; &amp; &lt;b&gt;more&lt;/b&gt;" in out
    assert "x &lt;/details&gt; \\| y" in out


def test_row_has_no_unit_keys():
    # Arrange
    # Act
    r = _build()

    # Assert
    assert not {"unit", "units_done", "units_total"} & r.keys()


def test_append_keeps_one_row_per_run_subject_and_repeat(tmp_path):
    # Arrange
    path = tmp_path / "h.jsonl"
    rows = [_row(repeat=1), _row(repeat=2), _row(repeat=2), _row("r2")]

    # Act
    history.append(path, rows)
    history.append(path, [_row()])

    # Assert
    assert [(r["run_id"], r["repeat"]) for r in history.load(path)] == [("r1", 1), ("r1", 2), ("r2", 1)]


def test_render_table_has_no_units_column():
    # Arrange
    rows = [_row("r1", subject="impl-sonnet"), _row("r2", subject="impl-sonnet", judge_version="v2")]

    # Act
    out = history.render(rows)

    # Assert
    assert "| run | date | note | n | quality |" in out
    assert "units" not in out.split("### impl-sonnet")[1]
    assert "| | | **judge changed → v2** | | | | | | |\n" in out


def test_render_reasoning_collapses_each_verdict():
    # Arrange
    judged = _judged(subject="impl-glm", overall=2.75, summary="s")

    # Act
    out = history.render_reasoning([judged])

    # Assert
    assert "<details><summary>impl-glm #1 — 2.75</summary>\n\n" in out
    assert "</details>" in out
