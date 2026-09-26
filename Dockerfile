FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Serve as an unprivileged user: the app only reads /app and talks to Postgres.
RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000

WORKDIR /app/agentic_backend/src
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
