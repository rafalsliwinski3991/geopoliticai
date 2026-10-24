import pytest
from pydantic import ValidationError

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
