"""Static checks on the frontend shell's user-facing behavior.

Same mechanism as `test_frontend_security.py`: the frontend is a single HTML
file with no build step or JS test runner, so the unit suite asserts on its
source.
"""

from pathlib import Path

FRONTEND_HTML = Path(__file__).parents[3] / "frontend" / "index.html"


def test_query_input_caps_length_at_api_limit() -> None:
    """The input cannot submit more characters than the API accepts."""
    html = FRONTEND_HTML.read_text()
    assert 'maxlength="2000"' in html


def test_sse_error_statuses_map_to_friendly_messages() -> None:
    """Each known server error status has purpose-built copy, and the SSE
    error branch renders it through the friendly-error helper."""
    html = FRONTEND_HTML.read_text()
    for key in ("error_422", "error_503", "error_502", "error_generic"):
        assert f"{key}:" in html
    assert "function friendlySseError(data)" in html
    assert "friendlySseError(data)" in html


def test_friendly_error_copy_is_action_oriented_and_jargon_free() -> None:
    """422 offers rephrasing, 503 frames the outage as temporary, 502 and the
    fallback ask to retry — and no internal vocabulary reaches the bubble."""
    html = FRONTEND_HTML.read_text()
    assert "rephrasing it" in html.lower()
    assert "temporarily unavailable" in html.lower()
    assert "please try again" in html.lower()
    assert "allow-listed" not in html
    assert "brave" not in html.lower()
