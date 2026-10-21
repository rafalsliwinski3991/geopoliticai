"""Unit tests for `evals.judges.expert_live`."""

from __future__ import annotations

from typing import Any

from evals.judges.expert_live import ANSWERS_PROMPT, judges
from evals.judges.shared import FAITHFUL_PROMPT

PAGE_URL = "https://news.example/a"
ANSWER = f"The summit agreed a target [report]({PAGE_URL})."


def _finished_output() -> dict[str, Any]:
    return {
        "finished": True,
        "side": "",
        "answer": ANSWER,
        "sources": [
            {"title": "Report", "url": PAGE_URL, "text": "page text", "author": ""},
            {"title": "Other", "url": "https://news.example/b", "text": "unread"},
        ],
    }


def _judge(name: str) -> Any:
    return next(judge for judge in judges() if judge.name == name)


def test_the_live_expert_judges_are_outcome_links_faithfulness_and_question() -> None:
    # Act
    named = [(judge.name, judge.kind) for judge in judges()]

    # Assert
    assert named == [
        ("finished_or_outside", "binary"),
        ("urls_from_sources", "binary"),
        ("faithful_to_sources", "numeric"),
        ("answers_the_question", "binary"),
    ]


def test_every_answer_judge_skips_a_run_that_did_not_finish() -> None:
    """A run that failed outside must not also fail every answer judge; the outcome judge already covers it."""
    # Arrange
    failed = {"finished": False, "side": "outside", "cause": "ConnectError"}
    answer_judges = [judge for judge in judges() if judge.name != "finished_or_outside"]

    # Act
    views = [judge.view({"query": "q"}, failed, {}) for judge in answer_judges]

    # Assert
    assert views == [None, None, None]


def test_the_link_and_faithful_views_read_the_pages_the_run_read() -> None:
    """Links are checked against the pages read, and only the cited page's text is shown to the faithfulness judge."""
    # Arrange
    output = _finished_output()

    # Act
    links = _judge("urls_from_sources").view({"query": "q"}, output, {})
    faithful = _judge("faithful_to_sources").view({"query": "q"}, output, {})

    # Assert
    assert links == {
        "answer": ANSWER,
        "source_urls": [PAGE_URL, "https://news.example/b"],
    }
    assert faithful == {
        "answer": ANSWER,
        "sources": f"SOURCE {PAGE_URL}\nReport\npage text",
    }


def test_the_faithful_view_says_so_when_the_answer_cites_no_page_it_read() -> None:
    """An empty sources block would let the judge score an answer against nothing."""
    # Arrange
    output = {**_finished_output(), "answer": "No links here."}

    # Act
    faithful = _judge("faithful_to_sources").view({"query": "q"}, output, {})

    # Assert
    assert faithful["sources"] == "(the answer cites no page it read)"


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    output = _finished_output()
    faithful = _judge("faithful_to_sources").view({"query": "q"}, output, {})
    answers = _judge("answers_the_question").view({"query": "q"}, output, {})

    # Act + Assert: str.format raises KeyError on a field the view leaves out.
    FAITHFUL_PROMPT.format(**faithful)
    ANSWERS_PROMPT.format(**answers)
