.PHONY: all format lint test tests test-integration test_watch docker_tests help extended_tests evals evals-fixed evals-live

# Default target executed when no arguments are given to make.
all: help

# Define a variable for the test file path.
TEST_FILE ?= tests/unit_tests/

# Run tools from the project's locked environment; no activated venv needed.
PYTHON ?= uv run python

# Needs a real Postgres migrated by both `make migrate-web` and
# `make migrate-agentic` at the root; the tests run the checkpointer's setup()
# themselves and fail without DATABASE_URL. CI's cross-service-schema job
# encodes that order.
test-integration:
	$(PYTHON) -m pytest tests/integration_tests/

test:
	$(PYTHON) -m pytest $(TEST_FILE)

test_watch:
	$(PYTHON) -m ptw --snapshot-update --now . -- -vv tests/unit_tests

test_profile:
	$(PYTHON) -m pytest -vv tests/unit_tests/ --profile-svg

extended_tests:
	$(PYTHON) -m pytest --only-extended $(TEST_FILE)


######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
PYTHON_FILES=src/
MYPY_CACHE=.mypy_cache
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --name-only --diff-filter=d main | grep -E '\.py$$|\.ipynb$$')
lint_package: PYTHON_FILES=src
lint_tests: PYTHON_FILES=tests
lint_tests: MYPY_CACHE=.mypy_cache_test

lint lint_diff lint_package lint_tests:
	$(PYTHON) -m ruff check .
	[ "$(PYTHON_FILES)" = "" ] || $(PYTHON) -m ruff format $(PYTHON_FILES) --diff
	[ "$(PYTHON_FILES)" = "" ] || $(PYTHON) -m ruff check --select I $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || $(PYTHON) -m mypy --strict $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || mkdir -p $(MYPY_CACHE) && $(PYTHON) -m mypy --strict $(PYTHON_FILES) --cache-dir $(MYPY_CACHE)

format format_diff:
	$(PYTHON) -m ruff format $(PYTHON_FILES)
	$(PYTHON) -m ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	codespell --toml pyproject.toml

spell_fix:
	codespell --toml pyproject.toml -w

######################
# EVALS
######################

# The lists .github/workflows/evals.yml reads, which runs them as parallel jobs.
# Here: sync dependencies, then run each eval of the chosen kind in order, keep
# going after a failure, and exit non-zero when any failed. Keys and the Phoenix collector endpoint come from the root .env
# (loaded by `shared.config.init_environment`); point a run at local Phoenix with
# `docker compose up -d phoenix`.
FIXED_EVALS = orchestrator_fixed reporter_fixed expert_fixed deep_expert_fixed
LIVE_EVALS = expert_live deep_expert_live deep_forecaster_live

define run_evals
	uv sync --locked --dev
	@failed=0; \
	for module in $(1); do \
		echo "===> $$module"; \
		uv run python -m evals.$$module || failed=1; \
	done; \
	if [ "$$failed" = 1 ]; then \
		echo "evals: one or more evals failed"; \
	else \
		echo "evals: all passed"; \
	fi; \
	exit $$failed
endef

evals-fixed:
	$(call run_evals,$(FIXED_EVALS))

evals-live:
	$(call run_evals,$(LIVE_EVALS))

evals:
	$(call run_evals,$(FIXED_EVALS) $(LIVE_EVALS))

######################
# HELP
######################

help:
	@echo '----'
	@echo 'format                       - run code formatters'
	@echo 'lint                         - run linters'
	@echo 'test                         - run unit tests'
	@echo 'tests                        - run unit tests'
	@echo 'test-integration             - run the db-web-schema suite against a real Postgres'
	@echo 'test TEST_FILE=<test_file>   - run all tests in file'
	@echo 'test_watch                   - run unit tests in watch mode'
	@echo 'evals-fixed                  - run the fixed evals (inputs written in advance)'
	@echo 'evals-live                   - run the live evals (Brave and live pages)'
	@echo 'evals                        - run both, like evals.yml with type all'

