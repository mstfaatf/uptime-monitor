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

## Run locally alongside Docker backend

This is the usual setup: backend (and DB, worker) run in Docker; the frontend runs on your machine so you can edit and hot-reload.

1. **Start the backend stack** (from the **repository root**):

   ```bash
   docker compose up -d
   ```

   This starts PostgreSQL, the API, and the worker. The API is at http://localhost:8000.

2. **Install frontend dependencies** (once, from `frontend/`):

   ```bash
   cd frontend
   npm install
   ```

3. **Start the Next.js dev server** (from `frontend/`):

   ```bash
   npm run dev
   ```

   Open [http://localhost:3000](http://localhost:3000). You’ll be redirected to `/dashboard`; if not logged in, you’ll be sent to `/login`.

4. **Stop when done**

   - Stop the frontend: press **Ctrl+C** in the terminal where `npm run dev` is running.
   - Stop Docker: from the repo root run `docker compose down`.

## Run locally (backend not in Docker)

If you run the API yourself (e.g. `uvicorn` from `backend/` with a local Postgres):

1. Install dependencies: `npm install`
2. Start the API and ensure it’s on port 8000 (or set `NEXT_PUBLIC_API_URL`).
3. Run `npm run dev` and open http://localhost:3000.

## Run with Docker

From the **repository root**, if the stack includes a frontend service:

```bash
docker compose up -d
```

Otherwise run the frontend locally with `npm run dev` and point `NEXT_PUBLIC_API_URL` at your API.

## Pages

- **/login** — Email + password form; POST `/auth/login` with credentials; redirects to `/dashboard` on success.
- **/register** — Email + password form; POST `/auth/register` with credentials; redirects to `/dashboard` on success.
- **/dashboard** — Add targets (URL required, name optional) via form; POST `/targets` with credentials. Table shows each target with status (Up/Down), last checked, and a Delete button; DELETE `/targets/{id}` with credentials. List refreshes after add/delete. Inline errors for bad URL, network errors; 401 redirects to `/login`. Log out via POST `/auth/logout`.

## Build

```bash
npm run build
npm run start
```

Production server runs on port 3000 by default.
