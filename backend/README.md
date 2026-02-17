# Uptime Monitor — Backend API

FastAPI backend for the multi-user uptime monitoring dashboard. Handles authentication (cookie-based), user targets CRUD, and health checks.

## Requirements

- Python 3.11+
- PostgreSQL (local or Docker)

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

3. **Environment variables** (create a `.env` in `backend/` or export):

   | Variable | Description | Default |
   |----------|-------------|---------|
   | `DATABASE_URL` | PostgreSQL connection string (async) | `postgresql+asyncpg://postgres:postgres@localhost:5432/uptime` |
   | `JWT_SECRET` | Secret for signing session cookies | `change-me-in-production` |
   | `JWT_EXPIRE_MINUTES` | Session expiry in minutes | `10080` (7 days) |
   | `COOKIE_NAME` | Session cookie name | `session` |
   | `COOKIE_HTTP_ONLY` | HTTP-only cookie flag | `true` |
   | `COOKIE_SECURE` | Secure (HTTPS only) | `false` |
   | `COOKIE_SAMESITE` | SameSite policy | `lax` |
   | `COOKIE_MAX_AGE` | Cookie max age in seconds | `604800` (7 days) |

   Example `.env`:

   ```
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uptime
   JWT_SECRET=your-secret-key
   ```

4. **Create the database** (if needed):

   ```bash
   createdb uptime
   ```

   Tables are created automatically on first run.

## Run

From the `backend/` directory:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API: <http://localhost:8000>
- Docs: <http://localhost:8000/docs>

## Endpoints

- **Health:** `GET /health` — returns `{"status": "ok"}`
- **Auth:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **Targets:** `GET /targets`, `POST /targets`, `DELETE /targets/{id}` (ownership enforced)

Authentication uses HTTP-only cookies; include credentials when calling from the frontend.
