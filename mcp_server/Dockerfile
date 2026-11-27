FROM python:3.12-slim AS base
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
# System Python only: a uv-managed interpreter under /root would be unreadable to
# the slot users.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12 \
    SANDBOX_SLOT_USERS=sandbox0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
# One user per run slot (one slot today). No home, no shell; owns nothing in the image.
RUN useradd --system --uid 10010 --no-create-home --shell /usr/sbin/nologin sandbox0

FROM base AS test
RUN uv sync --frozen --dev --no-install-project
COPY tests/ tests/
# `--capture=sys`: the container is read-only, and pytest's default capture needs
# a temporary directory.
CMD [".venv/bin/pytest", "tests/container_tests", "-p", "no:cacheprovider", "--capture=sys"]

FROM base AS runtime
# Runs as root holding only SETUID, SETGID and KILL (Compose drops the rest):
# Docker gives a non-root process no effective capabilities, and only root with
# these can start each run as a slot user and kill what it leaves behind.
# `--no-proxy-headers`: by default uvicorn lets 127.0.0.1 name any peer address in
# `X-Forwarded-For`, which would get a run past `app.LocalPeerGate`.
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
