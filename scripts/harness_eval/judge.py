"""Judge the harness eval's outputs with Gemini and append them to the history.

One structured call per output. For each named criterion the judge writes its
reasoning first, then a 1-4 score, grading the candidate against the task's
reference. Hard checks (`checks.py`) cap the matching criteria; `overall` is
the mean computed here. Tokens and time come from the agent jobs, never from
the judge. A failed judge call fails the job before anything is appended, so
"Re-run failed jobs" judges the same artifacts again.

Run from scripts/:
    uv run --no-project --with google-genai --with pydantic python -m harness_eval.judge ...
"""

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from harness_eval import checks, history

# Gemini 3.x ignores temperature, so the judge is not deterministic; its noise
# is part of the `≈` threshold.
JUDGE_MODEL = "gemini-3.6-flash"
CRITERIA = {
    "plan": {
        "decisions": "Covers every settled decision in the brainstorm; none is dropped or reopened.",
        "units": "Splits the work into ordered, independently reviewable units in a safe order.",
        "concrete": "Names exact paths, shows real before/after code, and names each test and "
        "what it asserts.",
        "right_sized": "Adds no scope the brainstorm did not ask for; its tier fits the real risk.",
        "grounded": "Matches the real repository: the files, functions, and commands it cites "
        "exist and behave as it says.",
    },
    "implement": {
        "does_the_unit": "Implements what the unit specifies: the same behaviour, interfaces, "
        "and defaults.",
        "tests": "Its tests would fail if the behaviour regressed, and cover what the unit's test "
        "section lists.",
        "in_scope": "Touches only what the unit names: no work from other units, no unrelated "
        "edits.",
        "repo_style": "Reads like the surrounding code: naming, comment density, where constants "
        "live, idiom.",
    },
}
SCALE = (
    "For each criterion, write your reasoning first, quoting the candidate where you can, then "
    "give a score: 4 fully meets it, 3 meets it with minor gaps, 2 has a significant gap, 1 fails "
    "it. Return exactly these criteria, using these names:\n{criteria}\n"
    "End with a two-sentence summary of the candidate's main strength and main weakness."
)
PLAN_PROMPT = (
    "You grade an implementation plan an AI agent wrote from a design brainstorm.\n\n"
    "The reference plan was written from the same brainstorm and was implemented successfully. "
    "Use it as an answer key for what the work needs, not as the only acceptable shape: a "
    "different plan that covers the same decisions as safely is as good.\n\n"
    + SCALE
    + "\n\n<brainstorm>\n{brainstorm}\n</brainstorm>\n\n"
    "<reference_plan>\n{reference}\n</reference_plan>\n\n"
    "<candidate_plan>\n{candidate}\n</candidate_plan>\n"
)
IMPLEMENT_PROMPT = (
    "You grade a code change an AI agent made to implement one unit of a plan.\n\n"
    "The reference diff is the change merged for the same unit. Use it as an answer key for what "
    "the unit needs, not as the only acceptable code: a different change with the same behaviour "
    "and tests is as good. The reference also carries later review fixes the unit text never "
    "asked for; where the unit text and the reference disagree, the unit text wins, and following "
    "it is never a fault.\n\n"
    + SCALE
    + "\n\n<unit>\n{unit}\n</unit>\n\n"
    "<reference_diff>\n{reference}\n</reference_diff>\n\n"
    "<candidate_diff>\n{candidate}\n</candidate_diff>\n"
)
JUDGE_VERSION = hashlib.sha256(
    json.dumps([JUDGE_MODEL, CRITERIA, PLAN_PROMPT, IMPLEMENT_PROMPT]).encode()
).hexdigest()[:8]
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
NO_OUTPUT = "The agent produced no output."


class Criterion(BaseModel):
    name: str
    reasoning: str
    score: int = Field(ge=1, le=4)


class Verdict(BaseModel):
    criteria: list[Criterion]
    summary: str


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _level(line: str) -> int:
    hashes = len(line) - len(line.lstrip("#"))
    return hashes if hashes and line[hashes : hashes + 1] == " " else 0


