# ADR 004: Viewer-Aware Scheduling

## Status

Accepted. Implemented in `worker/scheduler.py`, `worker/watching.py`, `worker/main.py`,
`backend/realtime.py` (`ListenerController`), `backend/activity.py`,
`backend/routers/internal.py`, `backend/database.py`, and the dashboard's hidden-tab handling in
`frontend/lib/use-hidden-tab-cutoff.ts`.

## Context

The database runs on Neon's serverless Postgres free tier. Compute there is billed in
compute-unit-hours against a fixed monthly allowance, and it accrues the whole time the database
is awake. The database suspends itself after five minutes with no activity, and only stops
accruing once it's suspended. Any query, and any connection that is in the middle of a
transaction, counts as activity and keeps it awake.

That puts a hard number on scheduling. A system that touches the database every few seconds
around the clock keeps it awake around the clock: at the smallest compute size that's about
180 compute-unit-hours a month, well past the free allowance. To fit, the database has to be
asleep for most of the day.

At the same time, the product only feels alive if it's live while someone is looking at it. A
signed-in user expects targets to be checked on their configured interval, a new target to get
its first check within seconds, and the dashboard to update by itself when a check lands.

Most of the day, nobody is looking. Those hours still need monitoring and alerting, but they
don't need second-by-second freshness.

## Decision

The workers run in one of two modes, chosen by whether anyone is using the site.

### Watching

The backend defines "watching" in one place, `realtime.is_watching()`: an open Server-Sent
Events stream, or any cookie-authenticated request in the last 5 minutes
(`WATCHING_WINDOW_SECONDS`). API-key requests never count, so a script polling the API on a
schedule can't keep the system in live mode. The timestamp lives in process memory, so asking
the question never touches the database.

Workers ask over HTTP: `GET /internal/watching` returns `{"watching": true|false}`. It's
authenticated with a shared secret in the `X-Internal-Secret` header, compared in constant time,
and left out of the public API schema. A worker that can't get a clear answer (backend
unreachable, a timeout, a wrong secret, an unexpected body) treats it as "not watching," so every
failure mode falls back to the cheap mode.

The dashboard closes its live stream after the tab has been hidden for 3 minutes, so a
forgotten background tab doesn't keep the system in live mode. When the tab comes back, it
reopens the stream, refetches, and merges by check time so nothing missed while hidden is lost.

### Live mode

While watching, each worker keeps a connection pool and runs a claim pass every 5 seconds.
Targets are checked on their normal interval (5 minutes by default, or a target's own interval,
with a 30 second floor), and a failing target backs off on its usual curve. The worker re-asks
every 30 seconds and leaves live mode only after two consecutive "no" answers, at the end of
the pass it's running.

### Idle mode

While nobody is watching, a worker holds no database connections at all. It sleeps until the
next multiple of `BURST_INTERVAL_SECONDS` (900 by default) since the Unix epoch, so every region
wakes on the same boundaries no matter when each one started. Meanwhile it re-asks every 15
seconds and switches to live mode immediately on a "yes."

At each boundary it opens a fresh pool and runs a burst:

- The first claim pass includes anything due within the next 60 seconds, so a target due just
  after the boundary doesn't wait a whole extra interval.
- Further passes run only while a target with one or two consecutive failures has a retry due
  before the burst's 90 second cap. Those are the early, short backoff steps, so a fresh failure
  gets confirmed or cleared in the same burst. Long-failing targets wait for a later burst.
- Retention pruning runs in the first pass after each UTC midnight.
- The pool is then closed, and the database can go back to sleep.

### The LISTEN connection

The backend delivers live updates and evaluates alerts from Postgres `NOTIFY`. Its `LISTEN`
connection is held only while it can matter:

- from 10 seconds before each burst boundary until 60 seconds after it,
- while the site is being watched, and for 120 seconds after it stops,
- for 30 seconds after the most recent notification,
- until a burst's retry cap plus 30 seconds, when a burst is retrying a target that just
  started failing,
- while a notification handler or a catch-up is still running.

Outside those windows the connection is closed. The controller re-evaluates every second and
wakes immediately when the first stream subscribes or a cookie request arrives.

Nothing is lost while it's closed. The backend keeps a watermark of the highest check id it has
handled. Every time `LISTEN` opens or reconnects, it replays checks above the watermark in
batches of 500, once per target and region, through the same handler a live notification uses.
At startup the watermark is set to the newest check older than 10 minutes, and a catch-up runs
right away, so a restart in the middle of a burst still sends that burst's alerts. Replays are
safe: alert history suppresses duplicates, and a repeated push carries the same current state.

### Connections

Ordinary API requests open a database connection per request and close it when the request ends
(SQLAlchemy `NullPool`). The SSE endpoint resolves the user from the session cookie in its own
short-lived session and then holds no database connection for the life of the stream. Every
connection carries an `application_name` (`api`, `api-listen`, `worker-<region>`), so
`pg_stat_activity` shows exactly who is connected at any moment.

## Alternatives considered

**Continuous polling with an always-open `LISTEN` connection.** One scheduling loop every few
seconds and a permanent listener is the simplest design and gives the best freshness. It also
means the database is never idle for five minutes, so it never suspends and compute accrues
around the clock, roughly 180 compute-unit-hours a month at the smallest size. Rejected because
it can't run within the budget.

**Paying for always-on compute.** A paid plan would make the budget question go away. Rejected
because this is a personal portfolio project, and the free tier is enough once the database is
only awake when it's doing something. Paying to keep an idle database awake buys nothing a user
would notice.

**Batch-only scheduling with no live mode.** Checking everything every 15 minutes, with no
notion of a viewer, is cheaper still and simpler than this design. Rejected because the product
depends on being live while someone uses it: a newly added target would sit unchecked for up to
15 minutes, configured intervals shorter than 15 minutes would mean nothing, and the dashboard
would rarely update while someone was watching it.

## Consequences

- **Up to 15 minutes of detection delay while nobody is watching.** A target that goes down
  between bursts is noticed at the next burst, so an idle-mode downtime alert can arrive up to
  15 minutes after the outage starts. A short interval configured on a target only applies while
  someone is watching. This is the main cost of the design, and it's stated as a limitation
  wherever limitations are listed.
- **Live mode starts within about 15 seconds of someone signing in**, the length of an idle
  poll. Anything stale is due straight away, so it's rechecked on the first live tick.
- **Live mode ends about five to six minutes after the last activity**: the 5 minute watching
  window plus two 30 second polls.
- **Checks can run up to 60 seconds early** on a burst's first pass. A small and harmless shift
  in exchange for not deferring a just-due target by a full interval.
- **Measured result.** Over about 19 hours in production, the database used about 2.2
  compute-unit-hours a day, roughly 66 a month, inside the free allowance with room left for
  live viewing. `BURST_INTERVAL_SECONDS` is configurable on all three services (it must match
  everywhere, since the backend's listener windows are computed from it), so a longer interval
  is a configuration change if usage grows.
- **Every API request pays for opening a connection.** A per-request connection adds connection
  setup to each request in exchange for leaving nothing open after the request ends.
- **Single API process.** The watching timestamp and the listener state live in one process's
  memory, the same assumption the rate limiter already makes. Running several API instances
  would need a shared store for both.
- **Shared configuration.** Workers need the backend's public URL and the same internal secret
  as the backend. If either is missing or wrong, a worker stays in idle mode and logs a warning
  about once a minute. Monitoring keeps working, just without live mode.
