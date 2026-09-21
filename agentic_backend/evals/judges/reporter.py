"""Reporter judges: structure, citation provenance, and output against the transcript.

The reporter samples at temperature 1.0, so nothing here compares with a
recorded outline or report: two correct runs differ.
"""

from __future__ import annotations

import json
import re
from typing import Any

from evals.helpers.judge import Judge, markdown_link_urls

HEADING_NOISE = re.compile(r"^(?:\d+[.)]\s*)?[*_]*(.*?)[*_]*:?$")
OUTLINE_PROMPT = """
You grade a report outline proposed from a conversation transcript.

Transcript:
{transcript}

User decisions at the outline, in order:
{decisions}

Final outline:
{outline}

Notice shown to the user:
{notice}

Rules the outline must follow:
- Every section is answerable from material already in the transcript.
- Three to eight short, concrete headings that name the subject.
- A revision asking for material the transcript lacks adds no section and is
  explained in the notice instead; otherwise the notice is empty.

Choose exactly one label:
1: most sections are not covered by the transcript.
2: several sections are uncovered, or a rule is clearly broken.
3: one section is uncovered or one rule is bent.
4: follows every rule with a minor weakness in the headings.
5: follows every rule.

Give a concise evidence-based explanation naming any uncovered section.
"""
REPORT_PROMPT = """
You grade a written report built only from a conversation transcript.

Transcript:
{transcript}

Approved outline:
{outline}

Report:
{report}

Rules the report must follow:
- Every claim comes from the transcript; nothing is added from outside it.
- Content is drawn from every turn that bears on a section, not one answer restated.
- A section with thin material says so plainly instead of filling the gap.

Choose exactly one label:
1: invents material, or is not a report on this outline.
2: several claims are not in the transcript.
3: one claim is not in the transcript, or a thin section is not flagged.
4: follows every rule with a minor weakness in synthesis.
5: follows every rule.

Give a concise evidence-based explanation naming any unsupported claim.
"""


def _normalize_heading(heading: str) -> str:
    """Drop numbering, emphasis, a trailing colon, and case before comparing."""
    match = HEADING_NOISE.match(heading.strip())
    return (match.group(1) if match else heading).strip().rstrip(":").strip().casefold()


def _report_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not expected["report"]:
        return None
    return {
        "report": output.get("report") or "",
        "outline": list(output.get("outline") or []),
        "transcript": input["transcript"],
    }


def _outline_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    # A refusal or revision-cap outcome ends with an empty outline plus a
    # notice; that is the prompt's rule 3, not an ungrounded outline.
    if not expected["outline"]:
        return None
    return {
        "transcript": input["transcript"],
        "decisions": json.dumps(input["resumes"]),
        "outline": "\n".join(output.get("outline") or []) or "(none)",
        "notice": output.get("notice") or "(none)",
    }


def _report_rules_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not expected["report"]:
        return None
    return {
        "transcript": input["transcript"],
        "outline": "\n".join(output.get("outline") or []),
        "report": output.get("report") or "",
    }


def follows_outline(variables: dict[str, Any]) -> bool:
    """Pass on one leading `#` title and `##` headings matching the outline (rules 1, 5)."""
    lines = [line.strip() for line in variables["report"].splitlines() if line.strip()]
    titles = [line for line in lines if line.startswith("# ")]
    headings = [
        _normalize_heading(line[3:]) for line in lines if line.startswith("## ")
    ]
    outline = [_normalize_heading(heading) for heading in variables["outline"]]
    return (
        bool(lines)
        and lines[0].startswith("# ")
        and len(titles) == 1
        and headings == outline
    )


def urls_from_transcript(variables: dict[str, Any]) -> bool:
    """Pass when the report preserves the transcript's citations (report rule 2).

    The transcript's own links set the bar: a link-free transcript carries
    nothing the report could drop, so it passes. A transcript with links
    requires the report to carry them, exactly as written.
    """
    report_urls = markdown_link_urls(variables["report"])
    transcript_urls = markdown_link_urls(variables["transcript"])
    if not transcript_urls:
        return True
    return bool(report_urls) and set(report_urls) <= set(transcript_urls)


def judges() -> tuple[Judge, ...]:
    """Return the reporter eval's judges."""
    return (
        Judge("follows_outline", "binary", _report_view, check=follows_outline),
        Judge(
            "urls_from_transcript", "binary", _report_view, check=urls_from_transcript
        ),
        Judge("outline_grounded", "numeric", _outline_view, prompt=OUTLINE_PROMPT),
        Judge("report_faithful", "numeric", _report_rules_view, prompt=REPORT_PROMPT),
    )
