"""Collect one harness-eval agent run into its artifact directory.

Usage comes from the harness's own records (Claude Code's `--output-format
json` result, OpenCode's SQLite database), so no number is guessed: what is
missing, for example after a timeout, is written as null. Hard-check results
are measured by the workflow and passed in.

Usage: python3 -m harness_eval.collect --subject impl-sonnet --kind implement ...
"""

import argparse
import json
import shutil
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
# A step killed by its timeout ends a few seconds after the limit.
TIMEOUT_SLACK_S = 30
CHECK_NAMES = ("tests_before", "tests_after", "lint")


@dataclass(frozen=True)
class Usage:
    tokens_in: int | None = None
    tokens_cached: int | None = None
    tokens_out: int | None = None
    est_cost_usd: float | None = None


def claude_usage(raw: Path) -> Usage:
    """Read the result object; `modelUsage` covers every model, subagents included."""
    try:
        result = json.loads(raw.read_text())
    except (OSError, ValueError):
        return Usage()
    cost = result.get("total_cost_usd")
    models = list((result.get("modelUsage") or {}).values())
    if models:
        def total(key: str) -> int:
            return sum(m.get(key, 0) for m in models)

        return Usage(
            total("inputTokens") + total("cacheCreationInputTokens"),
            total("cacheReadInputTokens"),
            total("outputTokens"),
            cost,
        )
    usage = result.get("usage") or {}
    if not usage:
        return Usage(est_cost_usd=cost)
    return Usage(
        usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
        usage.get("output_tokens", 0),
        cost,
    )


def opencode_usage(db: Path) -> Usage:
    """Sum every assistant message; the runner's database holds only this run."""
    if not db.exists():
        return Usage()
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    tokens_in = cached = out = 0
    cost = 0.0
    try:
        for (data,) in con.execute("select data from message"):
            msg = json.loads(data)
            if msg.get("role") != "assistant":
                continue
            t = msg.get("tokens", {})
            cache = t.get("cache", {})
            tokens_in += t.get("input", 0) + cache.get("write", 0)
            cached += cache.get("read", 0)
            out += t.get("output", 0) + t.get("reasoning", 0)
            cost += msg.get("cost", 0) or 0
    finally:
        con.close()
    return Usage(tokens_in, cached, out, round(cost, 4))


def git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ws), *args], check=True, capture_output=True, text=True
    ).stdout


def capture_diff(ws: Path, base: str, out: Path) -> list[str]:
    """Write the candidate diff, committed or not, and return the touched paths."""
    git(ws, "add", "-A", "-N")  # untracked, non-ignored files show in the diff
    (out / "candidate.diff").write_text(git(ws, "diff", "--binary", base))
    return git(ws, "diff", "--name-only", base).split()


def read_epoch(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def timing(started: int | None, ended: int | None, limit_s: int) -> tuple[float | None, bool]:
    if started is None or ended is None:
        return None, False
    elapsed = ended - started
    return round(elapsed / 60, 1), elapsed >= limit_s - TIMEOUT_SLACK_S


def parse_checks(value: str) -> dict[str, int] | None:
    parts = value.split(",") if value else []
    if len(parts) != len(CHECK_NAMES) or not all(p.strip() for p in parts):
        return None
    return dict(zip(CHECK_NAMES, (int(p) for p in parts), strict=True))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subject", required=True)
    p.add_argument("--kind", choices=("plan", "implement"), required=True)
    p.add_argument("--repeat", type=int, required=True)
    p.add_argument("--harness", choices=("claude", "opencode"), required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--raw", type=Path, help="Claude Code's --output-format json result")
    p.add_argument("--ws", type=Path, required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--output", default="", help="the plan path inside the workspace")
    p.add_argument("--started-file", type=Path, required=True)
    p.add_argument("--ended-file", type=Path, required=True)
    p.add_argument("--step-timeout-s", type=int, required=True)
    p.add_argument("--agent-outcome", required=True, help="the agent step's outcome")
    p.add_argument("--checks", default="", help="tests_before,tests_after,lint")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.harness == "claude":
        usage = claude_usage(args.raw) if args.raw else Usage()
        if args.raw and args.raw.exists():
            shutil.copy(args.raw, args.out / "raw.json")
    else:
        usage = opencode_usage(OPENCODE_DB)
    changed: list[str] = []
    if args.kind == "plan":
        plan = args.ws / args.output
        (args.out / "candidate.md").write_text(plan.read_text() if plan.exists() else "")
    else:
        changed = capture_diff(args.ws, args.base, args.out)
    logs = args.ws / "docs" / "harness_logs"
    if logs.is_dir():
        shutil.copytree(logs, args.out / "harness_logs", dirs_exist_ok=True)
    minutes, timed_out = timing(
        read_epoch(args.started_file), read_epoch(args.ended_file), args.step_timeout_s
    )
    result = {
        "subject": args.subject,
        "kind": args.kind,
        "repeat": args.repeat,
        "harness": args.harness,
        "model": args.model,
        **asdict(usage),
        "minutes": minutes,
        "timed_out": timed_out,
        # A timeout also fails the step; only a failure before the limit is a crash.
        "agent_failed": args.agent_outcome != "success" and not timed_out,
        "changed_files": changed,
        "checks": parse_checks(args.checks),
    }
    (args.out / "result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
