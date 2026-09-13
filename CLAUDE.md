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

0. Foundation & security (complete) — .gitignore/.env fix, remove insecure config defaults,
   rate limiting, SSRF-at-creation, pytest suite. Nothing else got built until this was done.
1. Worker Rewrite & Network Observability (complete) — async httpx, DNS/TCP/TLS/TTFB breakdown,
   backoff+jitter, cert expiry capture, WebSocket/SSE push. Changed the `checks` schema — landed
   before analytics/UI were built on the new fields, per plan.
2. Multi-region + coordination (next up) — second worker instance, REGION tagging,
   coordination/locking to prevent duplicate checks across instances. **Carries forward one
   known open item from Phase 1**: `get_due_targets` has no row-claiming mechanism at all today,
   so multiple concurrent worker instances could double-check the same due targets — this must
   be fixed before any multi-region check-dispatch logic is built on top of it, not after.
3. UI refresh + analytics — Tailwind/shadcn, all new pages listed above, summary strip, latency
   chart, heatmap, incident timeline, SLA %, landing page + demo account, forgot password.
4. Alerting + compliance export — Resend downtime + cert-expiry alerts with cooldown, CSV/PDF
   export.
5. Deploy — Neon (DB) + Railway (API + worker) + Vercel (frontend), CORS updated to real domain,
   CI pipeline.
6. Presentation / README / ADRs / load testing — README rewrite, ADRs, LOAD_TESTING.md against
   the live deployed instance.

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
  for the current single-instance deployment plan (Phase 5: one Railway API service). If the
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

Phase 0, prompt 0.6 (fix #5: pytest suite) is complete. **Phase 0 is now fully done** — all
six checklist items (gitignore/.env, config defaults, SSRF creation+redirect, rate limiting,
tests) are in place and verified.
- `backend/tests/` (pytest + pytest-asyncio + httpx.AsyncClient against the FastAPI app
  in-process via `ASGITransport`, no real server). 26 tests, all passing:
  - `test_auth.py` — register/login/logout/me roundtrip, duplicate email (400), wrong
    password (401), unknown email (401), unauthenticated `/auth/me` (401).
  - `test_ownership.py` — **the most important file in the suite**: user A cannot list, see
    status of, or delete user B's targets (404, not 403 — indistinguishable from "doesn't
    exist"); anonymous access to every target endpoint is 401. Zero regression coverage for
    this existed before today.
  - `test_targets.py` — trailing-slash normalization collapses to the same target (409 on
    the dupe), uniqueness is per-user not global, delete actually removes the row, invalid
    scheme rejected.
  - `test_ssrf.py` — creation-time blocking (400) for localhost/127.0.0.1/10.x/172.16.x/
    192.168.x/169.254.169.254; a real public URL still succeeds.
  - `test_config.py` — `Settings()` raises `ValidationError` with no `JWT_SECRET` (tests the
    class directly with `_env_file=None` + `monkeypatch.delenv`, since the module-level
    singleton is already-imported by the time tests run); also covers the
    `ENVIRONMENT=production` → `COOKIE_SECURE=True` override from prompt 0.3.
  - `test_rate_limit.py` — login/register/target-creation all confirmed to 429 exactly one
    request past their configured limit.
- **Test database**: a dedicated `<dbname>_test` Postgres database on the same server as
  `DATABASE_URL` (not SQLite) — the schema uses Postgres-specific DDL
  (`postgresql_ops` on `checks.checked_at`) and production runs on Postgres via asyncpg, so
  SQLite would test a different SQL dialect than what ships. `backend/tests/conftest.py`
  creates the test DB if missing and runs the real Alembic migrations against it every
  session (catches model/migration drift, not just a `create_all()` snapshot), then
  truncates all tables before every individual test for isolation. Single command from
  `backend/`: `pip install -r requirements-dev.txt && pytest` — new `requirements-dev.txt`
  (pytest/pytest-asyncio/httpx) is deliberately kept out of the Docker image.
- **Real bug hit and fixed while building this**: pytest-asyncio 1.x's default per-test-
  function event loop is incompatible with `database.py`'s module-level, session-lifetime
  async engine — reusing pooled asyncpg connections across a new loop threw
  `InterfaceError: another operation is in progress` on every test after the first. Fixed
  via `asyncio_default_fixture_loop_scope = session` +
  `asyncio_default_test_loop_scope = session` in `backend/pytest.ini`, giving the whole test
  session one event loop, matching the engine's actual lifetime assumption.
- **Also hit**: several early test URLs used made-up subdomains (`a.example.com`,
  `shared.example.com`) that don't resolve via DNS, so `is_url_blocked()` (called from
  `POST /targets`) correctly rejected them as "Resolution failed" — a self-inflicted false
  SSRF-block, not a real bug. Fixed by varying the **path** on the real `example.com`
  instead of the hostname (DNS only resolves hostnames, so `example.com/a`,
  `example.com/shared`, etc. are all real, resolvable, distinct targets).
