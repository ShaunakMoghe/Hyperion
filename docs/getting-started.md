# Local Development Guide

## Prerequisites

- Python 3.11+
- Node.js 18 LTS (`nvm use 18` or download from nodejs.org)
- Docker Desktop (or an equivalent Docker engine)
- `docker compose`, `git`
- Optional but helpful: `make`

## 1. Bootstrap the infrastructure

```powershell
# from repo root
make infra-up              # or: docker compose -f infra/docker-compose.yml up -d postgres redis
```

Verify that Postgres and Redis are reachable:

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker exec infra-postgres-1 pg_isready -U hyperion -d hyperion
```

## 2. Backend setup

```powershell
make backend-setup         # creates the venv and installs requirements
make backend-migrate       # applies Alembic migrations
make backend-run           # starts FastAPI on http://localhost:8000
```

Smoke-test the API:

```powershell
curl http://localhost:8000/healthz
curl -X POST http://localhost:8000/orgs/ -H 'Content-Type: application/json' -d '{"name":"Acme","slug":"acme"}'
curl http://localhost:8000/audit/
```

## 3. Frontend setup

```powershell
cd frontend
cp .env.local.example .env.local  # adjust NEXT_PUBLIC_BACKEND_URL if needed
npm install                       # or: make frontend-install
npm run dev                       # starts Next.js on http://localhost:3000
```

Visit http://localhost:3000/projects to confirm organizations load from the backend.

## 4. Tear-down

```powershell
make infra-down
# optional clean
make clean
```

## 5. Troubleshooting

- **Database connection errors**: ensure Docker containers are running and host ports 5432/6379 are free.
- **Alembic upgrade fails**: confirm that `.env.local` points to the correct Postgres URL (`postgresql+psycopg://...`).
- **CORS in dev**: the backend allows `http://localhost:3000` by default; update `FRONTEND_URL` in `.env.local` for other origins.
- **Node fetch errors**: confirm `NEXT_PUBLIC_BACKEND_URL` is reachable from the browser (same machine).
