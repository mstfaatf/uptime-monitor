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

Phase 3, prompt 3.9 (wrap-up verification) is complete. **Phase 3 is functionally done and
verified end-to-end against real, concurrent live-stack activity — with one known gap flagged
below, not fixed in this prompt (verification-only scope).** No application code changed this
prompt; only test/build/live-data verification.
- Rebuilt `api`/`worker`/`worker-eu-west` images fresh and ran both suites: **89 tests total
  (53 backend + 36 worker)**, all passing — up from 74 at Phase 2's close, with every net-new
  test attributable to 3.6/3.7's small backend additions (worker suite untouched at 36,
  confirming Phase 3 never touched worker code). `tsc --noEmit` and `next build` both clean;
  9 routes in the build output confirms the 3.3 scratch route is genuinely gone.
- **Re-confirmed the 3.5 data-shape bugfix with entirely fresh real data**: created a new
  target, let both region workers check it for real, then diverged the two regions via direct
  DB mutation + `pg_notify` (not touching `next_check_at`, avoiding a worker race) —
  `eu-west`→down, `local`→degraded. Dashboard showed both correctly, side by side, never
  "Pending." From the same open tab, flipped `local` back to up and confirmed the row updated
  and a toast fired ("local — Degraded → Reporting up") with no reload.
- **Detail view**: confirmed a previously-untested code path — an **ongoing** incident (down
  region with no recovery yet) renders "→ ongoing" / "duration unknown" correctly, not a
  broken duration. Region-tab switching correctly swapped every widget (gauge/chart/waterfall/
  heatmap/incidents/cert) between genuinely independent per-region data — 0.0% SLA/red/ongoing
  incident on one region, 100.0% SLA/green/no-downtime on the other, same target.
- **Settings**: toggled a preference and confirmed via a fresh `/auth/login` response (not just
  the UI's own success state) that it persisted server-side.
- **Phase 0-2 regression checks, all held**: ownership (404-not-403 cross-user on every
  endpoint including the 3.6 detail/checks routes, 401 anonymous everywhere); rate limiting
  (register 3→429 and target-creation 10→429 confirmed exact; login/change-password 5/min
  confirmed correct once accounting for a prior request from my own verification script in the
  same window — a test-ordering artifact, not a regression); `JWT_SECRET` fail-fast (stripped
  from `.env`, real container crash with the same `ValidationError` every prior wrap-up has
  hit, byte-identical `.env` restored via diff, clean recovery); cookie flags (`HttpOnly;
  SameSite=lax` confirmed, `Secure` correctly absent in local dev); per-user SSE filtering
  (the strongest test yet — two concurrent `curl -N` streams under real background worker
  traffic; User B's stream received many real events, all for User B's own targets, never once
  for User A's, proving isolation holds under real concurrent load, not just an idle
  single-event check).
- **Per-region independence (Phase 2 guarantee)**: holds completely — verified visually at
  every level of the detail page, not just in the API response shape.
- Accessibility/responsive items from 3.8 (focus ring on the target-row link, dark-on-red
  Delete button text, mobile chart rendering) all visibly held up throughout this walkthrough's
  screenshots without any dedicated re-testing needed.
- All verification users/targets created this prompt deleted afterward; confirmed via the live
  API that both walkthrough users have zero targets remaining. Docker stack and the port-3000
  dev server both confirmed healthy before finishing.
- **Known gap, explicitly not fixed here (out of this prompt's verification-only scope)**: the
  two navigation gaps flagged since 3.6/3.7 are still open — nothing links to
  `/dashboard/[id]` or `/settings` from the list view. Recommended as a small, quick follow-up
  before treating Phase 3 as truly shippable, rather than carrying it silently into Phase 4.
- **`consecutive_failures`-based degraded trigger (deferred since 3.1)**: recommended staying
  deferred — not because it's not worth doing, but because Phase 4's alerting/cooldown logic
  will need to reason about `consecutive_failures`/backoff state directly anyway, so exposing
  it once for both purposes together is more efficient than a standalone Phase 3 addition now.

**Phase 3 is complete.** Tokens/tooling, bespoke primitives, auth/static pages, the dashboard
list (with its real bugfix), the detail/analytics view, settings, and a motion/accessibility/
contrast polish pass are all built, tested, and verified against real concurrent live-stack
activity — not just individually, but together. **Next: Phase 4 — Alerting + compliance
export** (Resend downtime + cert-expiry alerts with a cooldown, CSV/PDF export) per CLAUDE.md's
phase plan. Recommend closing the two navigation gaps above first, and building the
`consecutive_failures` exposure as part of the alerting/cooldown work rather than bolting it on
separately.

Phase 3, prompt 3.10 (navigation links) is complete — closes the last open item from the 3.9
wrap-up. **Phase 3 is now fully, genuinely complete.**
- `app/dashboard/page.tsx`: each target row gained a "View details" button (shadcn `Button
  asChild` wrapping a `Link` to `/dashboard/{id}`, placed next to Delete) rather than making
  the whole row a link — keeps the existing external-site link (the target name/URL, opens the
  monitored site itself) and the new internal-navigation link unambiguous and non-overlapping.
  Header gained a "Settings" link next to "Log out".
- `app/dashboard/[id]/page.tsx`: header gained a "Settings" link next to "← Back to dashboard".
- `app/settings/page.tsx` deliberately left untouched — it already has its own way back
  (dashboard link), and a self-referential "Settings" link on the Settings page itself would be
  dead weight, not a real gap to close.
- **Verified live, not just visually**: registered a real user, created a real target, and
  confirmed with Playwright that clicking "View details" performs a genuine navigation to
  `/dashboard/{id}` (`page.waitForURL`, not just a visual check) and clicking "Settings" from
  the detail page genuinely navigates to `/settings`. Separately proved **pure keyboard
  operability** — tabbed to the "Settings" link and activated it with `Enter` alone (no mouse
  event at all) and confirmed real navigation. Read computed styles for every tabbed element
  and confirmed both new links carry the same on-brand `--ring`-colored focus indicator as
  everything else (the plain-link `a:focus-visible` outline for "Settings", the shadcn `Button`
  ring box-shadow for "View details", both established in 3.8).
- `tsc --noEmit` and `next build` both clean (routes unchanged, confirming this was purely
  additive markup, no new pages). Diff scope confirmed minimal: exactly the two files above,
  26 insertions / 13 deletions. No backend change, so the existing 89-test suite is
  unaffected — not re-run this prompt since nothing it covers could have changed.
- Verification target and user data cleaned up afterward; both the live dev stack and the
  Docker stack confirmed healthy before finishing.

**Phase 3 is complete — tokens/tooling, bespoke primitives, auth/static pages, the dashboard
list (with its real bugfix), the detail/analytics view, settings, a motion/accessibility/
contrast polish pass, end-to-end verification, and now full navigation between every
authenticated page — all built, tested, and verified.** No known gaps remain. **Next: Phase 4
— Alerting + compliance export** (Resend downtime + cert-expiry alerts with a cooldown,
CSV/PDF export), including building the `consecutive_failures` exposure as part of that
work rather than as a separate Phase 3 addition, per the 3.9 recommendation.

Phase 4, prompt 4.1 (auth-aware navigation, delete account, dashboard legend) is complete.
Three pre-existing UI bugs/gaps fixed before starting the alerting/export work proper.
- **Root cause of the nav bug, confirmed before fixing**: the session cookie was never being
  cleared. `SiteHeader`'s brand link was hardcoded to `"/"` and neither it nor the landing page
  (`app/page.tsx`) ever checked auth state at all — an authenticated user clicking the brand
  link, or just loading `/`, always got the signed-out variant regardless of session validity.
  Same root cause for `/login`/`/register`: neither had any auth check, so an authenticated
  user visiting them directly saw the form again instead of being redirected.
- New `frontend/lib/use-auth-status.ts` — a small `useAuthStatus()` hook wrapping a single
  `/auth/me` fetch, factored out since `SiteHeader`, the landing page, `/login`, and `/register`
  all now need the same authenticated/loading state. No shared auth context was introduced
  (each caller still fires its own request) — consistent with this app's existing per-page
  independent-fetch convention (dashboard, settings), and not enough duplication yet
  (2 callers on the landing page) to justify a global provider.
- `components/site-header.tsx` (used by `/`, `/about`, `/login`, `/register`) is now
  auth-aware: brand link routes to `/dashboard` when authenticated, `/` otherwise; nav swaps
  "Log in" for a "Sign out" button (calls `/auth/logout`, then routes home) when authenticated.
  This fix applies everywhere `SiteHeader` is used, including `/about` — a deliberate, in-scope
  side effect of fixing the shared component, not new landing-page content.
- `app/page.tsx` (landing): hero CTA swaps Register/Log in for "See my dashboard"
  (`/dashboard`) / "Sign out" when a valid session is present, per the prompt. Marketing copy/
  benefits/footer untouched, per this prompt's explicit scope.
- `app/login/page.tsx` and `app/register/page.tsx`: both now redirect an authenticated visitor
  straight to `/dashboard` via a `useEffect` on `useAuthStatus()`, rendering nothing until the
  check resolves (avoids flashing the form before the redirect fires).
- **Delete account**: confirmed no `DELETE /auth/me` (or equivalent) existed —
  `backend/routers/auth.py` only had register/login/logout/me/change-password/preferences.
  Added it: `await db.delete(current_user)` + `clear_session_cookie(response)`, 204 response.
  **Cascade is via the database's existing `ON DELETE CASCADE` foreign keys**, not explicit
  per-table cleanup code — `targets.user_id -> users.id`, `checks.target_id -> targets.id`,
  and `target_region_schedule.target_id -> targets.id` were all already declared CASCADE (see
  migrations 001 and 006), so one `DELETE FROM users WHERE id = ...` cascades all the way
  down at the DB level. **Ownership is enforced structurally, not by a filter clause**:
  `current_user` comes from `get_current_user`, resolved strictly from the caller's own
  session cookie — there is no id parameter an attacker could substitute, so this can only
  ever delete the caller's own account. 4 new backend tests
  (`backend/tests/test_account_deletion.py`): auth-required, account+cascaded-checks actually
  gone (verified via direct SQL count, not just via the API), session cleared, and a second
  user's data is untouched when the first deletes their account. 57 backend tests total (was
  53), all passing against a rebuilt `api` image; the running `api` container was recreated
  from that image afterward.
- Frontend delete-account UI lives in a new "Danger zone" section on `/settings`, in its own
  `rounded-sm` (small radius) box with a `--signal-down`-colored border and heading — no new
  colors introduced, both tokens already existed. **Confirmation pattern: type-to-confirm
  (type the account's exact email), not a modal** — stated reasoning inline in the component:
  this project has no Dialog primitive yet (would mean a new Radix dependency for one
  single use), and typing the exact email is a stronger deliberate-action barrier for an
  irreversible operation than clicking through a modal's own confirm button. The final
  "Permanently delete account" button stays disabled until the typed text matches the
  account's real email exactly.
- **Dashboard legend**: a compact single row of `SignalLight` dot+label pairs (all four
  states — up/degraded/down/pending, reusing the exact locked `SIGNAL_STATE_LABELS`
  microcopy) added directly below the summary strip on `/dashboard`, in the same
  bordered-strip instrument-panel treatment as the summary strip itself — not a separate
  boxed explainer competing with the real data, per the prompt.
- **Verified end-to-end against the live stack** (Playwright driving the real dev server on
  port 3000 against the real API, not mocks): registered a throwaway user in-browser so the
  session cookie landed in the test browser context; confirmed the logged-out landing page
  shows Register/Log in, the logged-in landing page swaps to See my dashboard/Sign out, the
  brand link genuinely navigates to `/dashboard` when authenticated, `/login` and `/register`
  both genuinely redirect an authenticated visitor to `/dashboard`, the dashboard legend
  renders all four state labels after adding a real target, the delete-confirm button is
  disabled for a wrong typed email and enabled for the correct one, deleting redirects to `/`
  and immediately shows the signed-out landing page, and — checked server-side, not just via
  the UI's own success state — `/auth/me` returns 401 and logging back in with the same
  credentials returns 401 after deletion. Also screenshotted the landing page (both auth
  states), the dashboard legend, and the settings danger-zone section to confirm the styling
  reads correctly (small radius, signal-down border/text, no competing visual weight against
  the real dashboard data). All scratch verification scripts/screenshots deleted afterward;
  no leftover test accounts (the verification/screenshot accounts were the ones deleted as
  part of testing the delete flow itself). `tsc --noEmit` clean throughout. Did not run
  `next build` this prompt — the user's own dev server was live on port 3000 throughout, and
  per the prompt-3.7 finding, `next build` corrupts a concurrently-running `next dev`'s shared
  `.next` directory regardless of whether it's cleaned first; live-stack Playwright
  verification stood in for it instead.
- Not touched in this prompt, per its explicit scope: landing page marketing copy/typography
  accents, alerting, compliance export.

**Next: continue Phase 4 — Alerting + compliance export** (Resend downtime + cert-expiry
alerts with a cooldown, CSV/PDF export), including the `consecutive_failures` exposure
recommended back in the 3.9 wrap-up.

Phase 4, prompt 4.2 (landing page expansion, typography accents, copy pass) is complete.
No "frontend-design" skill was available in this session's skill list to self-critique
against as the prompt asked — substituted the project's own established 3.1 avoid-list
(the same checklist CLAUDE.md has referenced throughout Phase 3) instead, flagged explicitly
rather than silently guessed at.
- **Landing page expansion** (`app/page.tsx`): replaced the old single 3-item benefits grid
  with five real sections between the hero and footer: "How a check works" (the actual DNS ->
  TCP -> TLS -> TTFB check lifecycle plus backoff-with-jitter behavior, in prose, with a plain
  labeled phase row underneath), "What gets measured" (two columns, per-check data vs.
  per-target analytics, naming real shipped Phase 3 features like the SLA%/heatmap/incident
  timeline rather than vague claims), "Multiple regions, independently" (expanded explanation
  plus a small mockup reusing the real `RegionBadge`/`SignalLight` components, labeled
  "Illustrative reading" like the existing hero panel, not presented as live data), "Private by
  default" (kept from the old grid, own paragraph), and "Built with" (the real stack by name,
  deliberately not claiming any live deployment, since deployment is still Phase 5 and 3.4
  already caught and fixed that exact false claim once before).
- **Copy pass**: rewrote the hero paragraph and all new section copy to read like a person
  describing a real tool — no em dashes anywhere (verified via grep across the file, zero
  matches), restructured with commas/colons instead. Confirmed against the avoid-list: no
  all-caps eyebrow labels, no arrow-suffixed buttons/links (the phase-row "->" and mockup are
  sequence/data notation, not decorative CTA arrows, same precedent as the incident timeline's
  "start -> end"), no middle-dot-joined meta text, no numbered markers outside the incident
  timeline (plain bullets used instead), no fake testimonials, no pricing.
- **Signal-color typography extended into the dashboard list view** (`app/dashboard/page.tsx`)
  — the detail page already colored SLA%/cert-expiry text (Phase 3), but the dashboard's own
  summary-strip counts and per-row latency numbers were still plain `--text-primary` regardless
  of state. Before: all four state counts and every row's latency number rendered in the same
  color no matter what they meant. After: each count colored to match its own state
  (`--signal-up`/`--signal-warning`/`--signal-down`/`--signal-pending-text`), and each row's
  latency number colored by that region's derived state via a new `latencyColor()` helper (down
  -> red, degraded -> amber, up -> left at the default `--text-primary`, deliberately not
  colored, so an accent still reads as "something worth noticing" rather than decoration
  applied to every number on the page). Used the raw signal tokens for up/warning/down text
  (already confirmed AA-safe for text by the 3.8 contrast audit) and the `--signal-pending-text`
  contrast-adjusted variant for pending, never the raw `--signal-pending` hex, per the prompt.
- **Checkered accent**: new `app/icon.svg`, a small monochrome 4x4 checkerboard favicon built
  only from the locked palette's own hex values (`--bg-base`/`--text-primary`/`--border`,
  copied literally since a standalone SVG file can't reference the page's CSS custom
  properties). No favicon existed at all before this prompt. Chose the favicon over a patterned
  divider or gauge-backdrop texture because it's the one placement that never competes with
  real in-page data legibility (a browser tab icon, noticed only if you look for it) and
  because this prompt's actual brief was fixing too much *empty* content space, so spending
  visual weight on in-page decorative texture would have worked against that goal. Verified
  served correctly (`GET /icon.svg` returns 200, `image/svg+xml`) and that Next's file-convention
  auto-generated the `<link rel="icon">` tag pointing at it, via a live Playwright check against
  the dev server, not just by creating the file and assuming the convention applies.
- **Verified against the live dev server and real backend** (Playwright, not just tsc): full-
  page screenshots of the landing page at both desktop (1280px) and mobile (400px) widths,
  confirming the new sections read cleanly, side gutters hold, and the region mockup/phase-row
  wrap sensibly narrow. Registered a throwaway user, created a real target, and seeded one
  degraded (950ms, `local`) and one down (`eu-west`) check directly via SQL to screenshot the
  dashboard's new colored counts/latency in a real non-trivial state (1 degraded amber, 1 down
  red, avg-latency gauge red at 950ms, row latency "950 ms" rendered in amber) rather than only
  the all-healthy case. Verification account and its seeded checks were deleted afterward via
  the real `DELETE /auth/me` flow (confirmed via direct SQL count that both the target and its
  checks were gone, cascade working as expected); all scratch scripts/screenshots removed.
  `tsc --noEmit` clean throughout. Did not run `next build` since the user's dev server was
  live on port 3000 (per the prompt-3.7 finding); live-stack Playwright screenshots stood in
  for it, consistent with 4.1's approach.
- Not touched in this prompt, per its explicit scope: `/about` (only the landing page's copy
  was in scope), alerting, compliance export.

**Next: continue Phase 4 — Alerting + compliance export** (Resend downtime + cert-expiry
alerts with a cooldown, CSV/PDF export), including the `consecutive_failures` exposure
recommended back in the 3.9 wrap-up.

Unplanned prompt (full UI design pass with the official `frontend-design` Anthropic skill) is
complete. Not a numbered Phase 4 prompt — the user asked to install the real, official
Anthropic `frontend-design` plugin (confirmed genuine via `github.com/anthropics/claude-code`
and `claude.com/plugins/frontend-design`, installed via `/plugin install
frontend-design@claude-plugins-official`; an earlier CLAUDE.md reference to "the
frontend-design skill" from a prior session turned out to have been informal prose, not an
actual installed skill — flagged and corrected) and then run a full critique pass against it
across every page.
- **Overall finding**: this app's existing design work (Phases 3.1-3.9) already avoids nearly
  every generic-AI-design tell the skill warns about — no cream/terracotta, no gradients, no
  drop shadows, a functionally-grounded (not decorative) traffic-light color system, mono
  reserved for genuine live-instrument readings, motion restrained to one orchestrated moment,
  a real signature custom instrument (SignalLight + LatencyGauge) rather than a stock
  illustration. This was not a redesign — it was a scoped critique-and-fix pass against real
  remaining gaps, verified with real seeded data across two regions via Playwright screenshots,
  not just code review.
- **Real finding #1, fixed**: the target detail page (`app/dashboard/[id]/page.tsx`) stacked
  six identically-bordered `bg-surface` boxes in a row regardless of content density — the
  "SaaS-card-kit" tell the skill specifically flags, just without the shadow. Fixed by keeping
  the full bordered-panel treatment only for the three genuinely dense visual modules (Latency
  gauge+chart, Timing breakdown, Uptime heatmap) and converting "Incidents" and "TLS
  certificate" (a short list and 2-3 lines of text) to a lighter divider-plus-heading treatment
  — creates real visual hierarchy instead of every section shouting at the same volume.
- **Real finding #2, fixed**: the type scale was nearly flat below the page H1 — every section
  H2 across the detail page, `/about`, `/settings`, and the dashboard's "Add target" was bare
  `font-semibold` at the browser default 16px, giving Latency/Timing breakdown/Uptime/
  Incidents/TLS certificate/Alert preferences/Account/Danger zone/Stack/Source all identical
  visual weight. Bumped all of them to `text-lg` (18px), matching the scale the landing page
  already established in the prior prompt — one consistent H1(24-30px)/H2(18px)/body(14-16px)
  scale app-wide now, not just on the landing page.
- **Real finding #3, fixed**: a handful of user-facing em dashes had survived outside the
  landing page copy pass (the prior prompt's "no em dashes" rule was scoped to `app/page.tsx`
  specifically). The skill's own tell-list separately flags "WORD — fragment"-style spaced-em-
  dash labels as template chrome, so fixed the remaining four: `/about`'s body copy, the
  dashboard's real-time toast description separator, the dashboard's "reconnecting" tooltip
  title, and the settings alert-preferences caption. Left the single "—" glyph used as a bare
  "no value" placeholder (e.g. `check.latency_ms ?? "—"`) alone — that's an idiomatic empty-
  state marker, not the punctuation pattern the skill warns about.
- **Real finding #4, fixed (found only by actually screenshotting at 400px, not from code
  review)**: `app/dashboard/page.tsx`, `app/dashboard/[id]/page.tsx`, and `app/settings/page.tsx`
  all shared an identical header row (`flex items-center justify-between`, no wrap) that, at
  narrow widths, didn't wrap the nav items onto a second line — instead it squeezed the "Uptime
  Monitor" wordmark itself into a narrow column, breaking it mid-word ("Uptime" / "Monitor" on
  separate lines). This is a real, previously-unflagged mobile bug, not present in any prior
  phase's mobile audit notes. Fixed by adding `flex-wrap gap-y-2` to all three header rows so
  the nav cleanly drops to its own line below the wordmark instead.
