"""Rules for the users app; management commands stay thin adapters."""

from allauth.account.models import EmailAddress
from django.db import transaction

from chat.models import Quota
from users.models import User

# One test user per Playwright worker, so parallel tests never share a meter or
# a sidebar. Keep it equal to `E2E_WORKERS` in e2e/users.ts.
E2E_USER_COUNT = 4


def e2e_emails(email: str) -> list[str]:
    """Return the E2E_EMAIL account and its worker siblings: `e2e@x`, `e2e+2@x`, `e2e+3@x`."""
    local, _, domain = email.strip().lower().rpartition("@")
    return [email.strip().lower()] + [
        f"{local}+{number}@{domain}" for number in range(2, E2E_USER_COUNT + 1)
    ]


@transaction.atomic
def ensure_e2e_users(email: str, password: str) -> list[User]:
    """Create or reset every worker's test user from the one E2E_EMAIL and password."""
    return [ensure_e2e_user(address, password) for address in e2e_emails(email)]


@transaction.atomic
def ensure_e2e_user(email: str, password: str) -> User:
    """Create or reset the end-to-end test user: password, verified email, full quota.

    allauth's mandatory verification refuses a login whose address has no
    verified `EmailAddress` row, so the row is part of the user. Re-running
    resets the password (keeping it in step with `.env`) and deletes the
    user's spent `quota` rows, so every run of the suite starts with a full
    day's research turns. It refuses a staff or superuser account, so a known
    password never lands on one, and reactivates an inactive user.
    """
    email = email.strip().lower()
    user, _ = User.objects.get_or_create(email=email)
    if user.is_staff or user.is_superuser:
        raise ValueError(f"{email} is a staff account; pick another E2E_EMAIL.")
    user.is_active = True
    user.set_password(password)
    user.save()
    EmailAddress.objects.update_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    Quota.objects.filter(user=user).delete()
    return user
