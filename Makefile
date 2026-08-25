.PHONY: up down restart logs ps config help

COMPOSE ?= docker compose
FRONTEND_PORT ?= 8082
BACKEND_PORT ?= 3001
POSTGRES_PORT ?= 55432

export FRONTEND_PORT BACKEND_PORT POSTGRES_PORT

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

restart: down up

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config

help:
	@printf '%s\n' \
		'up        Build and start frontend, backend, and PostgreSQL' \
		'down      Stop and remove the application containers' \
		'restart   Restart the application containers' \
		'logs      Follow application logs' \
		'ps        Show container status' \
		'config    Render the effective Compose configuration' \
		'' \
		'Ports can be overridden, for example:' \
		'  make up FRONTEND_PORT=8083 BACKEND_PORT=3002 POSTGRES_PORT=55433'