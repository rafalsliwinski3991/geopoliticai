"""Unit tests for the bearer-token identity module (unit 5)."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import jwt
import pytest
from fastapi import HTTPException

import auth
from config import require_env


def _key() -> str:
    return os.environ["JWT_SIGNING_KEY"]


def _mint(
    *,
    key: str | None = None,
    token_type: str = "access",
    user_id: Any = "1",
    expires: datetime | None = None,
    algorithm: str = "HS256",
    claims: dict[str, Any] | None = None,
) -> str:
    """Mint a token with simplejwt's documented claim shape (unit 3's view)."""
    return jwt.encode(
        _claims(token_type, user_id, expires, claims),
        key or _key(),
        algorithm=algorithm,
    )


def _claims(
    token_type: str = "access",
    user_id: Any = "1",
    expires: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "token_type": token_type,
        "exp": expires or datetime.now(timezone.utc) + timedelta(minutes=15),
        "jti": "test-jti",
    }
    if extra:
        payload.update(extra)
    return payload


def test_a_simplejwt_style_token_decodes_to_the_right_identity() -> None:
    """The cross-service contract, asserted against a minted fixture token."""
    identity = auth.decode_token(_mint(user_id="42"))
    assert identity == auth.Identity(user_id=42)


def test_an_expired_token_is_rejected() -> None:
    expired = _mint(expires=datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(expired)
    assert exc_info.value.status_code == 401


def test_a_token_signed_with_a_different_key_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(_mint(key="wrong-key-not-the-signing-key-0123456789abcdef"))
    assert exc_info.value.status_code == 401


def test_an_alg_none_token_is_rejected() -> None:
    none_signed = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(none_signed)
    assert exc_info.value.status_code == 401


def test_a_refresh_token_is_rejected() -> None:
    """PyJWT does not know simplejwt's types; the token_type check does."""
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(_mint(token_type="refresh"))
    assert exc_info.value.status_code == 401


def test_a_token_without_a_user_id_claim_is_rejected() -> None:
    raw = jwt.encode(
        {
            "token_type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        },
        _key(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(raw)
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "user_id", ["not-a-number", None, [1]], ids=["text", "null", "list"]
)
def test_a_user_id_claim_that_is_not_an_integer_is_rejected(user_id: Any) -> None:
    # Arrange
    raw = _mint(user_id=user_id)

    # Act + Assert
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(raw)
    assert exc_info.value.status_code == 401


def test_a_token_without_a_token_type_claim_is_rejected() -> None:
    # Arrange
    raw = jwt.encode(
        {"user_id": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
        _key(),
        algorithm="HS256",
    )

    # Act + Assert
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(raw)
    assert exc_info.value.status_code == 401


class _StubRequest:
    def __init__(self, authorization: str | None) -> None:
        self.headers = {"authorization": authorization} if authorization else {}


async def _require_identity(authorization: str | None) -> auth.Identity:
    request = cast(Any, _StubRequest(authorization))
    return await auth.require_identity(request)


@pytest.mark.anyio
async def test_a_missing_header_is_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _require_identity(None)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_a_non_bearer_header_is_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _require_identity("Basic dXNlcjpwYXNz")
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_bearer_with_nothing_after_it_is_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _require_identity("Bearer ")
    assert exc_info.value.status_code == 401


def test_require_env_fails_closed_without_the_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "k")
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    with pytest.raises(ValueError, match="JWT_SIGNING_KEY"):
        require_env()
