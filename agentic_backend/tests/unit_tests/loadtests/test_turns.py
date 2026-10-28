import os

from api import auth
from loadtests.turns import find_turn_error, mint_token, parse_frame

USER_ID = 7


def test_a_turn_ending_in_a_result_frame_succeeds() -> None:
    """The `result` frame is the endpoint's only sign that a turn finished."""
    # Arrange
    last_frame: dict[str, object] = {"type": "result", "content": "Hello"}

    # Act
    error = find_turn_error(last_frame)

    # Assert
    assert error is None


def test_a_turn_ending_in_an_error_frame_fails_with_its_status() -> None:
    """The endpoint answers 200 and reports a failed turn inside the stream, so
    the status code alone would count every refused turn as a success."""
    # Arrange
    last_frame: dict[str, object] = {"type": "error", "status": 429, "message": "x"}

    # Act
    error = find_turn_error(last_frame)

    # Assert
    assert error == "error frame 429"


def test_a_stream_cut_before_its_result_fails() -> None:
    """A stream that stops after its tokens never told the user the turn ended."""
    # Arrange
    last_frame: dict[str, object] = {"type": "token", "content": "Hel"}

    # Act
    error = find_turn_error(last_frame)

    # Assert
    assert error == "stream ended without a result"


def test_a_line_that_is_not_data_has_no_frame() -> None:
    """SSE separates frames with blank lines; reading one as JSON would crash
    the user mid-stream."""
    # Arrange
    blank_line = ""

    # Act
    frame = parse_frame(blank_line)

    # Assert
    assert frame is None


def test_a_frame_cut_off_mid_line_has_no_frame() -> None:
    """A stream that drops mid-frame leaves half a JSON object; raising there
    would kill the virtual user instead of counting a failed turn."""
    # Arrange
    cut_line = 'data: {"type": "token", "cont'

    # Act
    frame = parse_frame(cut_line)

    # Assert
    assert frame is None


def test_a_minted_token_passes_the_apis_own_check() -> None:
    """The load users sign their own tokens; if the claims drifted from what
    `auth` checks, every request of a run would be a 401."""
    # Arrange
    token = mint_token(USER_ID, os.environ["JWT_SIGNING_KEY"])

    # Act
    identity = auth.decode_token(token)

    # Assert
    assert identity.user_id == USER_ID
