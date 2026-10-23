"""Append a `## Metrics` table to a harness run log.

Stage windows come from the log's own headings, tokens from the harness's
records (Claude Code transcripts, OpenCode's SQLite database), so the model
never writes a token number. Every expected failure prints `metrics skipped:
<reason>` and exits 0: logging must never fail the command that runs it.

Usage: python3 scripts/log_metrics.py <log.md> [--session <id>]
"""

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
STAGE_RE = re.compile(
    r"^## (?P<heading>(?P<stage>.+?) — (?P<harness>[a-z-]+) "
    r"\((?P<d>\d{4}-\d\d-\d\d) (?P<a>\d\d:\d\d)[–-](?P<b>\d\d:\d\d)\))$",
    re.MULTILINE,
)
METRICS_RE = re.compile(r"^## Metrics\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
TABLE_HEAD = (
    "| Stage | Minutes | Tokens (all) | Output tokens | Cost |\n"
    "|---|---|---|---|---|\n"
)
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


@dataclass(frozen=True)
class Stage:
    heading: str
    harness: str
    start: datetime
    end: datetime
    minutes: int


def _minute_of_day(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def parse_stages(text: str) -> list[Stage]:
    stages = []
    for m in STAGE_RE.finditer(text):
        start = datetime.fromisoformat(f"{m['d']}T{m['a']}:00").astimezone()
        end = datetime.fromisoformat(f"{m['d']}T{m['b']}:59").astimezone()
        if m["b"] < m["a"]:
            end += timedelta(days=1)
        minutes = (_minute_of_day(m["b"]) - _minute_of_day(m["a"])) % 1440
        stages.append(Stage(m["heading"], m["harness"], start, end, minutes))
    return stages


def parse_header(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return {}
    block = lines[1 : lines.index("---", 1)]
    return {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in block)}


def encode_project_dir(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def claude_usage(paths: list[Path], stage: Stage) -> tuple[int, int, None]:
    """Sum usage of assistant messages in the window, once per message id."""
    seen: set[str] = set()
    total = out = 0
    for path in paths:
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message")
            if rec.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            usage, mid = msg.get("usage"), msg.get("id")
            if not usage or (mid is not None and mid in seen) or "timestamp" not in rec:
                continue
            if not stage.start <= _ts(rec["timestamp"]) <= stage.end:
                continue
            if mid is not None:
                seen.add(mid)
            out += usage.get("output_tokens", 0)
            total += total_tokens(usage)
    return total, out, None


def total_tokens(usage: dict) -> int:
    return sum(
        usage.get(k, 0)
        for k in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    )


def claude_paths(log: Path, since: datetime, session: str | None) -> list[Path]:
    root = CLAUDE_PROJECTS / encode_project_dir(str(Path.cwd()))
    if session:
        main = root / f"{session}.jsonl"
    else:
        found = [p for p in root.glob("*.jsonl") if p.stat().st_mtime >= since.timestamp()]
        if not found:
            raise LookupError(f"no Claude Code transcript under {root}")
        named = [p for p in found if log.name in p.read_text()]
        main = max(named or found, key=lambda p: p.stat().st_mtime)
    return [main, *sorted((main.with_suffix("") / "subagents").glob("*.jsonl"))]


def opencode_usage(
    db: Path, cwd: str, stage: Stage, session: str | None
) -> tuple[int, int, float]:
    lo, hi = int(stage.start.timestamp() * 1000), int(stage.end.timestamp() * 1000)
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        if session is None:
            row = con.execute(
                "select id from session where directory=? and parent_id is null "
                "and time_created<=? and time_updated>=? order by time_updated desc limit 1",
                (cwd, hi, lo),
            ).fetchone()
            if row is None:
                raise LookupError("no OpenCode session overlaps the window")
            session = row[0]
        ids = [session] + [
            r[0] for r in con.execute("select id from session where parent_id=?", (session,))
        ]
        total = out = 0
        cost = 0.0
        marks = ",".join("?" * len(ids))
        for (data,) in con.execute(
            f"select data from message where session_id in ({marks}) "
            "and time_created between ? and ?",
            (*ids, lo, hi),
        ):
            msg = json.loads(data)
            if msg.get("role") != "assistant":
                continue
            t = msg.get("tokens", {})
            cache = t.get("cache", {})
            total += sum(
                (t.get("input", 0), t.get("output", 0), t.get("reasoning", 0),
                 cache.get("read", 0), cache.get("write", 0))
            )
            out += t.get("output", 0) + t.get("reasoning", 0)
            cost += msg.get("cost", 0) or 0
        return total, out, cost
    finally:
        con.close()


def existing_rows(text: str) -> dict[str, str]:
    block = METRICS_RE.search(text)
    rows: dict[str, str] = {}
    for line in (block.group(0) if block else "").splitlines():
        if line.startswith("| ") and not line.startswith("| Stage"):
            rows[line.split("|")[1].strip()] = line
    return rows


def pending_stages(text: str) -> list[Stage]:
    done = existing_rows(text)
    return [s for s in parse_stages(text) if s.heading not in done]


def _row(stage: Stage, usage: tuple[int, int, float | None] | None) -> str:
    if usage is None:
        return f"| {stage.heading} | {stage.minutes} | n/a | n/a | n/a |"
    total, out, cost = usage
    cost_cell = "n/a" if cost is None else f"{cost:.4f}"
    return f"| {stage.heading} | {stage.minutes} | {total} | {out} | {cost_cell} |"


def _skip(reason: str) -> int:
    print(f"metrics skipped: {reason}")
    return 0


def write_metrics(log: Path, text: str, new_rows: list[str], session: str) -> None:
    old = METRICS_RE.search(text)
    sessions = [
        ln for ln in (old.group(0) if old else "").splitlines() if ln.startswith("Session:")
    ]
    if f"Session: {session}" not in sessions:
        sessions.append(f"Session: {session}")
    body = METRICS_RE.sub("", text).rstrip("\n")
    section = "\n\n## Metrics\n\n" + TABLE_HEAD
    section += "\n".join([*existing_rows(text).values(), *new_rows])
    log.write_text(body + section + "\n\n" + "\n".join(sessions) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", type=Path)
    ap.add_argument("--session")
    args = ap.parse_args(argv)
    try:
        text = args.log.read_text()
        harness = parse_header(text).get("harness")
        if harness not in {"claude-code", "opencode", "copilot", "antigravity"}:
            return _skip("log has no header with a known harness")
        pending = pending_stages(text)
        if not pending:
            return _skip("no stage headings without a metrics row")
        # Each stage is read from the records of the harness that wrote it: the
        # header names only the harness that started the log.
        claude = [s for s in pending if s.harness == "claude-code"]
        claude_files = (
            claude_paths(args.log, min(s.start for s in claude), args.session) if claude else []
        )
        sessions = [claude_files[0].stem] if claude_files else []
        rows = []
        for s in pending:
            if s.harness == "claude-code":
                rows.append(_row(s, claude_usage(claude_files, s)))
            elif s.harness == "opencode":
                rows.append(_row(s, opencode_usage(OPENCODE_DB, str(Path.cwd()), s, args.session)))
            else:
                rows.append(_row(s, None))
        if any(s.harness == "opencode" for s in pending):
            sessions.append(args.session or "opencode: latest overlapping")
        write_metrics(args.log, text, rows, ", ".join(sessions) or "n/a")
        print(f"appended metrics: {len(rows)} stages")
        return 0
    except Exception as exc:  # noqa: BLE001 - logging must never fail the command
        return _skip(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
