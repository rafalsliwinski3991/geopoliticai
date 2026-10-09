"""Hard checks for the harness eval, run in code before the judge.

Each failed check caps one rubric criterion, so the judge cannot score a
plan grounded when its paths do not exist, or an implementation in scope when
it touches another unit's files. Pure functions over text and lists.
"""

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass

PATH_RE = re.compile(
    r"`((?:[\w.-]+/)*[\w.-]+\.(?:py|toml|md|yml|yaml|json|jsonc|txt|lock|sh|ini|cfg|html|ts|js))`"
)
# A path on a line that says the file is new is declared new, along with
# every later mention of its bare file name (plans cite `tools.py` after
# declaring `agents/deep_expert/tools.py` new; a directory-qualified path
# is still checked against the repo). "add" is not enough: plans
# "add" to existing files constantly.
NEW_RE = re.compile(r"\b(?:new|creat(?:e|es|ed|ing))\b", re.IGNORECASE)
TIER_RE = re.compile(
    r"\btier\b\W{0,5}(lightweight|standard|full)\b|\b(lightweight|standard|full)\s+(?:plan|tier)\b",
    re.IGNORECASE,
)
UNIT_RE = re.compile(r"^#{2,4} .*\b(?:unit|commit|task) ?\d+", re.IGNORECASE | re.MULTILINE)
TIER_LINES = 40
GROUNDED_MIN = 0.9
MAX_SCORE = 4


@dataclass(frozen=True)
class PlanChecks:
    tier: str | None
    unit_headings: int
    cited: int
    unresolved: tuple[str, ...]


def _exists(path: str, files: list[str]) -> bool:
    """Plans cite paths relative to the repo, to agentic_backend/, or to src/."""
    path = posixpath.normpath(path).removeprefix("../")
    return any(f == path or f.endswith("/" + path) for f in files)


def plan_checks(text: str, files: list[str]) -> PlanChecks:
    head = "\n".join(text.splitlines()[:TIER_LINES])
    m = TIER_RE.search(head)
    tier = (m.group(1) or m.group(2)).lower() if m else None
    cited: set[str] = set()
    new: set[str] = set()
    for line in text.splitlines():
        paths = PATH_RE.findall(line)
        cited.update(paths)
        if NEW_RE.search(line):
            new.update(paths)
    new_names = {posixpath.basename(p) for p in new}
    unresolved = sorted(
        p for p in cited
        if p not in new
        and not ("/" not in p and p in new_names)
        and not p.startswith("docs/")  # gitignored plans, brainstorms, logs
        and not _exists(p, files)
    )
    return PlanChecks(tier, len(UNIT_RE.findall(text)), len(cited), tuple(unresolved))


def plan_caps(checks: PlanChecks) -> dict[str, int]:
    caps: dict[str, int] = {}
    if checks.unit_headings == 0:
        caps["units"] = 1
    if checks.tier is None:
        caps["right_sized"] = 2
    if checks.cited and 1 - len(checks.unresolved) / checks.cited < GROUNDED_MIN:
        caps["grounded"] = 2
    return caps


def out_of_scope(changed: Iterable[str], unit_files: Iterable[str]) -> list[str]:
    allowed = set(unit_files)
    return sorted(f for f in changed if f not in allowed)


def implement_caps(changed: Iterable[str], unit_files: Iterable[str]) -> dict[str, int]:
    """Scope is the only per-unit cap: tests and lint run once on the whole stack,
    so a failure cannot be pinned to one unit; they are reported, not capped."""
    return {"in_scope": 2} if out_of_scope(changed, unit_files) else {}
