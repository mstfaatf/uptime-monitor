# Uptime Monitor — Worker

Background service that periodically checks all targets (HTTP HEAD/GET), measures latency, and writes results to the `checks` table. SSRF protection blocks localhost and private IP ranges.

## Requirements

- Python 3.11+
- PostgreSQL (same DB as the API; tables created by API migrations)

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL URL (same pattern as backend; sync driver used internally) | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` |
| `CHECK_INTERVAL_SECONDS` | Seconds between full check cycles | `300` (5 min) |
| `HTTP_TIMEOUT_SECONDS` | Timeout per HTTP request | `10` |
| `HTTP_VERIFY_SSL` | Verify TLS certificates for checked URLs (`true`/`false`) | `true`. Set to `false` only for local/dev if CA verification fails (insecure). |

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

   It will loop every `CHECK_INTERVAL_SECONDS`, fetch all targets, perform a HEAD (or GET fallback) per target, and insert one row per target into `checks`.

## Run with Docker

From the **repository root**:

```bash
docker compose up -d
```

The `worker` service is built from `./worker`, uses the same `DATABASE_URL` as the API (with hostname `db` in Compose), and depends on `db` being healthy. No separate port; it only talks to Postgres and the internet (for HTTP checks).

To run only DB + worker (no API):

```bash
docker compose up -d db worker
```

## SSRF protection

The worker blocks targets whose hostname:

- Is `localhost` (or similar), or
- Resolves to an IP in: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16

Blocked targets get a check row with `is_up=false` and `error` set to the reason.
