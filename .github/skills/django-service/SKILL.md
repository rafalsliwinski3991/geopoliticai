---
name: django-service
description: "INVOKE THIS SKILL when working on web_backend/ — django-allauth auth, the admin panel, models and migrations, settings, URLs, templates, or issuing JWTs for agentic_backend. Use it before adding any Django app, model, migration, or setting."
---

Django's value is what you do not write: auth, admin, migrations and templates are
configuration. Reach for a Django app or a setting before a view, and a view before a
new dependency.

## Auth with django-allauth

Do not hand-write registration, email verification, password reset or password
hashing. allauth covers all of it; restyle `templates/account/*.html` instead of
replacing the views.

Current settings API (allauth ≥65.4 — the older names are deprecated and silently
still accepted, which hides mistakes):

```python
INSTALLED_APPS = [..., "django.contrib.auth", "django.contrib.messages",
                  "allauth", "allauth.account"]
MIDDLEWARE = [..., "allauth.account.middleware.AccountMiddleware"]  # required
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",            # admin login
    "allauth.account.auth_backends.AuthenticationBackend",  # login by email
]
ACCOUNT_LOGIN_METHODS = {"email"}          # was ACCOUNT_AUTHENTICATION_METHOD
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
                                           # was ACCOUNT_EMAIL_REQUIRED et al.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"   # requires "email*" above
```

Protect views with `@login_required`, or `@verified_email_required` from
`allauth.account.decorators` when verification actually matters. Social providers are
extras — add a provider app only when that login is being shipped.

## Admin

Django admin *is* the panel. Register models, set `list_display`/`search_fields`, and
stop. Building custom admin screens is the signal you wanted a real view instead. In
production, put auth or an IP allowlist in front of `/admin/` at the proxy — Django's
staff check is not the only gate you want on it.

## Models and migrations

- Migrations are the schema's source of truth. Never edit an applied migration; add
  the next one.
- Put the constraint in the database: `unique_together`/`UniqueConstraint`,
  `CheckConstraint`, `on_delete`, `db_index` on what you filter by. A DB constraint
  beats a `clean()` method and beats app-level checks entirely.
- Choose `on_delete` deliberately. `CASCADE` for data that is meaningless without its
  owner; `PROTECT` when silent deletion would be a bug.
- Rows in tables Django does not own (another service's, a library's) are not covered
  by cascades — delete them explicitly.
- `select_related` / `prefetch_related` for the N+1 you will otherwise ship.

## When Django shares a database with another service

- One owner of the schema: Django's `migrate`. The other service reads and writes with
  plain SQL and no ORM of its own.
- That coupling needs exactly one test: apply the migrations, then run the other
  service's real statements, so schema drift fails CI instead of production.
- Keep the boundary at HTTP or the tables — never import Django from the other service.

## JWT for a separate API

`djangorestframework-simplejwt` issues tokens; the API verifies them with PyJWT.

```python
refresh = RefreshToken.for_user(user)   # for_user does NOT check is_active
access = str(refresh.access_token)
```

- Check `user.is_active` yourself before minting.
- Use a **dedicated signing key** shared with the verifying service, not `SECRET_KEY`,
  and the same `ALGORITHM` on both sides.
- `USER_ID_CLAIM` defaults to `user_id`; changing it breaks every consumer.
- Short `ACCESS_TOKEN_LIFETIME`. A browser client should hold the token in memory and
  re-fetch it from a session-authenticated endpoint rather than store a refresh token.
- Never trust a privilege claim (`is_staff`, roles) baked into a token for an
  authorization decision — re-read it from the database.

## Async

Django's ORM is still thread-pool-backed; there is no native async database layer, and
transactions do not work in async mode without `sync_to_async`. The `a`-prefixed
methods (`aget`, `acreate`, `afirst`, `async for`) are the supported surface and
occupy a worker thread. The cheapest answer is usually to keep the ORM off any async
request path entirely. Blog posts claiming this is fixed are contradicted by the
release notes.

## Verify

`manage.py test` (or pytest-django) with its own CI step. `manage.py check --deploy`
before shipping: it catches the settings that turn into a security incident. Test what
you wrote — your models, views and permissions — not allauth's flows.

Check context7 before quoting Django, allauth or simplejwt APIs; settings names in
this ecosystem churn between minor versions.
