VENV_DIR := backend/.venv
ifeq ($(OS),Windows_NT)
PYTHON_BIN := $(VENV_DIR)/Scripts/python.exe
ALEMBIC_BIN := $(VENV_DIR)/Scripts/alembic.exe
else
PYTHON_BIN := $(VENV_DIR)/bin/python
ALEMBIC_BIN := $(VENV_DIR)/bin/alembic
endif

.PHONY: infra-up infra-down backend-setup backend-migrate backend-run backend-lint backend-format frontend-install frontend-dev frontend-lint clean

infra-up:
	docker compose -f infra/docker-compose.yml up -d postgres redis

infra-down:
	docker compose -f infra/docker-compose.yml down

backend-setup:
	python -m venv $(VENV_DIR)
	$(PYTHON_BIN) -m pip install --upgrade pip
	$(PYTHON_BIN) -m pip install -r backend/requirements.txt

backend-migrate:
	cd backend && $(ALEMBIC_BIN) upgrade head

backend-run:
	cd backend && $(PYTHON_BIN) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

backend-lint:
	cd backend && $(PYTHON_BIN) -m pip install black==24.10.0 ruff==0.6.9
	cd backend && $(PYTHON_BIN) -m ruff check app

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-lint:
	cd frontend && npm run lint

clean:
	docker compose -f infra/docker-compose.yml down -v
	rm -rf backend/.venv
	rm -rf frontend/node_modules frontend/.next
