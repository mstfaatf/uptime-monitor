# CLAUDE.md

This file gives Claude Code context on the Uptime Monitor project. Read it fully before making
any changes. Keep it updated at the end of every prompt — see "Workflow" below.

## What this is

A personal uptime-tracking web app. Users register, add URLs they care about, and a background
worker checks each one on a schedule and keeps a private history for that user — status,
latency, DNS/TCP/TLS timing breakdown, uptime %, incidents. It is NOT a public status-page
product; there is no page that lists other users' monitored sites. Being rebuilt from a working
local MVP into a deployed, portfolio-grade project for Summer 2027 internship applications
(telecom / banking / infra-adjacent companies specifically), alongside a separate fraud-detection
portfolio project — deliberately different domains, don't blend the two.

## Architecture (target state)

- `frontend/` — Next.js 14 (App Router), TypeScript, Tailwind CSS + shadcn/ui, Recharts.
  Deployed to Vercel.
- `backend/` — FastAPI, async SQLAlchemy, Alembic migrations, slowapi rate limiting,
  WebSocket/SSE endpoint for live push. Deployed to Railway.
- `worker/` — Python, async (httpx.AsyncClient), runs continuously. Checks targets on an
  interval, does DNS/TCP/TLS/TTFB timing breakdown, captures cert expiry, applies
  exponential-backoff-with-jitter before flipping a target's status to down. Deployed to Railway
  as one or more services (see multi-region below). NOT deployable to Vercel — it must run
  continuously, which serverless can't do.
- `db` — PostgreSQL. Docker Compose Postgres for local dev. Neon for production. Same schema,
  same Alembic migrations against both; only `DATABASE_URL` differs by environment.

## Non-negotiable rules

Correctness/security properties already in place or required going forward. Do not regress these.

1. **Ownership enforcement**: every query touching `targets` or `checks` (or any new user-owned
   table) must filter by the authenticated user's `id`. No endpoint may read or mutate another
   user's data. Any new endpoint touching user-owned rows needs a test proving cross-user access
   is denied.
2. **SSRF protection**: block localhost, RFC1918 private ranges, and link-local addresses.
   Validate at target-creation time (fast feedback) AND at check-time in the worker (defends
   against DNS-rebinding — a URL that resolves to a public IP at creation but a private one
   later). Keep both checks; don't replace one with the other.
3. **No secrets in git**: `.env` is never committed with real values. Config values with no safe
   default (`JWT_SECRET`) have no fallback — app must fail to start if unset, never silently run
   with a known-insecure default.
4. **Cookies**: session auth stays HTTP-only cookies, never localStorage. `COOKIE_SECURE=True`
   in every deployed environment.
5. **Multi-region coordination**: once more than one worker instance exists, they must not
   double-check the same target simultaneously or race on writes. Use region-scoped target
   claiming or `SELECT ... FOR UPDATE SKIP LOCKED` — decide and document in an ADR, then enforce
   it in code.
6. **Rate limiting**: login, register, forgot-password, and target-creation endpoints must be
   rate-limited. These are the classic abuse targets.

## Planned feature set (full scope, for reference across phases)

Networking depth: DNS/TCP/TLS/TTFB timing waterfall per check, TLS cert expiry capture +
alerting, async worker with exponential backoff + jitter before marking a target down,
multi-region checks (region-tagged), real-time push of check results via WebSocket/SSE.

Product/analytics: SLA % (24h/7d/30d), incident timeline (grouped consecutive downtime with
start/end/duration), GitHub-style uptime heatmap per target, latency chart + p95 (not just
average), dashboard summary strip (total targets, up/down count, avg latency), compliance
export (CSV/PDF per target, date range), forgot-password flow via Resend, downtime + cert-expiry
alerting via Resend with a cooldown so it doesn't spam.

Frontend pages required: `/` (landing page, value prop, seeded read-only demo account — no
real user data shown publicly), `/about` (builder blurb, stack summary, links), `/login`,
`/register`, `/dashboard` (list view: summary strip, per-target row with status/region/latency/
live indicator, links to detail), `/dashboard/[id]` (detail: timing waterfall, latency chart,
heatmap, incident timeline, export button), `/settings` (password reset, alert preferences).
UI elements needed: live/connected WebSocket indicator, cert-expiry warning badge, region
badges, empty state for zero-target accounts, toast on real-time down/up events.

