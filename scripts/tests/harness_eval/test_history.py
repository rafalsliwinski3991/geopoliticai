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
    out = history.render([_row(est_cost_usd=None, timed_out=True, agent_failed=True)])
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


def test_row_carries_unit_and_units_done():
    # Arrange
    stack = {"units_done": 7, "units_total": 9}

    # Act
    r = _build(unit="05", stack_checks=stack)
    default = _build()

    # Assert
    assert (r["unit"], r["units_done"], r["units_total"]) == ("05", 7, 9)
    assert (default["unit"], default["units_done"], default["units_total"]) == (None, None, None)


def test_append_keeps_one_row_per_unit(tmp_path):
    # Arrange
    path = tmp_path / "h.jsonl"
    rows = [_row(unit="01"), _row(unit="02"), _row(unit="02"), _row()]

    # Act
    history.append(path, rows)
    history.append(path, [_row()])

    # Assert
    assert [r.get("unit") for r in history.load(path)] == ["01", "02", None]


def test_runs_count_repeats_not_unit_rows():
    # Arrange
    rows = [
        _row(repeat=rep, unit=f"{u:02d}", overall=float(1 + (u + rep) % 4), units_done=9, units_total=9)
        for rep in (1, 2)
        for u in range(1, 10)
    ]
    expected = sum(1 + (u + rep) % 4 for rep in (1, 2) for u in range(1, 10)) / 18

    # Act
    (entry,) = history.runs(rows, "plan-opus")

    # Assert
    assert entry["n"] == 2
    assert entry["units_done"] == 9
    assert entry["units_total"] == 9
    assert entry["overall"] == expected


def test_render_shows_units_done():
    # Arrange
    rows = [
        _row("r1", subject="impl-sonnet", unit="01", units_done=7, units_total=9),
        _row("r2", subject="plan-opus"),
    ]

    # Act
    out = history.render(rows)

    # Assert
    assert "| 1 | 7/9 | 3.00 |" in out
    assert "| 1 | — | 3.00 |" in out
    assert "| run | date | note | n | units | quality |" in out


def test_quality_is_the_mean_over_reached_units():
    # Arrange
    rows = [
        _row(subject="impl-glm", unit=f"{i:02d}", overall=float(q), units_done=5, units_total=9)
        for i, q in enumerate([4, 4, 3, 3, 2], start=1)
    ]

    # Act
    out = history.render(rows)

    # Assert
    assert "| 1 | 5/9 | 3.20 |" in out


def test_render_by_unit():
    # Arrange
    judged = [
        _judged(subject="impl-glm", repeat=1, unit="01", overall=4.0),
        _judged(subject="impl-glm", repeat=1, unit="03", overall=2.0),
        _judged(subject="impl-sonnet", repeat=1, unit="01", overall=3.0),
        _judged(subject="impl-sonnet", repeat=1, unit="02", overall=3.5),
        _judged(subject="impl-sonnet", repeat=1, unit="03", overall=2.5),
    ]

    # Act
    out = history.render_by_unit(judged)

    # Assert
    assert "| leg | u01 | u02 | u03 | mean |" in out
    assert "| impl-glm #1 | 4.00 | — | 2.00 | 3.00 |" in out
    assert "| impl-sonnet #1 | 3.00 | 3.50 | 2.50 | 3.00 |" in out
    assert history.render_by_unit([_judged()]) == ""


def test_render_reasoning_collapses_each_verdict():
    # Arrange
    judged = _judged(subject="impl-glm", unit="05", overall=2.75, summary="s")

    # Act
    out = history.render_reasoning([judged])

    # Assert
    assert "<details><summary>impl-glm #1 u05 — 2.75</summary>\n\n" in out
    assert "</details>" in out
