---
name: fastapi-service
description: "INVOKE THIS SKILL when writing or changing a FastAPI service — routes, dependencies, Pydantic models, lifespan and startup, database access, streaming and SSE, auth and JWT verification, error statuses, or rate limiting. Use it before adding any endpoint or dependency."
---

FastAPI is an async framework; the whole value is one event loop that is never
blocked. Every rule below follows from that.

## The async contract

- A `def` endpoint runs in a thread pool; an `async def` endpoint that calls blocking
  code stalls the entire process. Pick one deliberately: if the library is sync and you
  cannot avoid it, declare the endpoint `def` and let FastAPI offload it.
- No sync ORM, no `requests`, no `time.sleep`, no blocking file I/O in `async def`.
  Use the async client the library ships, or `anyio.to_thread.run_sync`.
- Open pools and clients once in `lifespan` and store them on `app.state`; never per
  request, never at import time. Import-time side effects break tests and tooling.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = AsyncConnectionPool(dsn, open=False)
    await app.state.pool.open()
    try:
        yield
    finally:
        await app.state.pool.close()
```

The `try/finally` is not optional: an exception thrown at `yield` (startup failure
surfaced later, cancellation at shutdown) would otherwise skip `close()` and leak
the pool.

## Fail closed at startup

Validate required configuration when the process starts, not when the first request
arrives — a missing secret must stop the service, never downgrade it to
unauthenticated. Keep that check in one place and add every new secret to it.

## Validation and trust boundaries

- Pydantic models are the input contract. Put the length caps, ranges and enums in the
  model, not in the handler body.
- Model mutually exclusive inputs explicitly rather than accepting both and guessing.
- Validate and cap anything client-supplied that reaches a query, a prompt, or storage.
- Raise `HTTPException` with the right status; do not return error dicts with 200.

## Dependencies

`Depends` is the reuse unit — auth, pagination, the DB handle. Use `Annotated[...]`
types and alias the common ones once:

```python
CurrentUser = Annotated[int, Depends(current_user_id)]
```

Do not build a service/repository layer for a handful of queries. Do not add a
dependency-injection library; `Depends` is the one.

## JWT verification

```python
claims = jwt.decode(
    token,
    SIGNING_KEY,
    algorithms=["HS256"],                  # always pin algorithms
    options={"require": ["sub", "exp"]},   # require the claims the service relies on
    # issuer=... / audience=... when the service is configured to check them
)
```

Pinning `algorithms` is necessary but not sufficient: PyJWT validates `exp` only
when the claim is present, so a well-signed token with no expiry would be accepted.
Require every claim the service relies on before accepting the token — at least
`sub` and `exp`, plus issuer/audience when configured.

- Missing header, bad signature, missing required claims, expiry → **401**,
  always. Never fall back to an anonymous identity on a decode failure.
- The token's subject claim is the identity for the whole request. Do not let a
  client-supplied id in the path or body stand in for it.
- Authorization is a separate step from authentication: after decoding, check that
  *this* user owns *that* resource → **403** if not. Re-read privilege flags
  (`is_staff`, roles) from the database instead of trusting a claim in the token.

## Ordering: reject before you commit to work

Authenticate, then check quota/limits, then check ownership, then start the expensive
part. For a streaming endpoint this matters doubly — once the response has begun you
can no longer send a status code, only an in-band error event. Keep every rejection
ahead of the first byte.

## Streaming and SSE

- `StreamingResponse` with an async generator; bound its output and still drain the
  upstream iterator so cleanup and writes finish.
- Client disconnects mid-stream are normal, not errors — handle the cancellation.
- Keep a defined event vocabulary and document the statuses the client must handle.
- Disable proxy buffering for SSE (`X-Accel-Buffering: no` behind nginx).

## Database

Use the async driver's pool directly with plain SQL when the schema is small or owned
elsewhere; that is fewer moving parts than an ORM. Pass parameters — never f-string
SQL. If another service owns the schema, add one test that runs your real statements
against that service's migrated schema so drift fails CI.

## Rate limiting

An in-process dict is per worker: a second uvicorn worker doubles every limit, and it
resets on deploy. Fine as a rough guard, wrong for a per-user quota or anything
billable — those belong in the shared datastore. Behind a proxy, derive the client IP
from the right end of `X-Forwarded-For`, and only trust it if the proxy sets it.

## Verify

Mirror the source tree in the test tree. Use `httpx.ASGITransport` / `TestClient`
against the real app; test the status codes, not just the happy path — 401 on a bad
token, 403 on someone else's resource, 429 at the cap. Keep the app importable and
constructible without external services, or tests and dev tooling break.

Check context7 for current FastAPI, Pydantic and driver APIs before quoting them.