Ops/portfolio artifacts: `docs/adr/` with 4-5 architecture decision records (JWT-in-cookie vs.
server-side sessions, async worker vs. serverless cron, SSRF check-time vs. creation-time,
multi-region coordination approach), `LOAD_TESTING.md` with real k6/Locust results (req/s, p95
latency, breaking point) run against the deployed instance, GitHub Actions CI running pytest on
every push, rewritten root README (pitch, architecture diagram, live demo link, screenshots).

## Phases

0. Foundation & security — .gitignore/.env fix, remove insecure config defaults, rate limiting,
   SSRF-at-creation, pytest suite. Nothing else gets built until this is done.
1. Worker rewrite + networking depth — async httpx, DNS/TCP/TLS/TTFB breakdown, backoff+jitter,
   cert expiry capture, WebSocket/SSE push. Changes the `checks` schema — must land before
   analytics/UI are built on the new fields.
1.5. Multi-region — second worker instance, REGION tagging, coordination/locking to prevent
   duplicate checks across instances.
2. UI refresh + analytics — Tailwind/shadcn, all new pages listed above, summary strip, latency
   chart, heatmap, incident timeline, SLA %, landing page + demo account, forgot password.
2.5. Alerting + compliance — Resend downtime + cert-expiry alerts with cooldown, CSV/PDF export.
3. Deploy — Neon (DB) + Railway (API + worker) + Vercel (frontend), CORS updated to real domain,
   CI pipeline.
4. Presentation — README rewrite, ADRs, LOAD_TESTING.md against the live deployed instance.

## Workflow

- Schema changes go through Alembic (`backend/alembic/`). Never hand-edit tables in prod.
- Run the backend test suite before considering backend work done: `cd backend && pytest`
- Local dev stack: `docker compose up -d` from repo root. Frontend runs separately:
  `cd frontend && npm run dev`
- Frontend talks to the API via `NEXT_PUBLIC_API_URL` (see `frontend/lib/api.ts`). Never
  hardcode the API URL in components.
- Prompts are numbered per phase (0.1, 0.2, ... 1.1, 1.2, ...). Revisions/additions mid-phase
  get a sub-number (e.g. 2.3.1). The prompt log itself is kept outside this repo by the user —
  do not create or write to any prompt-log file. At the end of every prompt: update this file's
  "Current status" section below, then commit the changes. Do NOT run `git push` — the user
  pushes manually.

## Environment variables

