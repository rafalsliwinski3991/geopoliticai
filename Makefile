.PHONY: up down restart logs services ps config help migrate createsuperuser test-web-backend

COMPOSE ?= docker compose
FRONTEND_PORT ?= 8082
BACKEND_PORT ?= 3001
ACCOUNTS_PORT ?= 8083
POSTGRES_PORT ?= 55432

export FRONTEND_PORT BACKEND_PORT ACCOUNTS_PORT POSTGRES_PORT

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

restart: down up

logs:
	$(COMPOSE) logs -f

logs-%:
	$(COMPOSE) logs -f $*

services:
	$(COMPOSE) config --services

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config

# Django targets run the web_backend service's manage.py from the host, against
# the dev Postgres on $(POSTGRES_PORT). `.env` supplies POSTGRES_PASSWORD and
# the DJANGO_* / EMAIL_* variables; POSTGRES_DB/USER/HOST are set explicitly
# because the container defaults (postgres:5432) do not apply from the host.
# A host-run command that reaches into the repo's own .venv cannot use the
# Compose container's copy, so these targets inject the same dummy
# DJANGO_SECRET_KEY Compose would fail without in production; anything these
# commands sign (test cookies, migrations) stays on the dev database.
DJANGO_HOST_ENV = set -a && . ./.env && set +a; \
	POSTGRES_DB=geopoliticai POSTGRES_USER=geopoliticai \
	POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=$(POSTGRES_PORT) \
	DJANGO_SECRET_KEY=$${DJANGO_SECRET_KEY:-django-host-dev-only-secret}

migrate:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py migrate
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createcachetable

createsuperuser:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createsuperuser

test-web-backend:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py collectstatic --noinput
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py test

help:
	@printf '%s\n' \
		'up        Build and start frontend, agentic-backend, and PostgreSQL' \
		'down      Stop and remove the application containers' \
		'restart   Restart the application containers' \
		'logs      Follow application logs' \
		'logs-SERVICE Follow logs for one service (frontend, agentic-backend, web-backend, postgres, phoenix)' \
		'services  List all Compose services' \
		'ps        Show container status' \
		'config    Render the effective Compose configuration' \
		'migrate   Run Django migrations and create the cache table' \
		'createsuperuser Create a Django admin user' \
		'test-web-backend Run the Django service test suite' \
		'' \
		'Ports can be overridden, for example:' \
		'  make up FRONTEND_PORT=8083 BACKEND_PORT=3002 POSTGRES_PORT=55433'