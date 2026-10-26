import pytest
from pydantic import ValidationError

import api
from agents.deep_expert.consts import progress as deep_expert_progress
from agents.deep_forecaster.consts import progress as deep_forecaster_progress
from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.reporter.consts.progress import OUTLINE_PROGRESS, REPORT_PROGRESS
from frames import (
    NODE_EVENT,
    ErrorFrame,
    Frame,
    NoticeEvent,
    PauseFrame,
    ProgressFrame,
    ResultFrame,
    TokenFrame,
    encode_frame,
)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        pytest.param(
            ProgressFrame(node="classify", label="Thinking..."),
            'data: {"type": "progress", "node": "classify", "label": "Thinking..."}\n\n',
            id="progress",
        ),
        pytest.param(
            TokenFrame(content="Hello"),
            'data: {"type": "token", "content": "Hello"}\n\n',
            id="token",
        ),
        pytest.param(
            PauseFrame(
                outline=["Intro", "Analysis"],
                notice="",
                revisions_used=0,
                revisions_allowed=2,
            ),
            'data: {"type": "pause", "outline": ["Intro", "Analysis"], '
            '"notice": "", "revisions_used": 0, "revisions_allowed": 2}\n\n',
            id="pause with the revision keys",
        ),
        pytest.param(
            PauseFrame(outline=["Intro"], notice="Nothing to report."),
            'data: {"type": "pause", "outline": ["Intro"], '
            '"notice": "Nothing to report."}\n\n',
            id="pause without the revision keys",
        ),
        pytest.param(
            ResultFrame(output="Done.", kind="answer", truncated=False),
            'data: {"type": "result", "output": "Done.", "kind": "answer", '
            '"truncated": false}\n\n',
            id="result",
        ),
        pytest.param(
            ErrorFrame(status=502, message="The model returned an empty answer."),
            'data: {"type": "error", "status": 502, '
            '"message": "The model returned an empty answer."}\n\n',
            id="error",
        ),
    ],
)
def test_each_frame_encodes_to_the_old_bytes(frame: Frame, expected: str) -> None:
    """The browser parses these exact bytes, so a reordered key or a stray null breaks the stream."""
    # Arrange
    # The frame and its expected bytes come from the parameters.

    # Act
    encoded = encode_frame(frame)

    # Assert
    assert encoded == expected


def test_an_unset_pause_field_is_left_out() -> None:
    """A pause without revision counts omits those keys, not writes them as null."""
    # Arrange
    frame = PauseFrame(outline=["Intro"], notice="Nothing to report.")

    # Act
    encoded = encode_frame(frame)

    # Assert
    assert encoded == (
        'data: {"type": "pause", "outline": ["Intro"], "notice": "Nothing to report."}\n\n'
    )


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(
            {"type": "progress", "node": "classify", "label": "Thinking..."},
            ProgressFrame(node="classify", label="Thinking..."),
            id="progress dict",
        ),
        pytest.param(
            ProgressFrame(node="classify", label="Thinking..."),
            ProgressFrame(node="classify", label="Thinking..."),
            id="progress frame",
        ),
        pytest.param(
            {"type": "notice", "text": "The answer."},
            NoticeEvent(text="The answer."),
            id="notice dict",
        ),
    ],
)
def test_a_node_event_reads_a_frame_or_a_dict(
    event: object, expected: ProgressFrame | NoticeEvent
) -> None:
    """A node writes a frame object and a test fake writes the plain dict; both read as one frame."""
    # Arrange
    # The event and its expected frame come from the parameters.

    # Act
    parsed = NODE_EVENT.validate_python(event)

    # Assert
    assert parsed == expected


