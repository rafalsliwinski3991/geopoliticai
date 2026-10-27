"""Rules for the chat app's quota tables; admin classes only call these."""

from collections.abc import Iterable
from datetime import date

from django.db import transaction
from django.db.models import Sum

from chat.models import Quota
from users.models import User


@transaction.atomic
def reset_quota(users: Iterable[User], day: date) -> int:
    """Set these users' research-turn count for `day` to 0; return the units given back.

    Only that day's row changes: other days are history, and the daily cap
    reads one day. The row stays, so the admin still shows the user was active
    that day, and the API's `ON CONFLICT (user_id, day)` upsert counts up from 0.
    The site-wide counter (`SiteQuota`) is not touched.
    """
    rows = Quota.objects.filter(user__in=users, day=day)
    given_back = rows.aggregate(total=Sum("used"))["total"] or 0
    rows.update(used=0)
    return given_back