Backend: `DATABASE_URL`, `JWT_SECRET` (required, no default), `JWT_ALGORITHM`, `COOKIE_SECURE`
(True in prod), `COOKIE_SAMESITE`, `RESEND_API_KEY`
Worker: `DATABASE_URL`, `CHECK_INTERVAL_SECONDS`, `HTTP_TIMEOUT_SECONDS`, `HTTP_VERIFY_SSL`,
`REGION`
Frontend: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`

## Current status

Phase 0, prompt 0.2 (fix #1: .gitignore + untrack .env) is complete.
- Root `.gitignore` was empty (0 bytes, tracked since the initial commit) — corrects what
  prompt 0.1's report assumed; that report's quoted content (`node_modules`, `.env*.local`,
  etc.) was actually `frontend/.gitignore`, read under the wrong cwd. Root `.gitignore` now
  ignores `.env`/`.env.*` (with `!.env.example` kept trackable), Python artifacts
  (`__pycache__/`, `*.pyc`, `.venv/`, `*.egg-info/`), and Node artifacts (`node_modules/`,
  `.next/`).
- `.env` removed from git tracking (`git rm --cached`) but left in place locally; it is now
  gitignored so it won't be re-added accidentally.
- `docker-compose.yml`'s hardcoded `JWT_SECRET` (line ~29) and worker env values (lines
  ~38-43) were identified and deliberately left untouched — that's fix #2, next.
- Not touched in this prompt: `config.py`, SSRF logic, rate limiting, tests.

Phase 0, prompt 0.3 (fix #2: remove insecure config defaults) is complete.
- `backend/config.py`: `JWT_SECRET` now has no default — it's a required pydantic-settings
  field, so `Settings()` raises `ValidationError` (app fails to start) if it's unset. No
  hand-rolled check, just the library's normal required-field behavior. Verified in a
  container: missing `JWT_SECRET` raises `pydantic_core.ValidationError` at import time.
- Added `ENVIRONMENT` (`"development"` default / `"production"`). Chose approach (b): a
  `model_validator(mode="after")` forces `COOKIE_SECURE = True` whenever
  `ENVIRONMENT == "production"`, **overriding** any explicit `COOKIE_SECURE=false` rather than
  just defaulting to it — rule 4 in this file says cookies must be secure in every deployed
  environment, so treating it as a hard override (not a soft default) closes the "someone
  forgot/fat-fingered the env var" failure mode. Verified: `ENVIRONMENT=production` →
  `COOKIE_SECURE=True` in a container test. Local dev is unaffected (`ENVIRONMENT=development`
  default → `COOKIE_SECURE=False` as before).
- `docker-compose.yml`: `api`/`worker` services now use `env_file: .env` (repo-root `.env`)
  instead of a hardcoded `JWT_SECRET`; `DATABASE_URL` stays hardcoded in `environment:` per
  service since it must point at the `db` Docker-network hostname, not whatever's in `.env`.
  `environment:` values override `env_file:` values in Compose, so this works as intended.
- `.env.example` rewritten to list every var actually read by the code today (not the full
  future CLAUDE.md list — `RESEND_API_KEY`/`REGION`/etc. aren't implemented yet), with
  `JWT_SECRET` marked required and a one-liner to generate one.
- Found and documented a pre-existing local-dev quirk (not new, just newly load-bearing now
  that `JWT_SECRET` has no default): `backend/config.py`'s `env_file=".env"` resolves relative
  to the process's cwd, and `backend/scripts/run.sh`/`run.ps1` `cd` into `backend/` before
  running uvicorn — so local non-Docker runs need `backend/.env`, which is a **different file**
  from the repo-root `.env` Docker Compose reads. Documented in `backend/README.md` rather than
  changing `config.py`'s env-file resolution logic (out of scope for this prompt).
  `worker/README.md` got a one-line note only — the worker has no required vars, so this
  quirk doesn't block it.
- Populated the local (gitignored, uncommitted) root `.env` with a generated dev `JWT_SECRET`
  and `ENVIRONMENT=development` so the running stack keeps working; rebuilt `api`/`worker` and
  confirmed `docker compose ps` shows both `Up` and `/health` returns `{"status":"ok"}`.
- Not touched in this prompt: SSRF logic, rate limiting, tests.

Phase 0, prompt 0.4 (fix #3: SSRF at creation + redirect bypass) is complete.
- Added `backend/security/ssrf.py` (+ `backend/security/__init__.py`) — a **deliberate
  duplicate** of `worker/ssrf.py`'s blocklist logic (loopback, RFC1918, link-local,
  `localhost`), not a shared package. backend/ and worker/ are separately deployed with
  independent Dockerfiles; a shared installable package for ~50 lines would add real
  deployment complexity (versioning/publishing/syncing two services' dependency on it) for
  little benefit. Do not "clean this up" into a shared import without revisiting that
  tradeoff — kept in sync by hand, noted in both files' docstrings.
- Wired into `POST /targets` (`backend/routers/targets.py`): after `normalize_url()`, before
  the duplicate-check DB query, rejects with 400 and a clear message
  (`"This URL cannot be monitored: <reason>"`) if the URL resolves to a blocked range.
  `worker/ssrf.py`'s check-time validation is untouched — this adds creation-time on top, per
  rule 2 (both are required).
- Fixed the redirect bypass in `worker/checker.py`: `allow_redirects=True` (HEAD/GET) replaced
  with a manual redirect loop (`_follow_with_ssrf_check`), capped at 5 hops, re-running
  `is_url_blocked()` against each hop's resolved `Location` header before following it. A
  blocked hop or exceeding the cap raises `RedirectValidationError`, caught in `check_url()`
  and recorded the same way as an initial SSRF block (`is_up=False`, clear `error` reason,
  same as `worker/main.py`'s existing pre-check). Normal method-per-hop redirects (HEAD→HEAD,
  GET→GET) are preserved; not attempting full RFC-compliant 303-method-switching, which isn't
  needed for a monitoring tool.
- Unplanned but directly necessitated fix: `docker-compose.yml`'s `api` service never needed
  outbound DNS before; the new creation-time check does, and this Windows/Docker-Desktop
  setup's embedded DNS doesn't resolve external hostnames for it (same issue `worker` already
  had `dns: [8.8.8.8, 8.8.4.4]` for). Mirrored that fix onto `api` — without it, creation-time
  SSRF checks would 400 on every URL, including legitimate public ones.
- Verified end-to-end against the running stack: public URL → 201; `localhost`, `10.0.0.5`,
  `169.254.169.254` → 400 with clear reasons; a redirect to `169.254.169.254` (cloud metadata
  IP) is caught by the worker and recorded as `is_up=False` with `"Redirect target blocked: ..."`
  without the blocked address ever being requested; a normal public→public redirect still
  works (`200`, `is_up=True`).
- Not touched in this prompt: rate limiting, tests.

Phase 0, prompt 0.5 (fix #4: rate limiting) is complete.
- Added `slowapi` to `backend/requirements.txt`. New `backend/rate_limit.py` holds a single
  shared `Limiter(key_func=get_remote_address)` instance — kept out of `main.py` so the
  routers can import it without a circular import.
- `backend/main.py`: registered the limiter on `app.state`, added `SlowAPIMiddleware`, and a
  custom `RateLimitExceeded` handler returning `429` with `{"detail": "Too many requests —
  rate limit is <N per period>. Please try again shortly."}` — matches the existing
  `HTTPException` error shape (`detail` key) the frontend already parses, instead of slowapi's
  generic default body.
- Limits applied (all keyed by client IP, all as `@limiter.limit(...)` under the route
  decorator, each endpoint gained a `request: Request` param slowapi needs):
  - `POST /auth/login` — `5/minute` (highest-value brute-force target).
  - `POST /auth/register` — `3/minute` (bounds mass fake-account creation; a touch stricter
    than login since legitimate users register once, not repeatedly).
  - `POST /targets` — `10/minute` (bounds abuse of the SSRF-check/DB-write path while still
    allowing a legitimate user to add several targets in one sitting).
  Used the task's suggested numbers as-is — they matched my own judgment of the tradeoff
  between blocking abuse and not annoying legitimate users.
- Design choice worth flagging: `POST /targets` is keyed by **IP, not by authenticated user**,
  even though the task phrased it as "per user/IP." slowapi's `key_func` only ever sees the
  raw `Request`, before FastAPI dependencies like `get_current_user` run — keying by user would
  mean re-decoding the session cookie a second time inside the key function, duplicating
  `auth/cookies.py` logic for little real gain (an attacker hammering this endpoint from one
  IP is caught either way). Documented in `rate_limit.py`; revisit if per-user keying turns
  out to matter later (e.g. many users legitimately sharing one IP/NAT).
- Flagging per the prompt: slowapi's default storage is **in-memory and per-process**. Fine
  for the current single-instance deployment plan (Phase 3: one Railway API service). If the
  backend is ever horizontally scaled to multiple instances (not currently planned), each
  process enforces its own separate counters, so the *effective* limit multiplies by instance
  count — would need a shared store (Redis, via slowapi's `storage_uri`) at that point. Not
  implemented now — out of scope per the prompt.
- Verified end-to-end against the running stack: 6 rapid `/auth/login` attempts → first 5
  process normally (401 for bad creds), 6th → 429 with the clear message; 4 rapid
  `/auth/register` calls → first 3 succeed, 4th → 429; 11 rapid `POST /targets` calls (one
  authenticated user) → first 10 succeed (201), 11th → 429. Restarted the `api` container
  between tests to reset slowapi's in-memory counters (expected/correct behavior for
  single-instance in-memory storage, not a bug).
- Not touched in this prompt: tests (fix #5, next, will assert these limits).

Next: Phase 0 prompt 0.6 — pytest suite (fix #5), the last item in the Phase 0 checklist.
Update this line, and add brief notes below it, at the end of every prompt so a new chat session
can pick up context immediately without re-reading the whole codebase.
