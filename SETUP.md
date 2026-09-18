# Setup

How to get the full stack — Postgres, the API, both worker regions, and the frontend — running
locally.

## Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for the frontend)
- Python 3.11+ (only needed if you want to run a service outside Docker, or run the test
  suites)

## 1. Generate the two required secrets

Two environment variables have no default and the backend/worker will refuse to start without
them:

```bash
# JWT_SECRET — signs the session cookie
python -c "import secrets; print(secrets.token_urlsafe(32))"

# CREDENTIAL_ENCRYPTION_KEY — encrypts a target's basic-auth password at rest
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy `.env.example` to `.env` at the repo root and paste the two generated values in:

```bash
cp .env.example .env
```

`.env` is gitignored — it's never committed with real values.

## 2. Start the stack

```bash
docker compose up -d
```

This single command starts four containers: `db` (Postgres), `api` (FastAPI — runs
`alembic upgrade head` automatically on boot, then starts uvicorn), `worker` (`REGION=local`),
and `worker-eu-west` (`REGION=eu-west`, same image as `worker` — the two exist to demonstrate
the real multi-region coordination design, see
[`docs/adr/003-multi-region-coordination.md`](docs/adr/003-multi-region-coordination.md), not
just to have two containers running). No manual migration step is needed — it's part of the
`api` container's own boot sequence, not a separate command you have to remember.

Check everything came up:

```bash
docker compose ps
```

You should see `db`, `api`, `worker`, and `worker-eu-west` all `Up` (`db` additionally
`healthy`). Confirm the API directly:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## 3. Start the frontend

The frontend runs on your machine, not in Docker, so you get hot reload while editing it:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Register an account — there's no shared or
demo login; every visitor gets their own private set of targets. Add a target and within a
couple of scheduler ticks (every 5 seconds, per region) you should see a real check land for it
from both `local` and `eu-west`.

`NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000` and doesn't need to be set for this
setup. Override it in `frontend/.env.local` only if the API is reachable somewhere else (e.g.
pointing a local frontend at a deployed backend).

## 4. Stop the stack

```bash
docker compose down         # keep the Postgres volume — data survives a restart
docker compose down -v      # also delete the volume — start from a genuinely empty database
```

## Environment variables

Consolidated from every service. `.env` at the repo root (read via `env_file:` by `api` and
both worker services in Docker Compose) is the one place these are actually set for local dev.

### Backend (required, no default)

| Variable | What it does |
|---|---|
| `JWT_SECRET` | Signs the session cookie. The API refuses to start without it. |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key encrypting/decrypting a target's basic-auth password. Must be the **exact same value** on the backend and both worker regions — the worker decrypts what the backend encrypts. Both the API and the worker refuse to start without it. |

### Backend (optional — sensible local defaults)

| Variable | Default | What it does |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` forces `COOKIE_SECURE=True` and `COOKIE_SAMESITE="none"` regardless of the two settings below — needed once the frontend and backend are on different origins. |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` | Overridden inside Docker Compose to point at the `db` service hostname automatically. |
| `MIGRATION_DATABASE_URL` | falls back to `DATABASE_URL` | Only relevant against Neon in production, where the migration step and the running app need different connection-string shapes for the same database. Unused locally. |
| `LISTEN_DATABASE_URL` | falls back to `DATABASE_URL` | Only relevant against Neon in production — a direct (non-pooled) connection for the real-time `LISTEN` session, since Neon's pooled connection doesn't reliably deliver `NOTIFY`s to a listener. Unused locally (local Postgres has no pooler). |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) | |
| `COOKIE_NAME` | `session` | |
| `COOKIE_HTTP_ONLY` | `true` | |
| `COOKIE_SECURE` | `false` | Forced `true` in production regardless of this value. |
| `COOKIE_SAMESITE` | `lax` | Forced `"none"` in production regardless of this value. |
| `COOKIE_MAX_AGE` | `604800` (7 days, seconds) | |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist. Never a wildcard — the API sends credentialed cookies. |
| `FRONTEND_URL` | `http://localhost:3000` | Used to build links inside outgoing email. |
| `RESEND_API_KEY` | unset | Optional — with no key, email sending logs and no-ops instead of failing. |
| `RESEND_FROM_EMAIL` | `Uptime Monitor <onboarding@resend.dev>` | Resend's sandbox sender; works without a verified domain. |
| `DOWNTIME_ALERT_COOLDOWN_SECONDS` | `900` | Minimum gap between downtime alerts for the same `(target, region)`. |
| `CERT_EXPIRY_WARN_DAYS` | `14` | How many days out a certificate's expiry starts alerting. |
| `CERT_EXPIRY_REMINDER_COOLDOWN_DAYS` | `3` | How often an unrenewed, still-expiring certificate re-alerts. |
| `CHECKS_RETENTION_DAYS` | `90` | Informational on the backend (used only to annotate CSV exports) — the worker's own copy of this setting is what actually prunes. |

### Worker (required, no default)

| Variable | What it does |
|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | Same key as the backend's — see above. |

### Worker (optional — sensible local defaults)

| Variable | Default | What it does |
|---|---|
| `DATABASE_URL` | same default as the backend's | Connects via raw `asyncpg`, no ORM. |
| `CHECK_INTERVAL_SECONDS` | `300` (5 min) | Normal per-target recheck cadence on success; a target's own `check_interval_seconds` overrides this if set. |
| `HTTP_TIMEOUT_SECONDS` | `10` | Per-request timeout. |
| `HTTP_VERIFY_SSL` | `true` | Set `false` only for local testing against a self-signed cert. |
| `REGION` | `local` | Identity tagged onto every check row and log line. Set a distinct value per worker instance once more than one runs — Docker Compose already sets `worker-eu-west` to `eu-west`. |
| `CHECKS_RETENTION_DAYS` | `90` | How many days of check history the worker actually keeps before pruning. |

### Frontend

| Variable | Default | What it does |
|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL the browser calls. Set in `frontend/.env.local`, not the repo-root `.env`. |

## Running the API or worker outside Docker

Not the usual path (Docker Compose above is simpler and matches production more closely), but
useful for debugging one service directly against a local Postgres.

**Backend** (from `backend/`):
```bash
python -m venv .venv && .venv\Scripts\activate   # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy ..\.env.example .env                          # then fill in the two required secrets
alembic upgrade head
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Note: the backend reads `.env` from its current working directory, which is `backend/.env` here
— a different file from the repo-root `.env` Docker Compose reads.

**Worker** (from `worker/`):
```bash
pip install -r requirements.txt
python main.py
```

## Tests

Both suites need a reachable Postgres (the same one `docker compose up -d db` provides) but
never touch your dev database — each creates and migrates its own `<database>_test` database
automatically.

**Backend** (303 tests):
```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

**Worker** (59 tests, fully hermetic — no database or network, all HTTP mocked):
```bash
cd worker
pip install -r requirements-dev.txt
pytest
```
