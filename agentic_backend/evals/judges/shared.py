"""Judge pieces more than one eval uses: faithfulness, links, exact matches, and the finished-run gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import wraps
from typing import Any

from evals.helpers.judge import Judge, View, markdown_link_urls
from evals.helpers.live import OUTSIDE

FAITHFUL_PROMPT = """
You check whether a research answer is supported by the sources it cites.

Answer:
{answer}

Cited sources:
{sources}

Every factual sentence must be supported by the source its link points to.
Background knowledge that is not in the cited source text counts as unsupported.

Choose exactly one label:
1: most claims are unsupported or contradicted.
2: several claims are unsupported.
3: one material claim is unsupported.
4: all material claims are supported; a minor detail is not.
5: every claim is supported by its cited source.

Give a concise evidence-based explanation naming any unsupported claim.
"""


def urls_from_sources(variables: dict[str, Any]) -> bool:
    """Pass when the answer links, and only to the run's sources (expert rule 1)."""
    urls = markdown_link_urls(variables["answer"])
    return bool(urls) and set(urls) <= set(variables["source_urls"])


def matches_expected(variables: dict[str, Any]) -> bool:
    """Pass when the run's value equals the expected one exactly."""
    return bool(variables["actual"] == variables["expected"])


def render_cited_sources(sources: Sequence[Mapping[str, Any]], answer: str) -> str:
    """Return the text of every source the answer links to, as `FAITHFUL_PROMPT` reads it."""
    cited = set(markdown_link_urls(answer))
    return "\n\n".join(
        f"SOURCE {source['url']}\n{source['title']}\n{source['text']}"
        for source in sources
        if source["url"] in cited
    )


def finished_or_outside(variables: dict[str, Any]) -> bool:
    """Pass a finished run, or one a provider outage failed; fail one our rules failed (Q8)."""
    return bool(variables["finished"]) or variables["side"] == OUTSIDE


def skip_unless_finished(view: View) -> View:
    """Wrap a view so it applies only to a run that finished (Q8).

    A live run that failed outside must not also fail every answer judge; one
    that failed ours already fails `finished_or_outside`.
    """

    @wraps(view)
    def gated(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not output.get("finished"):
            return None
        return view(input, output, expected)

    return gated


def build_outcome_judge() -> Judge:
    """Return the code judge that fails a live eval on a failure of ours."""
    return Judge(
        "finished_or_outside", "binary", _outcome_view, check=finished_or_outside
    )


def _outcome_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if "finished" not in output:
        return None
    return {"finished": output["finished"], "side": output["side"]}
