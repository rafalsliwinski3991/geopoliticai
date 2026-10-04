import json
import sqlite3
from datetime import datetime
from pathlib import Path

import log_metrics

HEADER = "---\nharness: {h}\nstarted: 2026-10-04T14:00:00+00:00\n---\n"


def _local(day: str, hm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hm}:00").astimezone()


def _iso(day: str, hm: str) -> str:
    return _local(day, hm).astimezone(log_metrics.UTC).isoformat().replace("+00:00", "Z")


def test_heading_accepts_en_dash_and_hyphen_and_rejects_no_window():
    a = log_metrics.parse_stages("## Pre-flight — claude-code (2026-10-04 14:02–14:09)\n")
    b = log_metrics.parse_stages("## Pre-flight — claude-code (2026-10-04 14:02-14:09)\n")
    assert len(a) == len(b) == 1
    assert log_metrics.parse_stages("## Pre-flight — claude-code\n") == []


def test_midnight_rollover_is_twenty_minutes():
    (stage,) = log_metrics.parse_stages("## X — opencode (2026-10-04 23:50–00:10)\n")
    assert stage.minutes == 20
    assert stage.end.day == 5


def test_window_includes_whole_closing_minute():
    (stage,) = log_metrics.parse_stages("## X — opencode (2026-10-04 14:00–14:09)\n")
    assert stage.start <= _local("2026-10-04", "14:09").replace(second=45) <= stage.end


def test_project_dir_encoder():
    assert log_metrics.encode_project_dir("/a/.b_c") == "-a--b-c"


def _record(mid: str, ts: str, inp: int, out: int) -> str:
    usage = {"input_tokens": inp, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0, "output_tokens": out}
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"id": mid, "usage": usage}})


def test_claude_dedupes_message_id_excludes_outside_and_includes_subagent(tmp_path: Path):
    inside = _iso("2026-10-04", "14:05")
    outside = _iso("2026-10-04", "15:30")
    main = tmp_path / "s1.jsonl"
    main.write_text("\n".join([
        _record("m1", inside, 10, 5), _record("m1", inside, 10, 5), _record("m1", inside, 10, 5),
        _record("m2", outside, 100, 100),
    ]))
    sub = tmp_path / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text(_record("m3", inside, 7, 3))
    (stage,) = log_metrics.parse_stages("## X — claude-code (2026-10-04 14:00–14:10)\n")
    total, out, _ = log_metrics.claude_usage([main, *sub.glob("*.jsonl")], stage)
    assert (total, out) == (15 + 10, 5 + 3)


def _opencode_db(path: Path, rows: list[tuple[str, str, str | None, int, dict]]) -> None:
    c = sqlite3.connect(path)
    c.execute("create table session (id text, directory text, parent_id text, time_created int, time_updated int)")
    c.execute("create table message (id text, session_id text, time_created int, data text)")
    sess = {"top": ("/repo", None), "child": ("/repo", "top")}
    ms = lambda day, hm: int(_local(day, hm).timestamp() * 1000)
    for sid, (d, p) in sess.items():
        c.execute("insert into session values (?,?,?,?,?)", (sid, d, p, ms("2026-10-04", "13:00"), ms("2026-10-04", "16:00")))
    for mid, sid, _x, t, tok in rows:
        data = json.dumps({"role": "assistant", "cost": tok["cost"], "time": {"created": t},
                           "tokens": {"input": tok["i"], "output": tok["o"], "reasoning": 0,
                                      "cache": {"read": 0, "write": 0}}})
        c.execute("insert into message values (?,?,?,?)", (mid, sid, t, data))
    c.commit()
    c.close()


def test_opencode_includes_child_excludes_outside(tmp_path: Path):
    ms = lambda hm: int(_local("2026-10-04", hm).timestamp() * 1000)
    db = tmp_path / "o.db"
    _opencode_db(db, [
        ("a", "top", None, ms("14:05"), {"i": 10, "o": 5, "cost": 0.5}),
        ("b", "child", None, ms("14:06"), {"i": 4, "o": 1, "cost": 0.25}),
        ("c", "top", None, ms("15:30"), {"i": 99, "o": 99, "cost": 9.0}),
    ])
    (stage,) = log_metrics.parse_stages("## X — opencode (2026-10-04 14:00–14:10)\n")
    total, out, cost = log_metrics.opencode_usage(db, "/repo", stage, None)
    assert (total, out, cost) == (20, 6, 0.75)


def test_existing_metrics_row_kept_and_repeated_stage_gets_own_row(tmp_path: Path):
    log = tmp_path / "l.md"
    log.write_text(HEADER.format(h="copilot") + "## Pre-flight — copilot (2026-10-04 14:00–14:05)\n"
                   "## Pre-flight — copilot (2026-10-05 10:00–10:05)\n")
    log_metrics.main([str(log)])
    assert "n/a | n/a | n/a" in log.read_text()
    log.write_text(HEADER.format(h="claude-code") + "## A — claude-code (2026-10-04 14:00–14:05)\n"
                   "\n## Metrics\n\n| Stage | Minutes | Tokens (all) | Output tokens | Cost |\n|---|---|---|---|---|\n"
                   "| A — claude-code (2026-10-04 14:00–14:05) | 5 | 1 | 1 | n/a |\n"
                   "\n## A — claude-code (2026-10-05 10:00–10:05)\n")
    rows = log_metrics.existing_rows(log.read_text())
    assert len(rows) == 1
    assert log_metrics.pending_stages(log.read_text()) and \
        log_metrics.pending_stages(log.read_text())[0].heading.endswith("2026-10-05 10:00–10:05)")


def test_missing_header_exits_zero(tmp_path: Path, capsys):
    log = tmp_path / "l.md"
    log.write_text("# no header\n")
    assert log_metrics.main([str(log)]) == 0
    assert "metrics skipped" in capsys.readouterr().out


def test_records_without_message_id_are_all_counted(tmp_path: Path):
    ts = _iso("2026-10-04", "14:05")
    usage = {"input_tokens": 3, "output_tokens": 1}
    rec = json.dumps({"type": "assistant", "timestamp": ts, "message": {"usage": usage}})
    f = tmp_path / "s.jsonl"
    f.write_text(rec + "\n" + rec)
    (stage,) = log_metrics.parse_stages("## X — claude-code (2026-10-04 14:00–14:10)\n")
    assert log_metrics.claude_usage([f], stage)[0] == 8


def test_metrics_heading_at_end_without_newline_is_replaced_once():
    text = "## A — copilot (2026-10-04 14:00–14:05)\n\n## Metrics"
    assert log_metrics.METRICS_RE.sub("", text).count("## Metrics") == 0


def test_stage_from_another_harness_is_not_read_from_this_harness_records(tmp_path: Path):
    log = tmp_path / "l.md"
    log.write_text(HEADER.format(h="opencode") + "## A — copilot (2026-10-04 14:00–14:05)\n")
    assert log_metrics.main([str(log)]) == 0
    assert "| 5 | n/a | n/a | n/a |" in log.read_text()


def test_rerun_does_not_repeat_session_line(tmp_path: Path):
    log = tmp_path / "l.md"
    text = HEADER.format(h="opencode") + "## A — copilot (2026-10-04 14:00–14:05)\n"
    log.write_text(text)
    log_metrics.write_metrics(log, text, ["| row |"], "s1")
    log_metrics.write_metrics(log, log.read_text(), ["| row2 |"], "s1")
    assert log.read_text().count("Session: s1") == 1