def test_an_unknown_node_event_is_refused() -> None:
    """A custom event that is not a known frame is refused, so `_astream_answer` can drop it."""
    # Arrange
    event = {"type": "route", "destination": "geopolitical"}

    # Act + Assert
    with pytest.raises(ValidationError):
        NODE_EVENT.validate_python(event)


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        pytest.param(
            api.THINKING_PROGRESS,
            'data: {"type": "progress", "node": "supervisor", '
            '"label": "Thinking..."}\n\n',
            id="api thinking",
        ),
        pytest.param(
            api.ANSWER_PROGRESS,
            'data: {"type": "progress", "node": "answer", '
            '"label": "Writing the answer..."}\n\n',
            id="api answer",
        ),
        pytest.param(
            SEARCH_PROGRESS,
            'data: {"type": "progress", "node": "search_and_fetch", '
            '"label": "Searching and reading sources..."}\n\n',
            id="orchestrator search",
        ),
        pytest.param(
            OUTLINE_PROGRESS,
            'data: {"type": "progress", "node": "outline", '
            '"label": "Reading the conversation..."}\n\n',
            id="reporter outline",
        ),
        pytest.param(
            REPORT_PROGRESS,
            'data: {"type": "progress", "node": "write", '
            '"label": "Writing the report..."}\n\n',
            id="reporter write",
        ),
        pytest.param(
            deep_expert_progress.PLANNING_PROGRESS,
            'data: {"type": "progress", "node": "deep_expert", '
            '"label": "Planning the research..."}\n\n',
            id="deep expert planning",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_expert_progress.PROGRESS_NODE,
                label=deep_expert_progress.SEARCH_PROGRESS_LABEL.format(used=1, cap=8),
            ),
            'data: {"type": "progress", "node": "deep_expert", '
            '"label": "Searching sources (1 of 8)..."}\n\n',
            id="deep expert search",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_expert_progress.PROGRESS_NODE,
                label=deep_expert_progress.READ_PROGRESS_LABEL.format(count=3),
            ),
            'data: {"type": "progress", "node": "deep_expert", '
            '"label": "Reading sources (3 so far)..."}\n\n',
            id="deep expert read",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_expert_progress.PROGRESS_NODE,
                label=deep_expert_progress.REVISION_PROGRESS_LABEL.format(
                    round=1, cap=2
                ),
            ),
            'data: {"type": "progress", "node": "deep_expert", '
            '"label": "Revising the analysis (1 of 2)..."}\n\n',
            id="deep expert revision",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.RESEARCH_LABEL,
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Planning the research..."}\n\n',
            id="deep forecaster research",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.SEARCH_PROGRESS_LABEL.format(
                    used=1, cap=8
                ),
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Searching the forecasters\' sites (1 of 8)..."}\n\n',
            id="deep forecaster search",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.READ_PROGRESS_LABEL.format(count=3),
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Reading sources (3 so far)..."}\n\n',
            id="deep forecaster read",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.VIDEO_PROGRESS_LABEL.format(
                    used=1, cap=4
                ),
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Asking Gemini about a video (1 of 4)..."}\n\n',
            id="deep forecaster video",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.CLAIMS_LABEL,
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Drafting the claims..."}\n\n',
            id="deep forecaster claims",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.ROUND_LABEL.format(round=1),
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Council voting, round 1 of 2..."}\n\n',
            id="deep forecaster council round",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.WRITE_LABEL,
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Writing the analysis..."}\n\n',
            id="deep forecaster write",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.REWRITE_LABEL,
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Rewriting the analysis..."}\n\n',
            id="deep forecaster rewrite",
        ),
        pytest.param(
            ProgressFrame(
                node=deep_forecaster_progress.PROGRESS_NODE,
                label=deep_forecaster_progress.VERIFY_LABEL,
            ),
            'data: {"type": "progress", "node": "deep_forecaster", '
            '"label": "Checking the answer..."}\n\n',
            id="deep forecaster verify",
        ),
    ],
)
def test_every_progress_literal_encodes_as_before(
    progress: ProgressFrame, expected: str
) -> None:
    """The browser shows each progress label as it arrives, so its node, label and key order stay fixed."""
    # Arrange
    # The progress frame and its expected bytes come from the parameters.

    # Act
    encoded = encode_frame(progress)

    # Assert
    assert encoded == expected
