# Testing the Uptime Monitor MVP

Use these steps to verify services, add target, checks, status, and delete behavior. Run from the repository root unless noted.

## 1. Services running

Start the stack:

```bash
docker compose up -d
```

Check that all containers are up:

```bash
docker compose ps
```

You should see `db`, `api`, and `worker` with status `Up`. Optionally:

- **API health:** `curl -s http://localhost:8000/health` → `{"status":"ok"}`
- **Frontend:** From `frontend/` run `npm run dev`, then open http://localhost:3000 and log in or register.

## 2. Add target

**Via frontend (recommended):** Log in at http://localhost:3000, go to Dashboard, use “Add target” with a URL (e.g. `https://example.com`) and optional name. Submit; the table should refresh and show the new row with status “Pending”.

**Via API:** Log in first (e.g. via frontend or `POST /auth/login`), then with the session cookie:

```bash
curl -s -X POST http://localhost:8000/targets \
  -H "Content-Type: application/json" \
  -b "session=YOUR_SESSION_COOKIE" \
  -d '{"url":"https://example.com","name":"Example"}'
```

Expect `201` and JSON with `id`, `url`, `name`, `created_at`. Adding the same URL again (normalized) for the same user should return `409` with a message like “A target with this URL already exists.”

## 3. Checks being written

The worker runs periodically (default every 5 minutes). To see checks sooner, set a shorter interval and restart:

```bash
# In docker-compose.yml set worker environment: CHECK_INTERVAL_SECONDS: "30"
docker compose up -d worker
```

Watch worker logs:

```bash
docker compose logs -f worker
```

You should see lines like `Target <id>: 200 … ms is_up=True`. Then confirm in the DB:

```bash
docker compose exec db psql -U postgres -d uptime -c \
  "SELECT t.url, c.is_up, c.status_code, c.latency_ms, c.checked_at FROM checks c JOIN targets t ON t.id = c.target_id ORDER BY c.checked_at DESC LIMIT 5;"
```

You should see one or more rows per target after the worker has run.

## 4. Latest status accuracy

- **API:** With a valid session cookie, `GET http://localhost:8000/targets/status` returns each target with `id`, `url`, `name`, `created_at`, and `latest_check` (nullable) with `checked_at`, `is_up`, `status_code`, `latency_ms`, `error`. Each target appears once with at most one latest check.
- **Frontend:** Dashboard shows Status (Pending / Up / Down), Last checked, and Latency. After the worker has run, “Pending” should become “Up” or “Down” and latency should appear. Refreshing the page or re-opening the dashboard should show the same data.

## 5. Delete stops future checks

1. Note a target’s `id` (from the dashboard or from `GET /targets` or `GET /targets/status`).
2. Delete it: in the UI use “Delete” for that row, or:
   ```bash
   curl -s -X DELETE http://localhost:8000/targets/TARGET_ID \
     -b "session=YOUR_SESSION_COOKIE"
   ```
   Expect `204 No Content`.
3. Confirm the target is gone: `GET /targets/status` or the dashboard no longer lists it.
4. Confirm checks are gone: the `checks` table should have no rows for that `target_id` (CASCADE deletes them):
   ```bash
   docker compose exec db psql -U postgres -d uptime -c \
     "SELECT COUNT(*) FROM checks WHERE target_id = TARGET_ID;"
   ```
   Should be `0`.
5. Worker logs should no longer mention that target id on the next cycle.

## Apply migrations (if needed)

If you added the `normalized_url` migration (002), run:

```bash
docker compose exec api alembic upgrade head
```

Or start the API so it runs migrations on boot (if your setup does that). Then re-run the tests above.
