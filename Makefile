.PHONY: up down restart logs services ps config help migrate-web migrate-agentic \
	createsuperuser e2e-user test-web-backend test-web-integration sync-copilot inventory link-skills

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

# Two migration systems, and the order is load-bearing: Django owns `public`,
# Alembic owns `agentic`, and `agentic-backend`'s lifespan runs the
# checkpointer's setup() only after both have run.
migrate-web:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py migrate
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createcachetable

# Alembic's env.py reads DATABASE_URL, and `.env`'s copy names the Compose
# service host (`@postgres:5432`), which does not resolve from the host —
# `DJANGO_HOST_ENV` rewrites POSTGRES_HOST/PORT but never DATABASE_URL, and
# python-dotenv will not override an already-exported value. Build the
# host-flavoured DSN here, from the same variables settings.py uses. The
# password is percent-encoded: settings.py reads it as a separate field, so it
# may hold `@`, `:`, `/`, `#` or `%`, which a raw URL would misparse.
migrate-agentic:
	$(DJANGO_HOST_ENV) DATABASE_URL="postgresql://$${POSTGRES_USER}:$$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["POSTGRES_PASSWORD"], safe=""))')@$${POSTGRES_HOST}:$${POSTGRES_PORT}/$${POSTGRES_DB}" \
		uv run --directory agentic_backend alembic upgrade head

createsuperuser:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py createsuperuser

# Runs inside the web-backend container: Compose's env_file is what hands it
# E2E_EMAIL/E2E_PASSWORD, so recreate the container after adding them to .env.
# The command refuses unless DEBUG is on (docker-compose.override.yml sets it).
# Re-running also refills the test user's daily research quota.
e2e-user:
	$(COMPOSE) exec web-backend .venv/bin/python manage.py create_e2e_user

test-web-backend:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py collectstatic --noinput
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py test --exclude-tag=integration

test-web-integration:
	$(DJANGO_HOST_ENV) uv run --directory web_backend python manage.py test tests.integration_tests

# Skills excluded from both non-Claude harnesses: they need a Claude-only
# runtime, so neither `sync-copilot` nor `link-skills` propagates them.
# `e2e` drives Claude-only tools (`AskUserQuestion`) and this repo's Compose
# stack; it has no port.
SKIP_SKILLS := swarm e2e

# `sync-copilot` rebuilds .github/skills from scratch: copying in place leaves a
# skill that was deleted from the canonical tree behind forever, and a stale copy
# is exactly the drift Harness Integrity's diff exists to catch. `set -e` keeps a failed
# cp from being masked by the closing echo. Anything hand-written under
# .github/skills is destroyed; edit .claude/skills and re-run this instead.
sync-copilot:
	@set -e; rm -rf .github/skills; mkdir -p .github/skills; \
		for d in .claude/skills/*/; do n=$$(basename $$d); \
			case ' $(SKIP_SKILLS) ' in *" $$n "*) continue;; esac; \
			cp -r $$d .github/skills/$$n; \
			done; \
		find .github/skills -name __pycache__ -type d -prune -exec rm -rf {} +; \
		echo 'copied .claude/skills -> .github/skills (skipped: $(SKIP_SKILLS))'

inventory:
	python3 scripts/harness_integrity/ai_tools_inventory.py $(SKIP_SKILLS)

# Unlike sync-copilot this prunes only the symlinks, because OpenCode-only skills
# live here as real directories and must survive. A real directory sharing a
# canonical skill's name is refused rather than linked: `ln -s` would silently
# create the link *inside* it, where it dangles and `make inventory` reports
# the skill as missing. Every name is checked before anything is pruned,
# so a refusal leaves the existing links alone instead of deleting the ones it
# had not reached yet. git cannot track an empty directory, so a fresh checkout
# has no .opencode/skills at all until mkdir creates it.
link-skills:
	@set -e; mkdir -p .opencode/skills; \
		for d in .claude/skills/*/; do n=$$(basename $$d); \
			case ' $(SKIP_SKILLS) ' in *" $$n "*) continue;; esac; \
			if [ -e .opencode/skills/$$n ] && [ ! -L .opencode/skills/$$n ]; then \
				echo "$$n already exists as a real directory in .opencode/skills; remove or rename it" >&2; \
				exit 1; \
			fi; \
			done; \
		find .opencode/skills -maxdepth 1 -type l -delete; \
		for d in .claude/skills/*/; do n=$$(basename $$d); \
			case ' $(SKIP_SKILLS) ' in *" $$n "*) continue;; esac; \
			ln -s ../../.claude/skills/$$n .opencode/skills/$$n; \
			done; \
		echo 'linked .claude/skills -> .opencode/skills (skipped: $(SKIP_SKILLS))'

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
		'migrate-web   Run Django migrations and create the cache table (owns `public`)' \
		'migrate-agentic Run Alembic migrations for the agentic-owned schema (runs after migrate-web)' \
		'createsuperuser Create a Django admin user' \
		'sync-copilot Copy .claude/skills into .github/skills (Copilot keeps real copies, not symlinks)' \
		'inventory Fail if a Claude command or skill is missing from OpenCode or Copilot' \
		'link-skills Symlink .claude/skills into .opencode/skills (Claude Code is canonical; OpenCode-only skills stay untouched)' \
		'test-web-backend Run the Django service test suite (unit tests; integration excluded)' \
		'test-web-integration Run the Django integration suite against the dev Postgres' \
		'' \
		'Ports can be overridden, for example:' \
		'  make up FRONTEND_PORT=8083 BACKEND_PORT=3002 POSTGRES_PORT=55433'