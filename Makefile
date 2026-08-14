.PHONY: up down build logs migrate seed install-backend install-frontend setup test test-unit test-integration lint format eval-retrieval eval-generation lock

# docker compose (v2 plugin), not the standalone docker-compose (v1, EOL since
# 2023 and absent from current Docker installs). scripts/deploy.sh already
# used v2; these targets had drifted.
COMPOSE := docker compose

# `up` no longer needs a follow-up `make migrate`: the compose stack has a
# one-shot `migrate` service that the backend and worker wait on.
up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

logs:
	$(COMPOSE) logs -f backend worker

install-backend:
	cd backend && poetry install

install-frontend:
	cd frontend && npm ci

setup:
	cp .env.example backend/.env
	echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > frontend/.env.local
	@echo "Setup complete! Please configure your backend/.env file with API keys."

# Refresh poetry.lock after editing pyproject.toml. Run in the same Python
# version the image uses, so the resolution matches what gets deployed.
lock:
	cd backend && poetry lock

migrate:
	$(COMPOSE) run --rm migrate

seed:
	cd backend && poetry run python -m scripts.seed

# Unit tests only — no services required.
test-unit:
	cd backend && poetry run pytest -m "not integration"

# Integration tests: needs Postgres and Redis. `make up` provides both.
test-integration:
	cd backend && poetry run pytest -m integration

test:
	cd backend && poetry run pytest
	cd frontend && npm test

lint:
	cd backend && poetry run ruff check .
	cd backend && poetry run ruff format --check .
	cd frontend && npm run lint

format:
	cd backend && poetry run ruff check --fix .
	cd backend && poetry run ruff format .

eval-retrieval:
	cd backend && poetry run python -m app.evaluation.run

eval-generation:
	cd backend && poetry run python -m app.evaluation.run_generation
