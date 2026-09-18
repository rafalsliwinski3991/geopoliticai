"""Bearer-token identity for the API.

Django mints the token (`GET /accounts/token/`); this module only verifies it.
The two services share nothing but `JWT_SIGNING_KEY` and the claim names, which
is the whole of the coupling: no Django import, no ORM, nothing async-unsafe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

JWT_ALGORITHM = "HS256"
# simplejwt's own defaults (`USER_ID_CLAIM`, `TOKEN_TYPE_CLAIM`). Both are
# asserted by a unit test against a token minted with the documented settings,
# so a change on the Django side fails here rather than in production.
USER_ID_CLAIM = "user_id"
TOKEN_TYPE_CLAIM = "token_type"
ACCESS_TOKEN_TYPE = "access"
BEARER_PREFIX = "bearer "


@dataclass(frozen=True)
class Identity:
    """The authenticated user for one request."""

    user_id: int


def decode_token(token: str) -> Identity:
    """Verify one access token and return the identity it carries.

    Raises:
        HTTPException: 401 for anything that is not a currently valid access
            token. The message never distinguishes expired from malformed: to
            the caller both mean "fetch a new one".
    """
    try:
        claims = jwt.decode(
            token,
            os.environ["JWT_SIGNING_KEY"],
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", USER_ID_CLAIM]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token."
        ) from exc
    # A refresh token is signed with the same key and would otherwise pass.
    if claims.get(TOKEN_TYPE_CLAIM) != ACCESS_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    try:
        # simplejwt stringifies the id unconditionally in `Token.for_user`
        # (`user_id = str(user_id)`), whatever `USER_ID_FIELD` is — so this
        # claim is always a string and the coercion is the normal path, not a
        # defensive one. It also keeps an unvalidated value out of a SQL
        # parameter.
        return Identity(user_id=int(claims[USER_ID_CLAIM]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token."
        ) from exc


async def require_identity(request: Request) -> Identity:
    """FastAPI dependency: the authenticated caller, or 401."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return decode_token(header[len(BEARER_PREFIX) :].strip())
