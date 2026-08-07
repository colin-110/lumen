.PHONY: up down build logs migrate seed install-backend install-frontend setup test lint eval-retrieval eval-generation

up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

logs:
	docker-compose logs -f backend worker

install-backend:
	cd backend && poetry install

install-frontend:
	cd frontend && npm install

setup:
	cp .env.example backend/.env
	echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1" > frontend/.env.local
	@echo "Setup complete! Please configure your backend/.env file with API keys."

migrate:
	cd backend && poetry run alembic upgrade head

seed:
	cd backend && poetry run python scripts/seed.py

test:
	cd backend && poetry run pytest
	cd frontend && npm test

lint:
	cd backend && poetry run ruff check .
	cd frontend && npm run lint

eval-retrieval:
	cd backend && poetry run python -m app.evaluation.run

eval-generation:
	cd backend && poetry run python -m app.evaluation.run_generation