- **Verification methodology**: registered a throwaway account and seeded three targets with
  real, varied check history (healthy/both-regions, degraded/slow-latency-with-expiring-cert,
  down/with-a-real-incident-and-90-day-heatmap-history) directly via SQL. **Had to pause the
  `worker`/`worker-eu-west` containers partway through**: the real live worker kept re-checking
  the newly-created targets against their real (fake-path) URLs and overwriting the seeded
  "healthy"/"degraded" states with real 404-driven "down" results within seconds of creation,
  since new targets default to due-immediately — a genuine environment gotcha (same category as
  Phase 0's "made-up subdomains don't resolve" issue), not a product bug. Stopped both workers
  for the duration of the screenshot session, then restarted them afterward (confirmed both
  `Up` again). Screenshotted every page (landing, about, login, register, dashboard, detail x2
  target states, settings) at desktop width, plus the detail page and dashboard at 400px mobile
  width, both before and after the fixes above, to confirm each change actually rendered as
  intended rather than trusting the code alone. `tsc --noEmit` clean throughout.
- All verification data (the seeded account, its 3 targets, ~14 seeded check rows) deleted
  afterward via the real `DELETE /auth/me` flow; confirmed via direct SQL count that no rows
  remained. All scratch scripts/screenshots removed. Docker stack and the port-3000 dev server
  confirmed healthy before finishing.
- **Considered and deliberately left alone**: the locked color palette/tokens (already
  accessibility-audited and central to the app's identity across 6 phases — revisiting them
  wasn't justified by anything found in this pass); the auth pages' (`/login`, `/register`)
  large empty space around a centered card (a legitimate, deliberate minimal pattern from 3.4,
  not itself one of the skill's named generic-AI tells); the dashboard's own stacked-box
  structure (summary strip / legend / add-target form / target rows — each is genuinely
  panel-like content, not arbitrary content forced into cards, unlike the detail page's issue);
  the timing waterfall's descending-opacity-by-phase-order color scheme (flagged as a possible
  minor readability tension worth a future look, since the longest phase segment reads as the
  dimmest, but changing it would mean revisiting a deliberately-reasoned 3.6 decision without a
  strong enough reason found here).
- Not touched in this prompt: alerting, compliance export (still Phase 4's remaining scope).

**Next: continue Phase 4 — Alerting + compliance export** (Resend downtime + cert-expiry
alerts with a cooldown, CSV/PDF export), including the `consecutive_failures` exposure
recommended back in the 3.9 wrap-up.

Phase 4, prompt 4.3 (familiarization + design report for alerting/compliance export) is
complete. Read-only — no application code or new files, per this prompt's scope. Full report
delivered directly in the conversation (not saved to a file); reread the conversation history
if picking this up cold.
- Confirmed the 3.7 alert-preference stub precisely: `users.alert_on_downtime`/
  `alert_on_cert_expiry` (migration 007) exist, are exposed via `UserResponse`/
  `PATCH /auth/preferences`, and are read by nothing yet (confirmed via `auth.py`'s own
  docstring). Recommended no schema extension — two global per-user toggles already meets
  the "at minimum" bar and nothing in CLAUDE.md's plan asks for per-target granularity.
- Proposed a new `alert_history` table (`target_id, region, alert_type, last_state,
  last_sent_at, last_cert_expires_at`, unique on `(target_id, region, alert_type)`) combining
  state-transition suppression (don't re-alert every check while continuously down) with a
  15-minute cooldown floor (matches `backoff.py`'s own 900s cap) so a flapping target can't
  out-run state tracking; cert-expiry alerts get a separate 3-day repeat-reminder cadence with
  renewal detected via a changed `tls_cert_expires_at`.
- **Recommended alerting fire from the backend, specifically extending
  `realtime.py`'s existing `_handle_notification`** — read the full file first: it already
  fires once per committed, region-aware check, already resolves target→owner, and already
  has the fresh `Check` row in scope before publishing. Recommended against the worker
  (would mean every worker instance independently carrying Resend credentials and duplicating
  the alert-decision per region, when it should be made exactly once per check regardless of
  region count).
- **Resolved a real subtlety in the deferred `consecutive_failures` trigger** by re-reading
  `worker/main.py`'s `reschedule_target`: a success resets `consecutive_failures = 0`
  immediately, so the field can only ever be non-zero on a check that itself just failed —
  it cannot express "flaky but currently up." Reframed the proposal accordingly: a failed
  check is "degraded" (not immediately "down") until `consecutive_failures` crosses a
  threshold (proposed 3, aligned with backoff's ~120s-at-3-failures point) — a debounce on
  the down classification itself, not a new trigger on the up path. Requires exposing
  `target_region_schedule.consecutive_failures` through the backend API for the first time
  (a second join in `_latest_checks_per_region_query`; the ORM model already has parity for
  exactly this) and updating `deriveState` in both places it currently lives (`lib/status.ts`
  and the still-duplicated copy in `app/dashboard/page.tsx`).
- Resend: `RESEND_API_KEY` proposed as optional (`str | None = None`), deliberately not
  required-with-no-default like `JWT_SECRET` — a missing key is a safe degraded state (no
  emails sent), not a security hole, so shouldn't block local dev. New `backend/email/`
  module (`client.py` wrapping the `resend` package behind one `send_email()`,
  `templates.py` for three plain-text templates) shared by alerting and forgot-password —
  one integration point, not two.
- Forgot-password: new `password_reset_tokens` table (SHA-256 token hash, not argon2 —
  a random 32-byte token has no dictionary to defend against, so the slow-hash rationale
  behind password storage doesn't apply), 1-hour expiry, `POST /auth/forgot-password`
  (`3/minute`, always-200 generic response to prevent enumeration) and
  `POST /auth/reset-password` (`5/minute`), two new frontend pages (`/forgot-password`,
  `/reset-password`) that don't reuse `AuthForm` as-is since neither page is email+password
  shaped.
- Compliance export: recommended CSV first (stdlib `csv`, no new dependency) with PDF
  (`reportlab`, pure-Python, avoids `weasyprint`'s system-level Pango/Cairo dependency) as an
  explicit later add-on. `region` required on the export endpoint, never "all regions
  merged," matching `GET /targets/{id}/checks`'s existing rule. Flagged that the SLA%/
  incident computation currently only exists in TypeScript and needs a Python
  re-implementation for server-side generation — same "deliberately duplicated across
  services" tradeoff already established for `ssrf.py`/`checker.py`.
- **Proposed build order**: 4.4 consecutive_failures trigger (fully independent) → 4.5 Resend
  client wrapper (shared prerequisite for both 4.6 and 4.7 — build once) → 4.6 alert_history
  schema + alerting logic (depends on 4.5) → 4.7 forgot-password (depends on 4.5 only, not
  4.6) → 4.8 compliance export (fully independent, could even be reordered earlier) → 4.9
  Phase 4 wrap-up/regression verification, matching every prior phase's closing pattern.
- No code written, no files created, per this prompt's explicit scope. Pending review of the
  report before 4.4 begins.

**Next: Phase 4 implementation begins at prompt 4.4** (consecutive_failures degraded trigger),
per the build order above, pending the user's review of this report.

Phase 4, prompt 4.4 (consecutive_failures-based degraded trigger) is complete — implements the
4.3 report's proposal exactly. Independent of the rest of Phase 4, no Resend/alert_history
dependency.
- **`CONSECUTIVE_FAILURES_DOWN_THRESHOLD = 3`**, added as a named constant in
  `frontend/lib/thresholds.ts` (frontend-only — the backend doesn't apply this threshold
  itself, it only exposes the raw count; the classification stays a display concern).
- **Precedence rule, implemented exactly as specified** in both `frontend/lib/status.ts`
  (`deriveState`, used by the detail page) and the still-duplicated inline copy in
  `app/dashboard/page.tsx` (deliberately **not** consolidated as part of this change, per the
  prompt): no check yet -> pending; `is_up=false` -> `consecutive_failures < threshold` ->
  degraded, else -> down (authoritative, evaluated first — latency/cert thresholds never
  apply here); `is_up=true` -> slow or expiring-cert -> degraded, else -> up.
- **Backend**: `backend/routers/targets.py`'s `_latest_checks_per_region_query` now also
  outer-joins `target_region_schedule` on `(target_id, region)` — keyed off the ranked Check
  subquery's own region column, not a fixed column of `Target`, since a target's region set is
  only known from which regions it actually has checks in. This is the first time the backend
  API has read `target_region_schedule` at all (previously worker-only via raw asyncpg); the
  ORM model already had full parity for exactly this. `_group_checks_by_target` now returns a
  third dict (`failures_by_target`); `build_target_status_payload`/`_check_to_response_dict`
  thread it through as a new optional `consecutive_failures` field on `LatestCheckResponse`.
  All three call sites updated: `GET /targets/status`, `GET /targets/{id}`, and
  `realtime.py`'s `_handle_notification` (the SSE push path) — so a pushed update carries the
  same field a polled fetch would.
- **Deliberately null, not fabricated, for historical entries**: `GET /targets/{id}/checks`
  (past check rows) always returns `consecutive_failures: null` — it's a *live* schedule-table
  reading, not a fact recorded on the check row itself, so there's no honest value to attach
  to a check from an hour ago. Only the two "latest check" endpoints (and the SSE push) carry
  a real value.
- 3 new backend tests (`backend/tests/test_check_timing.py`): the field is populated correctly
  from a real `target_region_schedule` row, is `null` (not `0` or missing) when no schedule
  row exists yet for that region, and the detail-vs-history split above is exercised
  explicitly. 60 backend tests total (was 57), all passing against a rebuilt `api` image; the
  running `api` container was recreated from it.
- **Verified end-to-end against the live stack, not just the test suite**: paused both worker
  containers (same "new targets get checked immediately, overwriting seeded state" gotcha
  documented in the 4.3 UI-pass notes), created two real targets via the live API, seeded one
  at `consecutive_failures=2` and one at `=3` (both `is_up=false`) directly via SQL, and
  confirmed via both the raw `GET /targets/status` JSON and a Playwright screenshot of the
  real dashboard that the 2-failures target renders "Degraded" (amber) and the 3-failures
  target renders "No signal" (down, red) — the exact boundary the threshold is supposed to
  draw. Verification account and its targets deleted afterward via the real
  `DELETE /auth/me` flow; confirmed via SQL that no rows remained. Workers restarted and
  confirmed `Up` again. `tsc --noEmit` clean throughout.
- Not touched in this prompt, per its explicit scope: Resend, `alert_history`, forgot-password,
  compliance export, and the known `lib/status.ts`/`app/dashboard/page.tsx` `deriveState`
  duplication (left in place, both copies updated identically).

**Next: continue Phase 4 per the 4.3 build order — prompt 4.5, the shared Resend client
wrapper** (prerequisite for both the alerting logic in 4.6 and forgot-password in 4.7).

Phase 4, prompt 4.5 (Resend client wrapper + email templates) is complete. Plumbing only, per
this prompt's explicit scope — nothing wired into alert-sending or forgot-password logic yet.
- **Real deviation from the prompt's literal instruction, found before writing any code and
  worth flagging clearly**: the prompt said "create `backend/email/client.py`". Verified
  first (not assumed) that a package literally named `email` at `backend/`'s root would
  shadow Python's stdlib `email` module for the whole app — `backend/` sits directly on
  `sys.path` (confirmed via `sys.path[0] == ''`, resolving to `/app`, same as every other
  unqualified top-level import like `config`/`database`), and grepping installed
  site-packages showed `starlette/responses.py`, `fastapi/routing.py`, and `uvicorn/server.py`
  all import the stdlib `email` module directly — this would have broken core request
  handling, not just this feature. Used **`backend/mail/`** instead (confirmed no existing
  stdlib/installed module by that name), everything else built exactly as specified. Verified
  live in the container: stdlib `email` still resolves to `/usr/local/lib/python3.12/email/`
  with the new package present.
- `backend/config.py`: `RESEND_API_KEY: str | None = None` (optional, unlike `JWT_SECRET` —
  a missing key degrades safely to log-and-skip, not a startup failure) and
  `RESEND_FROM_EMAIL` (defaults to Resend's own sandbox sender address, which works without a
  verified custom domain — a small necessary addition beyond the prompt's literal ask, since
  the Resend SDK requires a `from` address on every send and there was nowhere else for one to
  come from).
- `backend/mail/client.py`: `send_email(to, subject, body) -> bool` wraps
  `resend.Emails.send_async` (the SDK's real async method, confirmed via its PyPI docs and
  live introspection in the container before use, not assumed) as plain-text mail (`text`
  field). Returns `False` and logs, without raising, both when no key is configured and when
  a real send fails — email is always a side effect of some other action and should never
  itself break the caller.
- `backend/mail/templates.py`: three functions (`downtime_alert_email`,
  `cert_expiry_alert_email`, `password_reset_email`), each returning `(subject, body)`, no
  templating engine. Templates format text only — they take already-built full URLs
  (`detail_url`, `settings_url`, `reset_url`) as plain string arguments rather than knowing
  about `FRONTEND_URL`/routing themselves, keeping them free of config/env coupling; whatever
  wires them up in 4.6/4.7 owns building those URLs. Both alert templates end with a
  "Manage alert preferences: {settings_url}" line; password reset ends with a
  standard "ignore this if you didn't request it" line instead (not an alert type, no
  preferences to manage). A small `_target_description()` helper avoids printing a target's
  URL twice when it has no name (`target_label == target_url`).
- `resend>=2.0.0` added to `backend/requirements.txt`. `RESEND_API_KEY`/`RESEND_FROM_EMAIL`
  documented in `.env.example` and `backend/README.md`'s env var table.
- 5 new tests (`backend/tests/test_mail.py`), hermetic — no real Resend calls, since
  `RESEND_API_KEY` is genuinely unset in the test environment (exercising the real no-op path,
  not a mock standing in for it): `send_email` returns `False` without a key; both alert
  templates include the right facts and links; the label/url dedup case; password-reset
  includes the link+expiry and deliberately has no settings link. 65 backend tests total (was
  60), all passing against a rebuilt `api` image. Also verified live in the container
  (not just via pytest): `resend.Emails.send_async` exists, the `mail` package imports
  cleanly, `send_email` with no key returns `False` without raising, and all three templates'
  rendered output read correctly (spot-checked printed output for tone/content, not just
  substring assertions). The running `api` container was recreated from the rebuilt image and
  `/health` reconfirmed `{"status":"ok"}`.
- Not touched in this prompt, per its explicit scope: `alert_history`, any hook into
  `realtime.py`'s `_handle_notification`, forgot-password endpoints/tables/pages. The `mail`
  package is fully built and tested but not yet called from anywhere in the app.

**Next: continue Phase 4 per the 4.3 build order — prompt 4.6, `alert_history` schema +
downtime/cert-expiry alerting logic**, wiring `mail.send_email` into `realtime.py`'s
`_handle_notification` (depends on 4.5, now complete).

Phase 4, prompt 4.6 (`alert_history` schema + downtime/cert-expiry alerting) is complete.
Alerting now genuinely fires from the backend, exactly per the 4.3 report's recommendation.
- **`alert_history` migration `008`**, exactly the schema specified (target_id/region/
  alert_type/last_state/last_sent_at/last_cert_expires_at, unique on
  (target_id, region, alert_type), `ON DELETE CASCADE` from targets). New `AlertHistory` ORM
  model — unlike `target_region_schedule`, this table is backend-owned (alerting logic lives
  in `realtime.py`, per the Phase 4 design report), so it's a normal SQLAlchemy model like
  every other backend table, not raw-asyncpg/worker-owned.
- **Cooldown constants added as real `Settings` fields** (env-configurable per the prompt's
  explicit ask, not just bare module constants like `CLAIM_TTL_SECONDS`):
  `DOWNTIME_ALERT_COOLDOWN_SECONDS = 900` (matches `backoff.py`'s own cap),
  `CERT_EXPIRY_REMINDER_COOLDOWN_DAYS = 3`. Also added `CERT_EXPIRY_WARN_DAYS = 14` (mirrors
  the frontend's `lib/thresholds.ts` value — the backend had no equivalent constant before
  this prompt, needed one to decide "is this cert now within the alerting window" at all) and
  `FRONTEND_URL` (needed so the alert-evaluation logic can build real detail/settings links
  for the templates, which deliberately don't know about routing themselves per 4.5's design).
- **Real 4.5 gap closed**: the prompt's recovery-email requirement ("is_up=true and
  last_state=='down' -> send a recovery/'back up' email") had no matching template — 4.5 only
  built the three originally-scoped templates (downtime alert, cert-expiry alert, password
  reset), not a recovery variant. Added `downtime_recovery_email` to `mail/templates.py` now,
  since the behavior this prompt requires genuinely didn't exist yet — this is completing the
  downtime-alert feature area this prompt is about, not scope creep into forgot-password/export.
- **Implemented in `realtime.py`'s `_handle_notification`**, in the same session that already
  resolves target -> owner and holds the fresh `Check` row, exactly per the report's
  recommendation to reuse this existing seam rather than adding new infrastructure:
  `_evaluate_downtime_alert` and `_evaluate_cert_expiry_alert`, each gated on the user's
  `alert_on_downtime`/`alert_on_cert_expiry` preference before doing anything else (including
  bookkeeping — a disabled preference means `alert_history` is never touched at all).
  Downtime precedence implemented exactly as specified: suppressed while still down,
  cooldown-gated against `last_sent_at` on a fresh down transition (this is what actually
  dampens flapping — even a legitimate down-after-recovery transition respects the cooldown
  from whichever email went out last, down or recovery), recovery email sent with no cooldown
  gate of its own. Cert-expiry: fires on first crossing `<= 14` days, re-reminds at most every
  3 days while unrenewed, and a changed `tls_cert_expires_at` (detected against
  `last_cert_expires_at`) resets eligibility immediately regardless of the reminder cooldown.
- **Region-awareness confirmed structurally, not just by inspection**: both evaluators only
  ever query/write the `alert_history` row for the exact `(target_id, region)` that triggered
  this specific notification — verified with a dedicated test seeding one target with a down
  `local` check and an up `eu-west` check in the same call, confirming exactly one email fired
  and only `local`'s `alert_history` row was touched.
- **The failure-isolation requirement confirmed concretely, not just by code review**: the
  entire alert-evaluation block sits in its own `try/except` around the email-sending step,
  and a dedicated test (`test_sse_push_still_delivers_when_alert_evaluation_raises`) mocks
  `send_email` to raise `RuntimeError`, then confirms the subscribed SSE queue still receives
  the full, correct `check_update` payload and that no half-written `alert_history` row was
  left behind (email is attempted before any bookkeeping write, so a raise can't leave stale
  state either).
- **Real test-environment gap found and fixed**: `test_mail.py`'s existing
  `test_send_email_skips_without_an_api_key` asserted `settings.RESEND_API_KEY is None` against
  the ambient environment — this broke the moment a **real Resend API key was added to this
  project's own `.env`** (confirmed present, needed for eventual manual delivery
  verification), since `docker compose run api` picks it up via `env_file`. Fixed properly
  with `monkeypatch` rather than assuming an empty ambient environment; added two more
  hermetic tests (key-configured send path, and a forced-failure path) mocking
  `mail.client.resend.Emails.send_async` directly so no real network call is possible from the
  test suite regardless of what's in `.env`. Every test in the new `test_alerting.py` likewise
  patches `realtime.send_email` — necessary in this specific environment, not just defensive
  style, since without it the suite would have attempted real Resend calls on every run.
- 18 new backend tests (`test_alerting.py`, `test_mail.py`), 83 total (was 65), all passing
  against a rebuilt `api` image.
- **Verified live against the real dev database, deliberately without ever risking a real
  email send**: recreated the running `api` container (confirmed the migration applied
  cleanly to the real dev DB, `\d alert_history` matches the spec exactly), then ran the
  alerting/SSE logic against real Postgres via `docker compose run --rm -e RESEND_API_KEY=`
  (empty override for that one-off process only — the long-running `api` service's real key
  from `.env` was never touched) so `send_email` was genuinely exercised but could only ever
  safely no-op. Confirmed via a real registered account and a real target: a seeded down check
  produced a real `alert_history` row (`last_state='down'`) and a real SSE push
  (`is_up: false`); a subsequent seeded up check flipped the same row to `last_state='up'`
  with a fresh `last_sent_at` and pushed `is_up: true` — the full downtime-then-recovery cycle,
  against real infrastructure, with zero real outbound email risk. Workers were paused for the
  duration (same "new/updated targets get picked up immediately" consideration as prior
  prompts) and restarted after; verification account/target/checks/alert_history rows deleted
  via the real `DELETE /auth/me` cascade, confirmed via SQL. All scratch scripts removed.
- Not touched in this prompt, per its explicit scope: forgot-password, compliance export.

**Next: continue Phase 4 per the 4.3 build order — prompt 4.7, forgot-password** (depends on
4.5's Resend wrapper only, not on this prompt's alert_history/alerting logic), then **4.8,
compliance export** (fully independent, could be reordered earlier if preferred).

Prompt 4.6.1 (live Resend delivery verification) is complete. **Live email delivery is now
verified end to end against the real, production Resend API — downtime alert, recovery
alert, and cooldown suppression all confirmed with real sends, not mocks.** Not a numbered
Phase 4 prompt (a direct follow-up closing the one thing 4.6 deliberately deferred).
- **Blocked twice before any verification could start, both resolved by asking rather than
  guessing**: (1) the recipient needed to be a real, checkable inbox — since `RESEND_FROM_EMAIL`
  is still Resend's sandbox address, delivery is restricted to the Resend account's own
  registered address, and this session has a standing instruction never to hand the user's
  email to a third-party service without them explicitly asking — user confirmed using their
  own address for this test. (2) That account (`m.attifff@gmail.com`, id=1) already existed in
  the dev DB with real, pre-existing monitored targets (reddit, bbc, github, etc.) and no known
  password — user shared the password directly rather than have it guessed or reset unprompted.
  Logged in normally via `POST /auth/login`; the 7 pre-existing targets were never touched, and
  exactly one throwaway target was added and later removed.
- **Real bug #1, found live, fixed**: the very first real send attempt failed with
  `resend.exceptions.ResendError: No async HTTP client configured. Install httpx with: pip
  install resend[async]` — `backend/requirements.txt` had `resend>=2.0.0` without the `[async]`
  extra, so `httpx` (which `resend.Emails.send_async` requires) was never installed. **Exactly
  why 4.6's own test suite never caught this**: every single test mocked either
  `mail.client.resend.Emails.send_async` or `realtime.send_email` directly — correct for
  keeping the suite hermetic (no real network calls), but it also means the real SDK internals
  were never actually exercised by any test, so a packaging gap like this could only surface
  through a genuine live call. Fixed: `resend[async]>=2.0.0`.
- **Real bug #2, found live, more serious, fixed**: neither `_evaluate_downtime_alert` nor
  `_evaluate_cert_expiry_alert` checked `send_email`'s return value — a failed send (exactly
  what bug #1 was doing on every attempt) was still being recorded in `alert_history` as
  `last_state='down'`/`'expiring'` with a real `last_sent_at`, identical to a real success. This
  meant a genuine delivery failure would have **permanently suppressed the real alert with no
  retry** via the "already alerted" check, even after whatever broke the send got fixed — the
  user would silently never be notified. Why 4.6's tests didn't catch this either: every
  "should send" test mocked `send_email` to `return_value=True`; the only failure case tested
  was an *exception* (the try/except safety net), never a clean `return False`. Fixed: both
  evaluators now check `sent = await send_email(...)` and return early without touching
  `alert_history` when `sent` is `False`, so the next check retries from scratch. Added 3
  regression tests (`test_failed_*_send_is_not_recorded_as_alerted`) covering all three alert
  paths (downtime, recovery, cert-expiry) — 86 backend tests total (was 83), all passing
  against a rebuilt `api` image.
- **Verified live, with real Resend sends, against the real running stack** (not the empty-key
  override 4.6 used): added one throwaway target (`https://example.com:8081/` — a real,
  publicly-resolving host on a closed port, chosen after a `.invalid` TLD was correctly
  rejected by the existing creation-time SSRF/DNS check) to the real account. The **real**
  worker's real check cycle produced a genuine `is_up=false` for it; the real, already-running
  `api` container's real LISTEN loop picked up the real NOTIFY and — after the fixes above —
  sent a real downtime alert with no errors logged, confirmed via `alert_history` showing
  `last_state='down'` with a real timestamp. Since there's no edit-target endpoint to "fix" a
  target's URL in place, recovery and the cooldown-suppression check were driven by inserting a
  real check row for the *same* `target_id` (preserving the same `alert_history` row) and
  firing a real `pg_notify('checks_inserted', '130:local')` by hand — the exact wire format the
  worker itself uses — so the real listener with the real key processed it identically to a
  worker-originated event. Confirmed: the recovery email flipped the row to `last_state='up'`
  with a fresh timestamp and no errors; a third failure fired 70 seconds later, still well
  inside the 900s cooldown from the recovery send, correctly produced **zero** further emails
  — `alert_history` stayed byte-identical, proving the flapping dampener holds under a real
  send path, the one behavior that genuinely couldn't be proven any other way. `eu-west`'s own
  `alert_history` row was independently confirmed untouched by every one of these `local`-only
  events, reconfirming region-scoping under real conditions.
- **What was not independently verified**: Resend's API key used here is `sending`-scoped
  (confirmed via a 401 `"restricted_api_key"` when attempting to query send history), so
  delivery status couldn't be cross-checked against Resend's own records — the absence of any
  error in the API logs across all three real sends is strong indirect evidence, but actual
  inbox receipt can only be confirmed by the user checking `m.attifff@gmail.com` directly.
- Cleanup: the throwaway target (and its `alert_history`/`checks` rows, via cascade) deleted
  via the real API; confirmed via SQL that nothing related to it remains. All 7 pre-existing
  real targets on the account untouched throughout. Workers were never paused this run
  (deliberately, so the first failure came from a genuine worker cycle, not a seeded one).

**Next: continue Phase 4 per the 4.3 build order — prompt 4.7, forgot-password** (depends on
4.5's Resend wrapper only), then **4.8, compliance export** (fully independent).

Phase 4, prompt 4.7 (forgot-password flow) is complete.
- **`password_reset_tokens` migration `009`**, exactly the schema specified, plus the
  `ix_password_reset_tokens_token_hash` index. New `PasswordResetToken` ORM model (backend-owned,
  same as `AlertHistory` — the flow lives entirely in `routers/auth.py`, no worker involvement).
- **Token handling**: `secrets.token_urlsafe(32)` generated, only its SHA-256 hex digest ever
  stored (never the raw token) — deliberately not argon2, since a 32-byte random token has no
  dictionary to defend against, unlike a human-chosen password; using the slow hash here would
  just make every lookup needlessly expensive for no real security gain. `RESET_TOKEN_EXPIRY_MINUTES
  = 60`, shared by both the DB expiry and the "expires in N minutes" line in the email itself so
  the two can never drift apart.
- **`POST /auth/forgot-password`** (`3/minute`): always returns the identical generic 200
  message regardless of whether the account exists (anti-enumeration, same shape reasoning
  `/auth/change-password`'s 401 already relies on). Token creation happens independent of
  whether the email actually sends — confirmed live (below) that a failed send still leaves a
  real, usable token row, which is correct: token issuance and email delivery are different
  concerns, and Phase 4.6.1 already established the "don't fake bookkeeping on a failed send"
  principle for a different table (`alert_history`) — this endpoint never had that risk since
  it doesn't skip writing the token based on send success at all.
- **`POST /auth/reset-password`** (`5/minute`): validates not-expired/not-used, sets the new
  password, marks this token used, and marks every *other* outstanding token for the same user
  used too (defense in depth — an earlier unused reset email shouldn't stay live after a later
  one is redeemed). **Known, accepted limitation, stated explicitly per the prompt**: this app's
  sessions are stateless JWTs with no server-side revocation list, so a reset does not invalidate
  any other already-logged-in session for the same user — not fixed here.
- **Frontend**: `/forgot-password` (email only) and `/reset-password` (`new password` +
  `confirm`, reads `?token=` via `useSearchParams`, wrapped in a `<Suspense>` boundary — required
  by the Next.js App Router for any client component using `useSearchParams`, or the build fails
  static generation for that route) — neither reuses `AuthForm` (email+password shaped, doesn't
  fit either page), each is its own small form per the prompt. "Forgot your password?" link
  added to `/login`, below the existing "Register" link.
- 9 new backend tests (`test_password_reset.py`), 95 total (was 86), all passing against a
  rebuilt `api` image. Hermetic — `routers.auth.send_email` mocked in every test, same
  necessity established in 4.6.1 (a genuine `RESEND_API_KEY` lives in this project's own `.env`).
  Coverage: real account gets a token + email attempt, unknown email gets the identical
  response with no token/email, a valid token actually changes the password (old rejected, new
  accepted), token reuse rejected, expired token rejected, bogus token rejected, redeeming one
  token invalidates a still-outstanding earlier one for the same user, both rate limits exact.
- **Verified live against the real dev database and the real running stack, deliberately without
  spamming a real inbox this time** (this prompt didn't ask for delivery verification the way
  4.6.1 did — token creation itself has no address-validity dependency, so a throwaway
  `@example.com` account was enough): recreated the `api` container (confirmed migration `009`
  applied cleanly, `\d password_reset_tokens` matches the spec exactly); called the real
  `POST /auth/forgot-password` over HTTP for a throwaway `@example.com` account — Resend
  correctly rejected the address with a clear `ValidationError` ("Please use our testing email
  address instead of domains like example.com"), cleanly caught, no crash, endpoint still
  correctly returned the generic 200 — and confirmed the token row was created anyway. Since the
  raw token only ever existed in that one (failed) email body, and even direct DB access can't
  recover it from the stored hash by design, substituted a known raw token into the same valid
  row (a legitimate test technique, not a security bypass in the app) to drive the real
  `POST /auth/reset-password` endpoint over HTTP end to end: old password rejected after reset,
  new password accepted, token-reuse correctly rejected. Then ran the **full flow through an
  actual browser** against the live dev server — registered a throwaway account, triggered a
  real `forgot-password` call, substituted a known token again, navigated to
  `/reset-password?token=...`, filled and submitted the real form, confirmed redirect to
  `/login`, and confirmed old/new password behavior over the real API from within that same
  browser session. Also screenshotted `/login` (new link visible), `/forgot-password` (both
  states), and `/reset-password` (both the no-token error state and the real form) to confirm
  visual correctness. All throwaway accounts/tokens deleted afterward (via the real
  `DELETE /auth/me` cascade); confirmed via SQL that none remain. All scratch scripts removed.
  `tsc --noEmit` clean; `next build` not run (dev server was live on port 3000), matching this
  project's established practice.
- Not touched in this prompt, per its explicit scope: `alert_history`/alerting (already done in
  4.6/4.6.1), compliance export.

**Next: continue Phase 4 per the 4.3 build order — prompt 4.8, compliance export** (fully
independent of everything else in Phase 4), which per the 4.3 report closes out the phase's
remaining scope ahead of a wrap-up/regression-verification prompt.

Phase 4, prompt 4.8 (compliance export, CSV) is complete. **PDF export is explicitly deferred,
not built** — `reportlab` per the 4.3 report's recommendation (pure-Python, avoids
`weasyprint`'s system-level Pango/Cairo dependency), left as a clearly-flagged follow-up.
- **`GET /targets/{id}/export?region=&format=csv&from=&to=`**: ownership-enforced identically
  to every other target-scoped endpoint (404 not 403), `region` required — never "all regions
  merged," matching `GET /targets/{id}/checks`'s existing rule. `format` is validated (only
  `csv` accepted today) so requesting `pdf` gets a clear 400 explaining it's planned but not
  built, rather than silently receiving CSV under the wrong label. `from`/`to` (optional, ISO
  8601) bound the date range; omitted means unbounded on that side. No new dependency — stdlib
  `csv` only, per the prompt.
- **New `backend/export.py`**: `compute_sla`/`compute_incidents` re-implemented in Python from
  the existing TypeScript (`app/dashboard/[id]/page.tsx`'s `computeSla`,
  `components/incident-timeline.tsx`'s `computeIncidents`) — the same deliberate cross-service
  duplication already established for `security/ssrf.py` vs `worker/ssrf.py`, not a new
  pattern, kept in sync by hand since export generation runs server-side in Python and the
  frontend's own logic runs client-side in TypeScript with no shared runtime. Incidents are
  returned chronologically (oldest first), not reversed like the frontend's own most-recent-
  first UI ordering — a CSV report reads more naturally in the same order as the raw check
  rows beneath it in the same file.
- **Real correctness decision, not just a port of the frontend logic**: `TLS Cert Days
  Remaining` in the export is computed relative to each row's own `checked_at`, not `now()`
  the way the live API's `_check_to_response_dict` computes it. The live API is always
  describing the *latest* check, so "as of right now" is the right frame; a historical export
  is mostly *not* the latest check, so a `now()`-relative figure on an old row would be
  actively misleading (e.g. reading a large negative number for a cert that was perfectly
  fine at the time but has since expired). Verified directly with a dedicated test asserting
  the correct figure on a 100-day-old row, and confirmed live (below) with real seeded data.
- **CSV structure**: a summary section (target/URL/region/date range/total checks/SLA%,
  then an "Incidents" sub-table with start/end/duration) followed by a blank line and the raw
  check-row table (`checked_at, is_up, status_code, latency_ms, dns_ms, tcp_ms, tls_ms,
  ttfb_ms, tls_cert_days_remaining, error`) — one file, readable both as a human report and as
  tabular data once past the summary section. Filename is a fixed `target-{id}-{region}-
  checks.csv`, deliberately not built from `target.name`/`url` — both are user-controlled
  strings, and interpolating them raw into a `Content-Disposition` header risks malformed
  headers (quotes/semicolons are syntactically meaningful there) for no real benefit, since the
  file's own contents already say what target it is.
- **Frontend**: the "Export (coming soon)" button is now a real, enabled link (disabled only
  when the target has no regions/checks yet) pointing straight at the export endpoint with the
  currently-selected region tab. Implemented as a plain `<a href>` (via `Button asChild`), not
  a fetch-and-blob dance — a top-level navigation already carries the session cookie
  (`SameSite=lax` allows this), and the backend's `Content-Disposition: attachment` header is
  what actually triggers a real download, no client-side JS needed for that part. **Scoping
  note**: no date-range picker UI was built — the endpoint supports `from`/`to`, but the
  prompt's ask was "wire the button," and the button exports the selected region's full
  history; a range-picker UI is a reasonable future addition, not built here to avoid scope
  creep beyond what was asked.
- **Sync vs. streaming, confirmed with real numbers rather than re-guessing**: queried the real
  dev DB before answering — the largest single (target, region) pair currently has ~295 rows;
  at the default 300s check interval that's ~288 rows/day, so even a full year of continuous
  history for one (target, region) would be ~105K rows. A synchronous in-memory CSV build
  handles that in well under a second, backed by the existing `ix_checks_target_id_checked_at`
  index for the query itself. The 4.3 report's synchronous recommendation is confirmed, not
  revised.
- 16 new backend tests (`test_export.py`): pure-function coverage for `compute_sla`/
  `compute_incidents`/`build_csv` (including the checked_at-vs-now() correctness case) using a
  lightweight fake-Check stand-in (no DB needed for pure logic), plus endpoint coverage
  (auth-required, ownership 404, unsupported-format 400, region required, correct headers/
  content-type/filename, region-scoping, date-range filtering). 111 backend tests total (was
  95), all passing against a rebuilt `api` image. One test bug caught and fixed along the way
  (not a production bug): a hand-built query string with an unencoded `+00:00` UTC offset
  broke on `+` being interpreted as a space — fixed by using httpx's `params=` dict instead of
  string interpolation, which encodes correctly.
- **Verified live end to end, including a real browser-triggered file download**: recreated the
  `api` container, seeded a real target with realistic check history (a healthy run, a 40-
  minute incident, a later cert renewal) via direct SQL (workers paused for the duration, same
  "new targets get checked immediately" consideration as prior prompts, restarted after), then
  used Playwright to load the real detail page, click the real "Export CSV (local)" button, and
  capture the actual downloaded file — confirmed the correct filename
  (`target-131-local-checks.csv`), correct SLA% (66.67%, matching 4 of 6 checks up), the exact
  40-minute incident window, and per-row `TLS Cert Days Remaining` figures correctly relative
  to each row's own `checked_at`. Screenshotted the enabled button rendering correctly
  ("Export CSV (local)") before triggering the download. Verification account/target/checks
  deleted afterward via the real `DELETE /auth/me` cascade; confirmed via SQL that nothing
  remained. All scratch scripts removed. `tsc --noEmit` clean; `next build` not run (dev
  server was live on port 3000).
- Not touched in this prompt, per its explicit scope: PDF export (deferred), a date-range
  picker UI (scoping note above), forgot-password/alerting (already done in 4.6-4.7).

**Next: Phase 4's remaining scope per the 4.3 build order is prompt 4.9, wrap-up/regression
verification** — matching the pattern every prior phase has closed with (0.7, 1.6, 2.8, 3.9) —
plus, whenever wanted, the deferred PDF export follow-up.

**Phase 4, prompt 4.9 (wrap-up + full verification) is complete. Phase 4 is genuinely,
verifiably done** — every piece (nav/delete-account/legend fixes, landing expansion,
degraded-trigger precedence, Resend client, downtime + cert-expiry alerting, forgot-password,
CSV export) confirmed working, with the two alert paths not yet proven with a real send
(cert-expiry, and a full forgot-password round-trip) closed out in this pass.
- **147 tests total** (111 backend + 36 worker), all passing against freshly rebuilt images.
  No coverage gaps found against what the prompt named — `test_alerting.py` (18),
  `test_password_reset.py` (9), `test_export.py` (16), and `test_check_timing.py`'s
  `consecutive_failures` exposure tests already cover cooldown/recovery/flapping, token
  expiry/reuse, export ownership, and the degraded-trigger's API dependency respectively — no
  new tests needed.
- **Cert-expiry alert proven live for the first time** (4.6.1 only proved downtime/recovery):
  seeded a near-expiry cert, fired a real notification — a real email sent, `alert_history`
  recorded correctly. Backdated past the 3-day reminder cooldown and re-notified: a real
  second reminder sent. Re-notified again immediately: correctly suppressed.
- **Downtime/recovery regression-checked live** on the same target (reusing the mechanism, not
  repeating 4.6.1's exhaustive original drill) — both alert types tracked independently for
  one target/region with no interference, confirming nothing in 4.7/4.8's later changes to
  `auth.py`/`targets.py` touched `realtime.py`'s alerting path.
- **Forgot-password proven as a genuine full round-trip for the first time** (4.7 deliberately
  used only throwaway `@example.com` accounts): real request against the real account, real
  send, a known-token substitution to complete a real reset (the same legitimate technique
  from 4.7 — raw tokens only ever exist in the sent email, by design), confirmed login with
  the new password, then restored the original password via `change-password` — net zero
  change to the real credential, full flow proven for real.
- **CSV export reconfirmed** with genuinely divergent seeded per-region data (`local` up/100%
  SLA, `eu-west` down/0% SLA, same target) — no collapsing, matching 4.8's original proof.
- **4.1 regressions held**: brand-link routing, landing page's authenticated CTA swap, and
  delete-account's real sign-out all reconfirmed via a fresh browser-driven run.
- **Phase 0-3 regressions all held**: ownership (404 not 403 cross-user, 401 anonymous, across
  detail/checks/export/delete), rate limiting exact on all five limited endpoints including the
  new forgot-password (3) and reset-password (5) limits, `JWT_SECRET` fail-fast (real container
  crash and clean recovery), cookie flags (`HttpOnly; SameSite=lax`, no `Secure` in dev,
  confirmed via raw header inspection), per-user SSE filtering (two real concurrent
  `EventSource` connections, exactly 1 event to the owner and 0 to the other user), and
  per-region independence in both the status API and export output.
- **One honest, out-of-scope finding**: 31 leftover test accounts turned up in the dev DB, but
  all at id 3-39 with timestamps from days before this session started — pre-existing cruft
  from Phase 0-3's own historical verification, not something this session left behind.
  Confirmed zero accounts remain at id 40+ (everything created this session, including this
  wrap-up's own verification, was cleaned up). Not fixed here, flagged for whenever convenient.
- Real account's 7 original targets and restored password confirmed untouched throughout.
- **Assessment: Phase 4 is genuinely done.** PDF export staying deferred is the right call, not
  a gap — CSV already satisfies the compliance-export requirement functionally, and
  `reportlab` remains a clean, scoped follow-up whenever wanted, not a Phase 5 blocker. Nothing
  else needs revisiting before deploy.

**Phase 4 complete. Next: Phase 5 — Deploy** (Neon for Postgres, Railway for the API and both
worker instances, Vercel for the frontend, CORS updated to the real domain, CI pipeline) per
CLAUDE.md's phase plan.

Phase 5, prompt 5.1 (familiarization + deployment proposal) is complete. Read-only — no
application code or new files, per this prompt's scope. Full report delivered directly in the
conversation (not saved to a file); reread the conversation history if picking this up cold.
- Full env var inventory across backend/worker/frontend, with local-dev value vs. required
  production value for each (fresh `JWT_SECRET`, Neon `DATABASE_URL`, `COOKIE_SAMESITE=none`
  in prod, real Vercel origin for CORS, real region names for `REGION`, etc.).
- Neon: provision once, run `alembic upgrade head` manually from a local shell against the
  Neon connection string for the first migration; every deploy after that is already handled
  automatically by `backend/Dockerfile`'s existing boot-time `alembic upgrade head && exec
  uvicorn ...` — no separate Railway release-phase command needed.
- Railway: one project, three services (`api`, `worker`, `worker-<region-b>`), each pointing
  at its existing Dockerfile as-is; one project (not two) so shared vars like `DATABASE_URL`
  stay a single source of truth. `REGION` is the only var that differs between the two worker
  services.
- Vercel: root `frontend/`, default Next.js build, `NEXT_PUBLIC_API_URL` set in the dashboard.
  Confirmed no server-only secret is exposed via any `NEXT_PUBLIC_*` var. Flagged that
  `playwright` (a devDependency used only for this project's own manual verification) may slow
  or complicate Vercel's install step via its browser-binary postinstall — recommended
  `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` on Vercel.
- **Cross-origin cookies/CORS — flagged as the riskiest untested part of this phase**:
  `COOKIE_SAMESITE` must become `"none"` in production (relies on the existing
  `ENVIRONMENT=production` → `COOKIE_SECURE=True` override already covering the `Secure`
  requirement); `main.py`'s hardcoded single-origin `allow_origins=["http://localhost:3000"]`
  must become an explicit env-driven allowlist (never `"*"`, since `allow_credentials=True`).
  Neither change is made yet — implementation is later prompts.
- Proposed verifying the cross-origin contract cheaply before Vercel is even involved: point
  the local `next dev` server's `NEXT_PUBLIC_API_URL` at the deployed Railway backend once it
  exists, and confirm login/cookie/SSE work over that real cross-origin (still-`localhost`
  frontend, real HTTPS backend) combination first.
- Resend: documented what DNS records domain verification needs and confirmed
  `mail/client.py` needs zero code changes — `RESEND_FROM_EMAIL` is already a configurable
  setting (not hardcoded). Flagged that Resend domain verification is independent of the
  frontend's hosting domain and may be deferred if no custom domain is purchased for this
  project.
- Multi-region: recommended real Railway regions **US East** and **EU West** (replacing the
  Phase 2 `local`/`eu-west` placeholders) — confirmed `REGION` is the only var that needs to
  differ between the two worker deployments.
- Secrets: confirmed none of `JWT_SECRET`/`DATABASE_URL`/`RESEND_API_KEY` should ever be
  committed or pasted into a prompt; each gets generated/copied directly into Railway's or
  Vercel's dashboard.
- Cleanup: confirmed the 31 leftover test accounts (ids 3-39) in the local dev DB are moot —
  production Neon gets populated only via migrations-from-scratch, no data copy from local.
- Proposed build order for 5.2 onward: Neon provisioning → backend Railway deploy (incl. the
  `COOKIE_SAMESITE`/CORS-allowlist code changes) → worker Railway deploy (both regions) →
  cross-origin verification via local frontend against the deployed backend → Vercel deploy →
  Resend domain verification (independent, can interleave) → CI pipeline → wrap-up/regression
  verification, mirroring every prior phase's closing pattern.
- No code changes, no new files, no migrations in this prompt — report only, pending review
  before Phase 5 implementation begins.

**Next: Phase 5 implementation begins at prompt 5.2** (Neon provisioning + first migration
run), per the build order above, pending the user's review of this report.

Phase 5, prompt 5.2 (Neon provisioning + first production migration) is complete. No
application code changed — documentation only (`backend/README.md`, `worker/README.md`). No
deployed service points at this database yet, per this prompt's explicit scope.
- **Neon project provisioned** — region **us-east-2 (AWS)**, database `neondb`, pooled
  connection host (`...-pooler...`). Ran `alembic upgrade head` once from a local Docker
  container (the already-built `api` image, run standalone with `docker run`, not via
  `docker compose`, so the real dev stack was never touched) pointed at the Neon connection
  string. All 9 migrations (`001`→`009`) applied cleanly; `alembic current`/`alembic history`
  confirm `alembic_version` landed at `009` (head).
- **Schema verified identical to local, not just assumed**: wrote a throwaway diff script
  (asyncpg, deleted after use — not committed) comparing `information_schema.columns`,
  `pg_indexes`, and `pg_constraint` between local Postgres and Neon. Columns (45) and indexes
  (17) matched exactly with zero differences. The only constraint-set difference was Neon's
  newer catalog materializing column-level `NOT NULL` constraints as explicit `pg_constraint`
  rows — a PostgreSQL 17+ catalog behavior change, not present on local's PG16 — confirmed via
  the column-level `is_nullable` comparison showing zero real differences; a metadata
  representation difference only, not a functional/migration risk.
- **Postgres version confirmed**: Neon runs PostgreSQL 18.6; local dev runs `postgres:16-alpine`
  — two major versions apart. No incompatibility found; all migrations (including the
  `postgresql_ops`-using index from migration 006) applied without modification.
  `password_reset_tokens`/`alert_history` (Phase 4 tables) also present and correctly shaped.
- **Confirmed empty, no local carryover**: every table has 0 rows except `alembic_version` (1
  row, correctly `009`) — matches the plan from 5.1: production Neon is populated only via
  migrations-from-scratch, never a data copy, so the 31 leftover local test accounts (ids
  3-39) never reach it.
- **Real, load-bearing connection-string finding, verified empirically rather than assumed
  from the 5.1 report's prediction**: Neon's dashboard gives a libpq-style string
  (`?sslmode=require&channel_binding=require`). Tested all four combinations directly against
  the real Neon instance: `sslmode=require` works for the **sync/psycopg2** path (Alembic's
  `env.py`) but throws `TypeError: connect() got an unexpected keyword argument 'sslmode'` on
  **asyncpg** (both SQLAlchemy's async engine and raw `asyncpg.connect()`); `ssl=require` is
  the reverse — works on asyncpg, fails on psycopg2/sync with `invalid dsn: invalid connection
  option "ssl"`.
- **New problem beyond what 5.1 anticipated, flagged (not fixed) for 5.3**: `backend/
  Dockerfile`'s boot command (`alembic upgrade head && exec uvicorn ...`) reads **one**
  `DATABASE_URL` for both the sync migration step and the asyncpg app runtime — but those two
  steps need incompatible query-string shapes on the same URL. A single production
  `DATABASE_URL` value cannot satisfy both today; deploying the backend as-is against this
  connection string would fail at either the migration step or app startup depending on which
  form is chosen. This needs a real code fix in 5.3 (e.g. `alembic/env.py` translating
  `ssl=`→`sslmode=` for its own sync connection, or `database.py` passing
  `connect_args={"ssl": "require"}` to the async engine instead of relying on the query
  string) before the backend can actually be deployed to Railway. The worker has no
  equivalent problem — it only ever uses the asyncpg path, confirmed in `worker/README.md`.
- Documented all of the above in `backend/README.md` (new "DATABASE_URL (production — Neon)"
  section) and `worker/README.md` (same section, worker-specific) — host pattern, the
  `ssl=require` vs `sslmode=require` distinction, the Postgres-version/schema-diff findings,
  and the flagged dual-DATABASE_URL conflict. No real credential or connection string was
  committed anywhere — confirmed via a full repo grep for the Neon host/password fragments
  after finishing, zero matches outside this conversation.
- Not touched in this prompt, per its explicit scope: `CORS_ORIGINS`/`COOKIE_SAMESITE` code
  changes, any Railway service, any Vercel config, `database.py`/`alembic/env.py` code (the
  fix for the flagged DATABASE_URL conflict above is 5.3's job, not this prompt's).

**Next: Phase 5, prompt 5.3 — backend Railway deploy.** Per the 5.1 build order, this needs to
resolve the newly-flagged `ssl=require`-vs-`sslmode=require` dual-DATABASE_URL conflict above
(a real blocker discovered in 5.2, not anticipated in 5.1) in addition to the originally-planned
`COOKIE_SAMESITE`/`CORS_ORIGINS` production-awareness changes, before the `api` service can be
deployed and verified against Neon.

Phase 5, prompt 5.3 (backend Railway-deploy readiness: DATABASE_URL fix, CORS/cookie
production-awareness) is complete. **Not yet deployed to Railway itself, per this prompt's
explicit scope** — this makes the backend deployable; the actual Railway deploy is a
following prompt.
- **DATABASE_URL conflict resolved with a second setting, `MIGRATION_DATABASE_URL`** — the
  approach the prompt itself suggested, confirmed as the right one rather than trying to force
  one URL to satisfy both drivers (not possible — asyncpg and psycopg2 accept mutually
  exclusive SSL query params). `backend/alembic/env.py` now reads `MIGRATION_DATABASE_URL`
  first, falling back to `DATABASE_URL` (stripped of `+asyncpg`) exactly as before when unset
  — so local dev/Docker Compose needed zero changes and keeps working unmodified. Deliberately
  **not** added to `config.py`'s `Settings` — `env.py` already read `DATABASE_URL` directly
  from `os.environ` rather than through the `Settings` singleton, so `MIGRATION_DATABASE_URL`
  follows the same existing pattern rather than introducing a new one.
- `backend/Dockerfile`'s boot command (`alembic upgrade head && exec uvicorn ...`) stays a
  **single, unchanged command** — confirmed by actually booting the real image against the
  real Neon database from 5.2 with `DATABASE_URL=...?ssl=require` and
  `MIGRATION_DATABASE_URL=...?sslmode=require&channel_binding=require` set together: the
  migration step ran via psycopg2 (reading `MIGRATION_DATABASE_URL`), then uvicorn started via
  asyncpg (reading `DATABASE_URL`), both in the one container boot Railway will actually run.
  Also registered and logged in a real throwaway user against that Neon-backed container to
  confirm the whole write path works end to end (not just `/health`), then deleted it via the
  real `DELETE /auth/me` cascade — confirmed via direct query that Neon is empty again
  afterward.
- **`COOKIE_SAMESITE` production-aware**, same mechanism as the existing `COOKIE_SECURE`
  override: `ENVIRONMENT=production` now forces `COOKIE_SAMESITE="none"` (not just permits it)
  in the same `model_validator`, renamed to `_enforce_secure_cookie_settings_in_production` to
  reflect the broader scope. `SameSite=None` requires `Secure`, which the same validator's
  existing `COOKIE_SECURE` override already guarantees runs first. Verified against the real
  Neon-backed container above: a real login's `Set-Cookie` header read exactly `HttpOnly;
  Max-Age=604800; Path=/; SameSite=none; Secure`.
- **New `CORS_ORIGINS` setting** (`config.py`): a comma-separated string (not a JSON-array
  field) specifically so it's easy to enter as a plain value in Railway's/Vercel's dashboard
  UI, parsed via a new `cors_origins_list` property. `main.py`'s `CORSMiddleware` now reads
  `settings.cors_origins_list` instead of the old hardcoded `["http://localhost:3000"]`.
  `allow_credentials=True` untouched — confirmed via a live preflight test against the
  rebuilt container that a non-allowlisted origin (`https://evil.example`) gets a real 400
  with no `Access-Control-Allow-Origin` header, i.e. never a wildcard fallback.
  Default value kept as `http://localhost:3000` (a sensible dev default, per the prompt's
  either/or) rather than "no default" — unlike `JWT_SECRET`, a wrong/missing `CORS_ORIGINS`
  fails loudly (blocked cross-origin requests) rather than silently, so the extra friction of
  a hard-required field isn't justified here.
- **`backend/Dockerfile`**: `--port 8000` hardcoded on uvicorn's CMD is now `--port
  ${PORT:-8000}` — Railway injects `PORT` and expects the app to bind to it; falls back to
  `8000` when unset, so local Docker Compose (which never sets `PORT`) is unaffected. Verified
  both paths: local `docker compose up api` still serves on 8000 as before; the Neon-backed
  boot test above (no `PORT` set, `-p 8010:8000` host mapping) also correctly fell back to
  8000 internally.
- **`GET /health` already existed** (`main.py`, since Phase 0) — confirmed, not re-added.
  Returns `{"status": "ok"}`, suitable for Railway's health check as-is.
- **Exact Railway `api` env var list**, documented in a new "Deploying to Railway" section in
  `backend/README.md`: `ENVIRONMENT=production`, `DATABASE_URL` (Neon, `ssl=require` form),
  `MIGRATION_DATABASE_URL` (Neon, `sslmode=require&channel_binding=require` form —
  Neon's dashboard default, unmodified), `JWT_SECRET` (freshly generated, never reused from
  local `.env`), `RESEND_API_KEY` (the real key), `RESEND_FROM_EMAIL=Uptime Monitor
  <onboarding@resend.dev>` (sandbox address, per the no-custom-domain decision),
  `CORS_ORIGINS=http://localhost:3000` and `FRONTEND_URL=http://localhost:3000` (both
  deliberately still local for now, per the prompt — updated together once the real Vercel
  domain exists in 5.5/5.6). Everything else (`JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`,
  `COOKIE_NAME`/`COOKIE_HTTP_ONLY`/`COOKIE_MAX_AGE`, the alerting-cooldown constants) left
  unset — safe defaults apply, and `COOKIE_SECURE`/`COOKIE_SAMESITE` are deliberately **not**
  set directly since `ENVIRONMENT=production` forces both correctly regardless.
- Tests: 7 new (`test_config.py` gained 4 — production `COOKIE_SAMESITE` override, dev
  default, `cors_origins_list` default and comma-parsing; new `test_cors.py` gained 3 —
  allowed-origin preflight succeeds, disallowed-origin preflight rejected with no CORS header,
  a disallowed-origin simple request still succeeds server-side but carries no CORS header).
  118 backend tests total (was 111), all passing against a rebuilt `api` image.
- **Verified end-to-end**: full local `docker compose` stack rebuilt and confirmed healthy
  (`/health` 200, real CORS preflight from `localhost:3000` allowed and from
  `https://evil.example` rejected); the Neon-backed single-container boot test above proved
  the actual Dockerfile CMD, both settings, and the full cookie contract together against real
  production-shape infrastructure, not just unit tests. Also found and restarted `worker`/
  `worker-eu-west`, which had exited ~17 hours before this session (a pre-existing condition
  from an earlier Docker Desktop restart, unrelated to this prompt's changes) — left the full
  local stack (`api`, `db`, `worker`, `worker-eu-west`) healthy before finishing.
- `.env.example` and `backend/README.md` updated with `MIGRATION_DATABASE_URL`,
  `CORS_ORIGINS`, and `FRONTEND_URL` (the last of which existed in `config.py` since Phase 4
  but was never documented in `.env.example` until now).
- No real credential or connection string committed anywhere — confirmed via a diff-scoped
  grep for the Neon host/password fragments after finishing, zero matches.
- Not touched in this prompt, per its explicit scope: any actual Railway deployment (no
  service created, nothing pushed to Railway), Vercel, `worker/` code (the worker has no
  equivalent DATABASE_URL conflict, confirmed in 5.2 — it only ever uses the asyncpg path).

**Next: Phase 5, prompt 5.4 — deploy to Railway for real.** Push this commit, create the
Railway project/service for `api` pointed at `backend/`, set the env vars listed in
`backend/README.md`'s "Deploying to Railway" section, and verify the deployed service is
reachable over HTTPS at its Railway domain with a real request (`/health`, then a real
register/login round-trip) before moving on to the worker services and the cross-origin
verification step from the 5.1 report.

Unplanned verification pass ("5.3-verify" — the `api` service's actual Railway deploy) is
complete. No code changed in this pass; one real bug found and fixed directly in Railway's
dashboard (not code).
- **Real bug found**: `/health` and every other endpoint returned a Railway-edge 502
  (`x-railway-fallback: true`) despite the deployment showing "Active" — root cause was the
  public domain's **target port** still pointing at `8000` while the app, correctly per this
  session's `${PORT:-8000}` fix, was bound to Railway's assigned `8080` (visible in the deploy
  log: `Uvicorn running on http://0.0.0.0:8080`). This was a stale Railway networking setting
  from before the port fix landed, not an application bug. Fixed by updating the domain's
  target port in Settings → Networking; `/health` returned `200` immediately after.
- **Every checklist item then verified against the real deployed service**: `/health` 200;
  register/login/`/auth/me` roundtrip real, `Set-Cookie` read exactly `HttpOnly; Max-Age=604800;
  Path=/; SameSite=none; Secure`; CORS preflight from `http://localhost:3000` allowed
  (`access-control-allow-origin` echoed back), from `https://evil.example` rejected with `400`
  and no CORS header; `JWT_SECRET` fail-fast re-proven **in production for the first time** —
  removing it via the dashboard and redeploying produced a genuine `CRASHED` deployment,
  crash-looping on the same `pydantic_core.ValidationError` this project has hit at every prior
  local wrap-up, and restoring it recovered cleanly (confirmed the pre-crash session cookie
  still validated afterward, meaning the original secret value was restored, not a fresh one).
  Verification account deleted afterward (`204`, confirmed via subsequent `401`s).
- Real Neon-provisioning finding, unrelated to the port bug: the Neon password was rotated and
  Railway's `DATABASE_URL`/`MIGRATION_DATABASE_URL` updated to match, independent of this
  session's own actions — noted here since any future prompt re-deriving these values needs
  the *current* Railway variable values, not anything cached from 5.2/5.3's own verification
  runs (which used the pre-rotation password and are now stale).

Phase 5, prompt 5.4 (single worker instance deployed to Railway, region `us-east`) is
complete, **with one real bug found in the backend's SSE push path** — not fixed in this
prompt (backend code change, beyond this prompt's worker-deployment scope), flagged clearly
for the very next prompt. No code changed in this session; verification only.
- **Corrected a wrong assumption in the prompt itself before proceeding**: `CHECK_CONCURRENCY`
  (`15`), `CLAIM_TTL_SECONDS` (`120`), and `SCHEDULER_TICK_SECONDS` (`5`) are bare module-level
  constants in `worker/main.py`, never read from `worker/config.py`'s `Settings` or any env
  var — there was nothing to set for them in Railway. Only `DATABASE_URL` and `REGION` are
  real settings for this service; `CHECK_INTERVAL_SECONDS`/`HTTP_TIMEOUT_SECONDS`/
  `HTTP_VERIFY_SSL` were correctly left unset (safe defaults). Also confirmed the worker has
  no Alembic directory at all — no migration-vs-runtime URL split is needed here, unlike the
  backend; a single `DATABASE_URL` (`ssl=require` form) is sufficient.
- **Worker service created and verified fully working**: `REGION=us-east`, same rotated Neon
  `DATABASE_URL` as the `api` service, no public domain generated (confirmed staying
  "Unexposed"). Startup log confirmed correct: `Worker starting (region=us-east,
  interval=300s, tick=5s, timeout=10s, concurrency=15)`.
- **Verified end-to-end against the real deployed `api` service**: registered a throwaway
  account (hit one **transient `500 Internal Server Error` on the very first request** after
  a period of the `api` service being idle — retried successfully immediately after, and the
  original email also succeeded on a second attempt with no partial/duplicate state left
  behind; consistent with Neon's serverless compute cold-starting after inactivity, not a
  code bug — flagged as a real production characteristic to be aware of, not fixed here).
  Created 3 real targets (`example.com`, `.org`, `.net`); all three were claimed and checked
  by the `us-east` worker within 5-7 seconds of creation (`ensure_schedule_rows`'s lazy
  per-region backfill + `claim_due_targets`'s `FOR UPDATE SKIP LOCKED` claim cycle, both from
  Phase 2, confirmed working against Neon for the first time). Real timing/cert data
  populated correctly (`dns_ms`/`tcp_ms`/`tls_ms`/`ttfb_ms`, real Cloudflare-issued certs,
  correct `tls_cert_days_remaining`), `region: "us-east"` tagged correctly throughout,
  `consecutive_failures: 0` confirming the schedule row updates correctly on success. No
  connection drops or pool exhaustion observed against Neon's pooled endpoint under this
  session's sustained polling.
- **Real bug found while verifying the SSE requirement**: connected to `GET /targets/stream`
  *before* creating a target (ruling out a race — confirmed `: connected` was received first),
  then created a target and confirmed via `GET /targets/status` that it was genuinely checked
  moments later — yet the still-open SSE connection received only `: connected` and keep-alive
  comments, never the `check_update` event. **Root cause**: `backend/realtime.py`'s
  `run_listener()` opens its one long-lived `LISTEN checks_inserted` connection via
  `settings.asyncpg_database_url` — the same `DATABASE_URL` used for ordinary app traffic,
  which on Railway is Neon's **pooled** (`-pooler`) endpoint. Neon's pooler runs in
  transaction-pooling mode by default, and Postgres `LISTEN`/`NOTIFY` does not work reliably
  over a transaction-pooled connection (a documented Neon limitation, not a guess) — `LISTEN`
  registers against one specific physical backend session, but a pooled connection's
  underlying backend can be swapped between queries, so a NOTIFY sent while a different
  physical connection is attached is never delivered to that session. This never surfaced
  locally because Docker Compose's Postgres has no pooling at all. **Not fixed in this
  prompt** — recommended fix: a separate setting (e.g. `LISTEN_DATABASE_URL`) pointing at
  Neon's direct (non-pooled) connection string, used only by `run_listener()`, leaving
  ordinary app traffic on the pooled `DATABASE_URL` unchanged. This is a real regression in a
  shipped Phase 1 feature (real-time dashboard push) and should be fixed before the frontend
  is deployed, since the dashboard's live-update/toast behavior depends on it entirely.
- All verification accounts/targets/checks deleted afterward via the real `DELETE /auth/me`
  cascade; confirmed via subsequent `401`s on login that both accounts are gone.
- Not touched in this prompt, per its explicit scope: the frontend, the second worker region,
  any code fix for the LISTEN/NOTIFY finding above.

**Next: fix the Neon pooled-connection LISTEN/NOTIFY bug found in 5.4** (add a direct,
non-pooled connection string setting for `backend/realtime.py`'s `run_listener()`) before
continuing to Phase 5's remaining steps — second worker region (`eu-west` or similar),
cross-origin verification via local frontend against the deployed backend, then the actual
Vercel deploy.

Phase 5, prompt 5.4.1 (SSE LISTEN/NOTIFY fix for Neon's pooled connection) is complete. Fixes
the bug found during 5.4's live verification — backend-only, `api`-service-only change.
- **New setting `LISTEN_DATABASE_URL`** (`backend/config.py`, `str | None = None`) — a
  direct (non-pooled) Neon connection string, used only by a new `listen_asyncpg_url`
  property. Falls back to `DATABASE_URL` when unset, same pattern as `MIGRATION_DATABASE_URL`
  from 5.3 — so local dev/Docker Compose (a single unpooled Postgres, where this distinction
  never mattered) needs zero changes. `asyncpg_database_url`'s dialect-stripping logic was
  factored into a shared module-level `_strip_asyncpg_dialect_suffix()` helper (mirroring the
  same-named helper already in `worker/config.py`) so both properties share it rather than
  duplicating the two-line strip.
- **`backend/realtime.py`'s `run_listener()`** now connects with `settings.listen_asyncpg_url`
  instead of `settings.asyncpg_database_url` — the one-line fix. `run_listener`'s docstring
  updated to explain why, pointing at `config.py`'s fuller explanation.
- **Confirmed the worker needs zero changes**: its `NOTIFY` calls (`SELECT pg_notify(...)`
  inside the same transaction as `insert_check`/`reschedule_target`) have no session-affinity
  requirement — sending a NOTIFY works fine over a pooled connection regardless of which
  physical backend handles it; only the *receiving* `LISTEN` side needs a stable, dedicated
  session, which is exactly what broke. No `worker/` files touched.
- 4 new tests: `test_config.py` gained 3 (`listen_asyncpg_url` falls back to `DATABASE_URL`
  when unset, prefers `LISTEN_DATABASE_URL` when set, strips the `+asyncpg` suffix correctly);
  `test_realtime.py` gained 1 — a regression test mocking `asyncpg.connect` to assert
  `run_listener()` actually connects with the direct URL, not the pooled one, closing the gap
  `test_realtime.py`'s own docstring had flagged since Phase 1 ("run_listener isn't unit
  tested... covered by manual verification instead" — now partially is, for exactly the part
  that broke). 122 backend tests total (was 118), all passing against a rebuilt `api` image.
- **Verified locally end-to-end**: rebuilt `api`, recreated the running dev container,
  confirmed `/health` still 200 and the boot log unchanged. Registered a throwaway account,
  opened a real SSE connection, created a target while it was live, and confirmed **two real
  `check_update` events arrived** (one per local worker region, `eu-west` and `local`) —
  proving the `LISTEN_DATABASE_URL`-unset fallback to `DATABASE_URL` genuinely still works
  against local Postgres exactly as before this change. Verification account (and its cascaded
  target) deleted afterward via the real `DELETE /auth/me` flow.
- **Production verification against the real deployed Railway `api` service and Neon is not
  yet done** — this requires the code to actually be deployed first (push this commit, let
  Railway redeploy, then set `LISTEN_DATABASE_URL` in the Railway dashboard to Neon's direct
  connection string and redeploy again), which is outside this prompt's "commit, don't push"
  scope. Documented in `backend/README.md`'s new "LISTEN_DATABASE_URL (production — Neon's
  pooler breaks LISTEN/NOTIFY)" section exactly how to get Neon's direct connection string
  (the dashboard's Connection Details panel has a pooled/direct toggle — same host, no
  `-pooler` segment) and what value to set. Once deployed, the follow-up verification is the
  same technique 5.4 used: connect to `GET /targets/stream` first (confirm `: connected`),
  then create/trigger a real check, and confirm the `check_update` event actually arrives this
  time — not just that the check itself lands (which already worked in 5.4; only the push was
  broken).
- Not touched in this prompt, per its explicit scope: the worker, the frontend, the second
  worker region.

**Next: push this commit, redeploy the `api` service on Railway, set `LISTEN_DATABASE_URL` to
Neon's direct (non-pooled) connection string, and re-verify the SSE push live** (the same
connect-first-then-trigger-a-check technique from 5.4) before continuing to Phase 5's
remaining steps — second worker region, cross-origin verification via local frontend against
the deployed backend, then the actual Vercel deploy.

`LISTEN_DATABASE_URL` was set on Railway and redeployed; re-ran the 5.4 SSE technique
(connect first, confirm `: connected`, then create a real target, confirm it's checked, then
confirm the push arrives) against the live service — **the fix works in production**: a real
`check_update` event arrived carrying the full expected payload
(`region: "us-east"`, real timing/cert data). One transient, non-reproducible blip during
cleanup (a `DELETE`'s effect appeared not to have landed on an immediate follow-up read, self-
resolved on retry, confirmed stable across three subsequent checks and a successful
re-registration of the freed email) — treated as test-tooling noise, not a backend issue,
since it never recurred and every other read was immediately consistent.

**Phase 5, prompt 5.5 (cross-origin cookie/CORS verification: local frontend → deployed
backend) is complete. The cross-origin contract is confirmed working — nothing needed
fixing.** This was flagged in the 5.1 report as the riskiest untested part of the whole
deploy phase; it now holds up under a real browser end to end.
- Created `frontend/.env.local` (gitignored, confirmed via both the root and `frontend/`
  `.gitignore`) with `NEXT_PUBLIC_API_URL` pointed at the live Railway backend; ran `next dev`
  locally so `localhost:3000` (HTTP) talked to the real deployed HTTPS backend — a genuine
  cross-origin scenario, no Vercel involved.
- **Verified with Playwright driving a real Chromium browser** (not curl — this specifically
  needed real browser cookie-jar/CORS enforcement, which curl doesn't replicate): registered a
  throwaway account, confirmed redirect to `/dashboard`, added a real target, confirmed the
  "● live" SSE indicator, confirmed the summary strip's up-count went `0 → 1` **in place with
  no reload** (real proof the 5.4.1 SSE fix works through an actual browser's `EventSource`,
  not just curl's `-N`), reloaded the page and confirmed it stayed on `/dashboard` rather than
  bouncing to `/login` (the real test of cross-origin session persistence, not just that login
  itself returns 200).
- **Cookie confirmed correctly stored via `context.cookies()`** (Playwright's own read of the
  browser's real cookie jar, not a header inspection): `domain:
  uptime-monitor-production-cff9.up.railway.app, httpOnly: true, secure: true, sameSite:
  "None"` — exactly the contract 5.3/5.4 set out to build and 5.3-verify/5.4 already confirmed
  via raw `Set-Cookie` headers; this is the first time it's confirmed as actually *accepted and
  stored* by a real browser, not just sent correctly by the server.
  `allow_credentials`/`CORS_ORIGINS` (already including `http://localhost:3000` since 5.3)
  needed no changes.
- Four `401` console messages appeared during the flow — investigated, not a bug: both
  `SiteHeader` and `RegisterPage` independently call `useAuthStatus()` on `/register`'s mount
  (an anonymous visitor correctly gets `401` from `/auth/me`, treated as "not logged in," not
  an error), and `next.config.js`'s `reactStrictMode: true` double-invokes effects once in dev
  — 2 callers × 2 dev-mode invocations = 4. Confirmed by reading `use-auth-status.ts` and
  `next.config.js` directly, not guessed.
- **One unrelated, pre-existing cosmetic observation, not fixed (outside this prompt's
  scope)**: a live-update screenshot caught the newly-added row's own reveal-animation label
  still reading "Pending" for an instant while the summary strip above it had already
  correctly counted the same update as "1 up" with real `35 ms`/`us-east` data — a minor
  animation-timing quirk in the row's reveal sequence (from Phase 3.5), not a data or
  cross-origin bug; the underlying state was already correct.
- Test account deleted afterward via a real in-browser `fetch(..., {credentials: 'include'})`
  call to `DELETE /auth/me` (204, confirmed via the same technique prior prompts used).
  `frontend/.env.local` deleted afterward too, restoring the frontend to its default local
  config (`NEXT_PUBLIC_API_URL` unset → falls back to `localhost:8000`) so a future local dev
  session isn't silently pointed at production; recreate it the same way if this needs
  re-testing later. No tracked files changed this prompt (`.env.local` is gitignored).
- Not touched in this prompt, per its explicit scope: Vercel, the worker, the second region.

**Next: Phase 5's remaining steps — second worker region (`eu-west` or similar, mirroring
5.4's single-region deploy), then the actual Vercel deploy** (frontend build settings,
`NEXT_PUBLIC_API_URL` pointed at the real Railway backend in Vercel's dashboard, confirmed
via this prompt that the cross-origin contract already works) per the 5.1 build order.

Phase 5, prompt 5.6 (second worker region, `eu-west`) is complete. **Both real Railway
regions from the 5.1 report are now running in production simultaneously**, and multi-region
coordination is proven against genuinely independent cloud infrastructure for the first
time — not two local Docker Compose instances labeled differently, and not one instance at a
time as in 5.4.
- Second worker service deployed (same `worker/` Dockerfile/build as `us-east`, only
  `REGION=eu-west` differs, same rotated Neon `DATABASE_URL`, no `LISTEN_DATABASE_URL` —
  confirmed that setting is backend/`api`-only, since the worker never runs `LISTEN`, only
  `NOTIFY`, which has no session-affinity requirement and works fine over Neon's pooled
  connection regardless of region). Startup log confirmed clean:
  `Worker starting (region=eu-west, interval=300s, tick=5s, timeout=10s, concurrency=15)`,
  no crash, no connection errors. No public domain — unexposed, same as `us-east`.
- **Verified end-to-end against the real deployed `api` service and both real worker
  regions**: registered a throwaway account, connected to `GET /targets/stream` first
  (confirmed `: connected`), then created one real target. Two independent `check_update`
  events arrived ~1.2s apart — first `region: "us-east"` (payload's `latest_checks` showing
  only `us-east` at that instant), then `region: "eu-west"` (payload's `latest_checks` now
  showing **both** `eu-west` and `us-east` together, neither overwriting the other) — this is
  live proof of the Phase 2 design's "always push the target's complete per-region map, never
  a partial delta" invariant holding under real infrastructure, and proof the two regions'
  data coexists rather than being collapsed or overwritten. `GET /targets/status` confirmed
  the same final state independently.
- **Confirmed no double-checking within either region** using the CSV export endpoint
  (`GET /targets/{id}/export?region=...`) to directly inspect each region's raw check-row
  history rather than trusting only the "latest check" view: **`Total checks,1`** for both
  `us-east` and `eu-west` — exactly one row each, proving neither region's single worker
  instance checked the target more than once for this test window. (Proving the stronger
  Phase 2 guarantee — that two same-region workers can't double-claim — isn't reachable with
  one instance per region in this deployment; that mechanism was already proven mechanically
  in Phase 2's local testing and doesn't change per-region, only per-worker-instance.)
  Real, independent per-check data confirmed too: distinct `checked_at` (39.203s vs 40.399s),
  distinct `latency_ms` (35 vs 37) and DNS/TCP/TLS/TTFB breakdowns — genuinely separate network
  measurements to the same real target, not shared/derived data.
- Test account (and its cascaded target/checks) deleted afterward via the real
  `DELETE /auth/me` flow; confirmed via a stable `401` on repeated login attempts (one
  transient-looking terminal output artifact on the very first post-delete check, same
  category as 5.4.1's — resolved immediately on a clean retry, not a backend issue).
- Not touched in this prompt, per its explicit scope: Vercel, any frontend code, `LISTEN_DATABASE_URL`/`api`
  service configuration (already correct from 5.4.1).

**Phase 5 is now down to one remaining step per the 5.1 build order: the actual Vercel
deploy** — frontend build settings, `NEXT_PUBLIC_API_URL` pointed at the real Railway backend
in Vercel's dashboard, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` per the 5.1 report's flagged
build-time concern. The cross-origin cookie/CORS contract (5.5) and both worker regions (5.4,
5.6) are already proven working against the real deployed backend, so the Vercel deploy
itself should be the last real unknown before a wrap-up/regression verification prompt.

**Vercel deployment done** — the user deployed the frontend directly (not a numbered prompt in
this session; the build/env configuration steps themselves weren't performed or observed here,
so they're not documented — only the CORS finding below was diagnosed and fixed in this
session). Production URL: **`https://uptime-monitor-atf-labs.vercel.app`** (Vercel project
`atf-labs`), already present in Railway's `CORS_ORIGINS` for the `api` service.
- **Real issue found and resolved, no code change needed**: every `OPTIONS` preflight from the
  browser was getting a real `400 "Disallowed CORS origin"`. Root cause: Vercel gives every
  individual deployment its own unique hash-suffixed URL
  (`uptime-monitor-<hash>-atf-labs.vercel.app`, e.g.
  `uptime-monitor-856u19z8y-atf-labs.vercel.app`) *in addition to* the stable production alias
  (`uptime-monitor-atf-labs.vercel.app`) — these are genuinely different `Origin` values to a
  CORS check, and only the stable alias is in `CORS_ORIGINS`. The user had been browsing a
  deployment-specific hash URL, not the production alias.
  - Confirmed `config.py`'s `cors_origins_list` parsing itself was never the bug (correctly
    splits/strips/drops-empties); confirmed via direct `curl -X OPTIONS` probes against the
    live backend that the exact production-alias origin already returned `200`, while the
    hash-suffixed URL the user was actually on returned `400` — isolating the mismatch to
    "which URL is being browsed," not any backend logic.
  - **Resolved by browsing the stable production URL instead of the deployment-specific one** —
    zero backend/code changes. Flagged, not implemented: a broader fix (`allow_origin_regex`
    matching any `uptime-monitor-*-atf-labs.vercel.app`) would let every preview deployment
    talk to this same backend too, at the cost of a looser CORS allowlist — not pursued since
    the user only needs the production URL working today.
  - **Worth remembering for later prompts**: always test/share the stable
    `uptime-monitor-atf-labs.vercel.app` URL, not whatever hash-suffixed URL Vercel's own
    dashboard/CLI shows immediately after a deploy — that per-deployment URL will never match
    `CORS_ORIGINS` as currently configured, by design, and that's expected, not a bug to chase
    each time it comes up again.

**Next: Phase 5 wrap-up/regression verification** (mirroring the pattern every prior phase has
closed with) — full regression pass against the now-fully-deployed stack (Vercel + both
Railway worker regions + Neon), confirming Phase 0-4 invariants (ownership, rate limiting,
`JWT_SECRET` fail-fast, SSRF, alerting, export) all still hold end-to-end through the real
production URL, not just the pieces verified individually across 5.2-5.6.

Phase 5, prompt 5.7 (full production walkthrough + Resend sender confirmation) is complete.
**The full production stack — Vercel + Railway (both worker regions) + Neon, SSE, and email —
is now verified working end to end through a real browser and real email delivery, with two
real, previously-undiscovered bugs found and fixed along the way.** No application code
changed; every fix this prompt was a Railway dashboard configuration value.
- **Real bug #1, found immediately, blocking everything**: the production Vercel URL was
  returning a `302` to `vercel.com/sso-api` for every anonymous request — **Vercel Deployment
  Protection was set to "All Deployments,"** gating the production custom-domain-less URL
  itself, not just previews. Confirmed via both a real Playwright browser and a raw `curl`
  (ruling out a browser-specific quirk) before reporting it. User fixed it by turning off
  "Require Log In" entirely in Vercel's Project Settings → Deployment Protection — no
  redeploy needed, confirmed via a fresh incognito load and a follow-up `curl` both returning
  `200` directly, no auth redirect. **This would have silently blocked every real visitor,
  including anyone reviewing this as a portfolio project** — a genuinely high-value catch for
  a walkthrough prompt to have surfaced.
- **Full browser walkthrough against the real production URL, via Playwright (not curl —
  needed real cookie-jar/CORS enforcement)**: registered a throwaway account, confirmed
  redirect to `/dashboard`; confirmed the session cookie on the Railway API origin (`secure:
  true, httpOnly: true, sameSite: "None"`); added a real target and — screenshotted as visual
  proof — watched **both `us-east` and `eu-west` region badges appear on the row live, with no
  reload**, the summary strip's up-count correctly reaching `2`, and cross-checked the exact
  rendered values against a direct `GET /targets/status` call from within the same browser
  context (byte-for-byte match: same `checked_at`/`latency_ms`/timing per region). Reloaded —
  session persisted (still `/dashboard`, not bounced to `/login`). Logged out — landed on
  `/login`; a subsequent direct visit to `/dashboard` correctly redirected back to `/login`,
  and `GET /auth/me` independently confirmed `401` — the session is genuinely cleared
  server-side, not just hidden client-side. Eight `401` console messages appeared across the
  whole run, all attributable to the same by-design "probe auth, treat 401 as not-logged-in"
  pattern from 5.5 occurring at the two genuinely-anonymous points in the script (initial
  `/register` load, and the post-logout `/dashboard` visit) — this is a production build
  (no React StrictMode double-invoke, unlike 5.5's dev-server run), so the count here reflects
  real component/fetch structure, not a dev-only artifact; still not a bug, confirmed by
  reading the actual call sites.
- **Real bug #2 and #3, found via an actual received email, not just config inspection**:
  triggered a real password-reset email against the account owner's own real address (explicit
  go-ahead obtained first, matching the 4.6.1/4.9 precedent, since Resend's sandbox sender can
  only deliver to the Resend account's own verified address). The first email showed **two
  real misconfigurations at once**: the sender rendered as the bare `onboarding@resend.dev`
  with no display name (meaning `RESEND_FROM_EMAIL` on Railway had been explicitly set to the
  unlabeled address, overriding `config.py`'s own correct default), and the reset link pointed
  at `http://localhost:3000/reset-password?...` in production — meaning `FRONTEND_URL` had
  never been updated from its default when Vercel went live, exactly the risk the 5.1 report
  flagged ("`CORS_ORIGINS`/`FRONTEND_URL` — update together" — only `CORS_ORIGINS` actually
  was). **This was a live, unqualified production bug**: any real user requesting a password
  reset right now would have received a completely unusable link. Fixed by setting
  `RESEND_FROM_EMAIL=Uptime Monitor <onboarding@resend.dev>` and
  `FRONTEND_URL=https://uptime-monitor-atf-labs.vercel.app` on the Railway `api` service.
  A second, fresh reset email (initially not found — landed in spam, a known/expected
  characteristic of Resend's shared, unverified sandbox sender, not a bug, and already flagged
  as deferred in the 5.1 report pending a verified custom domain) confirmed both fixes: sender
  correctly read `Uptime Monitor <onboarding@resend.dev>`, and the link correctly pointed at
  `https://uptime-monitor-atf-labs.vercel.app/reset-password?token=...`.
- **Real gap noticed while diagnosing the email bug, flagged not fixed (outside this prompt's
  scope)**: `POST /auth/forgot-password` calls `await send_email(...)` without checking or
  logging its return value — unlike `realtime.py`'s alerting evaluators, which explicitly
  check `sent = await send_email(...)` and skip bookkeeping on failure (a lesson from 4.6.1's
  "real bug #2"). A failed reset-email send today would be invisible from the API response
  (which always returns the same generic 200 by design, for anti-enumeration) and wouldn't
  even show up as a log line pointing at *why* — only a broader Resend-client-level log, if
  any. Worth applying the same "check and log the return value" treatment here in a future
  pass, though the generic-200 anti-enumeration response itself should stay unchanged either
  way.
- Cleanup: both the throwaway `@example.com` browser-walkthrough account and the real
  `m.attifff@gmail.com` production account (plus an accidental extra registration under the
  same real email, created by my own "confirm the address is genuinely free" check and deleted
  immediately after) were deleted via the real `DELETE /auth/me` flow; confirmed via
  subsequent `401`s on login. No test data remains under any account touched this prompt.
- Not touched in this prompt, per its explicit scope: any application code (every fix was a
  Railway dashboard value), the worker, any new frontend work.

**Phase 5 is functionally complete and genuinely production-verified**: Neon (5.2), the
backend on Railway with correct CORS/cookie/DATABASE_URL handling (5.3, 5.3-verify), the SSE
LISTEN/NOTIFY fix (5.4.1), both real worker regions (5.4, 5.6), the cross-origin cookie
contract (5.5), the Vercel frontend (this prompt, after fixing Deployment Protection), and
correct email sender/link configuration (this prompt) are all proven working together against
real infrastructure, not individually. **Next: Phase 5's own wrap-up/regression pass**
(confirming Phase 0-4 invariants — ownership, rate limiting, `JWT_SECRET` fail-fast, SSRF,
alerting, export — still hold through the real production URL end-to-end) **or, if that's
judged sufficiently covered by this prompt's walkthrough plus 5.3-verify/5.4/5.6's own
regression checks, proceed straight to Phase 6** (README rewrite, ADRs, `LOAD_TESTING.md`
against the live deployed instance) per CLAUDE.md's phase plan — worth explicitly deciding
which, rather than assuming, before the next prompt begins.

Phase 5, prompt 5.8 (production hardening, dependency updates, small fixes) is complete.
**One real, previously-undiscovered production bug found and fixed**: rate limiting was
completely non-functional on the live deployment.
- **Fixed the 5.7 forgot-password gap**: `routers/auth.py`'s `forgot_password` now checks
  `send_email`'s return value and logs a warning on failure (new `logger =
  logging.getLogger(__name__)`), same "log it, don't crash, don't pretend it sent" pattern as
  `realtime.py`'s alert evaluators. Token creation is still unconditional — delivery and
  issuance stay separate concerns, per 4.7's original design. New regression test
  (`test_forgot_password_still_creates_a_usable_token_when_the_send_fails`) — hit a real,
  environment-specific pytest quirk while writing it: `conftest.py` imports `routers.auth`
  (creating its logger) before running migrations in-process, and Alembic's `env.py` calls
  `logging.config.fileConfig`, whose `disable_existing_loggers=True` default silently disables
  any logger already created by that point — a test-process-only artifact (production runs
  Alembic as a fully separate process that exits before uvicorn starts) fixed by explicitly
  re-enabling the logger in the test.
- **`CORS_ORIGINS` confirmed exact-match, no stray entries**: verified twice — behaviorally
  (the two expected origins return `200`, a previously-seen preview-hash URL, an unrelated
  origin, and a literal `*` all correctly return `400`) and then directly via the user pasting
  Railway's raw value: `http://localhost:3000,https://uptime-monitor-atf-labs.vercel.app` —
  exactly the two intended values.
- **Full git-history secret grep, genuinely clean**: pickaxe/regex searches across `--all`
  history for the Neon password/host fragments, `neondb_owner`, a Resend-key shape (`re_...`),
  any JWT-shaped three-segment token, and any `DATABASE_URL`/`JWT_SECRET`/`API_KEY` assignment
  with a real-looking (non-placeholder) value — all clean. The one `.env` file ever tracked
  (Phase 0, before the gitignore fix) was confirmed to be git's canonical **empty**-blob hash —
  0 bytes, never held a real value. The only literal `JWT_SECRET` ever committed was the
  placeholder string `change-me-in-production`, already remediated in Phase 0.
- **Real bug found and fixed: rate limiting was not functioning in production at all** —
  confirmed by sending 8+ consecutive failed `/auth/login` attempts against the live Railway
  service with no spoofed headers and never once getting a `429` (configured limit: 5/minute).
  Root-caused precisely: uvicorn's `ProxyHeadersMiddleware` defaults to trusting
  `X-Forwarded-For` only from a directly-connecting peer at `127.0.0.1`; on Railway the direct
  peer is Railway's own edge (never `127.0.0.1`), so the header was silently never trusted and
  `request.client.host` (slowapi's rate-limit key) reflected Railway's own internal connection
  info instead of a stable real client IP — read uvicorn's own middleware source to confirm
  this precisely rather than guessing. Fixed via `--proxy-headers --forwarded-allow-ips='*'` on
  the uvicorn invocation in both `backend/Dockerfile`'s CMD (`'*'` is safe here specifically
  because Railway is the only path to this container — no direct-internet route exists that
  could exploit a trusted-everyone policy). **Verified locally** (Docker Compose, simulating a
  trusted-proxy scenario the same way): two different spoofed `X-Forwarded-For` values each
  independently got their own `5-then-429` budget, proving distinct real-IP keying now works.
  **Not yet verified against the live Railway deployment** — requires this commit to be pushed
  and redeployed first, same pattern as 5.4.1's fix.
- **Basic security headers added** (`main.py`, a new `add_security_headers` HTTP middleware):
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin` — deliberately minimal, no full CSP, since this API only
  ever serves JSON (the frontend is a separate app on Vercel with its own header story).
  Confirmed live on the local stack's `/health` response.
- **`npm audit` (frontend)**: bumped `next` `14.2.0` → `14.2.35` (confirmed the latest 14.2.x
  patch release) — a clean, same-minor-line patch that fixes roughly a dozen of the flagged
  CVEs. The remaining ~23 advisories share one trait: their earliest fix is Next 16.3.5, a real
  major-version jump (breaking changes, React 19 requirement) — **flagged as a Phase 6+
  follow-up, not attempted here**. `tsc --noEmit` clean after the bump; `next build` not run
  since the user's own `next dev` was occupying port 3000/`.next` at the time (established
  project rule).
- **`pip-audit` (backend + worker)**: both Dockerfiles now upgrade `pip` itself before
  installing requirements (`python:3.12-slim`'s bundled pip had several path-traversal/tarfile
  CVEs, all fixed by bumping to the latest release) — confirmed clean after rebuilding both
  images. The one remaining finding, `ecdsa` (backend only, pulled in transitively by
  `python-jose` as an unused pure-Python fallback backend) has **no available fix** — the
  maintainers consider its timing side-channel out of scope — but this app only ever signs
  JWTs with `HS256` (HMAC), never touching the vulnerable EC-specific code path; documented as
  an accepted, inert finding rather than silently ignored.
- **Vercel Deployment Protection re-confirmed still off**: the production URL returns a real
  `200` directly (no `vercel.com/sso-api` redirect, no `_vercel_sso_nonce` cookie) — the 5.7
  fix held.
- **124 backend + 36 worker tests, all passing** (was 122 + 36 after 5.4.1) — the 2 new tests
  are the forgot-password failure case and the security-headers check.
- **Open question raised, not yet resolved**: a direct Neon row-count query (run by the user,
  not assumed) showed **1 user, 1 target, 26 checks** remaining in production — a real,
  non-empty result that doesn't match any of this phase's own verification passes (every
  account created across 5.2-5.8 was explicitly deleted and confirmed via a subsequent `401`,
  and none of those targets lived long enough to accumulate 26 checks — that count implies
  something checked continuously by both regions for roughly two hours). Asked the user
  directly whether this is their own real usage (registered/added a target themselves while
  testing the site) or genuine leftover data needing cleanup — **awaiting their answer**, not
  assumed either way. Flagged here so it isn't silently lost; whoever picks this up next should
  resolve it before treating Neon as clean.
- Not touched in this prompt, per its explicit scope: any UI/feature work, the Next 15/16
  major upgrade, the worker (no equivalent proxy-header issue exists there — it makes outbound
  HTTP requests, never receives inbound ones).

**Next: resolve the open Neon-data question above, then do Phase 5's wrap-up/regression pass**
(or confirm it's sufficiently covered already) before deciding whether to proceed to Phase 6.

**Phase 5, prompt 5.9 (wrap-up + full regression verification) is complete. Phase 5 is marked
complete — moving to Phase 6 next.** One real production bug (rate limiting, found in 5.8)
was fixed, pushed, and re-verified live in this pass; every other Phase 5 piece and every
Phase 0-4 invariant checked held with no regressions.
- **Local**: rebuilt both images fresh from the committed state — **160 tests total (124
  backend + 36 worker)**, all passing, up from 147 (111 + 36) at the end of Phase 4. Worker
  count unchanged (Phase 5 never touched worker code) — every net-new backend test maps to a
  real Phase 5 addition (CORS, config settings, the realtime listener regression test, the
  forgot-password failure case, security headers). `tsc --noEmit` clean; `next build` not run
  (port 3000 occupied by the user's own `next dev` both times this phase needed it) —
  consistent with this project's established practice since prompt 3.7.
- **Finished committing 5.8's still-pending work first** (it had been implemented and tested
  but never committed/pushed) — see that entry above for the full rate-limiting bug writeup.
  Pushed and waited for Railway's redeploy, then re-tested rate limiting live for the first
  time: login, register, and target-creation all now fire at exactly their configured limits
  (`5-then-429`, `3-then-429`, `10-then-429`) — confirmed **broken** immediately pre-push
  (8+ consecutive logins, zero `429`s) and **fixed** immediately post-push, the clearest
  possible before/after proof.
- **Ownership enforcement re-confirmed with a fresh two-user test** against production: user
  B's `/targets`/`/targets/status` never showed user A's target; `GET`/`DELETE` on A's target
  both `404` for B.
- **`JWT_SECRET` fail-fast deliberately not re-run** — 5.3-verify did the actual live
  strip/crash/restore test against this same Railway service very recently in this phase, and
  `git log -p backend/config.py` confirms the required-no-default field definition hasn't
  changed since. Stated reasoning explicitly rather than silently skipping or needlessly
  repeating a destructive test with nothing new to find.
- **SSRF, per-user SSE filtering, and per-region independence** all re-confirmed fresh against
  production in this pass (private IP/localhost/metadata-IP all `400` at creation; two
  concurrent real SSE connections showed strict per-user isolation; one target's SSE payload
  showed `eu-west` and `us-east` coexisting with genuinely distinct timing/latency data, never
  merged).
- **The three 5.7 bugs re-confirmed**: Vercel Deployment Protection still off (live `200`, no
  SSO redirect). `RESEND_FROM_EMAIL`/`FRONTEND_URL` verified by code/history review rather than
  another real email send — `git log -p` shows neither field's definition or Railway value
  changed since 5.7 — deliberately avoided sending a third real email to the account owner's
  inbox for a fact already provable without one.
- **CSV export reconfirmed working and ownership-enforced** (`200` for the owner, `404` cross-
  user) — output formatting itself untouched, per the explicit Phase 6 deferral.
- All test accounts/targets created during this pass (two ownership-test users, three
  rate-limit-test users and their cascaded targets) deleted and reconfirmed gone via fresh
  `401`s — kept fully separate from, and not resolving, the still-open Neon question below.
- **Neon-data open item, now resolved**: the 5.8 finding of 1 user/1 target/26 checks in
  production Neon that didn't match any known verification pass — the user confirmed after
  this prompt closed that it's their own real account/target, not leftover test data. Left
  untouched, as it should be; nothing to clean up. Phase 5 has no remaining open items.
- Full deferred-to-Phase-6 list (nothing silently dropped): CSV export formatting, PDF export,
  the Next.js 15/16 major upgrade (14.2.35 already patches the fixable-without-breaking-changes
  subset), any UI refresh/new feature work, a full security audit beyond this phase's baseline
  hardening pass, and the README rewrite/ADRs/`LOAD_TESTING.md` against the live instance.

**Phase 5 complete.**

Phase 6, prompt 6.1 (familiarization + design report) is complete. Read-only — no application
code, no new files, per this prompt's scope. Phase 6 is now scoped as engineering work (fixes,
13 feature additions, UI/UX improvements, infra/scaling), with presentation (README/ADRs/load
testing) moved out to a separate Phase 7. Full report delivered directly in the conversation
(not saved to a file); reread the conversation history if picking this up cold.
- Reviewed `backend/routers/targets.py`, all `backend/models/`, `backend/security/ssrf.py`,
  `backend/rate_limit.py`, `backend/config.py`, `backend/auth/`, `backend/realtime.py`,
  `backend/mail/`, `backend/export.py`, `worker/checker.py`, `worker/main.py`,
  `worker/config.py`, and migrations 001-009 before writing the report.
- Proposed schema for all five new feature areas: `targets` gains request customization
  columns (method/headers/basic-auth/keyword-match) plus `paused`/`check_interval_seconds`/
  `group_id`; new `groups`, `webhooks`, `api_keys` tables. Flagged one real open question:
  "groups/tags" as worded could mean single-membership groups (proposed, simpler) or
  multi-tag labeling (a join table, additive later) — needs confirming before building.
- Keyword/content monitoring: proposed hooking into `checker.py` after a status-code pass,
  recording failures as a distinctly-prefixed `checks.error` string (no new column), and
  rejecting HEAD+keyword_match at the API layer rather than silently overriding it in the
  worker.
- Basic auth credentials: recommended Fernet encryption at rest via a new required,
  no-default `CREDENTIAL_ENCRYPTION_KEY` (mirrors `JWT_SECRET`'s fail-fast treatment, not
  `RESEND_API_KEY`'s optional one) — flagged that this key must be generated and set on all
  three Railway services *before* the migration ships, same lesson as Phase 0/5's
  `JWT_SECRET` deploy coordination.
- Webhooks: proposed a signed-JSON-payload/single-attempt-no-retry design (mirroring
  `mail/client.py`'s existing philosophy), reusing `backend/security/ssrf.py` at both creation
  and send-time (send-time check wrapped in `asyncio.to_thread`, no redirect-following).
  **Flagged the one real hidden dependency for the whole phase**: today's
  `_evaluate_downtime_alert`/`_evaluate_cert_expiry_alert` in `realtime.py` conflate "should
  this condition alert at all" with "send via email" — webhooks need that split into
  condition-eligibility vs. per-channel fan-out *before* webhook sending is added, or a
  webhook would incorrectly inherit the email preference toggle.
- API keys: proposed mirroring `password_reset_tokens`' exact hash-only-storage pattern,
  two scopes (read/full, keys can never manage other keys), and a rate-limiting scheme keyed
  by the API key itself rather than IP (existing `slowapi` limits stay IP-keyed and untouched).
- Retention: proposed a worker-side second `asyncio` task on a ~24h timer (no new deployed
  service), default 90-day window matching the existing heatmap's own window, and flagged an
  undecided product question (plain delete vs. rollup-then-delete) rather than picking one
  unilaterally. Proposed the CSV export note a pruned range rather than silently
  under-representing history.
- Pagination: proposed a cursor-based design (stable under the concurrent insert/delete that
  retention introduces) but flagged that nothing in the current frontend actually needs it yet
  — recommended confirming which of the 13 planned features drives the need before building it.
- Build order: noted that no prior "agreed" Phase 6 build order was actually present in this
  conversation or CLAUDE.md despite the prompt referencing one, and proposed an original
  dependency-ordered sequence instead, explicitly asking for the real one if it exists
  elsewhere. Flagged the alerting-restructuring-before-webhooks dependency as the one ordering
  detail most likely to get missed.
- No code changes, no new files, no migrations in this prompt — report only, pending review
  before Phase 6 implementation begins.

**Next: Phase 6 implementation, pending review of the above report** — in particular the
groups-vs-tags shape, the retain-vs-rollup retention choice, and confirmation of (or a
correction to) the proposed build order.

Phase 6, prompt 6.2 (target request customization + keyword monitoring) is complete — step 1
of the 6.1 build order. Pause/resume, check interval, tags, and every other Phase 6 feature
remain untouched, per this prompt's explicit scope.
- **Schema**: migration `010_add_target_request_customization.py` adds `request_method`
  (nullable — `NULL` preserves the worker's original HEAD-then-GET-on-failure default),
  `request_headers` (JSONB, nullable), `basic_auth_username`/`basic_auth_password_encrypted`
  (nullable), `keyword_match` (nullable), `keyword_match_mode` (`NOT NULL DEFAULT 'contains'`)
  to `targets`. `backend/models/target.py` updated to match.
- **`CREDENTIAL_ENCRYPTION_KEY`** (required, no default, fail-fast — mirrors `JWT_SECRET`
  exactly, per the 6.1 report's recommendation) added to both `backend/config.py` and
  `worker/config.py`. New `backend/security/crypto.py` (`encrypt_secret`) and `worker/crypto.py`
  (`decrypt_secret`) — Fernet, constructed at module import time so a malformed/missing key
  fails the service at startup, not on first use. **This key is NOT yet set on any Railway
  service** — I have no access to Railway's dashboard/CLI from this session, so I could not
  perform or confirm that step myself. **Action required before this migration is deployed**:
  generate one key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
  and set the identical value as `CREDENTIAL_ENCRYPTION_KEY` on all three Railway services
  (`api`, `worker`/us-east, `worker-eu-west`) — deploying without this first will crash all
  three on boot the same way a missing `JWT_SECRET` always has. Documented in both READMEs'
  env-var tables and the "Deploying to Railway" section.
- **Validation** (`backend/routers/targets.py`, shared by `POST /targets` and the new
  `PATCH /targets/{id}`): `request_method` restricted to `GET`/`POST`/`HEAD`;
  `keyword_match_mode` restricted to `contains`/`not_contains`; explicit `request_method="HEAD"`
  + `keyword_match` set → 400; `basic_auth_username`/`basic_auth_password` must be given
  together, never just one → 400.
- **New `PATCH /targets/{id}`** — didn't exist before this prompt; scoped narrowly to name +
  the new customization fields only (no `url` editing, no pause/interval — those stay separate
  Phase 6 features). Uses pydantic's `exclude_unset` so an omitted field is left alone and an
  explicit `null` clears it — except `basic_auth_password`, which is the deliberate
  "blank/omitted always means unchanged" exception matching the edit-form UX (username shown
  back, password never is); clearing `basic_auth_username` removes basic auth entirely.
  404-not-403 on a target that doesn't exist or isn't owned by the caller, same as every other
  target-scoped endpoint — added to both `test_ownership.py`'s cross-user and anonymous-access
  tests. The decrypted (and encrypted) password is never included in `TargetResponse` at all,
  by construction — there's no field for it to leak through.
- **`worker/checker.py`**: `check_url`/`_follow_with_ssrf_check` gained `method`/`headers`/
  `auth`/`keyword_match`/`keyword_match_mode` params, threaded straight into httpx's native
  `headers=`/`auth=` kwargs on every hop. SSRF/redirect revalidation itself is untouched — every
  hop's `Location` is still re-checked exactly as before, regardless of what's configured.
  A failed keyword condition writes `is_up=False` with a distinctly-prefixed `checks.error`
  string ("Keyword match failed: expected/unexpected ...") — no new column, matching the
  existing SSRF/redirect error-message convention.
- **Real bug found and fixed via live verification, not caught by the unit tests**: when a
  target has `keyword_match` set but no explicit `request_method` (the expected common case),
  the original HEAD-then-GET-on-failure default would try HEAD first — and since HEAD has no
  response body, a keyword check against it would spuriously report "not found" even on a page
  that genuinely contains the keyword, every single time. My own worker tests didn't catch this
  because every keyword-match test passed an explicit `method="GET"`. Fixed in `check_url`:
  `method=None` now means GET (not HEAD) whenever `keyword_match` is set. Confirmed against the
  real bug live: a real target against `https://example.com/` with `keyword_match="Example
  Domain"` and no explicit method first failed with the spurious HEAD-body error, then
  succeeded (`is_up=true, error=null`) immediately after the fix and a worker rebuild/restart.
  Added a regression test for exactly this case.
- **`worker/main.py`**: new `_init_connection` hook registers a jsonb codec on every pooled
  asyncpg connection (`request_headers` is the first jsonb column this raw-asyncpg codepath has
  ever needed to read/write — asyncpg doesn't do this automatically outside SQLAlchemy).
  `claim_due_targets`'s SELECT now also pulls the six new `targets` columns; `check_one` decrypts
  `basic_auth_password_encrypted` (if both username and password are set) into an
  `httpx.BasicAuth`, wrapped in its own try/except so a decrypt failure (most likely: the two
  services' `CREDENTIAL_ENCRYPTION_KEY` values have drifted) is logged distinctly and the check
  proceeds unauthenticated rather than being misreported as "target may have been deleted
  mid-check" by the existing broad catch-all.
- **Tests**: 24 new/updated across both suites — backend: `test_target_customization.py` (17:
  create/PATCH validation, blank-means-unchanged, clear-via-null, 404 ownership, encrypted
  password never returned), `test_crypto.py` (2), `test_config.py` (+2, the
  `CREDENTIAL_ENCRYPTION_KEY` fail-fast pair), `test_ownership.py` (extended with PATCH cases).
  Worker: `test_request_customization.py` (10: explicit method/headers/auth passed through,
  both keyword-match modes pass/fail, keyword-match skipped when the status is already down,
  the HEAD-vs-GET regression above), `test_crypto.py` (2, round-trip + wrong-key rejection).
  145 backend tests (was 122 at the 5.9 close), 48 worker tests (was 36), all passing against
  freshly rebuilt images.
- **Verified end-to-end against the real running stack, not just tests**: rebuilt `api`/
  `worker`, confirmed migration `009 → 010` applied cleanly; created real targets exercising
  every new field against real public endpoints — custom `POST` + header against
  `httpbin.org/post` (real 200, header genuinely sent), keyword-match against
  `example.com` (caught the HEAD-body bug live, then confirmed fixed), and — the strongest
  proof — basic auth against `httpbin.org/basic-auth/myuser/mypass`, an endpoint that returns
  401 unless the exact credentials are presented: got a real `200 OK`, proving the full
  encrypt-at-creation → store ciphertext → worker-decrypt → real HTTP Basic Auth pipeline
  works end to end. Re-confirmed SSRF-at-creation still blocks a metadata-IP URL (400). All
  verification targets/user deleted afterward via the real `DELETE /auth/me` cascade, confirmed
  via a subsequent `401` on login. Stack left healthy (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: any frontend UI for these fields (backend/
  worker only, as asked), pause/resume, check interval, groups/tags, any other Phase 6 feature.

**Follow-up fix (same day): a real credential-leak-on-cross-host-redirect vulnerability was
caught by an automated post-commit security review** and fixed immediately, before any further
work. `_follow_with_ssrf_check` passes a target's `headers`/`auth` on every redirect hop it
follows manually (needed for the existing per-hop SSRF revalidation) — but manually following
redirects bypasses httpx's own built-in protection, which strips `Authorization` on a
cross-origin `follow_redirects=True` redirect automatically. Without a fix, a target's
basic-auth password or a secret-bearing custom header (e.g. an API key) would have been
forwarded to whatever third-party host a 3xx response happened to name, not just the host the
user actually configured credentials for.
- Fixed with a new `_redirect_crosses_host()` helper (hostname-only comparison, case/
  trailing-dot normalized) — `headers`/`auth` are dropped for the remainder of the redirect
  chain the moment a hop crosses to a different host, and deliberately never restored even if
  a later hop redirects back to the original host (conservative by design, not re-derived
  hop-by-hop against a moving target).
- 3 new regression tests in `worker/tests/test_request_customization.py` (same-host redirect
  keeps credentials, cross-host redirect drops them, credentials stay dropped after a
  bounce-back) — using real IP literals (`1.1.1.1`/`8.8.8.8`), not domain names, matching
  `test_checker_redirects.py`'s existing convention: `is_url_blocked()` isn't mocked in these
  tests and does a real DNS lookup on every redirect hop, so a made-up hostname fails
  resolution and gets SSRF-blocked instead of actually exercising the code under test — hit
  this exact issue once while writing the tests, fixed by switching to IP literals. 51 worker
  tests total (was 48), 145 backend tests unaffected (this fix is worker-only).
- **Verified against real, live infrastructure, not just mocked tests**: created a real target
  at `https://httpbin.org/redirect-to?url=...httpbingo.org/headers` (a genuine cross-host 302)
  with a custom `X-Secret-Test` header and a `keyword_match` for that header's value —
  `httpbingo.org/headers` echoes back whatever headers it actually received, so a keyword match
  succeeding would have proven a real leak. Real result: `is_up=false, error="Keyword match
  failed: expected \"should-not-leak\" not found"` — proof the header was genuinely not
  forwarded to the second host. Verification target/account deleted afterward, confirmed via a
  subsequent `401` on login.
- Not committed as a separate prompt number — a direct fix to this same prompt's own work,
  found before moving on, not a new feature.

**Next: continue Phase 6 per the 6.1 build order — step 2, pause/resume + configurable check
interval** (bundle its migration with this prompt's `targets` migration's neighbor, per the 6.1
report's reasoning — same table, avoid two back-to-back migrations touching it). Before that
work is deployed, **`CREDENTIAL_ENCRYPTION_KEY` must be generated and set identically on all
three Railway services** — flagged above, not yet done, genuinely blocking.

Phase 6, prompt 6.3 (pause/resume + configurable check interval) is complete — step 2 of the
6.1 build order. Migration `010` had already shipped (prompt 6.2, pushed), so this is a new
migration rather than a bundled one, per the prompt's own either/or. Tags/groups, analytics, and
every other Phase 6 feature remain untouched, per this prompt's explicit scope. The
`CREDENTIAL_ENCRYPTION_KEY` Railway blocker from 6.2 is still open — not this prompt's job to
resolve, flagged again below.
- **Schema**: migration `011_add_targets_pause_and_interval.py` adds `paused`
  (`NOT NULL DEFAULT false`) and `check_interval_seconds` (nullable — `NULL` means "use the
  worker's global `CHECK_INTERVAL_SECONDS`") to `targets`. `backend/models/target.py` updated
  to match.
- **`POST /targets/{id}/pause` and `POST /targets/{id}/resume`** (`backend/routers/targets.py`)
  — both idempotent, both 404-not-403 on a target that doesn't exist or isn't owned by the
  caller, same pattern as every other target-scoped endpoint; added to `test_ownership.py`'s
  cross-user and anonymous-access tests alongside the dedicated new test file. `/resume`
  directly writes `next_check_at = now()` to every region's `target_region_schedule` row for
  the target — **the deliberate, narrow exception to that table's worker-only-write
  convention** the prompt asked for, commented at its one call site and cross-referenced back
  in `TargetRegionSchedule`'s own docstring so it's visible from either file.
- **`check_interval_seconds` is settable via `POST /targets` and the existing
  `PATCH /targets/{id}`** (not a new endpoint) — the prompt didn't specify how a user actually
  sets the interval, and routing it through the general create/edit surface already built in
  6.2 was the natural, lowest-scope-creep choice over inventing a third way to configure a
  target. Added `MIN_CHECK_INTERVAL_SECONDS = 30` (matches `backoff.py`'s own base delay — the
  fastest cadence anything in this system already retries at) as a floor-only validation, no
  ceiling; reused across create and update via a new small `_validate_check_interval_seconds`
  helper, kept separate from `_validate_request_customization` since it's a different concern
  (scheduling, not the request itself). `TargetResponse`/`_target_to_response` extended with
  `paused`/`check_interval_seconds`, same pattern 6.2 used for its own new fields. Pause state
  is deliberately **not** settable via create/PATCH — only through the dedicated endpoints, so
  it can never be flipped as a silent side effect of an unrelated field edit.
- **`worker/main.py`**: `claim_due_targets`'s WHERE gained `AND NOT t.paused` (a paused target
  is excluded from being selected at all, not filtered out after the fact) and its SELECT gained
  `t.check_interval_seconds`. `reschedule_target` gained a `check_interval_seconds` parameter,
  used only on the **success** branch (`check_interval_seconds or settings.CHECK_INTERVAL_SECONDS`)
  — a deliberate design call not spelled out in the prompt: a **failing** target still backs off
  on the standard curve regardless of any custom interval, since a fast custom cadence is meant
  for a healthy target, not license to hammer one that's currently down. `check_one`/`run_cycle`
  thread the new field straight through.
- **Tests**: 3 new worker tests (`test_scheduling.py`: custom interval respected on success,
  falls back to the global default when unset, ignored in favor of the backoff curve on
  failure) plus extended SQL-substring assertions on `claim_due_targets`'s query
  (`AND NOT t.paused`, `t.check_interval_seconds`) — 54 worker tests total (was 51). New
  `backend/tests/test_pause_resume.py` (11 tests: pause/resume state changes, idempotency,
  ownership, auth-required, interval validation) plus 4 new assertions in
  `test_ownership.py` — 156 backend tests total (was 145).
- **Verified end-to-end against the real running stack, not just tests**: rebuilt `api`/
  `worker`, confirmed migration `010 → 011` applied cleanly. Created a real target, let it get
  a genuine first check, paused it, forced it due via direct SQL, and confirmed across two
  scheduler ticks (12s) that it was never picked up — the worker log shows zero lines for that
  target id in that window, and `checked_at` stayed byte-identical. Resumed it and confirmed a
  fresh real check landed within ~8s (`checked_at` advanced, `consecutive_failures`
  incremented) — proof `/resume` genuinely forces immediate pickup rather than waiting out the
  backoff-computed `next_check_at` that would otherwise have been ~30-40s further out. Created
  a second real target with `check_interval_seconds=30` against a genuinely healthy URL and
  confirmed via a direct query that `target_region_schedule.next_check_at` landed ~19s out
  (i.e. ~30s after the check) rather than anywhere near the 300s global default. Re-confirmed
  SSRF-at-creation and the HEAD+keyword_match rejection from 6.2 still hold. All verification
  data deleted afterward via the real `DELETE /auth/me` cascade, confirmed via a subsequent
  `401` on login. Stack left healthy (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: tags/groups, analytics, webhooks, API
  keys, retention, any other Phase 6 feature area from the 6.1 report.

`CREDENTIAL_ENCRYPTION_KEY` has been generated and set on Railway by the user (confirmed
directly, not verified by this session — no Railway access) — the deploy blocker flagged since
6.2 is resolved. Not independently confirmed which of the three services (`api`,
`worker`/us-east, `worker-eu-west`) got it or that all three values match exactly; worth a
real end-to-end production check (same technique as 6.2's basic-auth live verification) once
this branch is actually deployed, rather than assuming it's correct.

Phase 6, prompt 6.4 (monitor tags) is complete — the "groups" item from the 6.1 report,
implemented using the multi-tag shape (a target can carry several labels), not a single
group_id — this resolves the open question flagged since 6.1. Schema and API only, no
frontend, per this prompt's explicit scope; the frontend for tags is its own later prompt
(6.13).
- **Schema**: migration `012_add_tags_and_target_tags.py` adds `tags(id, user_id FK CASCADE,
  name, created_at, UNIQUE(user_id, name))` and `target_tags(target_id, tag_id)` — a pure
  many-to-many join table (composite PK, both FKs `ON DELETE CASCADE`, no columns of its own).
  New `backend/models/tag.py` (`Tag`) and `backend/models/target_tag.py` (the `target_tags`
  Core `Table`, used as the `secondary=` for a `Target.tags <-> Tag.targets` relationship — the
  first many-to-many relationship in this codebase; every other cross-table link so far has
  been one-to-many). `target_tag.py` is deliberately its own tiny module so neither `target.py`
  nor `tag.py` has to import the other's module just to reach the join table.
- **New `backend/routers/tags.py`** (registered in `main.py`): `GET /tags`, `POST /tags`
  (409 on a duplicate name for the same user — name uniqueness is per-user, not global, same
  convention as target-URL uniqueness), `DELETE /tags/{id}` (404-not-403 if not owned;
  `target_tags` rows cascade at the database level, no explicit cleanup code).
- **`POST /targets/{id}/tags` and `DELETE /targets/{id}/tags/{tag_id}`** (in
  `routers/targets.py`, since they're target-scoped first): both ownership-enforced on *both*
  sides — the target must belong to the caller AND the tag must belong to the caller, either
  failing returns the same 404. Both idempotent (attaching an already-attached tag, or
  detaching one that isn't attached, is a no-op success, not an error) — same convention 6.3
  established for pause/resume.
- **`GET /targets` now returns each target's full `tags` list**, plus an optional `?tag=<name>`
  filter (by tag **name**, not `tag_id` — the more natural shape for a query-string filter,
  matching how `region` is already a plain string elsewhere in this file rather than a numeric
  id a caller would have to look up first). Deliberately scoped to `GET /targets`
  (`TargetResponse`) only, not `GET /targets/status` (`TargetStatusResponse`) — consistent with
  6.2/6.3's own precedent of keeping target-configuration metadata off the check-status
  response, which is reserved for check-result data. `GET /targets/status` tags/filtering is
  left for whichever later prompt actually wires the frontend dashboard to it.
- **Real async-ORM correctness issue, caught and designed around before it could become a live
  bug**: SQLAlchemy's async engine doesn't support lazy-loading a relationship outside an
  awaited context (accessing an unloaded `target.tags` inside a plain sync function would raise
  `MissingGreenlet`), and it was genuinely unclear whether `AsyncSession.refresh()` reliably
  keeps a `selectinload`-loaded relationship populated afterward. Rather than gamble on that,
  `_target_to_response()` now takes `tags` as a **required, explicit argument** instead of
  reading `target.tags` internally — every call site either knows the answer trivially (a
  brand-new target from `create_target` always has `tags=[]`) or captures `list(target.tags)`
  into a plain Python variable immediately after an eager `.options(selectinload(Target.tags))`
  fetch, *before* any subsequent `db.refresh()` call, sidestepping the ambiguity entirely
  rather than relying on undocumented-feeling framework behavior.
- **Tests**: `test_tags.py` (11: CRUD, alphabetical listing, duplicate-name 409, same name
  allowed across different users, empty/overlong name rejected, cross-user list/delete
  isolation, auth-required) and `test_target_tags.py` (18: attach/detach + idempotency,
  attach/detach 404 on a nonexistent tag, **both** cross-ownership directions — another user's
  tag onto my target, and my tag onto another user's target — detach-side cross-ownership,
  cross-user invisibility via target list, the `?tag=` filter returning the exact subset
  including with two different users each having their own same-named tag, deleting a tag
  detaches it everywhere, deleting a target leaves its tags alone, auth-required) plus 6 new
  assertions in `test_ownership.py`'s consolidated cross-user/anonymous tests. 183 backend
  tests total (was 156). No worker changes in this prompt — worker tests unaffected.
- **Verified end-to-end against the real running stack, not just tests**: rebuilt `api`,
  confirmed migration `011 → 012` applied cleanly. Created two real tags and three real
  targets, attached "production" to two of them and "staging" to the third via real HTTP
  calls, and confirmed `GET /targets?tag=production` returned exactly the two matching ids and
  `?tag=staging` returned exactly the one — real proof of the filter's correctness, not just
  the mocked/DB-backed test suite. Registered a second real user and confirmed live: their
  `GET /tags` came back empty (never sees the first user's tags) and attempting to attach the
  first user's real tag id to their own target returned a real 404. All verification data
  (both accounts, cascading their targets/tags) deleted afterward via the real
  `DELETE /auth/me` flow, confirmed via a subsequent `401` on login. Stack left healthy
  (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: any frontend code (deferred to prompt
  6.13), analytics, webhooks, API keys, retention, any other Phase 6 feature area.

Phase 6, prompt 6.5 (windowed uptime/latency-percentile/MTTR analytics) is complete. Backend
computation only, no frontend, per this prompt's explicit scope — the frontend for this is its
own later prompt (6.14). The user chose to build this ahead of API keys (the 6.1 report's own
suggested next item) — sequencing is the user's call, not a fixed order to enforce.
- **New endpoint `GET /targets/{id}/analytics?window=24h|7d|30d|90d`** (default `7d`) in
  `routers/targets.py` — 400 on an unsupported window value, 404-not-403 on a target that
  doesn't exist or isn't owned by the caller, same pattern as every other target-scoped
  endpoint. **Deliberately not `?region=`-scoped** like `/checks`/`/export` — every region the
  target has data for in the window comes back at once, keyed by region in one response, since
  side-by-side region comparison is this endpoint's whole point (same reasoning
  `/targets/status`'s `latest_checks` is already a region-keyed dict rather than one call per
  region).
- **New `backend/analytics.py`**: reuses `export.py`'s `compute_sla()`/`compute_incidents()`
  directly (imported, not reimplemented) — one definition of "uptime %" and "what counts as an
  incident" shared with the CSV export, per the prompt's explicit ask. Adds a linear-
  interpolation `_percentile()` helper (same method numpy's default and Excel's
  PERCENTILE.INC use — no new dependency, hand-rolled) for p50/p95/p99, and a new
  `_compute_mttr()` aggregate over `compute_incidents()`'s output.
- **MTTR handling of an in-progress (unresolved) incident — explicitly decided, not left
  ambiguous**: counted up to "now," not excluded. Justification (documented in
  `_compute_mttr`'s docstring): MTTR exists to reflect real user-facing pain from downtime;
  quietly excluding whatever is currently down would make the number look artificially healthy
  at exactly the moment it matters most. An unresolved incident's "up to now" duration also
  always overlaps the window by construction, since the window's right edge is always "now"
  itself (this endpoint has no `from`/`to` range concept, unlike `/export` — always
  right-anchored at "now").
- **A second, related window-boundary decision, also explicit**: a resolved incident counts
  toward MTTR if it recovered at or after `window_start` — using its own TRUE duration, not one
  clipped to the window edge, even if it actually started slightly before the window opened.
  Enabled by a small "context check" (the single most recent check strictly before
  `window_start`, fetched per region) prepended to the list handed to `compute_incidents()`
  purely to seed correct up/down boundary state — **used only for incident detection, never for
  uptime %/latency percentiles**, which are computed strictly from checks inside the window, so
  they keep their literal, expected meaning ("uptime % over the window," not "uptime % over the
  window plus one extra point"). Without the context check, a target already down when the
  window opened would misreport its incident as starting exactly at the window boundary,
  understating the real outage length.
- **Confirmed no per-region collapsing**: `TargetAnalyticsResponse.regions` is a plain
  `dict[str, RegionAnalyticsResponse]`, same convention as `TargetStatusResponse.latest_checks`
  — no derived cross-region average or overall figure anywhere. A region with zero checks in
  the requested window is simply absent from the dict (not present with nulls).
- **Tests**: `test_analytics.py` — 13 pure-function tests (`_percentile` including a verified
  known-value case, `_compute_mttr` covering every window-boundary/resolved/unresolved
  combination the prompt asked for, `compute_region_analytics` including the context-check
  behavior directly) plus 12 endpoint tests against the real test database: auth/ownership,
  invalid window, default window, a region absent when it has no checks in the window,
  independent per-region stats, **one dedicated boundary test per window value** (24h/7d/30d/
  90d, each inserting one check just inside and one just outside), real percentile computation
  from ten known latencies, and MTTR from a genuine mix of one resolved and one unresolved
  incident. Plus 2 new assertions in `test_ownership.py`. 208 backend tests total (was 183). No
  worker changes in this prompt — worker tests unaffected.
- **Verified end-to-end against the real running stack, not just tests**: rebuilt `api`
  (no migration needed — no schema change this prompt), created a real target, paused it
  immediately via the real `/pause` endpoint to stop the live worker from interfering, and
  seeded a real, hand-computed check history directly via SQL: ten checks with latencies
  10-100ms, one resolved 10-minute incident, one still-ongoing incident. Queried the real
  endpoint and confirmed **every figure matched independent hand-calculation exactly**:
  `uptime_percent=78.5714...` (11/14), `latency_p50_ms=50`, `p95=95`, `p99=99` (computed over
  all 11 checks with a real latency, including the recovered incident's own check — not just
  the clean 10-value set), `incident_count=2`, and `mttr_seconds≈456` (consistent with the
  600s resolved incident and the ~300s-and-still-growing unresolved one averaging correctly).
  Also confirmed live: an invalid `window` value 400s, and a second real user gets a real 404
  querying the first user's target's analytics. All verification data deleted afterward via
  the real `DELETE /auth/me` flow. Stack left healthy (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: any frontend code (deferred to prompt
  6.14), webhooks, API keys, retention, any other Phase 6 feature area.

Phase 6, prompt 6.6 (alerting fan-out restructure + webhook alerts) is complete — closes out
the alerting-fan-out prerequisite flagged since 6.1 and builds webhooks on top of it in the
same prompt. Explicit scope boundary honored: API keys and rate limiting untouched.
- **Prerequisite restructuring done first, as instructed**: `_evaluate_downtime_alert`/
  `_evaluate_cert_expiry_alert` in `realtime.py` now separate condition-eligibility (the
  existing cooldown/`alert_history` check — channel-agnostic, computes an `event`
  ("down"/"up"/none) or returns early) from channel fan-out (email if `user.alert_on_downtime`,
  each *enabled* webhook independently if its own `alert_on_downtime` is set). Bookkeeping is
  written once, after fan-out, if **at least one** channel delivered — a deliberate
  generalization of the existing single-channel "a failed send isn't recorded as alerted"
  rule, documented with one **known, accepted limitation**: if one channel succeeds and
  another fails, the failed one isn't individually retried next check, since `alert_history`
  tracks "was this transition alerted at all," not per-channel delivery status. Confirmed this
  was a real, not hypothetical, prerequisite — building webhook sends against the old fused
  shape would have wrongly tied webhook delivery to the *email* toggle specifically.
- **Schema**: migration `013_add_webhooks.py` — `webhooks(id, user_id FK CASCADE, url, secret,
  alert_on_downtime default true, alert_on_cert_expiry default true, enabled default true,
  created_at)`. `secret` stored plaintext, not Fernet-encrypted like a target's basic-auth
  password — documented reasoning: unlike that credential (authenticates INTO a third-party
  system), this one only ever authenticates payloads this app sends OUT to the user's own
  endpoint, a lower-severity exposure if the database were ever compromised. Flagged as
  revisitable, not silently decided.
- **New `backend/routers/webhooks.py`**: `POST/GET /webhooks`, `DELETE /webhooks/{id}` —
  matches `routers/tags.py`'s exact CRUD shape/precedent (no PATCH; ownership-enforced;
  404-not-403). `secret` is always server-generated (`secrets.token_urlsafe(32)`, same
  generation approach as password-reset tokens) and returned **only** in the create response,
  never by `GET /webhooks` afterward — same "shown once" convention as a generated API key.
  URL validated via `security.ssrf.is_url_blocked()` at creation — same 400 shape as
  `POST /targets`'s own creation-time check, called directly (not `to_thread`-wrapped), matching
  that existing endpoint's own precedent; the prompt's `to_thread` requirement is specifically
  for the send-time re-check (see below), where blocking the shared event loop would delay
  every other concurrent request, not just one request handler blocking itself.
- **New `backend/webhooks.py`**: `send_webhook()` mirrors `mail/client.py`'s `send_email()`
  philosophy exactly — one attempt, 5s timeout, log-and-swallow, never raises, so it structurally
  can't corrupt the SSE-push half of `_handle_notification`. Re-validates the URL via
  `is_url_blocked()` immediately before every send (DNS-rebinding defense — a URL can resolve
  safely at creation and unsafely later), wrapped in `asyncio.to_thread()` exactly as
  instructed. Sends via `httpx.AsyncClient(follow_redirects=False)`; a 3xx is simply not
  chased and fails the same `is_success` check as any other non-2xx — no need for a separate
  redirect-specific branch. Payload: `{event, target: {id, name, url}, region, checked_at,
  error, cert: {...} | null, detail_url}`, `event` one of `target.down`/`target.up`/
  `target.cert_expiring`. Signed via `X-Uptime-Monitor-Signature: sha256=<hex HMAC-SHA256 of
  the exact raw JSON body, using the webhook's secret>`.
- **Tests**: `test_webhook_delivery.py` (10, hermetic — mocked httpx: payload shape, SSRF
  rejection at send time using real IP literals matching this codebase's established
  convention, signature correctness/uniqueness-per-secret, no-redirect-following, non-2xx/
  connection-error/timeout handling), `test_webhooks.py` (9: CRUD, SSRF-at-creation for
  localhost/private-IP/link-local, non-http scheme rejected, ownership, auth-required), and
  11 new tests appended to `test_alerting.py` covering exactly what the prompt asked for:
  webhook fires on downtime/recovery/cert-expiry each independently of the email toggle (the
  core proof the restructuring worked), webhook respects the same cooldown as email, a
  disabled webhook never fires, per-webhook per-alert-type independence, bookkeeping recorded
  once whether one or both channels fire, bookkeeping recorded when only the webhook channel
  succeeds (and withheld when every channel fails), and multiple webhooks each firing
  independently. Plus 3 new assertions in `test_ownership.py`. **238 backend tests total (was
  208)**. Caught and fixed one real test-timing bug before it could land: an exact
  `timedelta(days=9)` fixture computed `days_remaining` a moment later than it fixed
  `expires_at`, and since `timedelta.days` truncates, that reads as 8 deterministically, not
  occasionally — fixed with an hour of margin, not a retry/tolerance hack.
- **Verified end-to-end against real infrastructure, about as strong as this project's own
  verification gets**: rebuilt `api`, confirmed migration `012 → 013` applied cleanly. Created
  a real webhook via the live API pointed at a real `webhook.site` capture token, created a
  real failing target, and let the real worker check it — webhook.site's own API confirmed a
  genuine HTTP POST was received with the exact expected payload (including real TLS cert
  data) and a `X-Uptime-Monitor-Signature` header. **Independently recomputed the HMAC-SHA256
  over the exact received body using the real secret and confirmed it matched the received
  signature byte-for-byte** — cryptographic proof the signing implementation is correct, not
  just that *a* header was present. Then forced a real recovery check via direct SQL +
  `pg_notify` and confirmed webhook.site received a second real request
  (`target.up`, after `target.down`, in the correct order) — proving both alert directions
  fire for real over genuine network I/O, decoupled from email (which was never configured to
  fail here — the test target's owner never touched `alert_on_downtime`, so this also
  incidentally reconfirms email continues to work unchanged alongside webhooks). Also
  reconfirmed SSRF-at-creation blocks a real metadata-IP URL (400) live. All verification data
  deleted afterward via the real `DELETE /auth/me` flow. Stack left healthy (`db`/`api`/
  `worker` all `Up`).
- Not touched in this prompt, per its explicit scope: API keys, rate limiting, any frontend
  code, retention, pagination.

Phase 6, prompt 6.7 (API keys, public REST API, per-key rate limiting, pagination) is
complete — the last backend feature area from the 6.1 report. Explicit scope boundary honored:
no frontend code touched.
- **Schema**: migration `014_add_api_keys.py` — `api_keys(id, user_id FK CASCADE, name,
  key_prefix, key_hash indexed, scope default 'read', created_at, last_used_at, revoked_at)`.
  Raw key = `"um_" + secrets.token_urlsafe(32)`; only `sha256(raw_key)` is stored, same pattern
  as `password_reset_tokens`. `revoked_at` is a soft-delete — `DELETE /api-keys/{id}` sets it,
  never removes the row, so `GET /api-keys` keeps showing a revoked key (with its revocation
  time) as an audit trail rather than silently dropping it.
- **New `backend/routers/api_keys.py`**: `POST/GET /api-keys`, `DELETE /api-keys/{id}` — the
  raw key is returned only in the create response, `key_prefix` (first 12 chars) is returned
  everywhere else so a list UI can distinguish keys without ever seeing the full value again.
  **Cookie-auth only, deliberately** — every endpoint here depends on the plain
  `get_current_user`, never the new combined dependency, at any scope: confirmed live and by
  test that presenting a valid, even `full`-scope, key with no cookie gets a real 401 on every
  one of these three endpoints, satisfying "API-key auth can never manage API keys themselves."
- **New `backend/auth/api_key.py`**: `get_current_user_or_api_key(scope)` — a dependency
  factory. `Authorization: Bearer <key>` present → must resolve to a valid, unrevoked key with
  sufficient scope (401 if the key itself is bad, 403 if under-scoped) — deliberately **no**
  silent fallback to cookie in that case, so a caller that explicitly presented a bad key gets
  an honest answer about it. Header **absent** → defers entirely to the existing, completely
  unmodified `get_current_user`, which is what keeps every current cookie-authenticated caller
  of these same endpoints (the dashboard) working exactly as before — confirmed by test that a
  non-`Bearer` `Authorization` header (e.g. Basic auth) and no-header-at-all both still resolve
  correctly via cookie. `last_used_at` is throttled to at most once per hour, not bumped on
  every request, per the write-volume concern flagged back in the 6.1 report.
- **Wired onto exactly the endpoints the prompt named**, no more: `GET /targets`,
  `GET /targets/{id}`, `GET /targets/{id}/checks`, `GET /targets/{id}/export` at scope `read`;
  `POST /targets`, `POST /targets/{id}/pause`, `DELETE /targets/{id}`, and all three
  `/webhooks` endpoints at scope `full`. Deliberately **not** extended to `PATCH /targets/{id}`,
  `POST /targets/{id}/resume`, the tags endpoints, `/targets/{id}/analytics`, `/targets/status`,
  or `/targets/stream` — the prompt's own enumeration stops at "create/pause/delete targets and
  manage webhooks," and extending further would have been my own extrapolation, not the
  literal ask. Ownership enforcement is structurally identical for both auth paths: both
  resolve to the same `current_user`, and every query already filtered by `current_user.id`
  before this prompt — confirmed live and by test that a key can never see, read, or act on
  another user's targets.
- **Rate limiting values chosen**: `60/minute` per key (`rate_limit.API_KEY_RATE_LIMIT`),
  applied via a custom `api_key_or_remote_address` key_func on every key-eligible route above
  — generous enough for a real integration (a Prometheus exporter, a personal dashboard
  polling every few seconds), far above anything a human clicking through the web dashboard
  would hit on these specific routes, while still bounding a misconfigured/abusive
  integration. `10/minute`, IP-keyed, added to `POST /api-keys` and `POST /webhooks` — the
  exact value the prompt asked to mirror from `POST /targets`'s existing creation limit.
  `POST /targets` and `POST /webhooks` end up with **two** stacked `@limiter.limit(...)`
  decorators (their existing 10/minute IP-keyed creation limit, untouched, plus the new
  60/minute per-key one) — slowapi enforces both independently; confirmed this doesn't break
  anything by re-running the full existing rate-limit suite unchanged. Every existing IP-keyed
  limit (login 5/min, register 3/min, target-creation 10/min, change-password 5/min,
  forgot/reset-password 3+5/min) is completely untouched.
- **Pagination on `GET /targets/{id}/checks`**: id-based cursor (`?cursor=<last-seen id>`),
  default 500 / max 2000 — same numbers as the existing (unpaginated) `limit` clamp, just now
  also cursor-walkable. Ordering switched from `checked_at ASC` to `id ASC` uniformly (the two
  are equivalent here — checks are inserted in real time order by an autoincrement id — so this
  doesn't change what a non-paginating caller sees, just simplifies the cursor semantics to
  match "id-based cursor" literally). **Honored only for API-key-authenticated requests** —
  gated on `request.state.api_key`, not just on whether `?cursor=` was passed — so the
  dashboard's existing behavior is unaffected even in edge cases, not just in the common case.
  A further page is signaled via an `X-Next-Cursor` response header, never a body-shape change
  (the response stays a bare list for every caller, cookie or key) — confirmed live that a
  cookie-authenticated request to the identical URL+params never receives that header, even
  though more rows exist.
- **Tests**: `test_api_keys.py` (11: CRUD, scope validation, uniqueness, revoke idempotency,
  ownership, auth-required, **the key-cannot-manage-keys rule explicitly proven** by presenting
  a real full-scope key with no cookie against all three `/api-keys` endpoints and confirming
  401, creation rate limit) and `test_api_key_auth.py` (22: valid/unknown/revoked/malformed key
  handling, non-Bearer-header and no-header cookie fallback, scope enforcement in both
  directions — read-scope correctly blocked from writes, full-scope correctly covers reads too
  — ownership-via-key against another user's targets across every key-eligible endpoint, the
  per-key rate limit firing at exactly 60, **proof it's keyed by the API key and not IP** (the
  same test client's cookie-authenticated request to the same route stays unaffected after
  exhausting a key's budget), two keys on the same account having fully independent budgets,
  pagination correctness via a full cursor walk across 5 known rows asserted in exact order,
  cookie requests never receiving pagination signaling, and **the 2000-row cap proven directly
  against 2005 real bulk-inserted rows**, not just asserted from the clamp math). Plus 3 new
  assertions in `test_ownership.py`. **271 backend tests total (was 238)**. No worker changes
  in this prompt — worker tests unaffected.
- **Verified end-to-end against the real running stack, not just tests**: rebuilt `api`,
  confirmed migration `013 → 014` applied cleanly. Created a real target via cookie auth, a
  real read-scope key, and confirmed **with no cookie attached at all** that the raw key alone
  reads `GET /targets`/`GET /targets/{id}` successfully, a create attempt with that same key
  gets a real 403, and an unknown key gets a real 401. Confirmed a second real user's key gets
  a real 404 reading the first user's target. Revoked the key live and confirmed its very next
  use fails with a real 401. Seeded real check rows and walked real pagination pages via
  `X-Next-Cursor`, then confirmed a cookie-authenticated request to the identical URL never
  receives that header. All verification data deleted afterward via the real `DELETE /auth/me`
  flow. Stack left healthy (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: any frontend code, retention.

Phase 6, prompt 6.8 (checks-table retention) is complete — the last backend item from the 6.1
report. **Retention window: 90 days**, matching the frontend detail page's existing 90-day
heatmap window exactly, so pruning never silently breaks a UI feature that already reads that
far back. Explicit scope boundary honored: no frontend code touched.
- **Plain delete, no rollup table, exactly as directed**: `worker/retention.py`'s
  `prune_old_checks()` is one `DELETE FROM checks WHERE checked_at < $1` — nothing else. A
  rollup/aggregate table remains a clean additive follow-up if long-term trend data beyond the
  window ever matters, not built speculatively now.
- **`CHECKS_RETENTION_DAYS` added to both `worker/config.py` (the real source of truth — this
  is the value the worker actually prunes by) and `backend/config.py`** (informational only,
  read by `build_csv`'s note logic; the backend never deletes a `checks` row itself). Both
  default to 90 — the same "duplicated across independently-deployed services, kept in sync by
  hand" tradeoff already established for `CERT_EXPIRY_WARN_DAYS`/SSRF/`NOTIFY_CHANNEL`/etc.,
  flagged explicitly so a future change to one without the other doesn't silently make the
  export note's threshold disagree with what's actually still on disk.
- **Runs as a second, independent `asyncio.create_task` in `worker/main.py`'s `main()`**,
  started once at boot alongside (not nested inside) the existing check-cycle `while True`
  loop, cancelled in the same `finally` block that closes the connection pool — the exact
  "second long-lived asyncio task... not folded into the 5s scheduler tick" shape the prompt
  asked for. Sleeps a full `RETENTION_INTERVAL_SECONDS` (24h) **before** its first sweep, not
  immediately at startup, so a routine redeploy/restart never triggers a prune burst as a side
  effect.
- **Idempotency, confirmed explicitly**: the bare `DELETE ... WHERE checked_at < cutoff` is
  naturally idempotent — a second identical DELETE from the other region's worker instance
  simply matches zero rows. No new "primary region"/coordination concept was introduced, per
  the prompt's own explicit steer away from inventing one.
- **Sequencing relative to Phase 2's row-claiming, stated explicitly, not just implied by the
  code structure**: `prune_old_checks()` only ever touches the `checks` table — never
  `targets` or `target_region_schedule`, the two tables `claim_due_targets()`'s
  `FOR UPDATE OF trs SKIP LOCKED` and `reschedule_target()`'s `UPDATE` actually lock. There is
  therefore no row-level contention between the retention loop and the claim/schedule path at
  any point in time, regardless of interleaving — the two loops share only the connection
  pool, which supports concurrent acquisition by design, and the retention loop holds its
  connection only for the duration of one DELETE statement, never across an await boundary
  that could stall a check cycle.
- **`build_csv` note line**: a `retention_days: int | None = None` parameter (default `None` —
  every pre-6.8 caller/test keeps getting byte-identical output). When given, a `Note` row is
  added to the summary whenever the **requested** `range_from` predates the retention cutoff —
  including `range_from=None` ("all time"), which trivially predates any cutoff — comparing
  the requested range as the prompt specified, not the actual earliest row present. The
  `GET /targets/{id}/export` endpoint now passes `settings.CHECKS_RETENTION_DAYS` through.
- **Tests**: `worker/tests/test_retention.py` (5, hermetic — same mocked-pool/connection
  convention as `test_scheduling.py`: exact `DELETE FROM checks WHERE checked_at < $1` SQL and
  cutoff-math assertions, command-status parsing including a malformed-status case, and the
  24h-interval constant itself). **Explicitly flagged, not silently accepted**: the specific
  claim "removes rows older than the cutoff and leaves recent ones untouched" is a real-data
  selectivity claim a mocked connection can't actually prove — worker's test suite has no real-
  database path at all (by design, since Phase 1), and building one for this single prompt
  would have been a heavier lift than the ask warranted, so that exact proof was done via live
  verification against the real dev database instead (below), not skipped. `test_export.py`
  gained 5 pure-function tests (note present/absent by range, the `range_from=None` case, and
  a boundary test confirming the comparison is strict `<` not `<=`) plus 3 endpoint tests
  against the real `GET /targets/{id}/export`. **279 backend tests total (was 271); 59 worker
  tests total (was 54)**.
- **Verified end-to-end against the real running stack, including the one thing hermetic tests
  structurally couldn't prove**: rebuilt both images, confirmed the worker's startup log now
  reads `retention_days=90` and the check cycle keeps running normally alongside it (no
  migration this prompt — no schema change). Seeded 6 real rows for one target spanning the
  90-day boundary (100/95/91 days old, and 89/10/1 days old) directly via SQL, then invoked the
  real `prune_old_checks()` against the real dev database from inside the running worker
  container (rather than waiting a real 24h for the loop's own timer) — **confirmed exactly
  the three >90-day rows were deleted and exactly the three ≤90-day rows survived untouched**,
  a precise boundary proof against genuine data, not a synthetic assertion. The same real sweep
  also pruned 147 total rows of old history accumulated across this project's own many
  verification sessions since Phase 0 — a real, non-trivial cleanup, not just a no-op on an
  empty table. Also confirmed live: an export with an old `from` shows the `Note` row with the
  correct cutoff date, and an export with a recent `from` shows no note at all. All
  verification data deleted afterward via the real `DELETE /auth/me` flow. Stack left healthy
  (`db`/`api`/`worker` all `Up`).
- Not touched in this prompt, per its explicit scope: pagination (already covered in 6.7), any
  frontend code, a rollup/aggregate table.

**Phase 6's entire backend feature list from the 6.1 report is now complete**: target request
customization + keyword monitoring, pause/resume + configurable interval, tags, windowed
analytics, webhook alerting, API keys/public REST access, and checks-table retention have all
shipped, tested, and been verified live. **Next**: everything remaining in Phase 6 is frontend
work for what's already shipped — deferred to its own later prompts (6.13 for
customization/pause/resume/tags, 6.14 for analytics, plus whatever prompts cover
webhooks/API-key management UI) per the explicit per-prompt scoping used throughout this phase.
No backend/worker work is currently outstanding in the 6.1 report.

Prompt 6.9 (CSV export formatting fix) is complete. Standalone, independent of the rest of
Phase 6, per the prompt — fixes the poor formatting flagged as a Phase 4 leftover; no data
content or ownership-enforcement change.
- **What was actually wrong, found via live investigation against real seeded data before
  touching any code**: the original `build_csv` produced one physical CSV file that was really
  three differently-shaped mini-tables (a 2-column summary, a 3-column incident table, a
  10-column check-row table) with only a bare "Incidents" title row and blank lines separating
  them — asymmetric and not self-describing. Concretely: (1) timestamps were inconsistently
  formatted — bare `datetime.isoformat()` omits the fractional-seconds part only when
  `microsecond == 0`, so two otherwise-identical-shaped timestamps in the same column could
  render with different string lengths depending on what microsecond a check happened to land
  on, confirmed via both a standalone Python reproduction and real seeded rows (one exact
  10:00:00, two with real `.123456`/`.654321` fractional seconds); (2) the "Date range" field
  mixed a real ISO timestamp with the English words "all time"/"now," and the Incidents
  section's "End" column did the same with the literal word "ongoing"; (3) the Incidents
  "Duration" column was a hand-formatted string like "20m"/"2h 15m" — a number with its unit
  baked into the text, unparseable without stripping the suffix, directly matching the
  prompt's "numeric fields... stringified with units baked in" complaint; (4) no section but
  Incidents had a title row, so the file's own structure wasn't self-describing; (5) minor
  inconsistencies — `True`/`False` casing, "SLA %" not following the "(unit)" convention every
  other header uses, "Total checks" not Title Case.
- **Fix** (`backend/export.py`): every timestamp-shaped cell now goes through one
  `_format_timestamp()` helper using `isoformat(timespec="seconds")` (`None` → empty string,
  never a word). "Date range" split into separate "Range Start"/"Range End" summary rows.
  Incidents gained an explicit "Ongoing" column (`true`/`false`) instead of overloading "End";
  "Duration (minutes)" is now a plain integer, blank while ongoing (deliberately not computed
  "as of now," so a fixed query's export stays deterministic on re-export). All three sections
  now open with the same single-cell title convention ("Summary"/"Incidents"/"Checks"),
  blank-line-separated — a caller can split on blank lines and read each section as its own
  well-formed sub-table. `Is Up` and `Ongoing` are lowercase `true`/`false`; header renamed to
  "SLA (%)"; "Total checks" → "Total Checks". The now-unused `_format_duration()` helper (the
  "20m" formatter) was deleted rather than left dead. `compute_sla`/`compute_incidents` (the
  data functions) were not touched — formatting only, confirmed by re-running the SLA/incident
  pure-function tests unchanged and by live-checking that the seeded data's SLA/incident
  figures matched hand computation before and after.
- **Tests** (`backend/tests/test_export.py`): added a `_parse_sections()` helper that splits
  the CSV into its three named sections by blank line + title row, then rewrote the structural
  test to assert against parsed sections instead of hardcoded row indices (which would have
  silently drifted every time a summary field is added/removed) — checks every section is
  present, every summary field/incident row/check row has the exact expected value and type
  (plain numbers, lowercase booleans, blank vs. populated). Added dedicated tests for: the
  ongoing-incident case (blank End/Duration, `Ongoing=true`), unbounded vs. explicit
  Range Start/End, and the exact microsecond-inconsistency bug (two checks at the same second
  with/without microseconds render byte-identical timestamp shapes). Updated the four
  endpoint-level tests whose assertions depended on the old row layout (`rows[2]` → `rows[3]`
  for the Region row now that Summary has its own title row at index 0, `,True,` → `,true,`,
  `"Total checks"` → `"Total Checks"`). All pre-existing retention-note tests
  (`_note_row`-based) needed zero changes — the Note row's own label/position logic didn't
  change, only its neighbors' formatting. 283 backend tests total (was 279; net +4 after
  replacing one old test with five new ones).
- **Verified live against the real running stack**: rebuilt `api`, registered a throwaway
  user, created and paused a target, and seeded 4 real check rows via direct SQL — one exact
  round-second timestamp, two with genuine `.123456`/`.654321` fractional seconds (to
  concretely exercise the fixed bug, not just a synthetic case), forming one resolved
  20-minute incident. Fetched the real export and inspected it with `cat -A`: confirmed all
  three timestamps in the Checks section render with identical shape
  (`2026-09-17T10:10:00+00:00`, fractional seconds correctly dropped) rather than the old
  inconsistent lengths, `Range Start`/`Range End` both genuinely blank (no target `from`/`to`
  was given), the Incidents row reads `...,false,20` (plain integer minutes, `Ongoing=false`),
  and all three sections open with their own title row. Re-confirmed ownership enforcement is
  untouched: a second user's export attempt on the same target still 404s, an unauthenticated
  attempt still 401s. Cleaned up both verification accounts via the real `DELETE /auth/me`
  cascade; confirmed via a direct query that the seeded checks were gone afterward.
- Not touched in this prompt, per its explicit scope: `compute_sla`/`compute_incidents` (data,
  not formatting), the export endpoint's auth/ownership/query logic, PDF export, any frontend
  code — this fix is entirely inside `backend/export.py`'s `build_csv` (plus its docstring) and
  the corresponding test file.

Prompt 6.10 (full cybersecurity walkthrough) is complete. Audited all of Phase 6's new backend
surface (6.2–6.9) plus a regression pass across the whole app; one real gap found and fixed,
everything else confirmed passing.
- **Rate limiting — one real gap, fixed**: `PATCH /targets/{id}`, `POST /targets/{id}/resume`,
  `POST /targets/{id}/tags`, `DELETE /targets/{id}/tags/{tag_id}`, `DELETE /api-keys/{id}`, and
  the entire `tags` router (`POST /tags`/`DELETE /tags/{id}`) had **no rate limit at all** —
  confirmed live before fixing: `PATCH /targets/{id}` processed 65+ consecutive requests with
  zero `429`s. Everything else from 6.2–6.9 (webhooks CRUD, target create/pause/delete, API key
  creation) was already correctly limited, and the 6.7 per-key budget
  (`api_key_or_remote_address`) was confirmed still stacking independently on top of the
  IP-based one wherever it applies. **Fixed**: `POST /tags` got the standard `10/minute`
  creation-endpoint limit; the other five got `API_KEY_RATE_LIMIT`'s `60/minute` magnitude,
  IP-keyed (none of the six are API-key-eligible, so there's no per-key traffic to distinguish
  — the constant is reused purely for a consistent bound). Live-verified: the same `PATCH`
  route now genuinely `429`s on request 61. 7 new regression tests
  (`backend/tests/test_rate_limit.py`) — one per newly-limited endpoint.
- **Injection protections — pass, one empirical check added**: confirmed `request_headers`/
  `keyword_match` are never interpolated into SQL anywhere (every worker query uses `$1`-style
  bind params; the jsonb column round-trips through asyncpg's registered codec, not string
  formatting) and `keyword_match` only ever does a plain Python substring check. Empirically
  confirmed (not just assumed from "httpx probably validates this") that httpx/h11 raises
  `LocalProtocolError` on a CRLF embedded in a header value — tested live in a worker
  container — which `check_url`'s broad `except` catches as an ordinary check failure, so
  request-splitting via a target's custom headers isn't possible. Re-confirmed SSRF is
  enforced at target creation, at every worker check, at every redirect hop (including the
  6.2-follow-up cross-host credential-drop fix), at webhook creation, and re-validated
  immediately before every webhook send — neither target nor webhook URLs have an edit path,
  so "SSRF at edit time" doesn't apply by construction.
- **Secrets/credential handling — pass, verified against real serialized responses, not just
  the Pydantic model definitions**: created a real target with basic-auth credentials and
  confirmed the password never appears in the create/list/detail/PATCH response bodies (all
  grepped directly), while the DB column holds real Fernet ciphertext, not plaintext. Created a
  real API key and confirmed `key_hash` never appears in any response (only `key_prefix` after
  creation) by grepping `GET /api-keys`' actual output and cross-checking against the DB's real
  hash value. Created a real webhook and confirmed `secret` is present only in the create
  response, never in a subsequent `GET /webhooks`. Grepped `webhooks.py`/`realtime.py`/
  `worker/main.py`'s logging: none of it includes a credential, secret, or password value —
  only target/webhook IDs and URLs.
- **Ownership enforcement — pass**: tags, API keys, webhooks, and `GET /targets/{id}/checks`
  (pagination included) all filter by owner on every query and return 404, never 403, on a
  mismatch — confirmed by grepping every new router file for `403` usage; the only hit is
  `auth/api_key.py`'s scope-insufficiency case (a *valid* key without enough scope), which is a
  different, correct use of 403 (identity known, action refused), not an ownership check.
- **`CREDENTIAL_ENCRYPTION_KEY` — pass**: still required/no-default in both services' `Settings`
  (same fail-fast mechanism as `JWT_SECRET`, covered by `test_config.py`), never logged, never
  present in any response model.
- **Git-history secret grep — pass, re-run and re-confirmed clean**: repeated the Phase 5.8
  methodology across the full history and specifically the 6.2–6.9 commit range for Neon/
  Resend/JWT/Fernet-shaped values and any tracked `.env`. Nothing real found; the one
  historically-tracked `.env` (Phase 0) is still git's canonical empty blob. A batch of
  base64-looking strings the grep initially flagged turned out to be `package-lock.json` npm
  integrity hashes (traced one back to its source commit to confirm) — a false positive, not a
  leak.
- **pip-audit/npm audit — no new findings since Phase 5.8**: backend has only the same
  pre-existing `ecdsa` finding (transitive via `python-jose`, no fix available, inert since this
  app only ever signs HS256); worker is clean; frontend's `next@14.2.35`-pinned advisory count
  grew from ~23 to 27 (new advisories published against the same pinned version since 5.8, not
  from any change this phase — frontend wasn't touched), all still requiring the
  already-deferred Next 16 major upgrade to fix.
- 290 backend tests total (was 283), all passing against a rebuilt `api` image. All
  verification data (throwaway account, its target/API key/webhook) deleted afterward via the
  real `DELETE /auth/me` cascade, confirmed via direct SQL count. Stack left healthy
  (`db`/`api`/`worker`/`worker-eu-west` all `Up`).

Prompt 6.11 (dashboard overview strip + loading skeletons) is complete. First frontend prompt
after Phase 6's backend build-out. Uses only the existing Phase 3 design tokens/components — no
new colors, typefaces, or motion primitives introduced.
- **Overview strip additions** (`app/dashboard/page.tsx`): a new "uptime (live)" stat in the
  existing summary strip, and a new persistent banner above it. **Aggregate uptime % — the
  methodology is stated explicitly in code, per the prompt's ask**: the fraction of
  (target, region) pairs that have reported at least one check and are currently `is_up`,
  averaged flat across every pair (not per-target — a target with 2 regions contributes 2
  pairs, weighted the same as any other pair). A pair with no check yet is excluded from both
  the numerator and denominator. This is deliberately a **live snapshot**, not a time-windowed
  SLA % — that already exists per-region on the detail page, computed from real historical
  check history; the list page only ever fetches the latest-check payload, so a windowed figure
  here would mean N extra `/analytics` calls per page load for a number that already exists one
  click away. Colored via the same 99.9/99 breakpoints as the detail page's `slaColor`, and
  labeled "uptime (live)" with a `title` tooltip spelling out the distinction, so the number
  doesn't get mistaken for SLA% by a user comparing the two pages.
- **Persistent banner**: renders only when `degradedOrDownCount > 0` (gone the instant nothing
  is), text "N region(s) reporting degraded/down" (singular handled correctly, confirmed in the
  mobile screenshot), severity escalates to `--signal-down` the moment anything is actually
  down (not just degraded) rather than a flat single color — matching the two-tier severity
  already used everywhere else on this page. Styled as a bordered box with a colored border/
  text, the same treatment already established for `/settings`' "Danger zone" section, not a
  new visual pattern. Both the strip and banner update live via the existing SSE mechanism with
  zero new wiring — they're derived from `items` state on every render, same as the existing
  counts.
- **Loading skeletons** (`components/skeleton.tsx`, new): `Skeleton` (the base pulsing block)
  plus shape-matched pieces — `SignalLightSkeleton` (SignalLight's own housing dimensions, not
  the real component rendered in some placeholder state, since a loading skeleton and a real
  "pending" app state are different things that shouldn't be conflated), `LatencyGaugeSkeleton`
  (a circle matching the gauge's bounding box, not a traced arc outline), `LatencyChartSkeleton`/
  `TimingWaterfallSkeleton`/`UptimeHeatmapSkeleton` (matching each real component's actual
  fixed dimensions, read directly from their source). Dashboard list: the "Loading…" text
  became a skeleton overview strip plus 3 skeleton rows shaped like real target rows (name,
  action buttons, region badge + signal-light + latency + timestamp placeholders). Detail page:
  became a full skeleton of the real layout (title, region cards, tabs, Latency section with
  gauge+chart, Timing section, Uptime heatmap, plus lighter placeholders for the Incidents/TLS
  divider sections) — kept the same "no site header while loading" structure the old bare
  "Loading…" state already had, not a new structural decision.
- **Real, screenshot-caught fix**: the skeleton blocks were first built filled with
  `--bg-surface-raised`, which turned out to be nearly invisible against the `--bg-surface`
  background most rows render on — confirmed via an actual screenshot, not assumed from the
  hex values. Fixed by filling with `--border` instead (still a locked, existing token, no new
  color) and raising the pulse's resting opacity floor from 0.55 to 0.7 — re-screenshotted to
  confirm the skeleton now reads clearly as "loading" rather than blending into the background.
- **Motion**: the pulse is an opacity animation (`.skeleton-pulse` in `globals.css`), not a
  gradient shimmer — this app's only established motion primitive is opacity (SignalLight's dot
  flip, LatencyGauge's needle sweep both work this way), so a shimmer would have introduced a
  second, unrelated animation technique for no real benefit. Wrapped in the same
  `prefers-reduced-motion: no-preference` gate every other animated rule uses. **Verified
  empirically, not assumed**: under `emulateMedia({ reducedMotion: "reduce" })`, a live
  `.skeleton-pulse` element's computed `animationName` is `"none"` and `animationDuration` is
  `"0s"`; under normal motion, the same element shows `"skeleton-pulse"` at `"1.6s"` — read
  directly via Playwright against the real running dev server, the same technique used in 3.3/
  3.8 for the other two motion primitives.
- **Verified against real seeded data on the real running stack**, not synthetic props:
  registered a throwaway account, created 3 real targets, paused them, and seeded real check
  rows (one healthy, one slow-but-up at 950ms, one down with `consecutive_failures=4` so it
  classifies as "down" not "degraded" per the existing threshold) directly via SQL — workers
  stopped for the duration, restarted after. Logged in through the real `/login` form (not an
  injected cookie) via Playwright against the real dev server and real backend. Screenshotted:
  the degraded/down state (banner reads "2 regions reporting degraded/down" in red, uptime
  66.7% in red, correct per-state counts); the fully-healthy state after flipping the same rows
  to healthy (no banner, 100.0% uptime in green); the dashboard loading skeleton (captured
  mid-load by delaying the `/targets/status` response via Playwright route interception); the
  detail-page loading skeleton (same delay technique on `GET /targets/{id}`); and a 400px-wide
  mobile capture of the degraded state (confirmed the singular-region banner grammar and that
  everything wraps/stacks cleanly at that width). `tsc --noEmit` clean throughout; `next build`
  not run (a dev server was started specifically for this verification and stopped cleanly
  afterward, so there was nothing to avoid corrupting, but skipping the production build in
  favor of live-stack Playwright verification is this project's established practice regardless).
- **Self-critique against the `frontend-design` skill's avoid-list**: clean. No new colors,
  typefaces, gradients, shadows, or card patterns were introduced — every new element reuses
  the existing bordered-box/token vocabulary. No all-caps eyebrow labels, no middle-dot-joined
  meta text, no "WORD — fragment" em-dash labels, no numbered markers (nothing new here is a
  sequence), no trailing arrows, no single-word headline accent. `font-mono` on the new uptime%
  figure matches this codebase's own established (not generic-default) convention that
  monospace marks a live-instrument reading, consistent with every other stat on this strip.
  The banner's bordered-box-with-colored-border treatment is a reused pattern (settings'
  Danger zone), not a new one. The skeleton pulse reuses the app's only existing motion
  primitive (opacity) rather than introducing a shimmer/gradient sweep.
- All verification data deleted afterward via the real `DELETE /auth/me` cascade, confirmed via
  direct SQL count of zero remaining rows. Scratch Playwright scripts (screenshot capture,
  reduced-motion check, mobile check) were written directly under `frontend/` so Playwright's
  local `node_modules` would resolve, then deleted before finishing — never committed. Docker
  stack and the dev server (started fresh for this prompt, not the user's own) both left/
  confirmed healthy — the dev server was stopped cleanly once verification finished.
- Not touched in this prompt, per its explicit scope: the quick-add modal, empty states, filter
  bar (none of these exist yet as separate concerns beyond what was already there — the
  existing "Add target" form and "No targets yet" empty state were both left exactly as they
  were), any backend/worker code.

Prompt 6.12 (quick-add modal + designed empty states) is complete. Second frontend prompt;
still no backend/worker changes. One real, screenshot-caught keyboard-accessibility bug found
and fixed before finishing.
- **New Dialog primitive** (`components/ui/dialog.tsx`): added via the project's pinned
  `shadcn@2.10.0` CLI (matching the Tailwind v3 JS-config workflow established in 3.2) — the
  first Dialog this app has ever had (4.1's delete-account flow deliberately avoided one at the
  time, calling it "a new Radix dependency for one single use"; that tradeoff no longer holds
  now that a second real use case exists). Trimmed to this app's own conventions, same
  treatment every other primitive got in 3.4: no `shadow-lg` (not in the locked spec), and the
  open/close motion is a plain opacity fade (`.dialog-overlay`/`.dialog-content` in
  `globals.css`) replacing shadcn's default zoom+slide, since opacity is this app's only
  established motion primitive (SignalLight, LatencyGauge, the loading skeleton all work this
  way) — introducing a second motion technique for one component would be inconsistent for no
  benefit. Gated behind `prefers-reduced-motion: no-preference` like every other animated rule.
  Pulled in `@radix-ui/react-dialog` and `lucide-react` (for the close **X** glyph only) as new
  dependencies — `tailwindcss-animate` was already installed since 3.2 but had never actually
  been used by anything until now.
- **`components/quick-add-target-modal.tsx`**: name/URL only, no advanced fields (request
  method, headers, basic auth, keyword match, check interval, tags) — those stay on the full
  edit surface, deferred to 6.14 per the prompt's explicit scope. A controlled dialog (the
  parent owns `open` state) so it can be triggered from two different places (the dashboard's
  own toolbar button and the empty state's CTA) without duplicating the form. On success it
  hands the raw `POST /targets` response back to the caller and closes itself; on a 401 it
  defers to the caller via an `onAuthFailed` callback rather than importing `useRouter` itself,
  keeping navigation ownership in the page component.
- **Real, screenshot-caught accessibility bug, found and fixed before finishing**: Radix
  Dialog's documented "return focus to the trigger on close" behavior turned out not to fire
  reliably here — confirmed empirically (not assumed) that after Escape, `document.activeElement`
  landed on `<body>`, not the button that opened it, tested at five points in time after close
  to rule out a timing fluke. Root cause: this modal is controlled and opened by a plain
  external `<Button>` outside the Dialog's own component tree (not a `<DialogTrigger>`), which
  is exactly the case Radix's built-in restore doesn't reliably cover. Fixed explicitly in
  `app/dashboard/page.tsx`: a `quickAddTriggerRef` captures whichever button was actually
  clicked (there are two — the toolbar button and the empty state's CTA), and
  `handleQuickAddOpenChange` refocuses it via `requestAnimationFrame` whenever the dialog
  closes, covering both Escape and a successful submit. Re-verified after the fix: focus lands
  on the exact trigger element immediately and stays there across every checked delay.
- **Dashboard**: the always-visible "Add target" card is gone, replaced by a toolbar button
  next to the `<h1>` that opens the modal. **On submit, the new target is inserted directly
  into local `items` state from the create response** (`latest_checks: {}`, prepended to match
  the backend's own newest-first ordering) — no full-list refetch, no navigation. It renders
  "pending" immediately, exactly like any other not-yet-checked target, and the *existing* SSE
  subscription (already merges any incoming `check_update` into `items` by id, with zero new
  wiring) takes over and updates it live the moment the worker actually checks it — this is the
  literal sense in which "the new target appears in the list live via the existing SSE wiring,"
  per the prompt's own framing: immediate local insert for the appearance, the pre-existing SSE
  path for every update after that.
- **`components/empty-state.tsx`** (new, shared): one `SignalLight state="pending"` + heading +
  optional description/action component, used everywhere something is legitimately empty rather
  than broken. `size="sm"` is deliberately borderless (meant to sit inside a section that's
  already inside its own bordered panel — Latency/Timing breakdown/Uptime on the detail page);
  `"md"`/`"lg"` get the dashed-border treatment already established for the dashboard's own
  empty state back in 3.5, reused rather than reinvented.
- **Dashboard empty state**: kept the existing dashed-box/pending-icon treatment (already
  design-system-consistent since 3.5), replaced the stale copy (which referred to a form that
  no longer exists "above") with a short one-line pitch, and added the actual "Add target"
  button as its CTA — satisfying the prompt's "short one-line pitch plus the quick-add CTA"
  literally, not just visually.
- **Detail page empty states — investigated the actual reachable "insufficient history" cases
  before building anything, rather than guessing**: confirmed a target with genuinely zero
  checks in any region is the only way the *page-level* gate (`regions.length === 0`) is ever
  hit — the backend only ever includes a region in `latest_checks` once it has at least one
  check, so a listed region tab always has real data to feed the per-region components. That
  page-level case got the shared `EmptyState` (size `md`) replacing a one-line
  `text-secondary` message. **Found a second, more interesting case that genuinely was
  reachable**: `load()`'s own per-region checks-history fetch falls back to `[]` on a failed
  request even when the region's *latest* check is real — meaning `LatencyChart`,
  `UptimeHeatmap`, and `IncidentTimeline` could each independently receive a genuinely empty
  `checks` array while the rest of the page (region cards, tabs, Timing breakdown, TLS
  certificate) still showed real data. `LatencyChart`/`IncidentTimeline` already had bare
  `text-secondary` fallback text for this; `UptimeHeatmap` had **no fallback at all** — it
  silently rendered 90 real, fully-populated "no data" cells regardless of whether the target
  was brand new or the fetch had simply failed, technically correct but telling a misleading
  story. All three (plus `TimingWaterfall`'s existing "No timing data" text, upgraded too for
  visual consistency, though not explicitly named in the prompt) now use the shared
  `EmptyState` (size `sm`, borderless) with the same "Waiting on the first check" copy the
  prompt itself suggested.
- **Verified against the real running stack with a genuine reproduction of the bug being
  fixed, not just the happy path**: registered a throwaway account, screenshotted the empty
  dashboard state and the quick-add modal open, drove the full submit flow end-to-end (fill →
  submit → modal closes → new row visible immediately with no reload, confirmed via
  `page.getByText(...).isVisible()` right after close) and visited its detail page with workers
  stopped to capture the genuine page-level "Waiting on the first check" state on a real
  brand-new target. Then, to prove the per-section fix rather than just the common case,
  seeded one real check for that target directly via SQL and used Playwright's `context.route()`
  to make the real `/targets/{id}/checks` endpoint return `500` — reproducing the exact
  fetch-failure code path — and confirmed via screenshot that the region card and Timing
  breakdown still showed real data while Latency/Uptime/Incidents each showed the clean new
  empty state instead of a broken-looking chart or (for the heatmap) a misleadingly-populated
  90-day grid. Confirmed keyboard accessibility empirically: autofocus lands on the URL field,
  focus stayed trapped inside the dialog across 8 tabs, a visible focus ring was present
  throughout, and (after the fix above) focus correctly returns to the exact trigger button.
  Confirmed `prefers-reduced-motion` empirically the same way as 6.11 — `animationName: "none"`
  under reduced motion, `"dialog-fade-in"` at `0.15s` under normal motion. Checked the modal at
  400px width too; found via a `fullPage` screenshot that it looked asymmetric, then confirmed
  via `document.documentElement.scrollWidth` (421px on a 400px viewport) and a viewport-clipped
  screenshot that this was a **pre-existing ~21px horizontal overflow on the dashboard row
  layout** (unrelated to anything built this prompt) distorting the `fullPage` capture, not a
  real dialog bug — the dialog itself is correctly centered with even gutters in the true
  viewport. **Flagged, not fixed** (out of this prompt's scope): worth a look in a future polish
  pass.
- **Self-critique against the `frontend-design` skill's avoid-list**: found and fixed one real
  instance of the em-dash "label" pattern this project's own house style (established in 4.2's
  copy pass and the later full design-pass prompt, both of which grepped for and removed em
  dashes from user-facing copy) already explicitly disallows — the dashboard empty state's own
  pitch text originally read "Nothing to monitor yet — add a URL to get started.", rewritten to
  two plain sentences. Confirmed clean otherwise: no new colors/shadows/gradients, the empty
  state's dashed-border+icon treatment reuses (not reinvents) the existing pattern, no all-caps
  labels, no middle-dot meta text, no numbered markers, no trailing arrows, and the bare "—"
  placeholders elsewhere on the page are the already-established idiomatic empty-value marker,
  not the punctuation pattern the skill actually warns about.
- All verification data deleted afterward via the real `DELETE /auth/me` cascade, confirmed via
  direct SQL count. All scratch Playwright scripts (7 of them across this prompt's several
  rounds of verification) written directly under `frontend/` so the local `node_modules` would
  resolve, deleted before finishing — never committed. Docker stack and the dev server (started
  fresh for this prompt) both confirmed healthy; the dev server was stopped cleanly and the
  workers restarted once verification finished.
- Not touched in this prompt, per its explicit scope: the overview strip (6.11's work, left
  exactly as it was), any filter bar (still doesn't exist), any feature-specific form fields
  (request customization, tags, check interval — all still 6.14's job), any backend/worker code.

Prompt 6.13 (filter/search/sort bar + tag management UI) is complete. Third frontend prompt.
One real, unplanned-but-necessitated backend addition (tag rename never existed); one real
bug found and fixed during verification (a tag rename wasn't propagating to already-loaded
row chips).
- **Backend: `PATCH /tags/{id}` (rename), added because it genuinely didn't exist** — 6.4's
  original tag CRUD was POST/GET/DELETE only, and this prompt's "create/rename/delete tags"
  ask needs a real rename operation to mean anything. Same validation as creation
  (non-empty, length cap) plus the same per-user duplicate-name 409; renaming to the tag's own
  current name is treated as a no-op success, not a spurious conflict against itself. 404 (not
  403) on a tag that doesn't exist or isn't owned by the caller, same pattern as every other
  ownership-scoped endpoint; `API_KEY_RATE_LIMIT`'s 60/minute IP-keyed bound, matching the
  other cookie-only tag-management endpoints per 6.10's precedent. 7 new backend tests (6 for
  the endpoint itself, 1 rate-limit boundary test) — **297 backend tests total (was 290)**,
  all passing against a rebuilt `api` image.
- **Data-shape decision, stated explicitly rather than left implicit**: the dashboard list
  page fetches `GET /targets` (authoritative existence + tags) and `GET /targets/status` (live
  per-region check data) and merges them client-side by id — **`tags` was deliberately not
  added to `TargetStatusResponse`/the SSE push payload**, since that would mean joining
  `target_tags` on every single check-update notification (a genuinely hot path — every worker
  check, times every connected client) for data that changes rarely. One extra fetch on page
  load is the right place to pay that cost, not the realtime pipeline. Direct consequence,
  handled explicitly: the SSE payload never carries `tags`, so the merge on every incoming
  `check_update` spreads the update *and* explicitly preserves the row's already-known
  `tags` — confirmed via the type system by typing the SSE payload as
  `Omit<TargetStatusRow, "tags">`, not the full row type, so a future edit that forgets this
  can't silently compile.
- **Filter/search/sort — computed fresh from `items` on every render, never a separate
  "filtered copy" kept in sync imperatively**: this is what makes it correct under live SSE
  updates for free, per the prompt's own explicit requirement — a `check_update` (or a tag
  attach/detach) changing `items` re-renders the page, which re-runs the filter/sort against
  the new data, so a row updates in place, disappears, or reappears exactly according to the
  *current* filter with no reconciliation logic anywhere. **Verified this isn't just true in
  theory**: with a live status filter narrowed to "No signal" showing exactly one down target,
  inserted a real recovery check for it directly via SQL and fired the real
  `pg_notify('checks_inserted', ...)` the worker itself sends — in the same still-open browser
  tab, with no reload, the row disappeared into a real "No targets match the current filters"
  empty state, the overview strip updated to 100% uptime/0 down, the persistent banner
  downgraded from red ("2 regions") to amber ("1 region"), and the existing state-transition
  toast fired, all from one real underlying event.
- **Filtering model**: status and region filters narrow which *region entries* within a row
  are visible (not just which rows) — a target is included if at least one of its regions
  survives both filters together (so "status=down AND region=eu-west" correctly means "down
  specifically in eu-west," not "down anywhere and also happens to have an eu-west reading").
  A target with zero checks in any region only matches the neutral case (no region filter,
  and status filter either "all" or "pending") since it has no real region to match against
  a specific filter. Tag filter and text search (name/URL, case-insensitive) are target-level
  filters, applied before the per-region narrowing.
- **Sort**: name (A-Z), status (worst-first — down > degraded > pending > up, matching the
  app's own existing severity language), latency (slowest-first, across a target's regions
  averaged — the readings worth noticing), last-checked (most recent first). Defaults to
  "Default order" (the backend's own newest-first ordering, left untouched) rather than
  silently reordering the list before anyone's touched the control. Nulls (no reading yet)
  always sort last on both numeric sorts regardless of direction — "unknown" isn't better or
  worse than a number, just not comparable.
- **Tag management UI**: `components/tag-manager-modal.tsx` (reuses the Dialog primitive from
  6.12 — create/rename/delete in one place) and `components/target-tag-chips.tsx` (per-row
  attach/detach, since a tag's attachment is a property of the target instance, not the tag
  itself). Small-radius bordered chips, mono tag-name text — the exact same convention
  `RegionBadge` already established, not a new pattern. Attaching uses a plain native
  `<select>` (populated with the tags not yet on that row) rather than pulling in a second
  Radix dependency for a handful of small dropdowns — Dialog earned its dependency in 6.12 by
  being genuinely hard to hand-build correctly (focus trap, portal, Escape); a `<select>` has
  none of that difficulty.
- **Real bug found and fixed during verification, not assumed correct**: renaming a tag in the
  manager updated the filter bar's own tag list (`allTags`) but **not** any target row's
  already-loaded copy of that tag (each row keeps its own `tags` array — see the data-shape
  note above) — confirmed live: renamed "staging" to "staging-env," and a row that already had
  "staging" attached kept showing the stale name until Reset. Fixed by adding a dedicated
  `onTagRenamed` callback (separate from `onTagsChanged`, mirroring the existing
  `onTagDeleted` callback's same reasoning) that pushes the rename into every row's own tags
  list. Re-verified after the fix: the same rename now updates the row's chip live, with no
  reload.
- **Verified end-to-end against the real running stack** with four real targets spanning every
  state (healthy/two-region, degraded, down, never-checked) and two real tags attached via the
  real API: confirmed status/tag/region filters and text search each isolate exactly the
  expected subset (independently verified via each control, not assumed from reading the
  code), confirmed worst-first status sorting produces the exact expected order, confirmed the
  live-SSE-vs-filter interaction described above, confirmed attach/detach through each row's
  own picker/× button (not just via curl), and confirmed the tag manager's keyboard
  accessibility (focus trap held across repeated tabs, focus correctly returned to the
  "Manage tags" trigger on close — the same explicit-restore fix from 6.12 applied here too,
  since this is the same "opened by an external button outside the Dialog's own tree"
  situation). Checked the filter bar at 400px width — wraps into a clean two-column grid, no
  overflow, side gutters hold. Did not re-verify `prefers-reduced-motion` on this Dialog usage
  specifically — it reuses the exact same `.dialog-overlay`/`.dialog-content` classes already
  proven twice (6.12's own verification, and empirically re-confirmed there), so there's
  nothing new in this prompt's own code that could regress it.
- **Self-critique against the `frontend-design` skill's avoid-list**: clean. No new colors,
  shadows, or gradients; tag chips reuse `RegionBadge`'s exact small-radius/mono/bordered
  treatment rather than inventing a pill/card style; filter labels are plain sentence case
  (no all-caps eyebrows); no em dashes in any new copy; no middle-dot meta text; no numbered
  markers; the "×"/"+ tag" affordances are plain text glyphs, not a new icon system (the only
  icon dependency in this app remains the Dialog's own close **X**, from 6.12).
- All verification data deleted afterward via the real `DELETE /auth/me` cascade, confirmed
  via direct SQL count of zero remaining rows across targets and tags. All scratch Playwright
  scripts written directly under `frontend/` (for local `node_modules` resolution), deleted
  before finishing — never committed. Docker stack and the dev server (started fresh for this
  prompt) both confirmed healthy; dev server stopped cleanly and workers restarted once
  verification finished.
- Not touched in this prompt, per its explicit scope: the quick-add modal (6.12's work, only
  the `handleTargetCreated` call site's return type changed to satisfy the new `tags` field),
  the overview strip's own computations (still operate on unfiltered `items`, exactly as
  6.11 left them).

Prompt 6.14 (feature UI surfacing) is complete. Fourth and largest frontend prompt — every
backend feature from 6.2/6.3/6.5/6.6/6.7 now has a real UI. One deliberate backend addition
(webhook `PATCH`, since the toggles this prompt asked for genuinely couldn't be made
interactive without it) and one real client-side validation gap found and fixed during
verification.
- **Backend: `PATCH /webhooks/{id}`, added because the prompt's own ask needed it** — 6.6's
  webhook CRUD was create/list/delete only, with its own docstring explicitly flagging
  "revisit if editing them without delete-and-recreate turns out to matter." It did: "per-
  webhook alert-type toggles, enable toggle" only means something as real interactive
  controls, and recreating a webhook on every toggle would mint a new secret and silently
  break the receiver's already-configured signature verification. URL/alert-type/enabled are
  all independently updatable (pydantic `exclude_unset`, same convention as
  `PATCH /targets/{id}`); a changed URL is re-validated exactly like creation (well-formed
  http(s) + SSRF check); the secret itself is never touched by this endpoint on principle —
  there's still no rotation story, so delete-and-recreate remains the only way to get a new
  one. 404 (not 403) on an unowned/missing webhook; `API_KEY_RATE_LIMIT`'s 60/minute bound,
  matching the router's other endpoints. 9 new backend tests (8 for the endpoint, 1 rate-limit
  boundary) — **303 backend tests total (was 297)**, all passing against a rebuilt `api`
  image.
- **Target settings modal** (`components/target-settings-modal.tsx`, reuses the Dialog
  primitive) — HTTP method, a key/value custom-headers list (add/remove rows), basic auth
  username/password (`autoComplete="new-password"`, "leave blank to keep the current password"
  placeholder once a password is already stored — same convention `PATCH /targets/{id}`'s own
  backend already documents), keyword match + mode, check interval override, and a pause/
  resume `Switch`. Reachable from a new "Edit settings" button on the detail page (per the
  quick-add modal's own 6.12 copy: "Request customization, tags, and check interval can be set
  from the target's own page afterward" — this prompt is what makes that sentence true).
  Pause/resume saves immediately on toggle via the dedicated `/pause`/`/resume` endpoints (not
  bundled into the PATCH body — mirrors why the backend itself keeps pausing as its own state
  transition, not a settable field); every other field saves together via one `PATCH` on
  submit. No backend endpoint exists to fetch one target's full settings shape by itself (only
  the list endpoint returns it) — the modal fetches `GET /targets` on open and picks out the
  matching id, a deliberate reuse rather than a new backend surface for a modal that only
  needs this once, on open.
- **Client-side validation mirrors the backend's own rules exactly**, not just a generic
  required-field check: HEAD + a non-empty keyword match is rejected with the same reasoning
  the backend's `_validate_request_customization` uses, checked both live (an inline warning
  appears the instant HEAD + a keyword are both set) and again at submit time so it can't be
  bypassed by an already-filled field the user never touched again; basic-auth username/
  password cross-requirement (tracked via whether the loaded target already had a stored
  password, since a blank password field alone is ambiguous between "removing auth" and
  "keeping the existing password"); the check-interval floor (30s, matching
  `MIN_CHECK_INTERVAL_SECONDS`); duplicate header names. **Verified live, not just read from
  the code**: filled in every field, switched the method to HEAD with a keyword match already
  set, confirmed the exact same inline warning and submit-blocking message the backend would
  give; fixed it and submitted for real, then confirmed via a direct authenticated API call
  that every field (custom header, basic auth username, keyword match, interval, method) had
  actually persisted — the basic-auth password itself correctly never came back in the
  response, at any point.
- **Analytics on the detail page** (`GET /targets/{id}/analytics`, 6.5's backend): a new
  "Analytics" section with a 24h/7d/30d/90d window selector (button row, matching the region
  tabs' own visual pattern) showing uptime %, p50 latency, p99 latency, and MTTR (with the
  incident count folded into its own label) for the currently selected region, all in mono
  matching every other stat on this page. Fetches all regions in one request per window change
  (the endpoint's own shape) — switching the region tab re-reads the already-fetched response
  instead of triggering a new one. **Verified against real seeded history**: seeded six real
  checks spanning a genuine down period and a real latency spike, and confirmed the 24h window
  showed the exact hand-computable figures (83.3% uptime, real p50/p99, 1h MTTR from 1
  incident) — not just that numbers rendered, that they were the *correct* numbers.
- **Webhook settings** (`components/webhook-settings.tsx`, new section on `/settings`): a
  create form (URL + the two alert-type checkboxes) and a list of existing webhooks, each with
  three real, independently-togglable switches (enabled/downtime/cert-expiry) now that the
  backend supports it. The signing secret is shown exactly once, right after creation, in an
  amber-bordered "copy this now" panel with a working clipboard-copy button — confirmed via a
  fresh page reload that it's genuinely gone afterward and a subsequent `GET /webhooks` never
  includes it, only the URL/toggles.
- **API key management** (`components/api-key-settings.tsx`, new section on `/settings`): a
  create form (name + read/full scope select, with both scopes' real capabilities spelled out
  underneath) and a list of existing keys showing name, scope, masked `key_prefix`, created
  date, and last-used (or "never") — each as its own separate line, deliberately not a middle-
  dot-joined meta string (see the self-critique note below). The raw key is shown once,
  identically to the webhook secret's own pattern. Revoking is soft-delete server-side
  (matches `DELETE /api-keys/{id}`'s existing behavior) — a revoked key stays listed with a
  red "Revoked" badge in place of the Revoke button, as an audit trail, not removed from view.
  **Verified server-side, not just via the UI's own state**: queried `GET /api-keys` directly
  after creating and revoking a key and confirmed the raw value never appears in the response
  at any point, only `key_prefix`.
- **Real client-side validation gap found and fixed during verification**: the webhook URL
  `<Input>` uses `type="url"`, and a genuinely malformed string (e.g. `"not-a-url"`) never
  reaches this app's own `isValidWebhookUrl` check at all — the browser's native constraint
  validation blocks form submission first, showing its own browser-native bubble instead of
  this app's error text. Found by testing with a plain garbage string and getting a Playwright
  timeout waiting for a `<p>` error that structurally can never render. This isn't a bug (the
  browser's own check is a legitimate first line of defense, and this app's custom check still
  needs to exist for cases the browser's native check *doesn't* catch), but it meant the test
  needed a case that passes native `type="url"` validation while still failing this app's own
  http/https-only rule to actually exercise the custom logic. Re-verified with `ftp://
  example.com/hook` (syntactically valid per the browser, invalid per this app's own rule,
  matching the backend's own `test_create_webhook_rejects_non_http_scheme` case exactly) —
  correctly rejected client-side with this app's own error message.
- **Self-critique against the `frontend-design` skill's avoid-list — two real instances found
  and fixed before finishing, not just a clean pass**: (1) the API key list's metadata line was
  originally written as a middle-dot-joined string (`{prefix}… · created {date} · last used
  {date}`) — exactly the template-chrome pattern the skill's avoid-list names explicitly;
  rewritten as separate flex items, matching how every other multi-fact row in this app (e.g.
  the dashboard's own target rows) already displays adjacent facts. (2) the API key scope
  descriptions and both "copy this now" messages originally used em dashes
  (`"Read — view targets..."`, `"Copy this key now — it won't be shown again."`) — this
  project's own house style has explicitly banned em dashes from user-facing copy since 4.2's
  copy pass (and a later full design-pass prompt found and fixed several more that had
  survived elsewhere), so these were rewritten as plain sentences/separate lines rather than
  left as a new instance of something already deliberately eliminated twice before. Otherwise
  clean: no new colors, shadows, or gradients; small-radius bordered chips/panels throughout,
  matching the existing instrument-panel vocabulary; mono used exactly where the rest of the
  app already uses it (live-instrument numbers, tag/key-prefix text); no all-caps labels; no
  numbered markers; no trailing arrows.
- **Verified end-to-end against the real running stack**: registered a throwaway account,
  created and paused a target, seeded six real check rows via SQL (workers stopped for the
  duration, restarted after), and drove every surface through Playwright against the real dev
  server and real backend — the settings modal's full save flow (including the HEAD+keyword
  rejection, confirmed both inline and as a submit-time block), the analytics window switch,
  webhook creation/toggle/secret-reveal, and API key creation/revoke — screenshotting each.
  Checked the target-settings modal and the full `/settings` page at 400px width: the modal
  scrolls internally (`max-h-[85vh] overflow-y-auto`, needed now that it's the single largest
  form in the app) and wraps its header key/value rows without overflow; `/settings` itself
  stacks cleanly with all three new/existing sections readable at that width.
- All verification data deleted afterward via the real `DELETE /auth/me` cascade, confirmed
  via direct SQL count of zero remaining rows across targets, webhooks, and API keys. Scratch
  Playwright scripts (3 across this prompt) written under `frontend/`, deleted before
  finishing, never committed. Docker stack and the dev server (started fresh for this prompt)
  both confirmed healthy; dev server stopped cleanly and workers restarted once verification
  finished.
- Not touched in this prompt: the dashboard list page (filter bar, quick-add modal, overview
  strip — all 6.11-6.13's work, untouched), the alert-preferences/change-password/danger-zone
  sections on `/settings` (unchanged, just joined by two new sections above them).

**All five backend feature areas from Phase 6 (6.2, 6.3, 6.5, 6.6, 6.7) now have a real UI.**
No planned Phase 6 work remains outstanding.

Phase 6, prompt 6.15 (general UI consistency, motion/accessibility, and mobile hardening pass
across 6.11-6.14) is complete. A genuinely thorough, evidence-based audit — every claim
verified against real source or real rendered behavior, not assumed — rather than a
superficial pass; found and fixed four real issues, confirmed everything else already held.
- **Design-system consistency audit, three real fixes**: (1) an em dash survived in a
  `title` tooltip attribute on the dashboard's aggregate-uptime-% stat (`app/dashboard/
  page.tsx`) — missed by 6.11's original em-dash check, which only looked at visible label
  text, not `title` attributes (equally user-facing, shown on hover and sometimes read by
  assistive tech); fixed by splitting into two sentences. (2) `webhook-settings.tsx`'s
  webhook-creation form used native `<input type="checkbox">` for its two alert toggles,
  rendering with a browser-default blue accent color outside the locked ten-token palette,
  while this exact app already has an established `Switch` component (already imported in
  the same file) used for every other boolean toggle everywhere else — swapped both to
  `Switch`. (3) a systemic gap across four files hand-built in 6.13/6.14
  (`target-filter-bar.tsx`, `target-tag-chips.tsx`, `target-settings-modal.tsx`,
  `api-key-settings.tsx`): every raw `<select>` (and, in `target-tag-chips.tsx`, the tag
  detach `×` button) lacked shadcn `Input`'s established
  `focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring` pattern — the
  detach button was the most serious instance, since it had `focus-visible:outline-none` with
  nothing replacing the removed outline, a genuine keyboard-accessibility regression, not just
  a visual nit. Fixed by adding the exact same utility classes to all five locations. All
  three fixes confirmed via `tsc --noEmit` (clean) and empirically via Playwright (below), not
  just by inspecting the added classNames.
- **Radius/type-scale consistency, confirmed clean, no fixes needed**: re-read
  `tailwind.config.ts`'s `borderRadius` block directly (not from memory) — `rounded-lg` on
  `DialogContent` still resolves to `var(--radius)` (4px), matching the 3.4 lock, no drift.
  `skeleton.tsx`'s `rounded-full` on `LatencyGaugeSkeleton` is the deliberate, already-
  documented circular-shape exception (approximating the gauge's genuinely round footprint,
  not a radius-token violation). Every new H2 across 6.11-6.14 (`Webhooks`, `API keys`,
  `Analytics`, `Latency`, `Timing breakdown`, `Uptime`, `Incidents`, `TLS certificate`, `Alert
  preferences`, `Account`, danger-zone heading) uses `text-lg font-semibold`; every new modal
  title (`tag-manager-modal.tsx`, `quick-add-target-modal.tsx`, `target-settings-modal.tsx`)
  uses shadcn's `DialogTitle`, itself `text-lg font-semibold` — one consistent scale
  throughout, confirmed by grep, not assumed.
- **Contrast audit, confirmed clean, no fixes needed**: grepped every new color usage across
  6.11-6.14 — every single one reuses an already-3.8-audited token (`--signal-up/warning/
  down` as text, `--signal-pending-text` for the pending case) exactly as established; no new
  hex value was introduced anywhere in this phase. The one raw `--signal-pending` usage found
  (`app/dashboard/[id]/page.tsx`'s null-SLA readout) is the pre-existing, already-flagged
  large-text (`text-3xl`, 3:1 threshold) exception from 3.8, untouched by 6.11-6.14.
- **Motion audit, confirmed empirically via Playwright, not just by reading the CSS**: drove
  a real browser against the local dev server with `emulateMedia({ reducedMotion: "reduce" })`
  — the quick-add modal's `.dialog-content` and a synthetic `.skeleton-pulse` element both
  read `animationName: "none"`, `animationDuration: "0s"`; under `"no-preference"` the same
  elements read the real animation (`dialog-fade-in`/`0.15s`, `skeleton-pulse`/`1.6s`).
  **Explicitly re-verified for the target settings modal by name**, per the prompt's specific
  ask: opened it under normal motion and confirmed it also correctly plays `dialog-fade-in`/
  `0.15s` (inherits the same `.dialog-content` class as every other modal — no separate motion
  code to diverge). The one-orchestrated-load-in rule was re-confirmed via grep across every
  6.11-6.14 file for `transition-`/`animate-`/`hover:`/`IntersectionObserver` — only the two
  documented primitives plus the dashboard's own existing load-in sequence exist; no new
  scroll-triggered fades or per-card hover effects crept in with the dashboard strip, filter
  bar, or any modal.
- **Keyboard focus audit, confirmed empirically via Playwright computed styles** on every one
  of the newly-fixed elements: tabbed to and read `getComputedStyle(...).boxShadow` on all
  four filter-bar selects, the tag attach-select, the tag detach button, both target-settings-
  modal selects, and the API-key scope select — all nine show the real
  `rgb(236, 239, 237) 0px 0px 0px 1px` ring (the same `--ring`/`--text-primary` value 3.8
  established), proving the fix genuinely works, not just that the CSS classes were added.
- **Real mobile bug found and fixed, via the screenshot pass, not code review**: the target
  detail page's header row (`app/dashboard/[id]/page.tsx`) — title plus the "Edit settings"/
  "Export CSV" buttons — used `flex items-start justify-between` with no `flex-wrap`, so at
  400px width the button pair forced genuine horizontal overflow (the page rendered at an
  actual 682px against a 400px viewport, confirmed by comparing the screenshot's reported
  dimensions before and after the fix). Fixed by adding `flex-wrap` to that row, its own
  loading-skeleton equivalent, the inner button-group div, and the region-tab pill row (same
  page) for consistency/safety. Re-screenshotted after the fix: genuinely 400px wide, buttons
  wrap cleanly onto their own line below the title, no overflow anywhere.
- **Full fresh mobile pass at 400px** across the dashboard (summary strip, legend, filter bar,
  tag chips, quick-add modal all visible together), the detail page (region cards, analytics,
  latency chart, timing breakdown, heatmap, incidents, cert panel, target-settings modal), and
  `/settings` (alert preferences, webhooks, API keys, account, danger zone) — all clean after
  the fix above, no other overflow or cramped-control issues found.
- **Known, pre-existing gap flagged, not fixed (out of this prompt's 6.11-6.14 scope)**:
  `site-header.tsx`'s "Sign out" button (`className="bg-transparent p-0 transition-colors
  hover:text-fg-primary"`, no `focus-visible` ring at all) predates Phase 6 entirely — it's a
  Phase 3 component. Consistent with this project's established practice of flagging rather
  than silently expanding scope onto incidentally-found pre-existing issues.
- **Verification methodology**: rebuilt nothing (frontend-only changes, backend/worker
  untouched) — relied on `tsc --noEmit` (clean throughout) plus real Playwright verification
  against a freshly-started local dev server and the already-healthy Docker stack. Registered
  several throwaway accounts, created real targets (including a real basic-auth-free public
  URL, no SQL seeding needed since this prompt's checks were about UI mechanics/motion/focus/
  layout, not data correctness), drove the real UI end to end (quick-add, tag create/attach/
  detach, target-settings modal open/close, region tabs, webhook/API-key sections),
  screenshotted every major page and modal at both desktop (1280px) and mobile (400px) width
  for the self-critique pass — clean against the avoid-list throughout, no new em dashes or
  middle-dot-joined strings found anywhere in this fresh pass. All verification accounts (6
  across this prompt, one recovered by direct SQL lookup after a console-output truncation
  lost its generated email) deleted afterward via the real `DELETE /auth/me` cascade, hitting
  and working around the real login rate limit (5/minute) along the way rather than bypassing
  it; confirmed via direct SQL count that zero verification users/targets remain. Scratch
  Playwright/cleanup scripts written under `frontend/`, deleted before finishing, never
  committed. Docker stack (`api`/`db`/`worker`/`worker-eu-west`) was never touched (no seeding
  needed this prompt) and stayed healthy throughout; the dev server was stopped cleanly at the
  end.

**Phase 6 is now fully complete, including this consistency/accessibility/motion hardening
pass across every 6.11-6.14 UI addition.** No planned Phase 6 work remains outstanding.

Phase 6, prompt 6.16 (wrap-up + full regression verification) is complete. **Phase 6 is
genuinely, verifiably done** — every backend feature (6.2-6.8), the CSV formatting fix (6.9),
the security walkthrough (6.10), and every UI prompt (6.11-6.15) confirmed working end-to-end
against the real running stack, not just re-read from prior notes. One real, previously-
unnoticed local-dev environment bug was found and fixed along the way (not a shipped-code
regression); every other check passed clean on the first or second try.
- **`PATCH /webhooks/{id}`'s security coverage (this prompt's step-1 ask) confirmed already
  complete, no gap found**: it carries the same `API_KEY_RATE_LIMIT` decorator as every other
  non-create webhook endpoint, a dedicated 60/minute boundary test
  (`test_webhook_update_rate_limited_after_sixty_per_minute`), cross-user ownership coverage
  (`test_user_cannot_update_another_users_webhook`, 404 not 403), and auth-required coverage
  — all already added when the endpoint itself landed in 6.14, correctly anticipating this
  exact follow-up. No new test needed; re-confirmed live with a real cross-user PATCH attempt
  (404) and a real owner PATCH (succeeds, change reflected).
- **Real bug found and fixed: `worker-eu-west`'s Docker image had been stale for a long
  time**, silently running old code while `worker` (local) was rebuilt regularly across
  Phase 6's many prompts. Root cause: `docker-compose.yml` gave `worker` and `worker-eu-west`
  each their own `build:` block against the identical Dockerfile/context but with no shared
  `image:` tag — Compose's default `<project>-<service>` naming then treats them as two
  entirely separate build targets, so `docker compose build worker` (this project's own
  shorthand habit, used in nearly every Phase 6 prompt's own verification) never rebuilt
  `worker-eu-west` at all. Caught live: re-verifying 6.2's cross-host-redirect credential-drop
  fix (a real target through `httpbin.org` → `httpbingo.org/headers`, confirming a custom
  header isn't forwarded across hosts) showed `eu-west` **failing** the check (keyword found,
  meaning the header genuinely leaked) while `local` correctly passed — reproduced twice
  before concluding it was real, not network flakiness. Rebuilding `worker-eu-west` alone
  fixed it immediately; **the committed/shipped code was, and always had been, correct** —
  this was purely a stale local image, never a real regression, and never affected Railway
  (which deploys each service from its own Dockerfile independently, not from this
  compose-level image-tag sharing). **Fixed structurally**, not just this once:
  `docker-compose.yml`'s `worker-eu-west` now has no `build:` block of its own and instead
  shares `worker`'s exact `image: uptime-monitor-worker:latest` tag, so rebuilding `worker`
  always rebuilds/recreates `worker-eu-west` too from now on — confirmed by testing that
  `docker compose build worker` alone now recreates both containers. **Caveat for whoever
  picks this up next**: because of this, any past prompt's own "confirmed both regions"
  claims specifically about `eu-west` behavior may, in a small number of cases, have silently
  been checking stale local code rather than what was actually committed at the time — the
  committed code itself was never wrong (re-verified live, see above), only this local
  container's copy of it, so nothing needs re-auditing, just flagging as a known blind spot
  in this project's own local-dev verification history.
- **Full pytest suites, fresh**: **303 backend + 59 worker = 362 tests total**, all passing
  against freshly rebuilt images (up from 160 total at the Phase 5 close — 179 new backend
  tests, 23 new worker tests, one for every Phase 6 backend addition: request customization/
  keyword monitoring, pause/resume/interval, tags, analytics, alerting restructure/webhooks,
  API keys/rate limiting/pagination, retention, the CSV formatting rewrite, and the 6.10
  rate-limiting-gap fixes). `tsc --noEmit` clean. `next build` intentionally not run — a dev
  server was live on port 3000 throughout (this project's own established rule since 3.7);
  live-stack Playwright verification stood in for it, as in every prompt since.
- **End-to-end manual verification, all nine items from this prompt's checklist confirmed
  against real infrastructure**: keyword monitoring correctly flagged a real mismatched
  target (`200 OK`, `is_up=false`, exact "Keyword match failed" error, both regions) — caught
  and fixed my own first attempt's flawed test target (a URL that 404'd before ever reaching
  the keyword check) along the way, a test-authoring mistake, not a product bug. Pause/resume
  proven against a real target: paused, forced due, confirmed zero checks across 2+ scheduler
  ticks, resumed, confirmed a fresh check landed within ~8s. Custom check interval (30s)
  confirmed respected on success (`next_check_at` landed ~30s out, not the 300s default) —
  again required fixing my own first test target, which had been failing and thus exercising
  the backoff curve instead of the custom interval, a design behavior 6.3 documented
  correctly, not a bug. Tags confirmed filtering the dashboard live via the real UI (attach
  via the row's own picker, filter via the bar's own select, exactly one matching row shown).
  Uptime/p50/p99/MTTR confirmed correct against hand-computed values from ten seeded checks
  (80.0% uptime, 58ms p50, 842ms p99, 40m MTTR/1 incident — every figure matched exactly)
  across window changes on the real detail page. A webhook created through the real Settings
  UI received two real, correctly-signed deliveries (`target.down` then `target.up`) from a
  real forced transition, with the dashboard's own row simultaneously updating live in the
  same browser tab with no reload — confirmed both the external delivery and the in-app UI
  together, not just one or the other. An API key created through the real UI authenticated
  60 real requests then hit a real 429 on the 61st, with the same account's cookie-
  authenticated session completely unaffected; the full raw key value was confirmed genuinely
  gone from the page after a reload (only the key showing "um_..." as its own prefix
  remained, not the full secret — my first check for this was a false positive matching that
  prefix substring, corrected with an exact-string comparison). Retention's `prune_old_checks`
  was invoked directly against seeded data spanning the 90-day boundary (3 rows correctly
  deleted, exactly the >90-day ones), and `GET /targets/{id}/analytics` and
  `GET /targets/{id}/export` were both confirmed to still return clean, correct 200 responses
  immediately afterward — no breakage from checks disappearing out from under a live query.
  The CSV export's 6.9 formatting fix was reconfirmed correct on real data (clean Summary/
  Incidents/Checks sections, consistent timestamp formatting, lowercase `true`/`false`, plain
  integer incident duration) — the one assertion my own script got wrong (expected "20"
  minutes, got "40") was again my own arithmetic error in seeding the seed data's down window,
  not a bug; the app's computed 40-minute duration was the objectively correct one.
- **Phase 0-5 regression checks, all held, re-verified live rather than assumed**: ownership
  enforcement (21 separate cross-user/anonymous checks across targets, webhooks, tags, API
  keys, analytics, and export — every one 404-not-403 or 401 as expected, including the
  6.10-fixed endpoints); cookie-auth rate limiting (login exactly 5-then-429, register
  exactly 3-then-429, both hit organically during this prompt's own verification traffic, not
  synthetically forced); `JWT_SECRET` fail-fast (stripped from `.env`, real container crash
  with the same `ValidationError` every prior wrap-up has hit, `.env` restored byte-for-byte
  via diff, clean recovery); SSRF blocking (metadata-IP and private-IP rejected at both target
  and webhook creation; the cross-host credential-drop fix from 6.2 re-verified live and
  found the `worker-eu-west` staleness bug above — the fix itself was never actually broken);
  per-user SSE filtering (two real concurrent streams, the target's owner received both
  regions' real check_update events, the other user received zero); per-region independence
  (the same target's `eu-west`/`local` entries showed genuinely distinct `checked_at`/
  `latency_ms`/timing-breakdown data, never merged or collapsed).
- **6.10's security-walkthrough findings reconfirmed still holding after 6.11-6.15's frontend
  work**: the six previously-ratelimit-gapped endpoints (`PATCH /targets/{id}`,
  `POST /targets/{id}/resume`, tag attach/detach, `POST /tags`, `DELETE /api-keys/{id}`) still
  carry their fixed decorators (confirmed via the full passing test suite, since none of
  6.11-6.15 touched backend code at all); credential handling re-spot-checked live — a
  target's basic-auth password never appeared in any response body, an API key's full raw
  value never appeared in `GET /api-keys`, a webhook's signing secret never appeared in
  `GET /webhooks`. Nothing in the five frontend prompts reintroduced a leak or weakened an
  ownership check, consistent with them never having touched backend code in the first place.
- All verification data (5 accounts, their targets/webhooks/tags/API keys, ~30 seeded check
  rows) deleted afterward via the real `DELETE /auth/me` cascade, confirmed via direct SQL
  count of zero remaining `wrap616*`-prefixed rows anywhere. Scratch Playwright/API scripts
  (11 across this prompt) written under `frontend/`, deleted before finishing, never
  committed. Docker stack confirmed healthy throughout and after; the one pre-existing
  self-healing safety path (a target deleted mid-check logs and swallows a
  `ForeignKeyViolationError` rather than crashing the cycle, per 1.3's original design) fired
  naturally during cleanup and behaved exactly as designed.
- **Assessment: Phase 6 is genuinely done.** No functional gap was found anywhere in the
  actual shipped code across 13 backend features, the CSV fix, the security walkthrough, and
  6 rounds of UI work. The one real finding (`worker-eu-west`'s stale local image) was an
  artifact of this specific local dev environment's Docker Compose setup, now structurally
  fixed so it can't recur, and never affected what was actually committed, tested, or would
  be deployed. Nothing needs revisiting before Phase 7 begins.

**Phase 6 complete. Next: Phase 7 — presentation** (README rewrite, ADRs, `LOAD_TESTING.md`
against the live deployed instance, and resume framing) per CLAUDE.md's phase plan.

Update this line, and add brief notes below it, at the end of every prompt so a new chat session
can pick up context immediately without re-reading the whole codebase.
