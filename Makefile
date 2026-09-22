.PHONY: up down restart logs services ps config help migrate createsuperuser test-web-backend \
	sync-copilot inventory link-skills

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
	JWT_SIGNING_KEY=$${JWT_SIGNING_KEY:-django-host-dev-only-secret} \
	DJANGO_SECRET_KEY=$${DJANGO_SECRET_KEY:-django-host-dev-only-secret}

migrate:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py migrate
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createcachetable

createsuperuser:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createsuperuser

test-web-backend:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py collectstatic --noinput
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py test

# Skills needing a Claude-only runtime; OpenCode and Copilot load them but
# cannot run them.
OPENCODE_SKIP_SKILLS := swarm

# Both sync targets rebuild their destination from scratch: copying in place
# leaves a skill that was deleted from the canonical tree behind forever, and a
# stale copy is exactly the drift `make inventory` exists to catch. `set -e`
# keeps a failed cp/ln from being masked by the closing echo.
sync-copilot:
	@set -e; rm -rf .github/skills; mkdir -p .github/skills; \
		for d in .claude/skills/*/; do n=$$(basename $$d); \
			case ' $(OPENCODE_SKIP_SKILLS) ' in *" $$n "*) continue;; esac; \
			cp -r $$d .github/skills/$$n; \
			done; \
		find .github/skills -name __pycache__ -type d -prune -exec rm -rf {} +; \
		echo 'copied .claude/skills -> .github/skills (skipped: $(OPENCODE_SKIP_SKILLS))'

inventory:
	python3 scripts/ai_tools_inventory.py

# Only the symlinks are pruned: OpenCode-only skills live here as real
# directories and must survive. git cannot track an empty directory, so a fresh
# checkout has no .opencode/skills at all until mkdir creates it.
link-skills:
	@set -e; mkdir -p .opencode/skills; \
		find .opencode/skills -maxdepth 1 -type l -delete; \
		for d in .claude/skills/*/; do n=$$(basename $$d); \
			case ' $(OPENCODE_SKIP_SKILLS) ' in *" $$n "*) continue;; esac; \
			ln -s ../../.claude/skills/$$n .opencode/skills/$$n; \
			done; \
		echo 'linked .claude/skills -> .opencode/skills (skipped: $(OPENCODE_SKIP_SKILLS))'

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
		'sync-copilot Copy .claude/skills into .github/skills (Copilot keeps real copies, not symlinks)' \
		'inventory Regenerate ai_tools_inventory.md from the harness directories on disk' \
		'link-skills Symlink .claude/skills into .opencode/skills (Claude Code is canonical; OpenCode-only skills stay untouched)' \
		'test-web-backend Run the Django service test suite' \
		'' \
		'Ports can be overridden, for example:' \
		'  make up FRONTEND_PORT=8083 BACKEND_PORT=3002 POSTGRES_PORT=55433'