def section(text: str, heading: str) -> str:
    """The heading's block, up to the next heading of the same or a higher level.

    Lines inside code fences are never headings: `# comment` in a fenced
    Python or bash block would otherwise end the section early.
    """
    lines = text.splitlines()
    start = lines.index(heading)  # ValueError: the fixture no longer has this heading
    level = _level(heading)
    in_fence = False
    for i in range(start + 1, len(lines)):
        if FENCE_RE.match(lines[i]):
            in_fence = not in_fence
        elif not in_fence and 0 < _level(lines[i]) <= level:
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:])


def ask(client: genai.Client, prompt: str) -> Verdict:
    response = client.models.generate_content(
        model=JUDGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=Verdict.model_json_schema(),
        ),
    )
    if not response.text:
        reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
        raise RuntimeError(f"judge returned no text (finish reason: {reason})")
    return Verdict.model_validate_json(response.text)


def score(kind: str, verdict: Verdict, caps: dict[str, int]) -> list[dict[str, Any]]:
    """Match criteria by name, in the rubric's order; a missing name is a judge error."""
    by_name = {c.name: c for c in verdict.criteria}
    missing = [n for n in CRITERIA[kind] if n not in by_name]
    if missing:
        raise ValueError(f"judge omitted criteria {missing}")
    return [
        {
            "name": n,
            "reasoning": by_name[n].reasoning,
            "score": min(by_name[n].score, caps.get(n, checks.MAX_SCORE)),
            "cap": caps.get(n),
        }
        for n in CRITERIA[kind]
    ]


def empty(kind: str) -> list[dict[str, Any]]:
    return [{"name": n, "reasoning": NO_OUTPUT, "score": 1, "cap": None} for n in CRITERIA[kind]]


def _criteria_list(kind: str) -> str:
    return "\n".join(f"- {name}: {text}" for name, text in CRITERIA[kind].items())


def judge_output(
    client: genai.Client, out_dir: Path, task: dict[str, Any], repo: Path, fixtures: Path
) -> dict[str, Any]:
    result = json.loads((out_dir / "result.json").read_text())
    kind = result["kind"]
    plan_v2 = (fixtures / "plan_v2.md").read_text()
    if kind == "plan":
        candidate = (out_dir / "candidate.md").read_text()
        files = git(repo, "ls-tree", "-r", "--name-only", task["plan"]["start"]).splitlines()
        found = checks.plan_checks(candidate, files)
        caps, hard = checks.plan_caps(found), asdict(found)
        prompt = PLAN_PROMPT.format(
            criteria=_criteria_list(kind),
            brainstorm=(fixtures / "brainstorm.md").read_text(),
            reference=plan_v2,
            candidate=candidate,
        )
    else:
        imp = task["implement"]
        candidate = (out_dir / "candidate.diff").read_text()
        hard = {
            **(result["checks"] or {}),
            "out_of_scope": checks.out_of_scope(result["changed_files"], imp["unit_files"]),
        }
        caps = checks.implement_caps(result["checks"], result["changed_files"], imp["unit_files"])
        prompt = IMPLEMENT_PROMPT.format(
            criteria=_criteria_list(kind),
            unit="\n\n".join(section(plan_v2, h) for h in imp["unit_sections"]),
            reference=git(repo, "diff", imp["start"], imp["reference_end"]),
            candidate=candidate,
        )
    if candidate.strip():
        verdict = ask(client, prompt)
        graded, summary = score(kind, verdict, caps), verdict.summary
    else:
        graded, summary = empty(kind), NO_OUTPUT
    return {
        **result,
        "criteria": graded,
        "summary": summary,
        "hard_checks": hard,
        "overall": round(mean(c["score"] for c in graded), 2),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True, help="one sub-directory per artifact")
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--verdicts", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--summary", type=Path, required=True)
    args = p.parse_args()

    task = json.loads((args.fixtures / "task.json").read_text())
    outputs = sorted(r.parent for r in args.results.glob("*/result.json"))
    if not outputs:
        raise SystemExit("no agent produced a result")
    client = genai.Client()  # reads GEMINI_API_KEY
    judged = [judge_output(client, d, task, args.repo, args.fixtures) for d in outputs]
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    rows = [
        history.row(j, run_id=args.run_id, date=date, sha=args.sha, note=args.note,
                    judge_version=JUDGE_VERSION)
        for j in judged
    ]
    history.append(args.history, rows)
    args.verdicts.write_text(json.dumps(judged, indent=2))
    with args.summary.open("a") as f:
        f.write(history.render(history.load(args.history)) + history.render_reasoning(judged))


if __name__ == "__main__":
    main()
