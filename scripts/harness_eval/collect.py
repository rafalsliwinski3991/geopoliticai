"""Collect one harness-eval agent run into its artifact directory.

Usage comes from the harness's own records (Claude Code's `--output-format
json` result, OpenCode's SQLite database), so no number is guessed: what is
missing, for example after a timeout, is written as null. Hard-check results
are measured by the workflow and passed in.

Usage: python3 -m harness_eval.collect --subject impl-sonnet --kind implement ...
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
# A step killed by its timeout ends a few seconds after the limit.
TIMEOUT_SLACK_S = 30
CHECK_NAMES = ("tests_before", "tests_after", "lint")
# `rs-implement-plan` (Claude Code and OpenCode alike) cuts one branch per unit,
# named `<stack-slug>/NN-<short-slug>` (a slug of lowercase letters, digits and
# hyphens): git, not the agent's prose, records them.
UNIT_BRANCH_RE = re.compile(r"^[^/]+/(\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$")
# The ledger line it appends when a unit's audit passes, "Unit 05: complete
# (commits …)". Written by hand, so tolerate bullets, bold, a missing zero, and "is complete".
UNIT_DONE_RE = re.compile(r"\bUnit\W{0,6}(\d{1,2})\W{0,6}(?:is\W{1,6})?complete\b", re.IGNORECASE)
# Appended after the final review, so it also says the review ran.
FINAL_HEADS_RE = re.compile(r"^\W*Final heads\W", re.MULTILINE | re.IGNORECASE)
REDACTED = b"[REDACTED]"
# A shorter value would scrub ordinary text; no real key is this short.
REDACT_MIN_CHARS = 8


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
    # NUL-separated and without rename detection: a rename lists both paths,
    # and names with spaces or non-ASCII characters stay whole.
    return git(ws, "diff", "--name-only", "-z", "--no-renames", base).split("\0")[:-1]


def read_ledger(ws: Path) -> str:
    """The run's ledger: one plan per eval run, so the first one found is it."""
    found = sorted((ws / "docs" / "harness_logs").glob("*/ledger.md"))
    return found[0].read_text() if found else ""


def completed_units(ledger: str) -> set[str]:
    """Two-digit numbers of the units the ledger marks complete."""
    return {m[1].zfill(2) for m in UNIT_DONE_RE.finditer(ledger)}


def unit_branches(ws: Path) -> dict[str, str]:
    """Unit number to branch name, in unit order; the first name sorted wins a duplicate."""
    found: dict[str, str] = {}
    for name in sorted(git(ws, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()):
        m = UNIT_BRANCH_RE.match(name)
        if m:
            found.setdefault(m[1], name)
    return dict(sorted(found.items()))


def _is_ancestor(ws: Path, older: str, newer: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ws), "merge-base", "--is-ancestor", older, newer], check=False
    ).returncode == 0


def _unit_diff(ws: Path, out: Path, unit: str, refs: list[str], complete: bool) -> dict[str, Any]:
    """One unit's diff: `refs` is [start, head], or [start] for the working tree."""
    rel = f"units/u{unit}.diff"
    (out / rel).write_text(git(ws, "diff", "--binary", *refs))
    names = git(ws, "diff", "--name-only", "-z", "--no-renames", *refs).split("\0")[:-1]
    return {"unit": unit, "diff": rel, "changed_files": names, "complete": complete}


def split_stack(
    ws: Path, base: str, ledger: str, out: Path, first_unit: int = 1
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cut the agent's stack into one diff per unit branch.

    Unit N's diff runs from the previous unit's branch (the overlay commit for
    `first_unit`) to its own branch. The branch checked out at the end is diffed
    against the working tree instead, so a run stopped mid-unit keeps its
    uncommitted work; call after `capture_diff`, whose intent-to-add makes
    untracked files part of that diff. Completion comes from the ledger.
    """
    (out / "units").mkdir(parents=True, exist_ok=True)
    branches = unit_branches(ws)
    done = completed_units(ledger)
    current = git(ws, "branch", "--show-current").strip()
    units: list[dict[str, Any]] = []
    chained, start = bool(branches), base
    for number, (unit, branch) in enumerate(branches.items(), first_unit):
        if unit != f"{number:02d}":
            # A missing unit's work would land in this unit's diff.
            chained = False
            break
        head = git(ws, "rev-parse", branch).strip()
        chained = chained and _is_ancestor(ws, start, head)
        refs = [start] if branch == current else [start, head]
        entry = _unit_diff(ws, out, unit, refs, unit in done)
        # A branch with no change is cut, not reached.
        if entry["changed_files"]:
            units.append(entry)
        start = head
    stack = {
        "units_reached": len(units),
        "units_done": sum(u["complete"] for u in units),
        "chained": chained,
        "final_heads": bool(FINAL_HEADS_RE.search(ledger)),
        # The final branch is not a unit branch: uncommitted work there is not graded.
        "head_off_stack": current not in branches.values(),
    }
    return units, stack


def redact(out: Path, secrets: Iterable[str]) -> None:
    """Replace every secret value in every collected file before upload."""
    # Longest first, so a secret that contains another is not left half-scrubbed.
    values = sorted({s.encode() for s in secrets if len(s) >= REDACT_MIN_CHARS}, key=len, reverse=True)
    if not values:
        return
    for path in out.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        clean = data
        for value in values:
            clean = clean.replace(value, REDACTED)
        if clean != data:
            path.write_bytes(clean)


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
    try:
        return dict(zip(CHECK_NAMES, (int(p) for p in parts), strict=True))
    except ValueError:
        return None


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
    p.add_argument(
        "--redact-env", default="", help="comma-separated names of env vars whose values are scrubbed"
    )
    p.add_argument("--first-unit", type=int, default=1, help="the number of the first unit the agent builds")
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
    units: list[dict[str, Any]] = []
    stack: dict[str, Any] | None = None
    if args.kind == "plan":
        plan = args.ws / args.output
        (args.out / "candidate.md").write_text(plan.read_text() if plan.exists() else "")
    else:
        changed = capture_diff(args.ws, args.base, args.out)
        units, stack = split_stack(args.ws, args.base, read_ledger(args.ws), args.out, args.first_unit)
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
        "units": units,
        "stack_checks": stack,
    }
    names = [n.strip() for n in args.redact_env.split(",") if n.strip()]
    redact(args.out, [os.environ.get(n, "") for n in names])
    (args.out / "result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
