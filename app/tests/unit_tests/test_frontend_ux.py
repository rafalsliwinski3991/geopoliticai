"""Static checks on the frontend shell's user-facing behavior.

Same mechanism as `test_frontend_security.py`: the frontend is a single HTML
file with no build step or JS test runner, so the unit suite asserts on its
source.
"""

from pathlib import Path

FRONTEND_HTML = Path(__file__).parents[3] / "frontend" / "index.html"


def _between(html: str, start: str, end: str) -> str:
    """Source slice from the first `start` anchor up to the first `end`
    anchor, for asserting inside one method's body."""
    start_index = html.find(start)
    end_index = html.find(end)
    assert start_index != -1, f"{start!r} not found"
    assert end_index != -1, f"{end!r} not found"
    assert start_index < end_index
    return html[start_index:end_index]


def test_query_input_caps_length_at_api_limit() -> None:
    """The input cannot submit more characters than the API accepts."""
    html = FRONTEND_HTML.read_text()
    assert 'maxlength="2000"' in html


def test_sse_error_statuses_map_to_friendly_messages() -> None:
    """Each known server error status has purpose-built copy, and the SSE
    error branch renders it through the friendly-error helper."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    for key in ("error_422", "error_503", "error_502", "error_generic"):
        assert f"{key}:" in html
    assert "function friendlySseError(data)" in html
    assert "friendlySseError(data)" in html


def test_friendly_error_copy_is_action_oriented_and_jargon_free() -> None:
    """422 offers rephrasing, 503 frames the outage as temporary, 502 and the
    fallback ask to retry — and no internal vocabulary reaches the bubble."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "rephrasing it" in html.lower()
    assert "temporarily unavailable" in html.lower()
    assert "please try again" in html.lower()
    assert "allow-listed" not in html
    assert "brave" not in html.lower()


def test_frontend_sends_a_sticky_thread_id() -> None:
    """The frontend persists a conversation id and sends it to the API."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "THREAD_STORAGE_KEY" in html
    assert "localStorage.getItem" in html
    assert "crypto.randomUUID" in html
    assert "thread_id: this.threadId" in html


def test_frontend_offers_a_new_chat_button() -> None:
    """The UI can reset the conversation to a freshly minted thread."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "newChat()" in html
    assert 'new_chat: "New chat"' in html
    assert 'class="new-chat"' in html


def test_pause_frame_is_handled_and_sets_paused_state() -> None:
    """A `pause` frame flips the paused state and pushes the outline card."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert 'data.type === "pause"' in html
    assert "this.paused = true" in html


def test_input_posts_resume_body_while_paused_and_query_body_otherwise() -> None:
    """The request body is a union: a paused thread resumes, anything else
    asks a fresh question."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "{ resume: text, thread_id: this.threadId }" in html
    assert "{ query: text, thread_id: this.threadId }" in html


def test_paused_is_cleared_only_where_the_pause_is_really_gone() -> None:
    """`paused` decides whether the next input posts `{resume}` or
    `{query}`, and a `{query}` destroys the pending report. So it is
    cleared only where the pause is provably gone: `newChat()`, a
    delivered `result`, and an SSE error with status 409. Any other
    error may be transient and leave the thread resumable, and a
    wrongly-kept `paused` self-corrects in one round trip: the stale
    `{resume}` draws a 409, which is the case that clears it. The
    network `catch` clears nothing — a dropped connection or timeout
    says nothing about server state."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    new_chat = html.find("newChat() {")
    send_message = html.find("async sendMessage()")
    assert -1 not in (new_chat, send_message)
    assert new_chat < send_message
    assert "this.paused = false" in html[new_chat:send_message]
    assert "this.paused = false" in _between(
        html, 'data.type === "result"', 'data.type === "error"'
    )

    error_branch = _between(html, 'data.type === "error"', "} finally {")
    assert error_branch.count("this.paused = false") == 1
    assert "if (data.status === 409) this.paused = false;" in error_branch

    network_catch = _between(html, "} catch (error) {", "} finally {")
    assert "this.paused = false" not in network_catch


def test_409_error_status_has_friendly_copy() -> None:
    """A resume on a thread that is no longer paused is an expected failure,
    so it gets purpose-built copy like the other known statuses."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "error_409:" in html
    assert "409: I18N.error_409" in html


def test_report_messages_have_download_and_copy_actions() -> None:
    """Report messages gain two client-side actions: a `.md` download —
    named `-partial` when the report was truncated, whose file body itself
    says what it is — and a copy button."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "downloadReport(msg)" in html
    assert "copyReport(msg" in html
    download_body = _between(html, "downloadReport(msg) {", "copyReport(msg, event) {")
    assert "const body = msg.truncated" in download_body
    assert "[This report was truncated at 50,000 characters.]" in download_body
    assert 'type: "text/markdown' in download_body
    assert "report-${stamp}.md" in download_body
    assert "-partial.md" in download_body


def test_copy_button_captures_event_target_before_await() -> None:
    """`currentTarget` is only set while the event is being dispatched, so
    reading it after the clipboard await yields null and the button would
    never say "Copied"."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    capture = html.find("const button = event?.currentTarget;")
    clipboard_await = html.find("await navigator.clipboard.writeText")
    assert capture != -1
    assert clipboard_await != -1
    assert capture < clipboard_await


def test_truncated_notice_copy_is_bound_to_reported_truncation() -> None:
    """The page flags a truncated report through purpose-built copy, shown
    only when the result was both a report and truncated."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    assert "truncated_notice:" in html
    assert 'data.kind === "report"' in html
    assert "msg.report && msg.truncated" in html


def test_outline_card_renders_via_x_text_and_guards_the_x_html_binding() -> None:
    """The outline carries model-produced text, so it renders through
    `x-text` only — and because `x-show` hides an element without stopping
    its bindings evaluating, the `x-html` binding must be ternary-guarded so
    outline messages never reach `renderContent`."""
    # Arrange
    html = FRONTEND_HTML.read_text()
    # Assert
    outline_card = html.find('class="message outline"')
    x_html_binding = html.find("x-html=", outline_card)
    guard = html.find("msg.role === 'outline' ? '' : renderContent(msg)")
    assert outline_card != -1
    assert x_html_binding != -1
    assert guard != -1
    assert outline_card < x_html_binding < guard
    outline_slice = html[outline_card:x_html_binding]
    assert "x-text" in outline_slice
    assert "x-html" not in outline_slice
