.PHONY: all format lint test tests test-integration test_watch docker_tests help extended_tests evals

# Default target executed when no arguments are given to make.
all: help

# Define a variable for the test file path.
TEST_FILE ?= tests/unit_tests/

# Needs a real Postgres that Django has migrated (`make migrate` at the root)
# and that the checkpointer has set up; the test skips itself without
# DATABASE_URL. CI's schema-drift job encodes that order.
test-integration:
	python -m pytest tests/integration_tests/

test:
	python -m pytest $(TEST_FILE)

test_watch:
	python -m ptw --snapshot-update --now . -- -vv tests/unit_tests

test_profile:
	python -m pytest -vv tests/unit_tests/ --profile-svg

extended_tests:
	python -m pytest --only-extended $(TEST_FILE)


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
	python -m ruff check .
	[ "$(PYTHON_FILES)" = "" ] || python -m ruff format $(PYTHON_FILES) --diff
	[ "$(PYTHON_FILES)" = "" ] || python -m ruff check --select I $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || python -m mypy --strict $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || mkdir -p $(MYPY_CACHE) && python -m mypy --strict $(PYTHON_FILES) --cache-dir $(MYPY_CACHE)

format format_diff:
	ruff format $(PYTHON_FILES)
	ruff check --select I --fix $(PYTHON_FILES)

spell_check:
	codespell --toml pyproject.toml

spell_fix:
	codespell --toml pyproject.toml -w

######################
# EVALS
######################

# Mirrors .github/workflows/evals.yml: sync dependencies, then run every eval
# in order, keep going after a failure, and exit non-zero when any failed.
# Keys and collector endpoints come from the root .env (loaded by
# `config.init_environment`); `ARIZE_PLATFORM` is taken from the environment,
# so point a run at local Phoenix with `docker compose up -d phoenix` and
# `make evals ARIZE_PLATFORM=PHOENIX`.
EVAL_MODULES = orchestrator expert reporter e2e

evals:
	uv sync --locked --dev
	@failed=0; \
	for module in $(EVAL_MODULES); do \
		echo "===> $$module evals"; \
		uv run python -m evals.$$module || failed=1; \
	done; \
	if [ "$$failed" = 1 ]; then \
		echo "evals: one or more evals failed"; \
	else \
		echo "evals: all passed"; \
	fi; \
	exit $$failed

######################
# HELP
######################

help:
	@echo '----'
	@echo 'format                       - run code formatters'
	@echo 'lint                         - run linters'
	@echo 'test                         - run unit tests'
	@echo 'tests                        - run unit tests'
	@echo 'test-integration             - run the schema-drift suite against a real Postgres'
	@echo 'test TEST_FILE=<test_file>   - run all tests in file'
	@echo 'test_watch                   - run unit tests in watch mode'
	@echo 'evals                        - run the offline evals like evals.yml'

