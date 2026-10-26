"""Bearer-token identity for the API.

Django mints the token (`GET /accounts/token/`); this module only verifies it.
The two services share nothing but `JWT_SIGNING_KEY` and the claim names, which
is the whole of the coupling: no Django import, no ORM, nothing async-unsafe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

JWT_ALGORITHM = "HS256"
# simplejwt's own default `USER_ID_CLAIM`, and the field name `AccessClaims`
# reads it by. A unit test asserts both against a token minted with the
# documented settings, so a change on the Django side fails here rather than
# in production.
USER_ID_CLAIM = "user_id"
BEARER_PREFIX = "bearer "


class AccessClaims(BaseModel):
    """The claims of an access token; simplejwt's other claims are ignored."""

    # A refresh token is signed with the same key and would otherwise pass.
    token_type: Literal["access"]
    # simplejwt stringifies the id unconditionally in `Token.for_user`
    # (`user_id = str(user_id)`), whatever `USER_ID_FIELD` is — so this claim is
    # always a string and the coercion is the normal path, not a defensive one.
    # It also keeps an unvalidated value out of a SQL parameter.
    user_id: int


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
        claims = AccessClaims.model_validate(
            jwt.decode(
                token,
                os.environ["JWT_SIGNING_KEY"],
                algorithms=[JWT_ALGORITHM],
                options={"require": ["exp", USER_ID_CLAIM]},
            )
        )
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token."
        ) from exc
    return Identity(user_id=claims.user_id)


async def require_identity(request: Request) -> Identity:
    """FastAPI dependency: the authenticated caller, or 401."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return decode_token(header[len(BEARER_PREFIX) :].strip())
