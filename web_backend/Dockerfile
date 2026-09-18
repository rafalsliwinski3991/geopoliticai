FROM python:3.13-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached layer — only re-runs when pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY . .
RUN uv sync --frozen --no-dev

# Whitenoise's CompressedManifestStaticFilesStorage (the production default)
# refuses to render any page without the manifest, so the image must ship it.
# settings.py reads these env vars at import; the placeholders are only used
# to satisfy the import — collectstatic touches no database.
RUN DJANGO_SECRET_KEY=build-only-placeholder \
    POSTGRES_DB=build-only-placeholder \
    POSTGRES_USER=build-only-placeholder \
    POSTGRES_PASSWORD=build-only-placeholder \
    .venv/bin/python manage.py collectstatic --noinput

EXPOSE 8000

CMD [".venv/bin/gunicorn", "politicalagent.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
