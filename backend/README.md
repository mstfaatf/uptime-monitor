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

**Resolved via a second setting, `MIGRATION_DATABASE_URL`** — `backend/Dockerfile`'s boot
command (`alembic upgrade head && exec uvicorn ...`) needs both query-string shapes at once,
since each step uses a different driver. Rather than trying to force one URL to satisfy both
(which isn't possible — the two drivers accept mutually exclusive query params), the two steps
now read two different settings:

- **`DATABASE_URL`** — read by the running app (`database.py`'s async engine, via `config.py`'s
  `Settings`). In production this is the `ssl=require` (asyncpg-shaped) form.
- **`MIGRATION_DATABASE_URL`** — read directly from the environment by `alembic/env.py` (not a
  `Settings` field — it's only ever needed at migration time, never by the running app). In
  production this is Neon's native `sslmode=require&channel_binding=require` (libpq-shaped)
  form. If unset, `alembic/env.py` falls back to `DATABASE_URL` exactly as before — so local
  dev and Docker Compose (where the two drivers' query-string difference never comes up, since
  neither uses an SSL query param at all) need no change and keep working unmodified.

This means the Dockerfile's boot command stays a single, unchanged command — no script
duplication, no conditional logic in the Dockerfile itself; only `alembic/env.py` needed a
two-line change (prefer `MIGRATION_DATABASE_URL`, fall back to `DATABASE_URL`). Verified against
the real Neon instance: booting the actual image with `DATABASE_URL=...?ssl=require` and
`MIGRATION_DATABASE_URL=...?sslmode=require&channel_binding=require` set together runs the
migration successfully via psycopg2, then starts uvicorn successfully via asyncpg, in one
container boot, exactly as Railway will run it.

Postgres version: Neon currently runs PostgreSQL 18.6; local dev runs `postgres:16-alpine`. All
9 migrations (`001`–`009`) applied cleanly against Neon with no errors. A full column/index/
constraint diff between the two found the schema functionally identical (same 45 columns, same
17 indexes, same nullability throughout) — the only difference was that Neon's newer catalog
materializes column-level `NOT NULL` constraints as explicit `pg_constraint` rows (a PostgreSQL
17+ catalog change), which PG16 doesn't do; this is a metadata/introspection difference only, not
a functional one.

## LISTEN_DATABASE_URL (production — Neon's pooler breaks LISTEN/NOTIFY)

`realtime.py` holds one long-lived Postgres `LISTEN checks_inserted` connection open for the
life of the process, used to push real-time check updates to connected SSE clients. **Neon's
pooled connection string (the same `-pooler` hostname `DATABASE_URL` uses) does not reliably
deliver NOTIFYs to a LISTEN session** — found live in production (prompt 5.4): a worker check
landed correctly and a client was genuinely connected to `GET /targets/stream` the whole time,
but the `check_update` push never arrived, only keep-alives.

Root cause: Neon's pooler runs in transaction-pooling mode by default. `LISTEN` registers
interest against one specific physical backend session, but a pooled connection's underlying
physical backend can be swapped between queries — so a `NOTIFY` sent while a *different*
physical backend happens to be attached to that pooled session is simply never delivered to it.
The `LISTEN` call itself never errors (so this fails silently, not loudly), and the connection
never drops or needs reconnecting — it just quietly never receives anything. This never surfaced
locally because Docker Compose's Postgres has no pooling at all; any connection works fine for
`LISTEN` there.

**Fix**: a separate setting, **`LISTEN_DATABASE_URL`**, holding Neon's **direct** (non-pooled)
connection string — same credentials, but the compute endpoint's hostname *without* the
`-pooler` segment (Neon's dashboard's "Connection Details" panel has a toggle for pooled vs.
direct; grab the direct one specifically for this). Used only by `realtime.py`'s
`listen_asyncpg_url` property, which `run_listener()` connects with instead of the pooled
`asyncpg_database_url`. If unset, falls back to `DATABASE_URL` — so local dev/Docker Compose
(no pooler, so the distinction is moot) needs no change, same fallback pattern as
`MIGRATION_DATABASE_URL`. Ordinary app traffic (`database.py`'s async engine, used by every
other endpoint) keeps using the pooled `DATABASE_URL` unchanged — pooling is fine and desirable
there; only the one `LISTEN` session needs to bypass it.

The worker's `NOTIFY` calls need no change at all — sending a `NOTIFY` has no session-affinity
requirement and works fine over a pooled connection; only the receiving `LISTEN` side does.

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
   | `CREDENTIAL_ENCRYPTION_KEY` | Fernet key encrypting a target's basic-auth password at rest (see `security/crypto.py`). Must be the exact same value on the worker (both regions) — the worker decrypts what this service encrypts. | **required — no default; the app fails to start without it. Must be a valid Fernet key** (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
   | `ENVIRONMENT` | `development` or `production` | `development`. `production` forces `COOKIE_SECURE=True` and `COOKIE_SAMESITE="none"` regardless of the settings below. |
   | `DATABASE_URL` | PostgreSQL URL used by the running app (async: `postgresql+asyncpg://...`) | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` |
   | `MIGRATION_DATABASE_URL` | PostgreSQL URL used only by Alembic's migration step at boot (sync). See "DATABASE_URL (production — Neon)" above. | unset — falls back to `DATABASE_URL` |
   | `LISTEN_DATABASE_URL` | Direct (non-pooled) PostgreSQL URL used only by `realtime.py`'s LISTEN connection. See "LISTEN_DATABASE_URL (production — Neon's pooler breaks LISTEN/NOTIFY)" above. | unset — falls back to `DATABASE_URL` |
   | `JWT_EXPIRE_MINUTES` | Session expiry in minutes | `10080` (7 days) |
   | `COOKIE_NAME` | Session cookie name | `session` |
   | `COOKIE_HTTP_ONLY` | HTTP-only cookie flag | `true` |
   | `COOKIE_SECURE` | Secure (HTTPS only) | `false` (see `ENVIRONMENT` above) |
   | `COOKIE_SAMESITE` | SameSite policy | `lax` (see `ENVIRONMENT` above — must be `"none"` in production, since the frontend and backend are different origins there) |
   | `COOKIE_MAX_AGE` | Cookie max age in seconds | `604800` (7 days) |
   | `CORS_ORIGINS` | Comma-separated list of allowed CORS origins. Never a wildcard — `allow_credentials=True` requires an exact allowlist. | `http://localhost:3000` |
   | `FRONTEND_URL` | Base URL used to build links in outgoing email (detail page, settings, password reset) | `http://localhost:3000` |
   | `RESEND_API_KEY` | Resend API key for transactional email (downtime/cert-expiry alerts, password reset) | unset — email sending no-ops (logged, not sent) rather than failing |
   | `RESEND_FROM_EMAIL` | Sender identity for outgoing mail | `Uptime Monitor <onboarding@resend.dev>` (Resend's sandbox address; works without a verified domain) |

   Example `backend/.env`:

   ```
   JWT_SECRET=your-secret-key
   CREDENTIAL_ENCRYPTION_KEY=your-fernet-key
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uptime
   ```

   Generate a `JWT_SECRET` with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

   Generate a `CREDENTIAL_ENCRYPTION_KEY` with:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

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

## Deploying to Railway

The existing `Dockerfile` works as-is — Railway auto-detects it when the service's root
directory is set to `backend/`. Its `CMD` binds uvicorn to `${PORT:-8000}`, so it respects
Railway's injected `PORT` automatically; nothing else to configure for networking.

Env vars to set on the Railway `api` service's dashboard (see the table above for what each
does):

| Variable | Value |
|----------|-------|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Neon's connection string, `ssl=require` form — see "DATABASE_URL (production — Neon)" above |
| `MIGRATION_DATABASE_URL` | Neon's connection string, `sslmode=require&channel_binding=require` form (Neon's dashboard default) |
| `LISTEN_DATABASE_URL` | Neon's **direct** (non-pooled) connection string, `ssl=require` form — same credentials as `DATABASE_URL` but the hostname without `-pooler`. See "LISTEN_DATABASE_URL (production — Neon's pooler breaks LISTEN/NOTIFY)" above. |
| `JWT_SECRET` | freshly generated — `python -c "import secrets; print(secrets.token_urlsafe(32))"`, never reused from local dev |
| `CREDENTIAL_ENCRYPTION_KEY` | freshly generated — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — and set to the **exact same value** on both worker Railway services (`worker`/`us-east`, `worker-eu-west`), not just this one; generate it and set all three **before** deploying this migration, the same coordination `JWT_SECRET` needed on its own first deploy |
| `RESEND_API_KEY` | the real Resend API key |
| `RESEND_FROM_EMAIL` | `Uptime Monitor <onboarding@resend.dev>` (sandbox address — no custom domain verified yet) |
| `CORS_ORIGINS` | `http://localhost:3000` for now (still verifying cross-origin behavior locally); update to the real Vercel domain once the frontend is deployed |
| `FRONTEND_URL` | same as `CORS_ORIGINS` for now — update together |

