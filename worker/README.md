# Uptime Monitor — Worker

Background service that periodically checks all targets concurrently (HTTP HEAD/GET via `httpx.AsyncClient`, or a target's configured method/headers/basic-auth/keyword-match — see `checker.py`), measures latency, and writes results to the `checks` table. SSRF protection blocks localhost and private IP ranges.

## Requirements

- Python 3.11+
- PostgreSQL (same DB as the API; tables created by API migrations)

## Environment variables

One of these is required (`CREDENTIAL_ENCRYPTION_KEY`, added Phase 6 prompt 6.2) — every other
one has a safe default, unlike the backend's `JWT_SECRET`. In Docker Compose, the `worker`
service also loads the repo-root `.env` (`env_file:`) for consistency with the `api` service.

| Variable | Description | Default |
|----------|-------------|---------|
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key decrypting a target's basic-auth password (encrypted by the backend — see `crypto.py`). Must be the exact same value as the backend's `CREDENTIAL_ENCRYPTION_KEY`, and the same value across both worker regions. | **required — no default; the worker fails to start without it. Must be a valid Fernet key** (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `DATABASE_URL` | PostgreSQL URL (same pattern as backend; connects via `asyncpg` directly, raw queries, no ORM) | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` |
| `CHECK_INTERVAL_SECONDS` | Seconds between full check cycles | `300` (5 min) |
| `HTTP_TIMEOUT_SECONDS` | Timeout per HTTP request | `10` |
| `HTTP_VERIFY_SSL` | Verify TLS certificates for checked URLs (`true`/`false`) | `true`. Set to `false` only for local/dev if CA verification fails (insecure). |
| `REGION` | Identifies which region this worker instance is checking from. Tagged onto log lines and `checks` rows. Set a distinct value per instance (e.g. `us-east`, `eu-west`) once more than one worker runs. | `local` |

## DATABASE_URL (production — Neon)

The worker talks to Postgres via raw `asyncpg` (see `config.py`'s `asyncpg_database_url`, which
strips a `+asyncpg` dialect prefix if present). Verified directly against the real Neon instance
this project provisions: `postgresql+asyncpg://<user>:<password>@<host>-pooler.<region>.aws.neon.tech/<db>?ssl=require`
connects successfully via both `asyncpg.connect()` directly and SQLAlchemy's async engine.

Neon's dashboard instead hands out `?sslmode=require&channel_binding=require` (libpq-style) —
that form does **not** work with asyncpg (`TypeError: connect() got an unexpected keyword
argument 'sslmode'`), so it must be rewritten to `?ssl=require` before use here. Unlike the
backend (see `backend/README.md`'s DATABASE_URL section), the worker only ever uses the asyncpg
path — no sync/psycopg2 migration step runs in this service — so `ssl=require` is the only form
the worker ever needs, with no conflicting dual-use requirement on the single env var.

## Run locally

1. **From repo root**, ensure Postgres and API migrations are up (e.g. `docker compose up -d db api` and API has run migrations).

2. **Install deps** (from `worker/`):

   ```bash
   pip install -r requirements.txt
   ```

3. **Set env** (or use `.env` in `worker/`):

   ```bash
   # Windows (PowerShell)
   $env:DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime"

   # macOS/Linux
   export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uptime
   ```

4. **Run the worker**:

   ```bash
   python main.py
   ```

   It will loop every `CHECK_INTERVAL_SECONDS`, fetch all targets, and check up to 15 of them concurrently at a time (a HEAD, or GET fallback, per target), inserting one row per target into `checks`.

## Run with Docker

From the **repository root**:

```bash
docker compose up -d
```

The `worker` service is built from `./worker`, uses the same `DATABASE_URL` as the API (with hostname `db` in Compose), and depends on `db` being healthy. No separate port; it only talks to Postgres and the internet (for HTTP checks).

`docker compose up` also starts `worker-eu-west` — a second worker instance, identical except for `REGION=eu-west` (the main `worker` service runs `REGION=local`), demonstrating the multi-region coordination design (see `docs/adr/001-multi-region-coordination.md`): both check the same targets against the same database independently, each claiming and scheduling only its own region's rows.

To run only DB + worker (no API, single region):

```bash
docker compose up -d db worker
```

## SSRF protection

The worker blocks targets whose hostname:

- Is `localhost` (or similar), or
- Resolves to an IP in: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16

Blocked targets get a check row with `is_up=false` and `error` set to the reason. Redirects are
followed manually with the same check re-run on each hop (see `checker.py`) — a target can't
pass the check and then 3xx to a blocked address.

## Tests

```bash
pip install -r requirements-dev.txt   # pytest — not in the Docker image
pytest
```

No database or network needed — `worker/tests/` unit-tests `ssrf.py`'s blocklist,
`checker.py`'s redirect-following and request-customization/keyword-match logic (with all HTTP
mocked), and `crypto.py`'s decryption against a session-wide test `CREDENTIAL_ENCRYPTION_KEY`
(set in `tests/conftest.py`, required before any test module can import `config`/`crypto`/
`main`). Kept separate from `backend/tests/` deliberately: the worker is a separately deployed
service with its own dependencies, so its tests don't need backend/'s FastAPI/Postgres test
setup at all.
