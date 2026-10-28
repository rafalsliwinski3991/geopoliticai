"""What a load-test user sends, and how a streamed turn is judged.

Free of Locust on purpose: importing Locust monkey-patches the standard library
with gevent, so the unit tests and the fakes import these from here instead.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from api.auth import JWT_ALGORITHM, USER_ID_CLAIM

# A query that names this word routes to the expert; any other is small talk.
RESEARCH_KEYWORD = "research"
STREAM_PATH = "/api/run_pipeline/stream"
THREADS_PATH = "/api/threads"
CHAT_QUERY = "Hello, what can you do?"
RESEARCH_QUERY = f"Please {RESEARCH_KEYWORD} the state of the ceasefire talks."
TOKEN_LIFETIME = timedelta(hours=1)
DATA_PREFIX = "data: "
# The Locust request type of a turn's time to its first answer token, which
# Locust tabulates beside the requests themselves.
FIRST_TOKEN = "TTFT"


def mint_token(user_id: int, signing_key: str) -> str:
    """Return an access token with the claims Django's simplejwt mints."""
    return jwt.encode(
        {
            USER_ID_CLAIM: str(user_id),
            "token_type": "access",
            "exp": datetime.now(UTC) + TOKEN_LIFETIME,
            "jti": uuid4().hex,
        },
        signing_key,
        algorithm=JWT_ALGORITHM,
    )


def parse_frame(line: str) -> dict[str, object] | None:
    """Return the JSON frame of an SSE `data:` line, or None for any other line.

    A frame cut off mid-line is not a frame: the turn then ends without a
    result and is counted as failed, instead of raising inside the user.
    """
    if not line.startswith(DATA_PREFIX):
        return None
    try:
        frame: dict[str, object] = json.loads(line.removeprefix(DATA_PREFIX))
    except json.JSONDecodeError:
        return None
    return frame


def find_turn_error(last_frame: dict[str, object]) -> str | None:
    """Say why a turn whose stream ended on `last_frame` failed; None if it did not.

    Only a `result` frame ends a turn well: the endpoint answers 200 and
    reports a refused or failed turn inside the stream.
    """
    if last_frame.get("type") == "result":
        return None
    if last_frame.get("type") == "error":
        return f"error frame {last_frame.get('status')}"
    return "stream ended without a result"
