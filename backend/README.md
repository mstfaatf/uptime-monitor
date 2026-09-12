# Uptime Monitor — Backend API

FastAPI backend for the multi-user uptime monitoring dashboard. Handles authentication (cookie-based), user targets CRUD, and health checks. Uses PostgreSQL and Alembic for migrations.

## Requirements

- Python 3.11+
- PostgreSQL (local or via Docker)

## DATABASE_URL (local vs Docker)

- **Local:** use `localhost` so the app and migrations connect to Postgres on your machine:
  ```bash
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uptime
  ```
- **Docker Compose:** the `api` service uses hostname `db` (the Postgres service):
  ```
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/uptime
  ```
  Set in `docker-compose.yml`; no change needed when running inside Compose.

Alembic uses the same `DATABASE_URL` and converts it to a sync driver (`postgresql://`) internally.

## Setup

1. **Create a virtual environment** (recommended):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # macOS/Linux
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

   Or use the helper script (from repo root or `backend/`):

   ```bash
   # Windows (PowerShell)
   .\scripts\install.ps1

   # macOS/Linux
   ./scripts/install.sh
   ```

3. **Environment variables**: the app reads `.env` from the **current working directory** —
   for local runs that's `backend/` (the run scripts `cd` there first), which is *not* the
   same `.env` that `docker compose` reads (that one lives at the repo root). Copy the root
   `.env.example` to `backend/.env` for local runs, or export the variables in your shell.

   | Variable | Description | Default |
   |----------|-------------|---------|
   | `JWT_SECRET` | Secret for signing session cookies | **required — no default; the app fails to start without it** |
   | `ENVIRONMENT` | `development` or `production` | `development`. `production` forces `COOKIE_SECURE=True` regardless of the setting below. |
   | `DATABASE_URL` | PostgreSQL URL (async: `postgresql+asyncpg://...`) | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` |
   | `JWT_EXPIRE_MINUTES` | Session expiry in minutes | `10080` (7 days) |
   | `COOKIE_NAME` | Session cookie name | `session` |
   | `COOKIE_HTTP_ONLY` | HTTP-only cookie flag | `true` |
   | `COOKIE_SECURE` | Secure (HTTPS only) | `false` (see `ENVIRONMENT` above) |
   | `COOKIE_SAMESITE` | SameSite policy | `lax` |
   | `COOKIE_MAX_AGE` | Cookie max age in seconds | `604800` (7 days) |

   Example `backend/.env`:

   ```
   JWT_SECRET=your-secret-key
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uptime
   ```

   Generate a `JWT_SECRET` with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

4. **Create the database** (if running Postgres locally):

   ```bash
   createdb uptime
   ```

## Commands (Makefile-style)

Run from the **backend/** directory (or use the scripts which `cd` there).

| Task | Command |
|------|--------|
| **Install deps** | `pip install -r requirements.txt` |
| **Run migrations** | `alembic upgrade head` |
| **Run API** | `uvicorn main:app --reload --host 0.0.0.0 --port 8000` |

Script helpers (from `backend/`):

```bash
# Windows (PowerShell)
.\scripts\install.ps1    # install deps
.\scripts\migrate.ps1     # alembic upgrade head
.\scripts\run.ps1         # uvicorn ...

# macOS/Linux
./scripts/install.sh
./scripts/migrate.sh
./scripts/run.sh
```

## Run (local)

1. Start Postgres (or use Docker: `docker compose up -d db`).
2. Apply migrations: `alembic upgrade head`
3. Start the API: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

- API: <http://localhost:8000>
- Docs: <http://localhost:8000/docs>

## Run (Docker Compose)

From the **repository root**:

```bash
docker compose up --build
```

- `db`: Postgres on port 5432 with volume `uptime_pgdata`.
- `api`: FastAPI on port 8000; runs `alembic upgrade head` then uvicorn on startup.

## Migrations

- Create a new revision: `alembic revision --autogenerate -m "description"`
- Upgrade: `alembic upgrade head`
- Downgrade one step: `alembic downgrade -1`

## Endpoints

- **Health:** `GET /health` — returns `{"status": "ok"}`
- **Auth:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **Targets:** `GET /targets`, `POST /targets`, `DELETE /targets/{id}` (ownership enforced)

Authentication uses HTTP-only cookies; include credentials when calling from the frontend.
