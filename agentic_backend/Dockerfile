FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached layer — only re-runs when pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY src/ src/
# deploy/vps.py runs `alembic upgrade head` from /app; alembic.ini resolves
# script_location and prepend_sys_path relative to itself (%(here)s/src).
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# Serve as an unprivileged user: the app only reads /app and talks to Postgres.
RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000

CMD [".venv/bin/uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
