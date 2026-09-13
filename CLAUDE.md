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

Update this line, and add brief notes below it, at the end of every prompt so a new chat session
can pick up context immediately without re-reading the whole codebase.