Not set (safe defaults apply): `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `COOKIE_NAME`,
`COOKIE_HTTP_ONLY`, `COOKIE_MAX_AGE`, `DOWNTIME_ALERT_COOLDOWN_SECONDS`, `CERT_EXPIRY_WARN_DAYS`,
`CERT_EXPIRY_REMINDER_COOLDOWN_DAYS`. `COOKIE_SECURE`/`COOKIE_SAMESITE` are not set directly —
`ENVIRONMENT=production` forces both correctly regardless.

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
creation time, target request-customization validation and the PATCH edit endpoint (method/
keyword-match/basic-auth rules, blank-means-unchanged password semantics, and that the
encrypted password is never returned in any response — see `test_target_customization.py`),
the `JWT_SECRET`/`CREDENTIAL_ENCRYPTION_KEY` fail-fast behaviors, rate limiting on
login/register/target creation, and the `mail/` package's Resend wrapper + email templates
(hermetic — no real Resend API calls; `RESEND_API_KEY` is unset in the test environment,
exercising the real no-op path rather than a mock standing in for it). Worker-side SSRF,
redirect-handling, and request-customization/keyword-match tests live in `worker/tests/`
instead — see `worker/README.md` — since the worker is a separately deployed service with its
own dependencies.

## Endpoints

- **Health:** `GET /health` — returns `{"status": "ok"}`
- **Auth:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **Targets:** `GET /targets`, `POST /targets`, `DELETE /targets/{id}` (ownership enforced)

Authentication uses HTTP-only cookies; include credentials when calling from the frontend.
