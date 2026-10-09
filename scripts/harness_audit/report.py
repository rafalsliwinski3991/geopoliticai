"""File the harness audit's findings as one GitHub issue per run.

The issue holds every finding, grouped by kind. Opening it closes the previous
open audit issue for the same target (a pull request, or a branch for a manual
run); a run with no findings opens none and closes the previous one as
resolved. Only the workflow's `report` job runs this; it never runs the agent.
Text the model wrote is neutralised so it cannot mention people or link issues.

Run from scripts/:
    python3 -m harness_audit.report --findings findings.json --target "PR #175" \
        --sha <sha> --run-url <url> --summary "$GITHUB_STEP_SUMMARY"
"""

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_audit.findings import Finding

LABEL = "harness-audit"
LABEL_COLOR = "BFD4F2"
LABEL_DESCRIPTION = "Findings of the harness audit workflow"
TITLE_PREFIX = "Harness audit: "
KIND_TITLES = {
    1: "A port differs in meaning from its Claude original",
    2: "A reference to something that does not exist",
    3: "A contradiction",
    4: "Syntax the target tool does not read",
    5: "Another tool's features in a harness's file",
    6: "A model the harness runs that does not belong to it",
}
# GitHub refuses an issue body over 65,536 bytes; keep a margin.
MAX_BODY_BYTES = 60_000
TRUNCATED = "\n\n…truncated: the run's Summary lists every finding.\n"
ZWSP = "\u200b"
ISSUE_REF_RE = re.compile(r"#(\d)")


@dataclass(frozen=True)
class Actions:
    create: bool
    close: tuple[int, ...]


def neutral(text: str) -> str:
    """Break `@name` mentions and `#123` references with a zero-width space."""
    return ISSUE_REF_RE.sub(f"#{ZWSP}\\1", text.replace("@", f"@{ZWSP}"))


def title(target: str, sha: str, count: int) -> str:
    noun = "finding" if count == 1 else "findings"
    return f"{TITLE_PREFIX}{target} @ {sha[:7]} ({count} {noun})"


def body(found: list[Finding], target: str, sha: str, run_url: str) -> str:
    lines = [f"Harness audit of {target} at `{sha[:7]}`: {len(found)} findings. [Run]({run_url})", ""]
    for kind, heading in KIND_TITLES.items():
        group = [f for f in found if f.kind == kind]
        if not group:
            continue
        lines += [f"## {kind}. {heading}", ""]
        for f in group:
            lines.append(f"- [ ] `{f.file}:{f.line}` {neutral(f.problem)}")
            lines += [f"  > {neutral(q)}" for q in f.quote.splitlines()]
            lines += [f"  Fix: {neutral(f.fix)}", ""]
    return "\n".join(lines)


def dropped_note(dropped: list[dict[str, Any]]) -> str:
    if not dropped:
        return ""
    rows = "".join(f"- `{d['file']}:{d['line']}` ({d['reason']})\n" for d in dropped)
    return f"\n### Dropped: not confirmed by the checkout\n\n{rows}"


def clip(text: str) -> str:
    """Cap the body on UTF-8 bytes, never splitting a multibyte character."""
    payload = text.encode()
    if len(payload) <= MAX_BODY_BYTES:
        return text
    limit = MAX_BODY_BYTES - len(TRUNCATED.encode())
    head = payload[:limit].decode(errors="ignore")
    if len(head.encode()) > limit:
        head = head[:-1]
    return head + TRUNCATED


def decide(open_issues: Iterable[dict[str, Any]], target: str, found: list[Finding]) -> Actions:
    """Open an issue when there are findings; close every open one for the same target."""
    prefix = f"{TITLE_PREFIX}{target} @ "
    previous = tuple(sorted(i["number"] for i in open_issues if i["title"].startswith(prefix)))
    return Actions(create=bool(found), close=previous)


def gh(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["gh", *args], input=stdin, check=True, capture_output=True, text=True
    ).stdout


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--findings", type=Path, required=True)
    p.add_argument("--target", required=True, help='"PR #175", or the branch of a manual run')
    p.add_argument("--sha", required=True)
    p.add_argument("--run-url", required=True)
    p.add_argument("--summary", type=Path, required=True)
    args = p.parse_args()

    data = json.loads(args.findings.read_text())
    found = [Finding(**f) for f in data["findings"]]
    text = body(found, args.target, args.sha, args.run_url)
    # The Summary first: it survives any gh failure below.
    with args.summary.open("a") as f:
        f.write(f"## Harness audit\n\n{text if found else 'No findings.'}\n{dropped_note(data['dropped'])}")
    gh("label", "create", LABEL, "--color", LABEL_COLOR, "--description", LABEL_DESCRIPTION, "--force")
    open_issues = json.loads(
        gh("issue", "list", "--label", LABEL, "--state", "open", "--limit", "200", "--json", "number,title")
    )
    actions = decide(open_issues, args.target, found)
    if actions.create:
        # --body-file - keeps a 60,000-byte body out of argv's per-argument limit.
        url = gh(
            "issue", "create", "--title", title(args.target, args.sha, len(found)),
            "--label", LABEL, "--body-file", "-", stdin=clip(text),
        ).strip()
        comment = f"Superseded by {url}."
    else:
        comment = f"Resolved in `{args.sha[:7]}`: the audit found nothing."
    failed = []
    for number in actions.close:
        try:
            gh("issue", "close", str(number), "--comment", comment)
        except subprocess.CalledProcessError as e:
            failed.append(f"#{number}: {e.stderr.strip()}")
    if failed:
        raise SystemExit("could not close: " + "; ".join(failed))


if __name__ == "__main__":
    main()