- **worker/tests/** (separate suite, own `pytest.ini`/`requirements-dev.txt`) — kept apart
  from `backend/tests/` for the same reason `backend/security/ssrf.py` was duplicated rather
  than shared in prompt 0.4: the worker is an independently deployed service and shouldn't
  need FastAPI/Postgres test infrastructure just to test its own SSRF/redirect logic. 11
  tests, all passing, all hermetic (no DB, no network — `requests.request` is mocked via
  `unittest.mock`, no new runtime dependency):
  - `test_ssrf.py` — same blocked-range coverage as backend's, using IP literals throughout
    so nothing depends on real DNS.
  - `test_checker_redirects.py` — directly exercises the prompt-0.4 redirect fix: a redirect
    to a blocked address (e.g. `169.254.169.254`) is caught and the blocked hop is *never
    requested* (`mock_request.call_count == 1`); a normal public→public redirect still
    resolves; a redirect chain exceeding `MAX_REDIRECTS` fails cleanly instead of looping.
- Minor unrelated cleanup: added `path_separator = os` to `backend/alembic.ini` — silences an
  Alembic deprecation warning that showed up on every test run.
- Verified everything by actually running both suites in Docker (`docker compose run --rm
  api|worker sh -c "pip install -r requirements-dev.txt && pytest"`, matching how CI would
  invoke them) — 26 backend + 11 worker tests, all green, confirmed idempotent on a second
  run against the already-migrated test database.
- Documented in `backend/README.md` and `worker/README.md` under new "Tests" sections.

Phase 0, prompt 0.7 (wrap-up verification) is complete. **Phase 0 is genuinely, verifiably
done** — every checklist item was re-proven against real running containers in this prompt,
not just re-read from prior test output:
- Rebuilt `api`/`worker` images from the committed state and ran the full suites fresh: 37
  tests (26 backend + 11 worker), all passing.
- Did a real `docker compose down`/`up` cycle. Proved the JWT_SECRET fail-fast against an
  *actual container boot* (temporarily stripped it from `.env`, `docker compose up api`
  crashed with the same `ValidationError` the unit test checks, then restored `.env`) — not
  just trusting the pytest coverage.
- End-to-end flow verified live: register → login → CORS preflight/credentialed cookie
  (`Origin: http://localhost:3000`, `HttpOnly`/`SameSite=lax`) → create target → ran the
  worker's actual `check_url`/`insert_check` against it → `/targets/status` shows the result
  exactly as the dashboard renders it. **Caveat**: no browser-automation tool is available in
  this environment, so this verified the exact HTTP contract the frontend uses rather than
  clicking through the actual UI — flagged explicitly, not silently assumed equivalent.
- Manually re-verified (not just re-running old tests): SSRF blocks `127.0.0.1`/`10.5.5.5` at
  creation (400); login rate limit is exactly 5-then-429 with a clean per-process counter;
  two independently-registered users confirmed cross-isolated (`GET /targets`,
  `GET /targets/status`, and `DELETE` on the other's target ID all correctly denied/empty).
- Repo-wide re-audit for anything missed across 0.1–0.6: no tracked secrets, no stray `.env`
  files, no leftover `change-me-in-production`, `.env.example` has only placeholders.
  `docker-compose.yml`'s `POSTGRES_PASSWORD: postgres` reviewed and confirmed fine (local-dev
  only, matches the Postgres image's own default; production uses Neon with its own
  credentials).
- Three **pre-existing, out-of-scope** items from the original 0.1 report remain open (not
  Phase 0 checklist items, don't block moving on): `worker/config.py`'s `HTTP_VERIFY_SSL` is
  still dead code (`checker.py` hardcodes `certifi.where()`), `backend/auth/password.py` has
  a harmless redundant bcrypt-fallback branch, and `SPEC.md` still documents an unimplemented
  `GET /targets/{id}/checks?limit=20` endpoint. Worth a cleanup pass sometime, not urgent.

**Phase 0 complete.** Next: Phase 1 — worker rewrite + networking depth (async httpx, DNS/TCP/
TLS/TTFB breakdown, backoff+jitter, cert expiry capture, WebSocket/SSE push). This changes the
`checks` schema, so plan the Alembic migration and the new columns before touching the worker's
check loop.

Phase 1, prompt 1.1 (familiarization + report) is complete. No application code or new files
were touched — this was read-only review plus a report delivered directly in the conversation
(not saved to a file, per the prompt).
- Confirmed current worker state: fully synchronous (`requests` + `psycopg2`), sequential
  `while True` loop over all targets on one flat `CHECK_INTERVAL_SECONDS` cadence, no
  concurrency, no retry/backoff/jitter beyond the single same-attempt HEAD→GET fallback in
  `checker.py`. SSRF redirect-revalidation loop (`_follow_with_ssrf_check`, Phase 0) is the
  one piece of existing logic that must survive the rewrite unchanged.
- Confirmed current frontend state: **not polling** — `dashboard/page.tsx` fetches
  `/targets/status` exactly once on mount, no interval, no refresh button. Only refetches
  after add/delete actions. This is more primitive than assumed going in; Phase 1's
  WebSocket/SSE work is replacing "no live-ness," not replacing an existing poll.
- Proposed and reviewed (not yet implemented): httpx.AsyncClient (one shared instance,
  semaphore-bounded concurrency) + asyncpg for the worker; `asyncio.to_thread()` around
  `is_url_blocked()`'s blocking `socket.getaddrinfo()` so concurrent async checks don't stall
  the event loop; httpx/httpcore `extensions={"trace": ...}` for TCP/TLS/TTFB phase timing,
  with DNS timing piggybacked on the SSRF resolution call already happening; TLS cert
  (expiry + issuer) read off the same handshake via
  `response.extensions["network_stream"].get_extra_info("ssl_object")` — no second
  connection; new nullable `checks` columns (`dns_ms`, `tcp_ms`, `tls_ms`, `ttfb_ms`,
  `tls_cert_expires_at`, `tls_cert_issuer`) rather than a new table; explicitly deferred
  alert-cooldown state (Phase 4's concern, not this migration's) to avoid designing that
  table blind. Recommended SSE over WebSocket (unidirectional data flow, reuses existing
  cookie auth, browser auto-reconnect) via Postgres LISTEN/NOTIFY filtered server-side by
  `user_id` so ownership rules carry over to the push path.
- Recommended build order: (1) async rewrite, (2) backoff+jitter scheduling (needs a
  `targets` migration for `consecutive_failures`/`next_check_at`), (3) timing breakdown +
  cert expiry together (shared `checks` migration, must land before Phase 3 UI), (4)
  WebSocket/SSE push last, once the pushed payload shape is final.
- Full report with reasoning for each decision was delivered in the conversation, not written
  to a file — reread the conversation history if picking this up cold, or ask for the report
  to be regenerated.

Phase 1, prompt 1.2 (async worker rewrite) is complete.
- `worker/checker.py` and `worker/main.py` rewritten around a single `httpx.AsyncClient`,
  created once in `main()` and reused for the process lifetime (not per-check) — `verify`
  and `timeout` are set once from `settings` at construction instead of being threaded
  through every call.
- `psycopg2` replaced with `asyncpg` (raw queries, no ORM, matching the pattern the backend
  already proves via SQLAlchemy's async engine, just without SQLAlchemy in the worker).
  `worker/config.py`'s `sync_database_url` property renamed to `asyncpg_database_url` — the
  name was about to be actively misleading (it strips the `+asyncpg` SQLAlchemy dialect
  suffix so raw `asyncpg` can parse the DSN; nothing "sync" about it anymore).
- Concurrency: `asyncio.gather` over all targets in a cycle, bounded by
  `asyncio.Semaphore(CHECK_CONCURRENCY)` with **`CHECK_CONCURRENCY = 15`** — middle of the
  10–20 range proposed in the 1.1 report: enough that a cycle over a few dozen targets
  finishes in roughly one round-trip instead of N sequential ones, low enough that the
  worker doesn't itself look like a burst against sites it doesn't control (or against its
  own asyncpg pool). Each concurrent check acquires its own pooled DB connection
  (`pool.acquire()`) rather than sharing one connection across tasks. Scheduling/backoff
  logic in `run_cycle`/`main` is unchanged — still one flat `sleep(CHECK_INTERVAL_SECONDS)`
  between cycles, per this prompt's scope (backoff+jitter is prompt 1.3, needs its own
  `targets` migration).
- SSRF/redirect logic preserved exactly per the 1.1 report: `_follow_with_ssrf_check` now
  does `await client.request(method, url, follow_redirects=False)`, still manually resolving
  each `Location` hop via `urljoin` and re-checking it with `is_url_blocked()` before
  following, same `MAX_REDIRECTS=5` cap and same error-message format. `is_url_blocked()`
  itself is untouched (still sync, still blocking `socket.getaddrinfo()`) — wrapped in
  `asyncio.to_thread()` at both call sites (pre-check in `check_one`, per-redirect-hop in
  `_follow_with_ssrf_check`) so one blocking DNS resolution can't stall every other in-flight
  check under the same semaphore.
- Incidental fix, directly caused by this rewrite (not scope creep): `HTTP_VERIFY_SSL` was
  flagged back in the 0.7 wrap-up as dead code (`checker.py` hardcoded `certifi.where()`
  instead of reading it). The new `httpx.AsyncClient(verify=settings.HTTP_VERIFY_SSL, ...)`
  wires it up for real. `certifi` itself dropped from `worker/requirements.txt` — no longer
  imported directly, and httpx already depends on it internally for its default CA bundle.
- `worker/requirements.txt`: removed `psycopg2-binary`, `requests`, `certifi`; added
  `asyncpg>=0.29.0`, `httpx>=0.27.0`.
- Tests: `worker/tests/test_checker_redirects.py` rewritten for the async interface — mocks
  `client.request` as an `AsyncMock` on a fixture client instead of patching
  `checker.requests.request`; same three cases (blocked-hop-never-fetched, normal chain
  followed, too-many-redirects) still pass. `worker/pytest.ini` gained
  `asyncio_mode = auto`; `worker/requirements-dev.txt` gained `pytest-asyncio`.
  `worker/tests/test_ssrf.py` untouched — `ssrf.py` itself didn't change.
  `worker/README.md` updated in the few places it described the old sync/psycopg2 setup.
- Verified against the real stack, not just unit tests: rebuilt the `worker` image
  (`docker compose build worker`), ran it against the actual dev DB/targets
  (`docker compose up -d db api worker`). Logs show genuinely concurrent, interleaved checks
  across ~23 real targets in one cycle with zero exceptions; confirmed via direct DB query
  that a real 301 redirect (`https://www.github.com` → `github.com/`) resolved correctly to
  `status_code=200, is_up=true` under the new async redirect loop; smoke-tested
  `asyncio.to_thread(is_url_blocked, ...)` directly inside the running container against a
  blocked metadata-IP address to confirm the threading wrapper doesn't change its behavior
  (no existing target in the dev DB is currently SSRF-blocked, since creation-time SSRF
  already screens those out — the mocked redirect-to-blocked-IP unit test remains the
  regression guard for that specific path).
- Not touched in this prompt (explicitly out of scope, per the prompt): backoff/jitter,
  scheduling cadence, `checks` schema, timing breakdown, cert expiry, SSE.

Phase 1, prompt 1.3 (per-target scheduling + backoff-with-jitter) is complete.
- New Alembic migration `003_add_targets_scheduling_columns.py`: adds `next_check_at`
  (`TIMESTAMPTZ NOT NULL DEFAULT now()`, indexed) and `consecutive_failures`
  (`INTEGER NOT NULL DEFAULT 0`) to `targets`. Default `now()` means every existing target is
  immediately due on the first cycle after migrating, same as the old check-everyone
  behavior. `backend/models/target.py`'s `Target` model updated to match.
- **Backoff curve** (`worker/backoff.py`, new module, unit-tested): exponential,
  `base=30s * 2^(failures-1)`, capped at `900s` (15 min), each draw jittered by `±20%`
  (symmetric jitter around the capped value, not "full jitter" — a single failing target
  still retries roughly on schedule rather than occasionally retrying near-instantly, while
  still avoiding multiple targets that started failing together getting stuck retrying in
  perfect lockstep forever). Concretely: 1 failure → ~30s, 2 → ~60s, 3 → ~120s, 4 → ~240s,
  5 → ~480s, 6+ → capped at ~900s. A successful check always resets
  `consecutive_failures = 0` and returns to the normal `CHECK_INTERVAL_SECONDS` cadence.
- `worker/main.py` rewritten around per-target due-scheduling: `get_due_targets()` now
  selects `WHERE next_check_at <= now()` instead of every row. **New design decision beyond
  the literal prompt wording**: decoupled the outer poll loop from
  `CHECK_INTERVAL_SECONDS` — added `SCHEDULER_TICK_SECONDS = 5` as the outer loop's actual
  sleep, since leaving the old 300s flat sleep in place would have quantized every backoff
  retry to 5-minute boundaries regardless of the computed curve, defeating the point of a
  30s-to-900s backoff range. `CHECK_INTERVAL_SECONDS` now means "normal per-target recheck
  cadence on success" only; `SCHEDULER_TICK_SECONDS` means "how often we ask the DB who's
  due." A 5s poll against an indexed `next_check_at` column is trivial at this project's
  scale.
- SSRF-blocked results are treated identically to a real check failure for scheduling
  purposes (increment `consecutive_failures`, apply backoff) — otherwise a permanently
  SSRF-blocked target would get re-resolved every single tick forever.
- **Confirmed**: `is_up=False` is still written to `checks` unconditionally and first, inside
  the same transaction as the scheduling update — backoff only changes `next_check_at`
  metadata on `targets`, never whether or when the historical check row itself gets written.
- **Mid-backoff deletion**: the only mutation the current API supports on an existing target
  is delete (no edit/PATCH endpoint exists yet). A deleted target simply stops appearing in
  `get_due_targets()`'s query — nothing to break there. The one real race is a target deleted
  *while* a check for it is already in flight: the subsequent `INSERT INTO checks` then
  violates the `checks.target_id` foreign key. `check_one()` now wraps its whole body in a
  try/except that logs and swallows any such per-target error, specifically so one vanished
  target can't propagate out of `asyncio.gather()` and cancel every other concurrently
  in-flight check in the same cycle — verified directly by calling `check_one()` in the
  running container against a nonexistent `target_id`: `ForeignKeyViolationError` raised
  and caught exactly as designed, process kept running. (If an edit-URL endpoint is added in
  a later phase, it should probably reset `next_check_at=now()`/`consecutive_failures=0` so
  an edited target is checked promptly instead of waiting out a backoff computed against the
  old URL — flagged for whoever builds that endpoint, not needed now since it doesn't exist.)
- Verified against the real stack: rebuilt `api`+`worker` images, `docker compose up`,
  confirmed migration `002→003` ran cleanly in the `api` container's startup log; watched a
  genuinely failing target's `consecutive_failures`/`next_check_at` in the DB advance
  `1→30s-ish→2→60s-ish` in real time across live polls, confirmed it was *not* re-picked-up
  before its `next_check_at`; confirmed a healthy target's `next_check_at` sits ~300s out
  with `consecutive_failures=0`. Also full test suites: 19 worker tests (8 new in
  `test_backoff.py`) and 26 backend tests, all passing, including against the freshly
  migrated schema.
- Noted, not a bug: worker and api start concurrently in Compose, so the worker briefly
  raced api's migration on this fresh `up` (`"column consecutive_failures does not exist"`
  logged once as `Cycle failed`) — the existing outer-loop try/except caught it and the next
  5s tick succeeded once the migration landed. Self-healing by design, left as is.
- Not touched in this prompt (explicitly out of scope): timing breakdown, cert expiry, SSE.
  Multi-instance locking (`SELECT ... FOR UPDATE SKIP LOCKED`) is still Phase 2's job — a
  second worker instance today would double-check whatever's due, since nothing yet claims a
  row before working it.

Phase 1, prompt 1.4 (DNS/TCP/TLS/TTFB timing breakdown + TLS cert expiry) is complete.
- New Alembic migration `004_add_checks_timing_and_cert_columns.py`: adds nullable `dns_ms`,
  `tcp_ms`, `tls_ms`, `ttfb_ms` (Integer), `tls_cert_expires_at` (`TIMESTAMPTZ`), and
  `tls_cert_issuer` (Text) to `checks`. `backend/models/check.py` updated to match.
  `tls_cert_days_remaining` is deliberately **not** a column — derived at read time in
  `backend/routers/targets.py` (`tls_cert_expires_at - now()`), per the 1.1 report's plan, so
  it can't go stale between checks.
- **Validated the risky assumption from the 1.1 report hands-on before writing any code**:
  spun up throwaway probe scripts inside the running `worker` container (httpx 0.28.1 /
  httpcore 1.0.9) to confirm httpx's `extensions={"trace": ...}` hook actually fires the named
  httpcore phase boundaries (`connection.connect_tcp.*`, `connection.start_tls.*`,
  `http11.send_request_*`, `http11.receive_response_headers.*`) rather than trusting memory of
  an obscure internal API. It does, exactly as hoped — deleted the probe scripts once
  confirmed.
- **New finding, not anticipated in the 1.1 report**: the worker's single long-lived
  `httpx.AsyncClient` (from prompt 1.2) pools/reuses keep-alive connections by default —
  meaning a check that happened to land on a still-warm connection (e.g. rechecking the same
  URL before the server's keep-alive expired) would silently skip the
  `connect_tcp`/`start_tls` trace events entirely, leaving `tcp_ms`/`tls_ms` null on an
  otherwise-successful check. Fixed by constructing the shared client with
  `httpx.Limits(max_keepalive_connections=0)` — every request now opens a fresh connection,
  which is the actually-correct behavior for a monitoring tool measuring real
  connection-establishment cost on every check, not an artifact of whatever the pool had lying
  around. Verified in-container: two consecutive requests to the same host both independently
  fired `connect_tcp`/`start_tls`.
- `worker/checker.py`: `dns_ms` piggybacks on the existing `asyncio.to_thread(is_url_blocked,
  ...)` call (timed, no second lookup) — the up-front check in `check_one` for the original
  URL, or the per-hop check inside `_follow_with_ssrf_check` for a redirect target, whichever
  one validated the URL that was *actually* connected to. `tcp_ms`/`tls_ms` come from the
  trace-event timestamp deltas; `ttfb_ms` is `receive_response_headers.complete` minus
  `send_request_body.complete` (falling back to `send_request_headers.complete` if no body
  event fired) — verified against real trace output that the actual network wait happens
  inside `receive_response_headers`, not in the gap before it, so this is the accurate
  boundary, not just a convenient approximation.
- **Correct-hop guarantee**: `_follow_with_ssrf_check` now returns a `_HopResult` built only
  from the trace events/response of the request that produced the final (non-redirect)
  response — each redirect hop gets its own fresh trace-collection dict, and an intermediate
  hop's timing/cert data is simply discarded when the loop continues past it. Verified live
  against real traffic: `http://github.com/` → 301 → `https://github.com/` correctly reports
  a real `tls_ms` and a Sectigo cert for github.com (the final hop), not null/absent data from
  the plain-HTTP first hop.
- TLS cert capture (`_extract_cert` in `checker.py`): `https://` only (checked via URL scheme
  before touching anything), reads
  `response.extensions["network_stream"].get_extra_info("ssl_object").getpeercert()` off the
  connection already open for that response — no second connection. `notAfter` parsed via
  stdlib `ssl.cert_time_to_seconds()`; issuer formatted as a flat `k=v, k=v` string from the
  RDN-tuple structure `getpeercert()` returns. Wrapped in a broad try/except that fails safe to
  `(None, None)` — this is enrichment, not the check itself, so a malformed/missing cert
  should never fail the whole check.
- `worker/main.py`: `check_one` times the pre-check `is_url_blocked` call for `dns_ms`, passes
  it into `check_url(client, url, dns_ms)`, and threads all six new fields through
  `insert_check`. Verified against the real stack (new targets created via the live API to
  force an immediate check rather than waiting out the normal cadence): a real `https://`
  target showed real `dns_ms`/`tcp_ms`/`tls_ms`/`ttfb_ms` plus a real Let's Encrypt cert and
  correct `tls_cert_days_remaining`; a plain `http://` target that actually completed (404, not
  a connection failure) showed a real `tcp_ms` with `tls_ms`/cert fields correctly null.
- `backend/routers/targets.py`'s `LatestCheckResponse` (returned by `GET /targets/status`, the
  only endpoint the frontend currently reads check data from) now carries all six new fields
  plus the derived `tls_cert_days_remaining`. Negative days-remaining (already expired) is
  exposed as-is, not clamped — Phase 4's alerting decides its own threshold later.
- Explicitly did **not** add any alert-cooldown/"last alert sent" state in this prompt, per
  the 1.1 report's plan — that's its own table in Phase 4, not columns bolted onto `checks`
  now.
- Tests: `worker/tests/test_timing.py` (new) unit-tests `_extract_timings`/`_extract_cert`
  against synthetic trace-event dicts and fake ssl objects, including fail-safe behavior for
  missing/malformed cert data. `worker/tests/test_checker_redirects.py` updated for the new
  `check_url(client, url, dns_ms)` signature and a `resp.extensions = {}` fixture (matching a
  real httpx.Response's shape instead of relying on MagicMock's auto-mock chaining).
  `backend/tests/test_check_timing.py` (new) covers `GET /targets/status`'s exposure of the
  new fields and the derived days-remaining, including the expired-cert (negative) case.
  28 worker tests and 30 backend tests, all passing.
- Not touched in this prompt (explicitly out of scope): SSE/real-time updates. The frontend
  dashboard itself is still Phase 3 work — these fields are exposed via the API now but not
  yet rendered anywhere.

Phase 1, prompt 1.5 (SSE real-time dashboard updates) is complete. **This closes out Phase 1**
— all five planned pieces (async rewrite, backoff scheduling, timing/cert capture, and now
real-time push) are in place and verified.
- New `GET /targets/stream` endpoint (`backend/routers/targets.py`), behind the same
  `get_current_user` cookie-auth dependency as every other route. Returns a `StreamingResponse`
  (`text/event-stream`) that yields `data: {...}\n\n` messages from a per-connection
  `asyncio.Queue`, with a 15s keep-alive comment (`: keep-alive\n\n`) when there's nothing new,
  and checks `request.is_disconnected()` each loop as a second, more active way to notice a
  dead client beyond just letting the generator's `finally` run on cancellation.
- New `backend/realtime.py`: an in-process pub/sub (`user_id -> set of asyncio.Queue`). The
  worker (`worker/main.py`) now runs `SELECT pg_notify('checks_inserted', target_id)` **inside
  the same transaction** as its `insert_check`/`reschedule_target` calls, so a notification
  only ever fires for a check that actually got persisted (Postgres only delivers NOTIFY at
  commit — a rolled-back transaction, e.g. the deleted-mid-check case from 1.3, sends nothing).
  `NOTIFY_CHANNEL = "checks_inserted"` is duplicated by hand between the two services (same
  "separately deployed, kept in sync manually" tradeoff as `worker/ssrf.py` vs
  `backend/security/ssrf.py`).
- **Ownership enforcement for push**: `realtime._handle_notification` resolves the notified
  `target_id` to its owning `Target.user_id` via a real DB query and only publishes to that
  user's queue(s) — a connected client's queue is registered under `current_user.id` (from the
  cookie session) and can structurally never receive another user's event, since nothing ever
  puts another user's payload on it. Verified live with two real concurrently-connected users:
  user B's stream showed only a `: keep-alive`, never user A's target's data, while user A's
  own stream correctly received it.
- **Payload reuse**: extracted `build_target_status_payload()` (and a shared
  `_latest_check_query()` builder) out of `list_targets_status` so both the polled
  `GET /targets/status` and the SSE push build the identical shape from one place — confirmed
  live that a pushed event carries the full `dns_ms`/`tcp_ms`/`tls_ms`/`ttfb_ms`/
  `tls_cert_expires_at`/`tls_cert_issuer`/`tls_cert_days_remaining` set from 1.4, so the
  frontend never needs a follow-up fetch to get the complete picture.
- **Backend-side recovery, confirmed by actually killing the connection**: `realtime.run_listener()`
  holds one long-lived asyncpg LISTEN connection in a loop that reconnects after a fixed 5s
  delay if the connection is ever lost — started as a background task in `main.py`'s new
  `lifespan`, cancelled cleanly at shutdown. Verified against the real stack: found the LISTEN
  connection's backend PID via `pg_stat_activity`, ran `pg_terminate_backend()` on it directly,
  confirmed a fresh LISTEN connection appeared within the reconnect window, and confirmed a
  still-open client SSE stream kept receiving new check-update events afterward without any
  restart on either side. Browser-side reconnect needs no code at all — `EventSource` retries
  automatically on drop, per spec.
- Frontend (`frontend/app/dashboard/page.tsx`, `frontend/lib/api.ts`): minimal, functional
  wiring only, per this prompt's scope (full UI polish is Phase 3) — a new `useEffect` opens
  `new EventSource(.../targets/stream, { withCredentials: true })` once the initial poll has
  confirmed the user is authenticated, merges incoming `check_update` events into the existing
  `items` list by id, and closes the connection on unmount. A small "● live / reconnecting…"
  indicator was added next to the heading (driven by `onopen`/`onerror`) — the only new visible
  UI, intentionally unstyled beyond that. `LatestCheck`'s TS type gained the 1.4 timing/cert
  fields (not rendered anywhere yet, just carried through so the shape matches what's actually
  sent). `API_BASE` exported from `lib/api.ts` so the dashboard can build the stream URL.
- Tests: `backend/tests/test_realtime.py` (new) covers the pub/sub primitives directly
  (publish reaches only the subscribed user, unsubscribe stops delivery and cleans up empty
  entries, multiple connections for one user both receive an update) plus
  `_handle_notification` against the real test DB (resolves the correct owner and full
  payload, ignores a malformed payload, no-ops harmlessly for a since-deleted target).
  `run_listener` itself isn't unit-tested (needs a live LISTEN connection) — covered by the
  manual kill-and-recover verification above instead. 37 backend tests, 28 worker tests, all
  passing. Frontend: `tsc --noEmit` clean and `npm run build` succeeds; no browser-automation
  tool is available in this environment, so the actual dashboard UI wasn't clicked through —
  verified the real HTTP/SSE contract instead (two concurrent curl-based SSE sessions against
  the live stack, as described above), same caveat flagged as far back as the 0.7 wrap-up.

**Phase 1 complete.** Per CLAUDE.md's phase plan, next is Phase 2 (multi-region: second
worker instance, `REGION` tagging, `SELECT ... FOR UPDATE SKIP LOCKED` or region-scoped
claiming so two worker instances can't double-check the same target) — flagged as still-open
in every prompt since 1.2, since today's single-worker `get_due_targets()` has no claiming at
all.

Phase 1, prompt 1.6 (wrap-up verification) is complete. **Phase 1 is genuinely, verifiably
done** — every piece (async rewrite, backoff scheduling, timing breakdown, cert expiry, SSE)
was re-proven this prompt against real network traffic and a real database, not just mocks,
before moving to Phase 2.
- Ran both suites fresh: 70 tests total (37 backend + 33 worker), all passing. Added
  `worker/tests/test_scheduling.py` (5 new tests, mocked-connection/hermetic, consistent with
  the rest of `worker/tests/`) — closed a real gap: nothing previously asserted that
  `insert_check`'s SQL column list and positional-argument list stay in matching order, and
  `get_due_targets`'/`reschedule_target`'s success/failure SQL branches had no direct coverage
  at all (only `backoff.py`'s curve math was unit-tested).
- Concurrency cap: mechanically proven via a throwaway script (60 fake tasks through a real
  `asyncio.Semaphore(CHECK_CONCURRENCY)`) that peak concurrency saturates at exactly 15, never
  above; then confirmed in practice with ~10 real targets created in one burst, all completing
  within a ~0.6s window with visibly interleaved logs.
- Backoff/reset: verified against real, organically-failing targets rather than synthetic
  ones — Wikipedia/npmjs (403, bot-blocked) and Reuters (401) climbed
  `consecutive_failures`/`next_check_at` exactly along the 30s→60s curve in real time; a
  target left failing since an earlier prompt sits correctly capped at ~900s after 7
  failures; healthy targets reset to `consecutive_failures=0` and ~300s cadence on success.
- Redirect/SSRF: re-confirmed `169.254.169.254` still 400s at creation, and a real
  `http://github.com` → 301 → `https://github.com` chain resolved with the final hop's real
  cert/timing (not the plain-HTTP first hop's absence of them).
- Timing/cert: every real check showed populated `dns_ms`/`tcp_ms`/`tls_ms`/`ttfb_ms` (TLS
  fields correctly null only for a plain-HTTP hop); real certs from four different real CAs
  captured correctly across the batch.
- SSE: live push confirmed end-to-end with two real, concurrently-connected authenticated
  users — user B's stream showed only keep-alives while user A's updates (including a
  post-backoff retry) landed exclusively on user A's own stream. Payload carried the full
  timing/cert set on every push.
- Phase 0 regressions: none found. Login (5-then-429) and target-creation (10-then-429) rate
  limits both fired correctly (the latter hit organically mid-burst-test); cross-user delete
  still 404s, non-owner's list stays empty, anonymous access still 401s on `/targets` *and*
  the new `/targets/stream`; `JWT_SECRET` fail-fast re-verified by actually stripping it from
  `.env` and watching the container crash with the same `ValidationError` as in the 0.7
  wrap-up, then recovering cleanly once restored.
- All verification artifacts (test targets, temporary SSE connections, throwaway scripts)
  cleaned up afterward; containers left healthy and stable.
- No outstanding issues to revisit before Phase 2. The one thing Phase 2 must address
  head-on — already flagged in every prompt since 1.2 — is that `get_due_targets` has no
  row-claiming: a second worker instance today would double-check whatever's due.

**Next: Phase 2 — multi-region.** Second worker instance, `REGION` env var tagging, and a
coordination mechanism (`SELECT ... FOR UPDATE SKIP LOCKED` or region-scoped claiming — decide
and document as an ADR per CLAUDE.md rule 5) so two worker instances can't double-check the
same target or race on writes. **Known open item carried forward from Phase 1**:
`get_due_targets` (`worker/main.py`) has no row-claiming mechanism at all today — every worker
instance would independently select and check whatever's currently due, so this must be fixed
as the first piece of Phase 2, before any multi-region check-dispatch logic is layered on top
of it, not after.

Phase 2, prompt 2.1 (familiarization + design proposal) is complete. Read-only — no
application code or schema changes in this prompt; full report delivered directly in the
conversation (not saved to a file), reread the conversation history if picking this up cold.
- Confirmed and traced the known gap precisely: `get_due_targets` has no claiming, so two
  concurrent workers can select the same due target, both fire real HTTP requests against it,
  and race on the `reschedule_target` write (lost-update, not a crash — `checks` has no
  uniqueness constraint so duplicate observation rows are harmless, but duplicate outbound
  traffic to the target and inconsistent final scheduling state are real problems).
- Proposed row-claiming: `SELECT ... FOR UPDATE SKIP LOCKED` plus a new nullable
  `claimed_at` column on the schedule state, claimed-and-released in a short transaction
  (not held for the full HTTP check) so locks aren't tied up for network I/O latency; a stale
  claim (crashed worker) self-heals via a time-based check rather than a heartbeat/lease
  system.
- Proposed multi-region schema: `region` column on `checks`; scheduling state
  (`next_check_at`/`consecutive_failures`/`claimed_at`) moves off `targets` into a new
  per-target-per-region table, since each region's worker should independently track its own
  success/failure history against a target rather than sharing one global clock — this also
  means region-scoping (each worker only queries its own region's rows) and `SKIP LOCKED`
  (for same-region horizontal scaling) are both needed together, not one replacing the other.
  Recommended 2 regions for this portfolio project — enough to exercise the coordination and
  independent-display story, more would just add hosting cost without a new architectural
  lesson.
- Recommended per-region results stay independently tracked and displayed (no single
  collapsed up/down verdict across regions) — this is a personal monitoring tool for the
  target's owner, not a public status page, so hiding which specific region sees a problem
  would destroy exactly the diagnostic signal (and the Phase 1 timing-breakdown investment)
  that makes multi-region checking useful here.
- Flagged (not built): SSE notify payload needs to carry region so the frontend can tell
  which region an incoming `check_update` is for; `TargetStatusResponse.latest_check` needs
  to become per-region (a dict/list, not a single latest check) once regions are independent;
  the dashboard's current full-row-replace reducer would need to merge into a region's slot
  instead. All deferred to Phase 3 per the existing phase plan.
- Recommended build order: row-claiming first (proven against the current single-region
  schema, since it's needed even for two same-region replicas) → `REGION` env var plumbing →
  schema migration (checks.region + per-target-per-region schedule table, replacing the
  `targets` scheduling columns) → region-scoped `get_due_targets` → backend/SSE payload
  changes (+ ADR written at this point, once both halves of the coordination story are
  implemented) → second worker instance actually run concurrently as the integration test
  proving no double-checks/lost updates, mirroring how Phase 1 verified each piece against
  the live stack rather than trusting unit tests alone.
- No code changes, no new files, no migrations in this prompt — report only, pending review
  before Phase 2 implementation begins.

Phase 2, prompt 2.2 (row-claiming) is complete — step 1 of the 2.1 build order. Region config,
`checks.region`, and the per-target-per-region schedule table are explicitly untouched, per
this prompt's scope.
- New Alembic migration `005_add_targets_claimed_at.py`: adds nullable `claimed_at`
  (`TIMESTAMPTZ`) to `targets`. `backend/models/target.py` updated to match (worker-owned
  scheduling field, same as `next_check_at`/`consecutive_failures`).
- `worker/main.py`: `get_due_targets` replaced by `claim_due_targets(conn)`, implementing the
  claim-then-release-then-recheck pattern exactly as proposed in 2.1 — one short transaction
  runs `SELECT ... FOR UPDATE SKIP LOCKED` against due, unclaimed-or-stale-claimed targets,
  stamps `claimed_at = now()` on whatever it selected, and commits immediately. The actual
  HTTP check in `check_one` happens entirely outside any transaction/lock, exactly as planned
  — a row lock is never held for network I/O latency.
- **`CLAIM_TTL_SECONDS = 120`** (the self-healing window): a claim older than 120s is treated
  as abandoned (crashed/killed worker) and becomes claimable again — `claimed_at IS NULL OR
  claimed_at < now() - make_interval(secs => $1)`. Chosen against the worst realistic
  single-check duration: up to `MAX_REDIRECTS` (5) hops each capped at
  `HTTP_TIMEOUT_SECONDS` (10s default) is ~50s worst case; 120s leaves over 2x headroom above
  that (so a genuinely slow-but-alive check is never falsely reclaimed and double-checked)
  while still recovering well within the normal 300s `CHECK_INTERVAL_SECONDS` cadence rather
  than leaving a crashed worker's targets stuck indefinitely.
- `reschedule_target` now clears `claimed_at` back to `NULL` in the same `UPDATE` as the
  success/failure reschedule — the claim's job is done once that write lands. Confirmed
  single-worker behavior is unchanged: a healthy single instance always gets every due target
  back from `claim_due_targets`, just via two quick transactions instead of one bare
  `SELECT` — claiming is a no-op safety net until a second instance actually exists.
- `worker/tests/test_scheduling.py` updated: `_mock_conn()` now mocks `conn.transaction()` as
  an async context manager; new/renamed tests cover the `FOR UPDATE SKIP LOCKED`
  select+stamp SQL, the empty-result no-op case, and that both reschedule branches include
  `claimed_at = NULL`. 34 worker tests (was 33), all passing; 37 backend tests unaffected.
- **Two-worker concurrency verification** (throwaway script run against the real dev DB via
  `docker compose run --rm -v ... worker python ...`, deleted after — not committed, worker
  tests stay hermetic per existing convention): Phase 1 proved the actual mechanism
  deterministically rather than relying on asyncio scheduling luck — one connection opens a
  transaction, runs the claim `SELECT ... FOR UPDATE SKIP LOCKED`, and holds it open
  (uncommitted); a second, fully independent connection running the identical query
  concurrently returned in 0.003s with zero rows (proving `SKIP LOCKED` doesn't block *and*
  every due row was already locked). Phase 2 ran the full claim+check+reschedule pipeline for
  two concurrent "instances" via `asyncio.gather` against synthetic `.invalid`-domain targets
  (deterministic DNS-resolution failure, no live network dependency): claims were disjoint and
  covered every target exactly once, every target got exactly one `checks` row (no double
  actual check), and every target's `consecutive_failures`/`claimed_at` reflected one
  consistent write (no lost-update race). Pre-existing real dev-DB targets were temporarily
  deferred (`next_check_at` pushed out, saved and restored exactly afterward) so they didn't
  also get scooped up and pollute the assertions — verified via direct DB query afterward that
  no synthetic targets remained and all real targets' schedules were restored unchanged.
- Verified against the real stack end-to-end beyond the script: rebuilt `api`/`worker` images,
  confirmed migration `004 → 005` ran cleanly in the `api` container's startup log, and
  confirmed the `worker` container resumed normal per-target checking against real targets
  immediately after the code change with no behavior change visible in the logs (as expected
  for the single-instance no-op case).
- Not touched in this prompt (explicitly out of scope, per the prompt and the 2.1 build
  order): `REGION` env var/config, `checks.region`, the per-target-per-region schedule table,
  region-scoped `get_due_targets`/`claim_due_targets`, any ADR. Per the 2.1 report's build
  order, next is step 2 — `REGION` env var + worker config plumbing — before the bigger
  per-target-per-region schema migration (step 3).

Phase 2, prompt 2.3 (`REGION` env var + worker config plumbing) is complete — step 2 of the
2.1 build order. Config/logging only; no schema changes, no query-logic changes, per this
prompt's scope.
- `worker/config.py`'s `Settings` gained `REGION: str = "local"` — read once at startup the
  same way every other worker setting is (no new pattern). Kept as a defaulted, optional field
  for now per the 2.1 report's own recommendation; flagged in a comment to become required
  (no default) once a real multi-region deployment is actually in view (Phase 5), so a
  misconfigured worker instance can't silently report under the wrong or blank region.
- `worker/main.py`: startup log line now includes `region=%s`; the three existing per-check
  log lines (SSRF-blocked, normal check result, deleted-mid-check exception) now prefix
  `[region=%s]` using `settings.REGION`. This is log-line tagging only — no new column, no
  new function parameter threading region through `check_one`/`insert_check`/etc. — so
  region-aware log greping/tests can be written now, ahead of the schema change that will
  actually persist `region` onto `checks` rows in a later prompt.
- `.env.example` and `worker/README.md` document `REGION` (default `local`, set a distinct
  value like `us-east`/`eu-west` per instance once more than one worker runs).
- Verified against the real stack: rebuilt the `worker` image, restarted the container, and
  confirmed the real startup log line reads `region=local`; forced a target due now via a
  direct DB update and confirmed the resulting check log line reads
  `[region=local] Target 1: 200 279 ms ...`. 34 worker tests and 37 backend tests both still
  pass unchanged (no test behavior depends on log line content).
- Not touched in this prompt (explicitly out of scope, per the prompt and the 2.1 build
  order): `checks.region` column, `targets`/`get_due_targets`/`claim_due_targets` query logic,
  the per-target-per-region schedule table, any ADR. Per the 2.1 report's build order, next is
  step 3 — the schema migration replacing `targets.next_check_at`/`consecutive_failures` with
  a per-target-per-region schedule table and adding `region` to `checks` — the biggest single
  change in Phase 2, planned as its own dedicated prompt.

Phase 2, prompt 2.4 (schema migration: `checks.region` + `target_region_schedule`) is
complete — step 3 of the 2.1 build order, schema-only. **This intentionally leaves the worker
temporarily unable to schedule checks** until the very next prompt (step 4) rewrites its
scheduling queries — see below.
- New Alembic migration `006_add_region_and_target_schedule.py`:
  1. `checks.region` added nullable, backfilled, then set `NOT NULL` (the standard safe
     pattern for a NOT NULL column on a table with existing rows).
  2. New table `target_region_schedule(target_id, region, next_check_at,
     consecutive_failures, claimed_at)` with a composite primary key on `(target_id, region)`
     (doubles as the uniqueness constraint) plus an index on `(region, next_check_at)` for the
     region-scoped due-query step 4 will add.
  3. Data migration seeds one `target_region_schedule` row per existing target, carrying
     `next_check_at`/`consecutive_failures`/`claimed_at` forward **exactly** (not reset to
     "due now" — that would cause a check storm the moment this migration lands).
  4. A hard gate — a PL/pgSQL `DO` block that `RAISE EXCEPTION`s and aborts the whole
     migration transaction if `target_region_schedule`'s row count doesn't match `targets`'
     row count — runs before the old columns are dropped, so a silent seeding bug would fail
     the migration loudly rather than quietly losing a target's schedule.
  5. Only after that gate passes: `next_check_at`/`consecutive_failures`/`claimed_at` (and
     their index) are dropped from `targets`.
- **Seed region value: `"local"`** — matches `worker/config.py`'s `REGION` default added in
  prompt 2.3. Every check this project has ever recorded, and every target's current schedule
  state, genuinely was produced by the single local worker instance, so labeling the
  historical data under the same identity the worker itself already reports is the accurate
  choice, not an arbitrary placeholder.
- Backend models updated to match: `Target` no longer has the three scheduling columns (with
  a comment pointing at their new home); `Check` gained `region` (`String`, not null); new
  `backend/models/target_region_schedule.py` (`TargetRegionSchedule`) added and registered in
  `models/__init__.py` and `alembic/env.py` so the table has ORM/autogenerate parity, even
  though only the worker (via raw asyncpg SQL) reads/writes it today — the backend API doesn't
  query it yet.
- **Explicit, accepted temporary regression** (this is the "stub minimally or note it"
  fork from this prompt's instructions — chose "note it," not stubbing): `worker/main.py` was
  deliberately **not touched** in this prompt (schema-only, rewriting scheduling queries is
  step 4/next prompt). Once this migration lands, `claim_due_targets`'s and
  `reschedule_target`'s queries against `targets.next_check_at`/`consecutive_failures`/
  `claimed_at` fail with a real `asyncpg.exceptions.UndefinedColumnError` on every cycle.
  This does **not** crash the worker process or put the container in a restart loop — `main()`'s
  existing outer-loop `try/except` around `run_cycle()` (already there since Phase 1, the same
  path that already self-heals the worker racing the API's migration on a fresh
  `docker compose up`) logs `"Cycle failed"` and retries every `SCHEDULER_TICK_SECONDS` (5s)
  forever. Verified live: rebuilt and restarted the `worker` container after the migration
  landed, confirmed the container stays `Up` and repeats the same caught
  `UndefinedColumnError` indefinitely rather than crash-looping. **No checks are actually
  performed by the worker from this prompt until the next one lands** — flagging this clearly
  since it's a real (if brief, single-developer-environment) functional gap, not swept under
  the rug.
- `backend/tests/test_check_timing.py`'s raw `INSERT INTO checks` fixture updated to include
  `region` (`"local"`) — a mechanical fixture fix required by the new `NOT NULL` column, not a
  worker/query-logic change. No other test file inserts into `checks` directly.
- **Verified end-to-end against the real dev stack**: migration `005 → 006` ran cleanly;
  confirmed via direct query that all 23 existing targets got exactly one seeded
  `target_region_schedule` row each (`region='local'`) with their prior schedule state carried
  forward unchanged, and all existing `checks` rows backfilled to `region='local'`. **Tested
  the downgrade for real** (`alembic downgrade 005`): `targets` regained its three columns
  with the original values correctly restored from `target_region_schedule`, `checks.region`
  and `target_region_schedule` were dropped — then re-ran `alembic upgrade head` to restore
  the final state before finishing. 37 backend tests pass (conftest reruns the full migration
  chain 001→006 from scratch against the test DB each session, so this also proves the whole
  chain applies cleanly, not just 005→006 incrementally). 34 worker tests pass unchanged
  (hermetic/mocked — they don't touch a real schema, so they can't and don't catch the
  real-DB failure mode described above; that's expected, not a gap in this prompt's own
  verification, which used the real dev DB instead).
- Not touched in this prompt (explicitly out of scope, per the prompt and the 2.1 build
  order): any worker query/scheduling logic, region-scoped `claim_due_targets`, `insert_check`
  supplying `region` (also currently missing it — moot right now since `claim_due_targets`
  already fails first and `insert_check` is never reached, but it will need `region` added
  too once step 4 gets past the claim step), backend API/SSE payload exposure of `region`, any
  ADR. Next per the 2.1 build order: step 4 — rewrite `claim_due_targets`/`reschedule_target`/
  `insert_check` to be region-scoped against `target_region_schedule`, restoring real
  scheduling behavior.

Phase 2, prompt 2.5 (region-scoped `get_due_targets`) is complete — step 4 of the 2.1 build
order. **This restores real worker scheduling**, ending the temporary regression accepted in
2.4. Backend/API/SSE payloads untouched, per this prompt's scope.
- `claim_due_targets(conn, region)` now queries `target_region_schedule` joined to `targets`,
  filtered by `region = $1`, with the same `FOR UPDATE ... SKIP LOCKED` + `claimed_at` stamp
  pattern from prompt 2.2 — but scoped with `FOR UPDATE OF trs SKIP LOCKED` so the lock (and
  skip-on-contention) applies only to the schedule row, not the joined `targets` row (no
  reason to contend with e.g. a concurrent delete on `targets`). Two workers in the *same*
  region still can't double-claim (same mechanism as 2.2, now on the new table); two workers
  in *different* regions never even query the same rows, since each is scoped to its own
  `region` — this is the region-scoping half of the 2.1 report's "both mechanisms needed
  together" design.
- `reschedule_target(conn, target_id, region, is_up, consecutive_failures_before)` now writes
  `next_check_at`/`consecutive_failures`/`claimed_at` back to the matching
  `(target_id, region)` row in `target_region_schedule` instead of `targets`.
- **Real gap found and fixed, exactly as the prompt anticipated**: nothing created a
  `target_region_schedule` row for a target's region — not target creation (`POST /targets`
  only ever inserted into `targets`), and no other code path did it either. Without a fix, a
  target created after this rewrite would simply never be checked (zero schedule rows = never
  "due" in any region), and a brand-new region's first worker would see zero due targets
  against an entire existing target list. Fixed with a new `ensure_schedule_rows(conn,
  region)`, called at the start of every `claim_due_targets` call: an anti-join
  (`targets LEFT JOIN target_region_schedule ... WHERE trs.target_id IS NULL`) backfills one
  row per target missing this region's row, due immediately (`next_check_at = now()`,
  matching the old `targets.next_check_at` server-default behavior for a new target),
  `ON CONFLICT (target_id, region) DO NOTHING` so concurrent same-region workers racing to
  backfill the same gap can't collide. **Deliberately lazy, not at target-creation time**:
  the backend/API has no concept of "which regions exist" (`REGION` is a worker-only env var,
  never written anywhere the API could read), so the worker — the only thing that actually
  knows its own region — is the right place to self-register interest in any target it
  hasn't seen yet.
- `insert_check` gained a required `region` parameter (now that `claim_due_targets` works
  again, `check_one` actually reaches `insert_check`, so `checks.region NOT NULL` — added
  schema-only in 2.4 — needed a real value supplied here for the first time). Confirmed
  unconditional: `insert_check` still runs before `reschedule_target` in the same
  transaction, so `is_up=False` is recorded immediately regardless of backoff/claim state —
  backoff/claiming affects only *when* the next check happens, never *whether* this one gets
  honestly recorded.
- `check_one`/`run_cycle` thread `region` (read once from `settings.REGION` in `run_cycle`)
  through to `claim_due_targets`, `insert_check`, `reschedule_target`, and the existing
  per-check log lines (now using the threaded value instead of re-reading `settings.REGION`
  directly, for the small logical improvement of logging the region a check actually ran
  under rather than a second independent read of global config).
- `worker/tests/test_scheduling.py` updated for every new signature/SQL shape, plus a new
  test asserting `ensure_schedule_rows`'s backfill runs before the claim SELECT. 35 worker
  tests (was 34), all passing; 37 backend tests unaffected (no backend code touched).
- **Verified end-to-end against the real dev stack**: rebuilt and restarted the `worker`
  container — it immediately resumed real checking (confirmed via logs showing
  `[region=local]`-tagged results and via direct query showing new `checks` rows with
  `region='local'` and `target_region_schedule` rows advancing/`claimed_at` clearing
  correctly), ending the 2.4-accepted regression. **Explicitly tested the gap-and-fix**:
  inserted a target directly (simulating `POST /targets`, which creates no schedule row) —
  confirmed it had zero `target_region_schedule` rows immediately after creation, then
  confirmed the very next worker tick backfilled a `local` row for it and checked it (a real
  `checks` row appeared, tagged `region='local'`). **Explicitly tested the brand-new-region
  case** with a throwaway script (deleted after, not committed): called
  `claim_due_targets(conn, "us-east-verify")` — a region with zero pre-existing schedule
  rows — against the real dev DB's 23 existing targets; confirmed it backfilled and claimed
  all 23, and confirmed the `local` region's own schedule rows were byte-for-byte unchanged
  by the other region's activity (proving actual region isolation, not just isolation by
  construction). Cleaned up all test data (`us-east-verify` rows, the directly-inserted test
  target) afterward — verified via query that only `local` region rows remain (23, matching
  the real target count).
- Not touched in this prompt (explicitly out of scope, per the prompt): `backend/routers/
  targets.py`, `backend/realtime.py`, any SSE/API payload exposure of `region`, any ADR. Per
  the 2.1 report's build order, next is step 5 — backend/SSE payload changes to expose
  `region` (the dashboard data model implications flagged back in the 2.1 report), at which
  point an ADR documenting the SKIP LOCKED + region-scoping decision should also be written
  per CLAUDE.md rule 5.

Phase 2, prompt 2.6 (backend/API + SSE region-awareness) is complete — step 5 of the 2.1
build order, and **the last piece of Phase 2's backend/worker work**. Frontend dashboard
changes remain explicitly out of scope (Phase 3), per the 2.1 report.
- **API shape chosen**: `TargetStatusResponse.latest_check: LatestCheckResponse | None` →
  `latest_checks: dict[str, LatestCheckResponse]`, keyed by region. A target with no checks
  yet in any region now reports `{}` rather than `null` — a target is never dropped from the
  response just because one (or every) region lacks data yet. **No derived "overall status"
  field was added**, per the 2.1 report's explicit recommendation: collapsing multiple
  regions into one boolean would hide exactly the per-region signal multi-region checking
  exists to show; a future summary (if ever needed) should say "X of N regions reporting
  down" explicitly, never a silent boolean.
- `backend/routers/targets.py`: `_latest_check_query` replaced by
  `_latest_checks_per_region_query`, using a `ROW_NUMBER() OVER (PARTITION BY target_id,
  region ORDER BY checked_at DESC)` subquery outer-joined to `targets`, returning one row per
  `(target, region)` that has data (plus one `(target, None)` row for a target with none at
  all). New `_group_checks_by_target` collapses those rows into `{target_id: Target}` /
  `{target_id: {region: Check}}` — shared by both `GET /targets/status` and realtime's
  single-target lookup, same "one place decides the shape" principle as before.
  `build_target_status_payload` now takes a `checks_by_region` dict instead of a single
  `Check | None` and returns the new `latest_checks` shape.
- **pg_notify payload**: `worker/main.py` now sends `"{target_id}:{region}"` (was bare
  `target_id`) — documented in both `worker/main.py`'s `NOTIFY_CHANNEL` comment and
  `backend/realtime.py`'s module docstring as the exact wire format, kept in sync by hand
  (same tradeoff as the SSRF-blocklist duplication). `realtime._handle_notification` parses
  it (`partition(":")`, warns and no-ops on a missing region or non-numeric id — same
  fail-safe style as the old bare-id parsing) and rebuilds the **complete** per-region
  payload for that target (every region's latest check, not just the one that changed) via
  `_latest_checks_per_region_query`/`_group_checks_by_target` — chosen deliberately over
  shipping a partial single-region delta, so the existing "one shape, poll and push can never
  drift apart" invariant from Phase 1 keeps holding without new merge logic anywhere. The
  parsed `region` is still carried in the published event's top level (`{"type":
  "check_update", "region": ..., "target": {...}}`) purely to say which region's check
  triggered this event, for whatever the Phase 3 frontend wants to do with that (e.g.
  highlighting) — it is not used to scope what data comes back.
- **Confirmed timing/cert fields still flow through per region**: `_check_to_response_dict`
  (renamed from the old inline block) builds the full `LatestCheckResponse` shape — including
  `dns_ms`/`tcp_ms`/`tls_ms`/`ttfb_ms`/cert fields/derived `tls_cert_days_remaining` — for
  each region's check independently, so the frontend never needs a follow-up fetch no matter
  how many regions a target has.
- Tests updated: `backend/tests/test_check_timing.py`'s assertions moved from
  `latest_check` to `latest_checks["local"]`; `backend/tests/test_realtime.py`'s
  notification tests updated for the `"{target_id}:{region}"` payload format (including a new
  test for a payload with a colon but a non-numeric id, alongside the existing
  missing-colon case) and the `latest_checks == {}` empty-state assertion. 38 backend tests
  (was 37), all passing; 35 worker tests unaffected (no worker test asserts the exact
  `pg_notify` payload string — that path is covered by live verification instead, below).
- **Verified end-to-end against the real dev stack**, not just the test suite: registered two
  real users via the live API, created a real target for user A, confirmed
  `GET /targets/status` returns the new `latest_checks: {"local": {...full timing/cert
  data...}}` shape; opened two real concurrent SSE connections (one per user) via `curl -N`,
  forced a recheck of user A's target directly in the DB, and confirmed user A's stream
  received a `{"type": "check_update", "region": "local", "target": {...}}` event with the
  complete per-region payload while user B's stream received only a keep-alive — **per-user
  isolation (the Phase 0/1 rule) holds exactly as before under the new region-aware payload**.
  All verification users/targets/checks cleaned up afterward.
- Not touched in this prompt (explicitly out of scope, per the prompt): any frontend/dashboard
  code (`frontend/app/dashboard/page.tsx` still expects the old `latest_check` shape and will
  need updating in Phase 3 — flagged, not silently left broken: this is a backend-only prompt
  and the frontend wasn't running against this response shape as part of this prompt's
  verification), any ADR.

Phase 2, prompt 2.7 (second-region integration test + ADR) is complete — step 6 of the 2.1
build order, the last piece. **Phase 2 (multi-region + coordination) is now fully complete**,
verified against real concurrent worker processes, not just unit tests or mocked scripts.
- **`docs/adr/001-multi-region-coordination.md`** — the first ADR in this repo (CLAUDE.md's
  planned `docs/adr/` batch of 4-5 is otherwise still a Phase 6 deliverable; this one was
  written now because CLAUDE.md rule 5 explicitly requires it once more than one worker
  instance exists, and both halves of the design — `SKIP LOCKED`/`claimed_at` claiming and
  per-target-per-region scheduling/independent display — are now implemented and provable).
  Documents the claiming design, the scheduling-state-shape decision, and the
  independent-per-region-display decision together, each with alternatives considered and
  rejected (bare SELECT / advisory locks / a separate leases table for claiming; shared
  per-target state / a JSON blob column for scheduling shape; "down if down anywhere" /
  "down only if down everywhere" for display) and why, plus consequences including the
  `target_region_schedule` row-count tradeoff (targets × regions) and the lazy-backfill
  tradeoff from 2.5.
- `docker-compose.yml` gained a second worker service, **`worker-eu-west`** (`REGION:
  eu-west`), identical to the existing `worker` service (which now sets `REGION: local`
  explicitly, matching its long-standing implicit default — no behavior change) in every
  other respect — same image, same DB, same env. Documented in `worker/README.md`.
- **Verified end-to-end against real concurrently-running Docker processes** (not scripts or
  mocks):
  - Started `worker` (`local`) and `worker-eu-west` (`eu-west`) together against the existing
    23 real dev targets. `worker-eu-west` immediately self-healed via `ensure_schedule_rows`
    (from 2.5) — backfilled and began independently scheduling all 23 targets under
    `eu-west` — confirmed via query that `target_region_schedule` ended with exactly 23 rows
    per region, and that `local`'s existing rows were untouched by the new region's activity.
  - **Re-verified the same-region no-double-check guarantee with two real processes**, a
    stronger proof than 2.2's mocked/scripted version: ran a second, genuinely independent
    worker process also on `REGION=local` alongside the existing one, then repeatedly forced
    all `local` targets due to create real contention. Both processes won claims across the
    burst (confirming real, not one-sided, contention) with zero overlapping target IDs at
    any point. Directly queried `checks` for the minimum time gap between any two consecutive
    checks of the same `(target_id, region)` during the burst: **~3.85 seconds** — consistent
    with two distinct due-cycles roughly a tick apart, never the sub-second/near-simultaneous
    gap a genuine double-claim would produce. `target_region_schedule.claimed_at` was `NULL`
    for every row afterward — no stuck claims from the extra process.
  - **Verified divergent per-region results are stored and retrieved as genuinely independent
    data, not merged**, via the real running API (not a direct DB read): created a fresh test
    target, let both regions check it organically (both agreed, as expected — both containers
    hit the same real internet from the same host), then inserted one deliberately divergent
    newer check (`local` reachable, `eu-west` not) to isolate the storage/retrieval guarantee
    from real network variance. `GET /targets/status`, called as the target's real
    authenticated owner, returned both regions' `latest_checks` entries independently and
    correctly — `eu-west.is_up=false` alongside `local.is_up=true` in the same response, with
    no aggregate field anywhere collapsing them.
  - All test artifacts (the extra `worker-local2` container, the divergence-test user/target/
    checks) cleaned up afterward; confirmed via query that only the expected 23×2 real
    schedule rows remain, all unclaimed.
  - 38 backend + 35 worker tests still pass (no test code changed this prompt — this was a
    live-infrastructure and documentation prompt, per its own scope).
- Not touched in this prompt (explicitly out of scope, confirmed via API/logs/scripts only,
  never the dashboard UI, per the prompt): any frontend code.

Phase 2, prompt 2.8 (wrap-up + full regression verification) is complete. **Phase 2 is now
fully verified, not just individually implemented** — every piece was re-proven together
against real concurrent processes and real traffic in this pass, including the two scenarios
flagged as previously untested (orphaned-claim self-heal, precise same-region no-double-check).
- **Coverage gaps closed**: added `test_ensure_schedule_rows_new_rows_are_due_immediately` and
  an anti-join assertion (`LEFT JOIN target_region_schedule trs` / `WHERE trs.target_id IS
  NULL`) on the existing backfill test; strengthened the claim-query test to assert the exact
  self-heal clause text (`trs.claimed_at IS NULL OR trs.claimed_at < now() - make_interval(...)`)
  instead of a loose substring check that wouldn't have caught the OR-staleness half being
  dropped. Worker suite: 36 tests (was 35). Backend suite unchanged at 38 (no backend code
  touched this prompt). **74 total**, up from 65 at the end of Phase 1.
- **Live end-to-end two-region run**: forced all 46 schedule rows (23 targets × 2 regions) due
  at once — 23 checks per region completed within ~1.1-1.2s (confirms real concurrency under
  the Phase 1 `CHECK_CONCURRENCY=15` cap, not sequential execution). Confirmed per-region
  backoff independence on a real persistently-failing target (`consecutive_failures` 6 in
  `eu-west` vs 40 in `local`, both correctly capped-and-jittered around 900s) and per-region
  reset-on-success. Confirmed the Phase 0 redirect+SSRF path (`www.github.com` → `github.com`,
  real cert on the final hop) and Phase 1 timing/cert capture are unchanged and populate
  correctly per region. Re-confirmed divergent per-region data via the live authenticated API
  (one region `is_up=true`, the other `is_up=false` for the same target, both intact).
- **Orphaned-claim self-heal, verified live for the first time this phase**: stamped a fresh
  `claimed_at` on a real schedule row and confirmed it was left untouched across several real
  ticks; aged it to 130s old (past the 120s TTL) and confirmed the very next tick reclaimed
  and successfully checked it, clearing `claimed_at` and rescheduling normally. Previously this
  was only proven via mocked tests and a deterministic lock-hold script (2.2) that tested "two
  simultaneous claimants" but not "a claim goes stale and is later reclaimed."
- **Same-region no-double-check, verified more rigorously than 2.7**: ran a genuine second real
  `local`-region worker process alongside the original (not a throwaway script this time),
  forced repeated contention — both processes won claims across the burst (real contention,
  not one-sided), zero overlapping target IDs at any point. Precisely queried the minimum time
  gap between any two checks of the same `(target_id, region)`: **~3.85 seconds**, consistent
  with separate due-cycles roughly a tick apart, never the sub-second gap an actual double-claim
  would produce.
- **SSE/dashboard resilience to the new payload shape**: `tsc --noEmit` and `npm run build`
  both clean. Since no browser-automation tool exists in this environment (flagged
  consistently since the 0.7 wrap-up), captured a real SSE event stream and replayed the
  frontend's exact reducer/render logic (from `frontend/app/dashboard/page.tsx`) against it in
  Node — confirmed no exception is thrown, no event is dropped, and rendering safely degrades
  to "Pending"/"—" (since `latest_check` no longer exists on the new `latest_checks` shape)
  rather than crashing. Real UI verification remains Phase 3's job.
- **Phase 0/1 regression check — no regressions found**: cross-user ownership (empty lists,
  404 not 403 on cross-user delete, 401 on anonymous access to `/targets` *and*
  `/targets/stream`), rate limiting (login 5-then-429, register 3-then-429, target-creation
  10-then-429, all exact), `JWT_SECRET` fail-fast (stripped from `.env`, real container boot
  crashed with the same `ValidationError` as every prior wrap-up, restored and recovered
  cleanly), and SSE per-user filtering under the new region-aware payload (re-confirmed with
  two fresh users) all still hold exactly as before.
- **ADR corrected against actual shipped code** (`docs/adr/001-multi-region-coordination.md`):
  added the `FOR UPDATE OF trs SKIP LOCKED` join-scoping detail (the ADR previously described
  a bare `FOR UPDATE SKIP LOCKED`, omitting that the claim query joins to `targets` and scopes
  the lock to only the schedule-table side); added the two new live-verification results above
  (precise ~3.85s min-gap measurement, orphaned-claim self-heal) to the Decision/Consequences
  sections as now-proven facts rather than only-designed-and-assumed ones. Everything else in
  the ADR checked out accurate against the current code.
- All test data (regression-check users/targets, SSE capture target, divergence-test target,
  the extra `worker-local2` process) cleaned up afterward; confirmed via query that only the
  real 23 targets × 2 regions (46 schedule rows, all unclaimed) remain.

**Phase 2 is genuinely, fully complete and verified.** Row-claiming, region config,
per-region scheduling schema, region-scoped scheduling queries, region-aware API/SSE
payloads, a running second-region worker instance, and an accurate coordination ADR are all
in place, individually and end-to-end proven against real infrastructure. **Next: Phase 3 —
UI refresh + analytics** (Tailwind/shadcn, all new pages, summary strip, latency chart,
heatmap, incident timeline, SLA %, landing page + demo account, forgot password) per
CLAUDE.md's phase plan. The dashboard's current TypeScript types
(`frontend/app/dashboard/page.tsx`) still expect the old single `latest_check` shape and will
need updating to `latest_checks: Record<string, LatestCheck>` as part of that work — confirmed
in this prompt that the mismatch degrades safely (no crash, no dropped events) rather than
breaking, but it still needs real UI work, not just safety.

Phase 3, prompt 3.1 (familiarization + design system implementation plan) is complete.
Read-only — no application code or new files, per this prompt's scope. Full report delivered
directly in the conversation (not saved to a file); reread the conversation history if picking
this up cold.
- Confirmed current frontend state precisely: zero Tailwind/shadcn adoption (no config, no
  dependency, no `components/` dir) — one hand-rolled `globals.css` with hardcoded hex, every
  route a self-contained file. Confirmed the exact Phase 2 degradation mechanism:
  `dashboard/page.tsx`'s `TargetStatusRow` still types the pre-2.6 single `latest_check` shape,
  so `row.latest_check` is `undefined` against the real `latest_checks: dict[str, ...]` API
  response — every target always renders "Pending"/"—" today, not a crash but zero real
  per-region treatment. Also confirmed `consecutive_failures`/backoff state is worker-only
  (`target_region_schedule`, raw asyncpg) and not exposed through the API at all today.
- Design tokens: recommended CSS custom properties (plain hex, not shadcn's default HSL-triplet
  convention, since the locked palette is exact hex) in `globals.css`, consumed by
  `tailwind.config.ts` — written before `shadcn init` so its scaffolded defaults (8px radius,
  wrong palette) never need tearing out.
- Signal icon (`components/signal-light.tsx`): custom inline SVG, three-dot stack, "flip"
  implemented as an opacity transition on always-present fixed-color circles (not a fill
  color-swap) specifically to avoid a hue cross-fade, per the locked motion spec. Speedometer
  gauge (`components/latency-gauge.tsx`): custom inline SVG (arc + rotated needle), not
  Recharts — no native gauge chart type exists there.
- Degraded/amber proposal: is_up=false → down (no change); is_up=true with latency_ms over a
  threshold (proposed 800ms, shared with the gauge's amber zone) or tls_cert_days_remaining
  ≤14 → degraded — both buildable today with zero backend change. Flagged, not built: a
  stronger backoff-based degraded trigger (mid-retry, debouncing a single blip before going
  red) would need `consecutive_failures` added to the API response — a real but contained
  backend change, deferred as optional.
- Charting: Recharts (`type="linear"`, not the smoothed default) for the latency chart per
  CLAUDE.md's existing stack choice; heatmap hand-rolled as a CSS grid of square divs rather
  than a calendar-heatmap library, since those default to soft rounded cells and fighting that
  default costs more than hand-rolling.
- Proposed build order: 3.2 design-system foundation (tokens, fonts, Tailwind/shadcn install) →
  3.3 bespoke primitives built in isolation (signal light, gauge) → 3.4 auth/static pages →
  3.5 dashboard list rewrite (fixes the confirmed `latest_checks` bug, region badges, summary
  strip) → 3.6 target detail page (waterfall, chart, heatmap, incident timeline) → 3.7
  `/settings` → 3.8 motion/polish pass → 3.9 verification. No code changes made pending review
  of this plan.

Phase 3, prompt 3.2 (design system foundation: tokens + tooling) is complete. Tokens and
tooling only, per this prompt's scope — no `SignalLight`/`LatencyGauge`, no page redesign.
- Installed Tailwind CSS v3 (not v4): the current `shadcn` CLI (v4.21.0) defaults to Tailwind
  v4's CSS-native theming (no `tailwind.config.ts`, `@theme` blocks instead), which conflicts
  with this prompt's explicit instruction to override the palette/radius in
  `tailwind.config.ts`. Used `shadcn@2.10.0` instead — the last line compatible with Tailwind
  v3's JS-config workflow — via `npx shadcn@2.10.0 init -y -d -b neutral --css-variables`.
  Flagging the version pin here since it's a real, deliberate deviation from "just run
  `shadcn init`" and future component adds (`npx shadcn add <component>`) need the same
  `@2.10.0` pin or they'll hit the same v3/v4 mismatch.
- `app/globals.css`: the ten locked tokens (`--bg-base`, `--bg-surface`,
  `--bg-surface-raised`, `--border`, `--text-primary`, `--text-secondary`, `--signal-up`,
  `--signal-warning`, `--signal-down`, `--signal-pending`) plus `--radius-sm`/`--radius` are
  now the only hex literals anywhere in the frontend (verified via a full-tree grep before
  committing). shadcn's semantic CSS slots (`--background`, `--foreground`, `--card`,
  `--popover`, `--primary`, `--secondary`, `--muted`, `--accent`, `--destructive`, `--input`,
  `--ring`) are kept — future `shadcn add` components depend on those exact utility classes
  existing — but every one is aliased onto the locked tokens (`var(--bg-base)` etc.), not left
  at shadcn's generated oklch neutral scale. No brand/CTA accent color exists in the locked
  palette, so `--primary` deliberately stays monochrome (near-white on near-black) rather than
  inventing one — flagged for reconsideration in 3.4 once real buttons get built. Dropped
  shadcn's generated `--chart-*`/`--sidebar-*` slots and the light/dark (`.dark` class) split
  entirely — this app is one permanent dark theme, no toggle planned, so keeping unused
  duplicate tokens would violate the project's own anti-premature-abstraction rule.
- `tailwind.config.ts`: colors reference the CSS vars directly (`var(--signal-up)`, not
  `hsl(var(--signal-up))`) since the tokens are already exact hex, not HSL triplets — matches
  the 3.1 report's reasoning. `borderRadius.DEFAULT/sm/md/lg` all resolve to `var(--radius)`
  (4px) or `var(--radius-sm)` (2px) — confirmed via the compiled build CSS that no `0.5rem`/
  `8px` (shadcn's default) or `oklch(...)` survives anywhere in the output.
  `postcss.config.js` had to be rewritten from `tailwindcss init`'s generated ESM
  `export default` form to plain CommonJS `module.exports` — the ESM form broke `next/font`
  with "must export a `plugins` key" under Next 14's webpack config loader.
- `app/layout.tsx`: IBM Plex Sans (weights 400/500/600) and IBM Plex Mono (400/500) wired via
  `next/font/google`, exposed as `--font-sans`/`--font-mono` on `<html>`, consumed by
  `tailwind.config.ts`'s `fontFamily`. Verified in the compiled output: both fonts are
  self-hosted `@font-face` declarations (no runtime Google Fonts request) and the classes land
  on `<html>` in a real rendered page.
- Retired `globals.css`'s two rules now fully superseded by Tailwind's preflight
  (`* { box-sizing: border-box }`, `input, button { font: inherit }`) — genuinely dead, zero
  behavior change. Did **not** delete the other hand-rolled component classes (`.form-group`,
  `.btn`, `.btn-danger`, `.status-*`, table styles, `.add-target-form`, `.error-message`/
  `.success-message`) — every current page's JSX still references those exact classNames and
  no page gets touched until 3.4/3.5, so deleting them now would break rendering. Instead,
  retokenized every hardcoded hex value inside them (mapped to the closest-matching locked
  token) and replaced ad hoc hover-darken hex values with `filter: brightness(0.85)` on the
  existing token, so no invented colors were added. `dashboard/page.tsx`'s two inline-style
  hex literals (`:234-239`'s live-indicator dot, `:312`'s URL-subtitle text) were updated to
  `var(--signal-up)`/`var(--signal-pending)` and `var(--text-secondary)` respectively — the one
  explicitly-scoped exception to "don't touch pages" this prompt, since leaving known-dead hex
  in place was explicitly called out as unacceptable.
- **Degraded-state threshold contract, now locked for 3.3/3.5 to build against**:
  `latency_ms > 800` OR `tls_cert_days_remaining <= 14` (when non-null) → degraded, exactly as
  proposed in 3.1. Not implemented yet (no page touched this prompt) — this is the frozen
  number contract, not code. The `consecutive_failures`/backoff-based degraded trigger remains
  explicitly deferred/flagged, not built, per this prompt's scope.
- Verified end-to-end: `tsc --noEmit` clean, `next build` succeeds (all 4 routes), and a real
  dev-server request to `/login` on a scratch port confirmed the dark palette/fonts actually
  apply in rendered HTML (not just present in source) — grepped the compiled CSS output
  directly for zero remaining `oklch(`/`hsl(var`/`0.5rem`/`8px` and confirmed all ten locked
  hex tokens plus both radius values are present.
- Not touched in this prompt (explicitly out of scope, per the prompt): `SignalLight`,
  `LatencyGauge`, any page redesign, the `consecutive_failures` backend field. Next per the
  3.1 build order: prompt 3.3 — build the two bespoke primitives in isolation before wiring
  them into real pages.

Phase 3, prompt 3.3 (bespoke primitives: SignalLight + LatencyGauge) is complete. Built in
isolation on a scratch route, per this prompt's scope — no real page touched.
- `components/signal-light.tsx`: one inline SVG housing (rounded-rect, `rx=3` in a 24×68
  viewBox scaling to the instrument-panel radius at every size) containing three
  always-present circles at fixed hex fills (red/amber/green). The "hot" dot is expressed via
  `opacity` (1 vs. 0.22), never a fill swap — `up→bottom`, `degraded→middle`, `down→top`,
  `pending→none`. Props: `state`, `size` (`sm`/`md`/`lg`, one shared geometry scaled via the
  SVG's own `width`/`height`, not redrawn per size), `showLabel`, `className`. Labels use the
  locked microcopy exactly: up→"Reporting up", degraded→"Degraded", down→"No signal",
  pending→"Pending".
- `components/latency-gauge.tsx`: custom SVG, 270° arc (135°→405° in SVG's y-down angle
  convention, opening at the bottom) built from three `<path>` zone segments
  (`stroke-linecap="butt"`, sharp ends) plus a polygon needle inside a `<g>` rotated via
  `transform: rotate(...)` around the arc's center. Props: `value`, `goodMs=200`,
  `warnMs=800`, `maxMs=2000` — matching the thresholds locked in 3.2 exactly. Needle rest
  position (value=0 or null) sits at the arc's start (135°, lower-left); rotation increases
  monotonically to 270° at `maxMs`, so there's no wraparound case to worry about. Numeric
  readout below the arc in mono, colored by which zone the value falls in.
- Motion, implemented via two small `globals.css` rules (`.signal-dot`, `.gauge-needle`) each
  wrapped in `@media (prefers-reduced-motion: no-preference)` so no transition exists at all
  unless the OS allows motion — collapses to instant otherwise by construction, not by an
  explicit override. `.signal-dot` transitions `opacity` only (180ms ease-out) — confirmed by
  design and by a before/after screenshot pair that the flip never interpolates between two
  fill colors. `.gauge-needle` transitions `transform` (350ms ease-out) — the one deliberate
  smooth-motion exception, per the locked spec.
- Scratch route: `app/dev/components/page.tsx` — a static grid of every `SignalLight`
  state×size combination plus the `showLabel` variants, a static row of `LatencyGauge` across
  8 values spanning its full range (0 through 2000ms plus null), a size-comparison row, and
  two small live demos (a 1.8s state-cycle timer, a 500ms/250ms-step sweep timer) specifically
  so the CSS transitions actually fire during verification rather than only proving each end
  state renders. **Not linked from anywhere in the app; not deleted yet** — per the prompt,
  kept through 3.5/3.6 as a visual reference. Flagging clearly: **this route must be deleted
  in the Phase 3 wrap-up/verification prompt (3.9)** before Phase 3 is considered done.
- Verified with real screenshots, not just code review — installed Playwright
  (`devDependencies`) and found Chromium/Firefox/WebKit already cached locally, so no slow
  download was needed. Screenshotted the scratch route twice, ~1.6s apart: confirmed all four
  signal states render correctly at all three sizes, the `showLabel` microcopy matches exactly,
  the live flip demo visibly moved from "Reporting up" to "Degraded" between the two captures
  (dot relocated, opacity mechanism confirmed working live not just in source), and the live
  sweep demo advanced from 0ms to 750ms with the needle correctly repositioned into the amber
  zone and the numeric label correctly colored amber (800ms boundary: `value <= warnMs` holds
  at exactly `warnMs`, confirmed both by reading the code and by the rendered color at a
  nearby value). Additionally emulated `prefers-reduced-motion: reduce` via Playwright and
  read the computed `transitionDuration` directly: 0.18s/0.35s normally, 0s under reduced
  motion — the media-query approach genuinely works, not just presumed from the CSS source.
  Screenshots sent to the user directly; verification scripts were scratch files outside the
  repo (not committed).
- Self-critique against the 3.1 avoid-list: no Inter/gradient, no uniform soft-shadow card
  grid (no cards at all here), no all-caps eyebrow labels, no arrow appended to a button/link
  (the page has neither; the "→" in a section heading denotes a numeric range, 0→2000ms, not
  the flagged link-affordance pattern), no middle-dot-joined meta text, no numbered markers,
  no single-word headline color accent. One minor, deliberate observation: the signal
  housing's rounded-rect (bg-surface-raised on the page's bg-base) is a subtle tonal step
  rather than a high-contrast outline — intentional (instrument panel, not bright chrome) but
  worth a second look once it's sitting in a real dashboard row in 3.5, not just on a plain
  dark scratch page.
- Not touched in this prompt (explicitly out of scope, per the prompt): dashboard, detail
  view, auth pages, landing/about pages. Next per the 3.1 build order: prompt 3.4 — auth and
  static pages.

Phase 3, prompt 3.4 (auth + static pages: `/login`, `/register`, `/`, `/about`) is complete.
Dashboard, detail view, and settings untouched, per this prompt's scope.
- **Asked and settled before building**: the landing page omits any "demo account" mention
  entirely (CLAUDE.md's feature list calls for a seeded read-only demo account, but no backend
  support exists for it — seeding, read-only enforcement — and building that wasn't this
  prompt's scope). User chose "omit for now" over a disabled placeholder or building it for
  real; revisit once the backend work actually exists.
- Added shadcn `button`, `input`, `label`, `card` primitives (`components/ui/`). **Found and
  fixed a real gap in 3.2's "no shadcn default survives" claim**: `Card` uses `rounded-xl`,
  a Tailwind radius keyword 3.2 never overrode (only `sm`/`md`/`lg` were touched, since no
  component using `xl` existed yet) — would have silently rendered at Tailwind's default
  0.75rem/12px. Fixed by extending `tailwind.config.ts`'s `borderRadius` to cap `xl`/`2xl`/
  `3xl` at `var(--radius)` too, so no future shadcn component can reintroduce a >4px radius
  no matter which keyword it reaches for. Also stripped shadcn's default `shadow`/`shadow-sm`
  classes from `Button`/`Input`/`Card` — a soft drop shadow wasn't in the locked spec at all,
  and the avoid-list flags exactly this look; depth now comes from the border + tonal surface
  steps only. Verified via the compiled build CSS: only `var(--radius)`/`var(--radius-sm)`
  appear as `border-radius` values anywhere in the output.
- `components/auth-form.tsx`: extracted the shared email/password form shell out of
  `/login`/`/register` (per 3.1's finding — they were near-identical hand-rolled forms). Owns
  field markup and local field state; each page still owns its own API call, error, and
  loading state, since that's real per-page behavior, not visual duplication. No form
  library pulled in (no react-hook-form/zod) — plain `useState`, matching the prompt's "don't
  over-engineer a form library into this."
- `components/site-header.tsx`: shared header for the four public/auth pages only (a
  `SignalLight` "up" + wordmark as the logo/home link, "About"/"Log in" nav) — deliberately
  **not** added to `app/layout.tsx`, so the dashboard's own separate header stays untouched
  until 3.5.
- **Landing page concept** (stated before building, per the prompt): the hero pairs a large
  lit `SignalLight` and a sample `LatencyGauge` reading — real product components, not
  illustration — beside plain copy about the network-level detail each check captures.
  `components/hero-panel.tsx` holds this (a small client component so the page's one
  motion moment — the hero's `SignalLight` starting `pending` and powering on to `up` ~500ms
  after mount — lives in one place; reuses `SignalLight`'s existing opacity transition, no new
  animation code). The sample timing breakdown (DNS/TCP/TLS/TTFB) is laid out as a small grid
  with a labeled "Illustrative reading" caption, not a middle-dot-joined string (the avoid-list
  explicitly flags that pattern) and not presented as real/live data. Three benefit blocks
  below the hero (network-layer detail, independent multi-region results, private-by-default)
  are plain text columns behind a single border-top divider, not a card grid — each describes
  real, already-built functionality, nothing invented. Footer is one GitHub link.
- **Caught and fixed a factual-accuracy issue while drafting `/about`**: initial copy claimed
  the stack is "deployed on Vercel, Railway, and Neon" — false today, since deployment is
  Phase 5 and hasn't happened. Corrected to describe the stack without asserting a live
  deployment status that doesn't exist yet.
- **Polish fix found via screenshot, not caught by code review**: the hero's `items-center`
  row alignment centered the (shorter) copy column against the (taller) panel, leaving the
  headline oddly low and a large gap before the benefits divider. Changed to
  `md:items-start` — confirmed via a before/after screenshot comparison.
- Verified with real screenshots (Playwright, scratch scripts outside the repo, not
  committed): all four pages plus a 400px-wide mobile capture of the landing page — responsive
  stacking, side gutters, and button sizing all held up. Considered but did not change the
  shadcn default button height (36px) against the frontend-design skill's 44px mockup
  hit-target guidance — treated that guidance as scoped to generated mobile mockups, not a
  hard rule for a desktop-oriented web app, and 36-40px buttons are standard across comparable
  professional tools (GitHub, Linear, Vercel). Flagging the call rather than silently making
  it. `tsc --noEmit` and `next build` both clean throughout.
- Self-critique against the 3.1 avoid-list: no Inter/gradient, no uniform soft-shadow card
  grid, no all-caps eyebrow labels, no arrow appended to button/link text, no middle-dot-joined
  meta text anywhere (including the hero's timing sample, deliberately grid-laid-out instead),
  no numbered markers on the non-sequential benefit list, no single-word headline color accent.
- Not touched in this prompt (explicitly out of scope, per the prompt): dashboard, detail
  view, settings. The `/dev/components` scratch route from 3.3 is still present and still
  needs deleting before the Phase 3 wrap-up prompt. Next per the 3.1 build order: prompt 3.5 —
  dashboard list view rewrite (fixes the confirmed `latest_checks` bug, region badges, summary
  strip with `SignalLight`/`LatencyGauge` wired to real data).

Phase 3, prompt 3.5 (dashboard list view rewrite) is complete. **This prompt fixed the
pre-2.6 data-shape bug flagged in every status note since Phase 2's wrap-up, in addition to
the redesign** — `/dashboard` was never actually broken-looking (it silently degraded to
"Pending" everywhere), so the bug was invisible without deliberately checking real per-region
data, which this prompt did. Detail view, settings, and the auth/static pages untouched.
- **The bugfix**: `TargetStatusRow.latest_check: LatestCheck | null` → `latest_checks:
  Record<string, LatestCheck>`, matching `backend/routers/targets.py`'s real response shape
  since prompt 2.6. New `deriveState()` classifies each region independently (no check yet →
  pending; `is_up: false` → down; `is_up: true` with `latency_ms > 800` or
  `tls_cert_days_remaining <= 14` → degraded, using the exact 3.2-locked thresholds via a new
  shared `lib/thresholds.ts` — also wired into `LatencyGauge`'s default props, closing a real
  drift risk where the gauge and the dashboard could otherwise have hardcoded the same "800"
  independently and diverged later). The SSE merge logic itself needed no fix — replacing the
  whole row by id was already correct once the types matched the real payload; the type
  mismatch was the entire bug.
- **Verified the fix against real data, not synthetic props**: the app's Docker stack was
  already running with real `local` and `eu-west` workers. Registered a throwaway
  verification user via the live API, created two real targets — one plain `https://
  example.com` (real `up` in both regions) and one deliberately 404ing URL (real `down` in
  both regions, `is_up=false` from an actual HTTP response, not a mock) — and directly
  mutated one check row's `latency_ms` to 950 to also exercise the `degraded` path with real
  backend data flowing through the real API response shape. Loaded `/dashboard` as that user
  via Playwright with an injected session cookie against the project's own running dev server
  on port 3000 (a scratch port was tried first and rejected by the backend's CORS allowlist,
  which is correctly locked to `localhost:3000` per Phase 0 — did not loosen it for
  convenience, used the already-running server instead). Confirmed every row shows real,
  distinct per-region status instead of "Pending" everywhere — see screenshots sent to the
  user. All verification targets and the cookie jar were deleted afterward; the throwaway
  user account was left in place (harmless, matches this project's existing precedent for
  verification users from earlier phases).
- **Verified the SSE live-flip with an airtight before/after**: from within the same
  Playwright script (never calling `page.reload()`), captured a baseline screenshot, then
  forced a real recheck via a direct DB update (`next_check_at = now()`), waited 8s, and
  captured a second screenshot from the same still-open tab. Latencies, timestamps, and the
  recalculated average-latency gauge all changed in place with no reload — real proof the SSE
  → state update → re-render → `SignalLight` opacity transition chain works end to end, not
  just plausible from reading the code.
- Summary strip: total target count (plain number) + four `SignalLight`+count chips
  (up/degraded/down/pending, counted per-region per the Phase 2 design — never collapsed to
  one status per target) + a `LatencyGauge` showing the mean `latency_ms` across every region
  with a reading. Confirmed against real data: 4 region-entries averaging to the gauge's
  displayed value and matching its own zone coloring.
- Empty state: reuses `SignalLight state="pending"` (the existing vocabulary, not a new
  icon) inside a dashed border with plain copy — verified by literally deleting both test
  targets and re-screenshotting.
- Motion: one load-in sequence (rows reveal top-to-bottom, 90ms apart, `pending` until their
  turn) that runs once after initial load and never re-triggers on later SSE updates or
  add/delete (deliberately keyed only to `loading`, not `items`); skips straight to fully
  revealed under `prefers-reduced-motion: reduce`. No per-row hover effects, no scroll
  triggers.
- **Retired the last of the pre-Tailwind hand-rolled CSS**: dashboard was the only remaining
  page still using `.form-group`/`.btn`/`.status-*`/`table`/`.dashboard-actions`/
  `.btn-danger`/`.add-target-form`/`.error-message`/`.success-message` — confirmed via grep
  that nothing in `app/` or `components/` references any of them any more, then deleted the
  whole block from `globals.css`. This also closed a latent hazard the block left behind:
  `button[type="submit"] { background: ... }` was a bare element+attribute selector that
  would have kept matching every shadcn `<Button type="submit">` (including dashboard's own
  "Add target" button) indefinitely, not just the old hand-rolled buttons it was written for.
  Only the still-load-bearing `a`/`a:hover` global link rule remains outside the token/base
  layers.
- Self-critique against the 3.1 avoid-list: clean — no Inter/gradient, no all-caps eyebrow
  labels, no arrow-appended button/link text, no middle-dot-joined meta text, no numbered
  markers, no single-word headline accent. The target rows are visually uniform bordered
  boxes, which could superficially resemble the "identical card grid" tell — but they're a
  genuine list of comparable data rows (not decorative content forced into cards) and carry
  no soft drop shadow, so this reads as an intentional data-list treatment, not the avoided
  pattern.
- `tsc --noEmit` and `next build` both clean throughout, including after the CSS cleanup.
- Not touched in this prompt (explicitly out of scope, per the prompt): detail view,
  settings, auth/static pages. The `/dev/components` scratch route from 3.3 **still needs
  deleting** before the Phase 3 wrap-up prompt — not yet due. Next per the 3.1 build order:
  prompt 3.6 — target detail page (timing waterfall, latency chart, heatmap, incident
  timeline, cert-expiry badge, export button stub).

Phase 3, prompt 3.6 (target detail page, `/dashboard/[id]`) is complete. List view, settings,
and auth/static pages untouched, per this prompt's scope.
- **Real, unplanned backend addition, needed before any of this could use real data**: no
  endpoint existed to fetch a single target or its check history (`SPEC.md` flagged this gap
  as far back as the Phase 0 wrap-up). Added `GET /targets/{id}` (reuses the existing
  `_latest_checks_per_region_query`/`build_target_status_payload` helpers from prompt 2.6 —
  same shape as one row of `/targets/status`) and `GET /targets/{id}/checks?region=&limit=`
  (ordered oldest-first, `region` required — never "every region mixed together," matching
  the page's own no-collapsed-aggregate rule). Both 404 — not 403 — for a target that doesn't
  exist or isn't owned by the caller, same pattern as `DELETE`. 8 new/extended backend tests
  (ownership cases in `test_ownership.py`, shape/behavior in new `test_target_detail.py`) — 46
  backend tests total, all passing. Caught and fixed my own copy-paste bug in a new ownership
  test (wrong test-user email pasted from the neighboring test) via the actual test failure,
  not by re-reading the code.
- **Timing waterfall design approach** (stated before building, per the prompt): rather than
  inventing four new brand colors for DNS/TCP/TLS/TTFB, `components/timing-waterfall.tsx` uses
  ONE token (`--text-primary`) at four fixed opacity steps (0.9/0.7/0.5/0.3) to distinguish
  phases proportionally — stays entirely inside the locked palette, with a 1px `--bg-base` seam
  between segments for a sharp (not blurred/rounded) boundary. A phase the check never reached
  (null, not 0) is omitted from the bar entirely rather than rendered as a zero-width sliver.
- `components/uptime-heatmap.tsx`: hand-rolled CSS grid (not a library, per the 3.1 reasoning),
  day-bucketed over a 90-day window, each cell colored by that day's worst state (down > amber
  > up > no-data using `--signal-pending` as the fourth muted tone, exactly as specified).
  Deliberate simplification flagged, not hidden: cells lay out in plain chronological
  (row-major) order rather than true Sunday-Saturday calendar alignment — real calendar
  alignment adds real complexity for no visible benefit on what is, in this project's own dev
  data, a history of at most a couple of weeks.
- `components/latency-chart.tsx` (Recharts): `<Line type="linear">` explicit (not the
  smoothed `"monotone"` default most Recharts examples use), solid `<CartesianGrid>` (no
  `strokeDasharray`) for the graph-paper feel, p95 computed client-side from the fetched
  history and rendered as a dashed `<ReferenceLine>`.
- `components/incident-timeline.tsx`: scans the ordered check history for runs of consecutive
  `is_up=false`, converts each run into a start/end/duration entry (`end: null` = still
  ongoing). Rendered as a real `<ol>` with number badges — the one place on this page (and in
  the whole design system so far) a numbered marker is used, since this is a genuine
  chronological sequence, not a feature list dressed up as one.
- **SLA% and the no-collapsed-aggregate rule**: the header shows one SLA%-plus-`SignalLight`
  block **per region**, each computed from that region's own fetched check history — not one
  combined number for the target. This meant fetching every region's check history up front
  (in parallel, `Promise.all`) rather than only the selected tab's region, so each region's SLA
  can be computed independently regardless of which region's deeper analytics (chart/heatmap/
  waterfall/timeline/cert panel) happen to be selected below.
- Region tabs pick which region's chart/heatmap/waterfall/timeline/cert panel is shown; the
  export button is a genuinely disabled shadcn `Button` (`Export (coming soon)`, no handler,
  tooltip explaining CSV/PDF export lands in Phase 4) — visually present, not wired.
- **Verified against ~10 days of real seeded history, not a single flat data point**: created a
  fresh verification target on the live dev stack, let it get one real check in each region,
  then seeded ~47 additional realistic rows directly via SQL for the `local` region (a healthy
  baseline every 6h, two isolated slow/degraded checks on different days, and one real 3-check,
  45-minute down-then-recover incident) — the same direct-SQL verification technique this
  project has used since Phase 2. Screenshotted both regions: `eu-west` (sparse, 1 real check,
  100% SLA) and `local` (the rich seeded history, 93.6% SLA) rendering **independently** —
  confirmed by literally switching the region tab and re-screenshotting, not assumed from
  reading the code. The chart showed the two real latency spikes and a correctly-positioned
  p95 line; the heatmap showed a real mix of green/amber/red/muted days; the incident timeline
  computed the exact real 45-minute window from the seeded down/up timestamps, not a
  hardcoded example.
- **Found and fixed a real responsive bug via the mobile screenshot, not code review**: the
  latency-chart section's flex container used `items-start`, which (in the column layout the
  `flex-col` default uses below the `md` breakpoint) meant the chart's wrapper never received a
  real width, so Recharts' `ResponsiveContainer` rendered nothing — the gauge showed, the chart
  was silently just gone. Fixed with `items-stretch md:items-start`; re-screenshotted mobile to
  confirm the chart now renders.
- **Caused and fixed a real regression to the user's own running dev server**: the production
  `next build` verification step's `rm -rf .next` was run twice this prompt while the user's
  separate long-running `npm run dev` process (port 3000) was still up, corrupting its webpack
  runtime state (`Cannot find module './682.js'`) both times. Fixed both times by restarting
  that dev server process (confirmed healthy afterward) — flagging this plainly since it's a
  real disruption I caused to state outside this session's own sandbox, not a silent recovery.
- All verification data cleaned up afterward (target deleted, scratch scripts and SQL removed,
  cookie jar deleted); confirmed via the live API that the verification user has zero targets
  remaining. Stack confirmed healthy (`docker compose ps`) before finishing.
- Self-critique against the 3.1 avoid-list: clean, with two deliberate judgment calls flagged
  rather than silently made — the "← Back to dashboard" link uses a **leading** arrow (a
  wayfinding convention indicating direction of navigation), and the incident timeline's
  "start → end" notation is a literal range separator in a data readout, not a button/link;
  neither is the specific "decorative trailing arrow on CTA text" pattern the avoid-list
  targets. No Inter/gradient, no all-caps eyebrow labels, no middle-dot-joined meta text, no
  numbered markers anywhere except the one earned place, no single-word headline accent.
- **A known gap, not fixed here**: the list view (`app/dashboard/page.tsx`, out of scope this
  prompt) has no link to `/dashboard/[id]` yet — there's no way to reach the detail page
  except by typing its URL. Flagging clearly for whichever prompt touches the list view next
  (3.8 polish or 3.9 wrap-up) to close.
- `tsc --noEmit` and `next build` both clean. Backend: 46 tests passing (`api` image rebuilt
  and the running container recreated from it, so the live dev stack serves the new endpoints,
  not just the test suite).
- Not touched in this prompt (explicitly out of scope, per the prompt): list view, settings,
  auth/static pages — beyond the known-gap note above, nothing in `app/dashboard/page.tsx`
  was edited. Next per the 3.1 build order: prompt 3.7 — `/settings` (password-reset and
  alert-preference UI stubs, ahead of Phase 4's real Resend wiring).

Phase 3, prompt 3.7 (`/settings`) is complete. No other page touched; no alerting/email
logic built (that's still entirely Phase 4).
- **Asked and settled before building**: the prompt's wording ("wired to whatever
  password-change endpoint already exists from earlier phases") assumed one existed — it
  didn't (`backend/routers/auth.py` had only register/login/logout/me). Asked whether to
  build a real minimal endpoint now or stub the form disabled; user chose to build it for
  real, reasoning that unlike alert emails (needs Phase 4's Resend integration) or CSV export
  (Phase 4, file generation), password change is small, self-contained, and has no external
  dependency — much closer to the alert-preferences case, which the prompt already explicitly
  authorized building minimal backend support for.
- **Backend additions** (migration `007_add_users_alert_preferences.py`): two plain boolean
  columns on `users` (`alert_on_downtime`, `alert_on_cert_expiry`, both default `true`) rather
  than a separate preferences table — there are only two of them and they're global per-user,
  not per-target, so a whole extra table would be premature. `POST /auth/change-password`
  (verify current password via the existing `verify_password`, rehash, update; 401 on a wrong
  current password — same shape as `/auth/login`'s failure, not a distinct error type, so it
  can't be used to probe how close a guess was; rate-limited 5/minute, matching login, even
  though CLAUDE.md's rule 6 doesn't name this endpoint specifically — same abuse shape) and
  `PATCH /auth/preferences` (partial update — only fields present in the request body change).
  `UserResponse` (shared by register/login/me) now includes both preference fields via
  `UserResponse.model_validate(user)`, replacing the three call sites that previously
  hand-listed `id`/`email` and would otherwise have silently omitted the new fields. 8 new
  backend tests (roundtrip password change + old-password-now-rejected, wrong-current-password
  rejected with the target user confirmed unchanged, auth-required on both new endpoints,
  partial-preference-update semantics, new-user defaults, the rate-limit boundary) — 53
  backend tests total, all passing. `api` image rebuilt and the running container recreated
  from it so the live stack actually serves the new endpoints, not just the test suite.
- Frontend: alert toggles use shadcn's `Switch` (added fresh, drop-shadow stripped like every
  other primitive so far — same reasoning as 3.4/3.6). Toggling is optimistic (flips
  immediately, reverts with an inline error if the `PATCH` fails) rather than waiting on the
  network round-trip first. The change-password form adds a client-side "confirm new
  password" field (not required by the prompt, small effort, meaningfully better UX) checked
  before the request is even sent.
- Microcopy is deliberately honest about scope: "Sending itself isn't wired up yet — these
  toggles just save your preference for when it is," directly under the Alert preferences
  heading, so nothing implies working email delivery that doesn't exist.
- **Verified against the live stack with real requests, not mocked state**: registered a
  throwaway user, confirmed fresh defaults (`alert_on_downtime`/`alert_on_cert_expiry` both
  `true`) via the real register response, then drove the actual page with Playwright — flipped
  the downtime-alerts switch (real `PATCH`) and ran the full password-change form (real
  `POST`). Confirmed server-side, not just from the UI's own success message: the old password
  now gets `401` on `/auth/login`, the new one gets `200`, and the toggled preference persisted
  in the same response. Mobile layout confirmed responsive (one minor, non-blocking cosmetic
  note: the header's "← Back to dashboard" link can wrap awkwardly at narrow widths — inherited
  unchanged from the same header pattern in 3.6's detail page, not a regression introduced
  here; worth a look in a future polish pass, not fixed now).
- **Root-caused a recurring dev-server-corruption issue properly this time**: 3.6's wrap-up
  attributed the port-3000 dev server breakage to `rm -rf .next` specifically. This prompt
  proved that diagnosis incomplete — running a plain `npm run build` with **no** prior `rm -rf`
  still 404'd the live dev server's static chunks, because `next build` and `next dev` both
  write to the same `.next` directory; any production build while the dev server is running
  against that directory corrupts its manifest, regardless of whether it's cleaned first.
  Restarted the dev server (confirmed healthy after) — flagging the corrected root cause
  explicitly so a future prompt doesn't re-diagnose it from scratch: **don't run `next build`
  at all while the user's own dev server is live on port 3000**, or budget for a restart every
  time one does.
- Self-critique against the 3.1 avoid-list: clean. No Inter/gradient, no uniform soft-shadow
  cards (two genuine content sections, not decorative filler), no all-caps eyebrow labels, no
  middle-dot-joined meta text, no numbered markers (correctly absent — nothing on this page is
  a genuine sequence), no single-word headline accent. The header's leading "←" is the same
  wayfinding pattern already reasoned about in 3.6, not the avoided trailing-CTA-arrow tell.
- **A known gap, not fixed here**: nothing links to `/settings` from any other page yet (same
  situation as the dashboard → detail-page link gap flagged in 3.6). Flagging for 3.8/3.9.
- Verification user and scratch scripts cleaned up afterward (no target data was created this
  prompt, so nothing to delete there); confirmed stack healthy via `docker compose ps` before
  finishing.
- Not touched in this prompt (explicitly out of scope, per the prompt): list view, detail
  view, auth/static pages, any alerting/email-sending logic. Next per the 3.1 build order:
  prompt 3.8 — motion/polish pass (the one orchestrated dashboard load-in already exists from
  3.5; this prompt is about auditing hover states, `prefers-reduced-motion` coverage across
  every custom component, and toast wiring for real-time events) — and it's a natural point to
  also close the two known navigation gaps (dashboard → detail page, and a settings link)
  flagged in 3.6 and here.

Phase 3, prompt 3.8 (motion, accessibility, and contrast polish pass) is complete. Audited and
hardened everything built across 3.3–3.7; no backend changes this prompt.
- Removed the 3.3 scratch route (`app/dev/`) — confirmed gone from the build output (9 routes,
  was 10).
- **Motion audit**: grepped the whole frontend for `transition`/`animate-`/`hover:`/
  `IntersectionObserver` — found only the two intentional custom transitions (`.signal-dot`,
  `.gauge-needle`), standard shadcn interactive-state transitions on real controls (button/
  input/switch/link hover+focus color changes — functional feedback, not decorative), and the
  dashboard's one load-in sequence. **Confirmed the dashboard load-in is the only multi-element
  entrance animation** — the landing hero's power-on (3.4) is single-element and reuses the
  same `.signal-dot` mechanism, not a second animation system. No accidental scroll-triggered
  fades or per-card hover effects found anywhere; nothing to remove.
- **Toast notifications**: added `sonner` (shadcn's `Toaster` wrapper simplified to drop its
  `next-themes` dependency — this app is permanently dark, decided in 3.2, so a runtime theme
  hook was dead weight; hardcoded `theme="dark"` instead, and stripped `shadow-lg` like every
  other primitive). Dashboard now tracks each region's last-known state in a ref, seeded once
  after initial load, and compares against it on every SSE push — a toast fires only on a
  genuine transition (never on the first reading for a region, which is "new data" not "a
  change"). Exported `SIGNAL_STATE_LABELS` from `signal-light.tsx` so the toast text reuses the
  exact locked microcopy instead of a re-typed copy. Verified live against the real backend:
  drove a genuine up→down transition via a direct DB mutation + `pg_notify` (matching the wire
  format from `backend/realtime.py`) into an already-connected SSE session and confirmed the
  toast fired with correct text/color and the row/summary strip updated in the same push.
- **`prefers-reduced-motion` audit, confirmed component by component**: `SignalLight`/
  `LatencyGauge` — re-confirmed via the same Playwright `emulateMedia` technique from 3.3
  (0.18s/0.35s → 0s). Dashboard load-in — explicitly checks `matchMedia` and jumps straight to
  fully-revealed. Toasts — read `sonner`'s own bundled CSS directly (`node_modules/sonner/dist/
  styles.css`) and confirmed it ships `@media (prefers-reduced-motion) { ... transition: none
  !important; animation: none !important; }` on the toast element itself, so no extra wiring
  was needed. Landing hero's power-on inherits `SignalLight`'s handling automatically (it's a
  prop change, not separate animation code). All five collapse to an instant/static state
  without hiding any information, not just skipping to a blank state.
- **Contrast audit, computed exactly (WCAG relative-luminance formula, not eyeballed)** against
  all three surface tiers:
  - `--signal-up` (14.7–13.1:1), `--signal-warning` (12.3–10.9:1), `--signal-down`
    (5.7–5.1:1), `--text-primary` (16.8–14.9:1), `--text-secondary` (6.4–5.7:1) — **all already
    clear AA for text on every background tier, no adjustment needed.** The "neon" colors
    read as harsh but are in fact high-luminance against this near-black palette — it's the
    muted tone that actually fails.
  - `--signal-pending` (#5b6660) is the one real failure: 3.25:1 on `--bg-base`, 2.89:1 on
    `--bg-surface-raised` — fails AA-text (4.5:1) everywhere and fails even AA-large (3:1) on
    the raised tier. It's fine as a **graphic/icon fill** (heatmap no-data cells, legend
    swatches — non-text UI only needs 3:1, and those sit on `--bg-base`/`--bg-surface` where it
    clears). Added **`--signal-pending-text: #7c8580`** — a lightened variant clearing 4.5:1
    against all three tiers (4.54:1 on the hardest case) — and swapped the two places it was
    actually rendered as small text: `LatencyGauge`'s null-value label and the dashboard's
    "reconnecting…" indicator. Left the detail page's null-SLA readout on the raw token
    deliberately — it's `text-3xl` (large text, only needs 3:1, clears at 3.05:1 on its actual
    `--bg-surface` context).
  - **Found a second, unrelated real bug while doing this audit**: shadcn's `Button` component
    references a `text-destructive-foreground` Tailwind class that was never defined anywhere
    in `tailwind.config.ts` — Tailwind silently generated no rule for it, so every destructive
    button's text (the dashboard's "Delete") fell back to inherited `--text-primary` on a
    `--signal-down` background at **2.94:1, failing even AA-large**. Added
    `--destructive-foreground: var(--bg-base)` (5.69:1 against `--signal-down`, the same
    dark-on-bright pairing the primary button already uses) and wired it into
    `tailwind.config.ts`'s `destructive` color as `{DEFAULT, foreground}`. Confirmed visually
    with a close-up screenshot: was near-white-on-red, now clearly dark-on-red.
  - **Flagged, not fixed**: `--border` (#232b27) against `--bg-base` is 1.34:1 — well under the
    3:1 WCAG 1.4.11 threshold for non-text UI boundaries (relevant to shadcn `Input`, which
    relies on `border` alone with no background fill to mark its boundary). This is outside
    the prompt's literal scope (signal colors for text use) and, unlike `signal-pending-text`,
    would mean changing one of the ten originally-locked hex tokens rather than adding a new
    derived variant — not something to silently override. Flagging the exact number for a
    decision, not fixing it.
- **Keyboard focus audit**: shadcn's `Button`/`Input`/`Switch` already ring in `--ring` via
  Tailwind's `focus-visible:ring-*` utilities (confirmed via computed styles, not just source
  reading: every one showed a `1–2px` box-shadow ring in `rgb(236, 239, 237)` = `--text-primary`
  = `--ring`). Plain `<a>` links (nav, target rows, footer, "back" links) had no explicit style
  and fell back to each browser's own default outline — present, but inconsistent and off-brand.
  Added one base-layer rule, `a:focus-visible { outline: 2px solid var(--ring); outline-offset:
  2px; }`, so every link now matches the same `--ring` color buttons/inputs already use.
  Confirmed no custom click targets exist outside real `<button>`/`<a>` elements (grepped every
  `onClick` — all on shadcn `Button`s), so nothing is keyboard-unreachable.
- **Responsive re-check across every Phase 3 page** at 400px width, fresh (not just trusting
  each prompt's own earlier pass, since this prompt's global token/CSS changes touch all of
  them): landing, about, login, register, dashboard (including the live toast), detail page,
  and settings all held up with no new issues from this prompt's changes.
- **Final screenshot self-critique across all pages against the 3.1 avoid-list**: clean. No
  Inter/gradient, no uniform soft-shadow card grid (every bordered section is a genuine content
  group, never decorative filler, and none carry a drop shadow), no all-caps eyebrow labels, no
  arrow appended to button/link text (the leading "←" back-links and the toast/incident-timeline
  "→" transition notation are wayfinding/data notation, not the decorative trailing-CTA-arrow
  tell — same reasoning as 3.6/3.7, re-confirmed), no middle-dot-joined meta text, numbered
  markers used in exactly the one earned place (incident timeline), no single-word headline
  color accent.
- **Dev-server discipline maintained**: ran `next build` exactly once this prompt, after all
  other live-stack verification was done (to minimize how many times the shared `.next`
  corruption from prompt 3.7's finding would hit), then restarted the port-3000 dev server
  immediately after and confirmed it healthy before finishing.
- All verification users/targets created this prompt were deleted afterward; confirmed via the
  live API. Docker stack confirmed healthy (`docker compose ps`) before finishing.
- **Known gaps carried forward, still not fixed** (out of scope for this prompt's literal ask,
  which was motion/contrast/focus/responsive/self-critique, not navigation): nothing links to
  `/dashboard/[id]` or `/settings` from the list view yet (flagged in 3.6 and 3.7). Genuinely
  the last two loose threads before Phase 3 can be called done — recommend closing both in the
  3.9 wrap-up prompt itself, or a final 3.8.5-style micro-prompt just before it, since 3.9 is
  meant to be verification, not new UI work.
- Not touched in this prompt: any backend code, any page's actual content/copy, alerting/
  email-sending logic. Next per the 3.1 build order: prompt 3.9 — final verification (full
  regression pass on Phase 0/1/2 invariants under the finished UI, plus the two nav-gap
  closures flagged above).

Update this line, and add brief notes below it, at the end of every prompt so a new chat session
can pick up context immediately without re-reading the whole codebase.
