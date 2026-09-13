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

## DATABASE_URL (production — Neon)

Neon's dashboard hands out a libpq-style connection string:

```
postgresql://<user>:<password>@<host>-pooler.<region>.aws.neon.tech/<db>?sslmode=require&channel_binding=require
```

That string works as-is for **Alembic's migration path** (sync engine via `psycopg2` — see
`alembic/env.py`, which only strips a `+asyncpg` prefix if present and passes the rest through
unchanged; `sslmode`/`channel_binding` are real libpq parameters psycopg2 understands natively).

It does **not** work unmodified for the **app's own runtime connection** (SQLAlchemy's `asyncpg`
dialect, used by `database.py`'s async engine): `asyncpg` doesn't recognize `sslmode`/
`channel_binding` as connection kwargs and raises `TypeError: connect() got an unexpected keyword
argument 'sslmode'`. For the asyncpg path, the query string must instead be `?ssl=require`:

```
postgresql+asyncpg://<user>:<password>@<host>-pooler.<region>.aws.neon.tech/<db>?ssl=require
```

Both forms were verified directly against the real Neon instance this project provisions:
`sslmode=require&channel_binding=require` succeeds via psycopg2/sync, fails via asyncpg;
`ssl=require` succeeds via asyncpg (both SQLAlchemy's async engine and raw `asyncpg.connect()`),
**fails via psycopg2/sync** (`invalid dsn: invalid connection option "ssl"`).

**Open problem, not yet resolved (flagged for the prompt that wires up the Railway `api`
deploy)**: `backend/Dockerfile`'s boot command is `alembic upgrade head && exec uvicorn ...` —
both steps read the *same* `DATABASE_URL` env var, but each needs a different query-string shape
(`sslmode=require` for the migration step, `ssl=require` for the app). A single production
`DATABASE_URL` value cannot satisfy both today. This needs a code fix (e.g. `alembic/env.py`
translating `ssl=` to `sslmode=` for its sync connection, or `database.py` adding
`connect_args={"ssl": "require"}` instead of relying on the query string) before this backend can
actually be deployed — not fixed in this pass, since Neon provisioning didn't touch application
code by design.

Postgres version: Neon currently runs PostgreSQL 18.6; local dev runs `postgres:16-alpine`. All
9 migrations (`001`–`009`) applied cleanly against Neon with no errors. A full column/index/
constraint diff between the two found the schema functionally identical (same 45 columns, same
17 indexes, same nullability throughout) — the only difference was that Neon's newer catalog
materializes column-level `NOT NULL` constraints as explicit `pg_constraint` rows (a PostgreSQL
17+ catalog change), which PG16 doesn't do; this is a metadata/introspection difference only, not
a functional one.

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
   | `RESEND_API_KEY` | Resend API key for transactional email (downtime/cert-expiry alerts, password reset) | unset — email sending no-ops (logged, not sent) rather than failing |
   | `RESEND_FROM_EMAIL` | Sender identity for outgoing mail | `Uptime Monitor <onboarding@resend.dev>` (Resend's sandbox address; works without a verified domain) |

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

## Tests

```bash
pip install -r requirements-dev.txt   # pytest, pytest-asyncio, httpx — not in the Docker image
pytest
```

Requires a reachable Postgres server (the same one used for local dev — `docker compose up -d db`
from the repo root is enough). Tests never touch your dev database: they create and migrate a
separate `<database>_test` database on the same server automatically (derived from `DATABASE_URL`,
or set `TEST_DATABASE_URL` explicitly to point somewhere else). No other manual setup needed —
each test run creates the test DB if missing, migrates it to head, and wipes all tables before
every test for isolation.

If Postgres isn't reachable at the default `localhost:5432` (e.g. it's mapped to a different host
port to avoid a conflict with another local project), set `DATABASE_URL` or `TEST_DATABASE_URL`
accordingly before running `pytest`.

Coverage: full auth flow (register/login/logout/me, duplicate email, wrong password), ownership
enforcement across all target endpoints (the most important tests here — user A can never read,
list, or delete user B's targets), URL normalization + duplicate-target 409s, SSRF blocking at
creation time, the `JWT_SECRET` fail-fast behavior, rate limiting on login/register/target
creation, and the `mail/` package's Resend wrapper + email templates (hermetic — no real
Resend API calls; `RESEND_API_KEY` is unset in the test environment, exercising the real
no-op path rather than a mock standing in for it). Worker-side SSRF and redirect-handling
tests live in `worker/tests/` instead — see `worker/README.md` — since the worker is a
separately deployed service with its own dependencies.

## Endpoints

- **Health:** `GET /health` — returns `{"status": "ok"}`
- **Auth:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **Targets:** `GET /targets`, `POST /targets`, `DELETE /targets/{id}` (ownership enforced)

Authentication uses HTTP-only cookies; include credentials when calling from the frontend.
