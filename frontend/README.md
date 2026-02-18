# Uptime Monitor — Frontend

Next.js (App Router) frontend for the uptime monitoring dashboard. Pages: login, register, dashboard. All API calls use the FastAPI backend with `credentials: "include"` for cookie-based auth.

## Requirements

- Node.js 18+
- Backend API running (e.g. `http://localhost:8000`)

## Environment

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Base URL of the FastAPI backend | `http://localhost:8000` |

Create a `.env.local` in `frontend/` to override:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

When the frontend runs in Docker or on another host, set this to the API URL the browser can reach (e.g. `http://localhost:8000` for local dev).

## Run locally

1. **Install dependencies** (from `frontend/`):

   ```bash
   npm install
   ```

2. **Start the backend** (from repo root: `docker compose up -d db api`, or run uvicorn from `backend/`).

3. **Start the dev server**:

   ```bash
   npm run dev
   ```

   Open [http://localhost:3000](http://localhost:3000). You’ll be redirected to `/dashboard`; if not logged in, you’ll be sent to `/login`.

## Run with Docker

From the **repository root**, if the stack includes a frontend service:

```bash
docker compose up -d
```

Otherwise run the frontend locally with `npm run dev` and point `NEXT_PUBLIC_API_URL` at your API.

## Pages

- **/login** — Email + password form; POST `/auth/login` with credentials; redirects to `/dashboard` on success.
- **/register** — Email + password form; POST `/auth/register` with credentials; redirects to `/dashboard` on success.
- **/dashboard** — Fetches GET `/targets/status` (falls back to GET `/targets` if status is not implemented). Shows a table: URL, status (Up/Down with green/red), last checked timestamp. Log out button calls POST `/auth/logout`.

## Build

```bash
npm run build
npm run start
```

Production server runs on port 3000 by default.
