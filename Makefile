SHELL := /bin/bash

.PHONY: build up sh test testq e2e fmt clean nuke

build:
\tdocker compose build

up:
\tdocker compose up -d

sh:
\tdocker compose run --rm app bash

test:
\tdocker compose run --rm app pytest

testq:
\tdocker compose run --rm app pytest -q

e2e:
\tdocker compose run --rm app npx playwright test -c playwright.config.ts

fmt:
\t# add formatters later (black/ruff/prettier)

clean:
\trm -rf playwright-report test-results artifacts logs .pytest_cache

nuke: clean
\tdocker compose down -v --remove-orphans || true
\tdocker image prune -f
