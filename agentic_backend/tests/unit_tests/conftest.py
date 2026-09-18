import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def jwt_signing_key() -> None:
    """The identity tests run without a database; the key is a test constant.

    32+ bytes so PyJWT does not warn about an undersized HMAC key.
    """
    os.environ.setdefault(
        "JWT_SIGNING_KEY", "unit-test-signing-key-not-long-enough-0123456789"
    )
