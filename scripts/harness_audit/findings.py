"""Read the harness audit's findings from Claude Code's JSON result, and keep
only the ones the repository confirms.

Claude Code validates `structured_output` against findings.schema.json; this
checks the same rules again, so a result without valid output fails the job
instead of filing an empty or garbled issue (a `success` subtype with no
`structured_output` is a failure too, per Claude Code's structured-output docs).
A well-formed finding whose file is not a tracked file of this repository, whose
line is past the end, or whose quote is not on that line is dropped and listed,
never filed: the model's claims are checked against the checkout.

Run from scripts/:
    python3 -m harness_audit.findings --raw raw.json --repo .. --out findings.json
"""

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FIELDS = ("kind", "file", "line", "quote", "problem", "fix")
TEXT_FIELDS = ("file", "quote", "problem", "fix")
KINDS = range(1, 7)


class AuditFailed(Exception):
    """The audit produced no usable findings."""


@dataclass(frozen=True, order=True)
class Finding:
    kind: int
    file: str
    line: int
    quote: str
    problem: str
    fix: str


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse(item: Any) -> Finding:
    if not isinstance(item, dict) or set(item) != set(FIELDS):
        raise AuditFailed(f"a finding needs exactly the fields {FIELDS}: {item!r}")
    if not _is_int(item["kind"]) or item["kind"] not in KINDS:
        raise AuditFailed(f"kind must be 1-6: {item['kind']!r}")
    if not _is_int(item["line"]) or item["line"] < 1:
        raise AuditFailed(f"line must be a positive integer: {item['line']!r}")
    for name in TEXT_FIELDS:
        if not isinstance(item[name], str) or not item[name].strip():
            raise AuditFailed(f"{name} must be non-empty text: {item[name]!r}")
    return Finding(**item)


def load(raw: Path) -> list[Finding]:
    """Findings sorted by kind, file, then line."""
    try:
        result = json.loads(raw.read_text())
    except (OSError, ValueError) as e:
        raise AuditFailed(f"no readable Claude Code result: {e}") from e
    if not isinstance(result, dict):
        raise AuditFailed("the Claude Code result is not a JSON object")
    output = result.get("structured_output")
    if result.get("subtype") != "success" or not isinstance(output, dict):
        raise AuditFailed(f"the audit ended without findings (subtype {result.get('subtype')!r})")
    items = output.get("findings")
    if not isinstance(items, list):
        raise AuditFailed("structured_output has no findings list")
    return sorted(parse(i) for i in items)


def _tracked(repo: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True, text=True
    ).stdout
    return set(out.split("\0")[:-1])


def problem_with(f: Finding, repo: Path, tracked: set[str]) -> str | None:
    """Why the checkout contradicts this finding, or None when it holds.

    A path through a symlinked skill directory counts as its target's path.
    """
    root = repo.resolve()
    target = (root / f.file).resolve()
    if not target.is_relative_to(root):
        return "path leaves the repository"
    rel = target.relative_to(root).as_posix()
    if rel not in tracked:
        return "not a tracked file"
    lines = target.read_text(errors="replace").splitlines()
    if f.line > len(lines):
        return f"line {f.line} is past the end ({len(lines)} lines)"
    first = f.quote.strip().splitlines()[0].strip()
    if first not in lines[f.line - 1]:
        return "the quote is not on that line"
    return None


def verify(found: list[Finding], repo: Path) -> tuple[list[Finding], list[dict[str, Any]]]:
    tracked = _tracked(repo)
    kept, dropped = [], []
    for f in found:
        reason = problem_with(f, repo, tracked)
        if reason is None:
            kept.append(f)
        else:
            dropped.append({**asdict(f), "reason": reason})
    return kept, dropped


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, required=True, help="claude --output-format json result")
    p.add_argument("--repo", type=Path, required=True, help="the audited checkout")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    try:
        kept, dropped = verify(load(args.raw), args.repo)
    except AuditFailed as e:
        raise SystemExit(f"harness audit failed: {e}") from e
    args.out.write_text(json.dumps({"findings": [asdict(f) for f in kept], "dropped": dropped}, indent=2))
    print(f"{len(kept)} findings, {len(dropped)} dropped")


if __name__ == "__main__":
    main()
