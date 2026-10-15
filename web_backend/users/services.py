"""Rules for the users app; management commands stay thin adapters."""

from allauth.account.models import EmailAddress
from django.db import transaction

from chat.models import Quota
from users.models import User


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
