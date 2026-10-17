# Case Study

## Problem Statement

Most uptime monitors reduce a check to one number: up or down. That throws away almost
everything useful about *why* a service is slow or unreachable, and it papers over the fact
that "reachable" genuinely depends on where you're asking from. I built this to keep that
detail instead of discarding it: every check breaks its own request down into DNS, TCP, TLS,
and time-to-first-byte, captures the TLS certificate it saw along the way, and runs
independently from more than one region so a regional problem shows up as a regional problem,
not a vague global "down." None of that is exotic engineering on its own. The interesting part
was building it as a small, coherent system: a worker that schedules and backs off per target
per region, a backend that never collapses that detail on the way out, and enough real
infrastructure discipline (ownership enforcement, SSRF defense, signed webhook delivery, scoped
API keys) that the whole thing could actually be handed a stranger's URLs.

## Key Technical Decisions

### SSRF defense: two checkpoints, not one, plus a redirect problem I didn't see coming

A worker that fetches user-supplied URLs on a schedule is a textbook SSRF vector. The obvious
targets are a cloud metadata endpoint or an internal service the worker's own network can reach
but the public internet can't. Blocking loopback, RFC1918, and link-local ranges is the easy
part. Deciding *when* to check is the real decision: at submission time only misses DNS
rebinding (a hostname that resolves safely today and unsafely tomorrow); at check time only
means a bad URL sits silently unrejected until the next cycle instead of failing fast for the
person who just typed it in. I built both: a synchronous check at `POST /targets` for
immediate feedback, and an independent check on the worker before every single request,
including every hop of a redirect chain.

That second part surfaced a bug I hadn't anticipated. Re-validating each redirect hop meant
disabling the HTTP client's own automatic redirect-following and walking the chain by hand.
That also silently disabled the client's default behavior of stripping `Authorization` on a
cross-origin redirect. Once targets could carry custom headers and basic-auth credentials, that
meant a target's password or a secret-bearing header would have been forwarded to whatever host
a `3xx` response happened to name, not just the host the user configured it for. I found this
by reading through what manual redirect-following actually gives up versus what the client
normally does for you, not by someone reporting it. I fixed it by dropping a target's
configured headers and auth the moment a redirect crosses to a different host, and never
restoring them even if a later hop redirects back. See
`docs/adr/002-ssrf-validation-timing.md` for the full reasoning and the alternatives I ruled
out.

### An async worker with per-target backoff, not a flat polling loop

The worker checks every target on the schedule it's individually earned, not a single global
interval. `httpx.AsyncClient` plus `asyncio.gather` (bounded by a semaphore, 15 concurrent
checks at a time) lets one process handle a real batch of targets in roughly one round-trip
instead of one-by-one. A failing target backs off exponentially: 30s, 60s, 120s, 240s, 480s,
capped at 900s. Each retry is jittered by ±20% so targets that start failing at the same
moment, like a shared upstream DNS blip, don't all retry in perfect lockstep forever. A
successful check resets the streak and returns to the normal cadence immediately. While
someone is using the site, the worker looks for due work every 5 seconds, much shorter than the
normal per-target interval, so a 30 second backoff step really does retry after about 30
seconds instead of waiting for the next 5-minute mark.

### Viewer-aware scheduling: a database that sleeps when nobody is looking

The database is Neon's serverless Postgres on its free tier. Compute there accrues for as long
as the database is awake, and it only suspends after five minutes with no activity. A scheduler
that touches the database every few seconds around the clock would keep it awake around the
clock, about 180 compute-unit-hours a month at the smallest size, far past the free allowance.
So the scheduler is built around one question: is anyone using the site right now?

The backend answers it from memory. The site counts as watched while any live-update stream is
open, or for 5 minutes after any cookie-authenticated request. API-key requests don't count, so
a script polling the API can't hold the system awake. Workers ask over an internal endpoint
protected by a shared secret, and any failure to get a clear answer counts as "no," so every
failure mode falls back to the cheap behavior. A dashboard tab hidden for 3 minutes closes its
stream, and resyncs when it comes back.

While someone is watching, the worker runs **live mode**: a held connection pool, a claim pass
every 5 seconds, every target on its normal interval. While nobody is, it runs **idle mode**: no
database connections at all, and a batch on every 15-minute multiple of the Unix epoch, so both
regions wake together no matter when each one started. A batch's first pass picks up anything
due within the next 60 seconds; further passes run only to retry a target on its first or
second consecutive failure, capped at 90 seconds; then the pool closes. The backend's `LISTEN`
connection follows the same rhythm: open from 10 seconds before a batch to 60 seconds after it,
or while someone is watching, and closed otherwise. Whenever it opens, it replays any check it
hasn't handled yet from a check-id watermark, through the same handler a live notification
uses, so an alert is never lost to a closed connection or a restart. Ordinary requests open one
database connection each and close it when the request ends, and the live-update stream holds
no database connection at all once it's established.

I considered three alternatives. Continuous scheduling with an always-open listener keeps the
database awake permanently, so it can't fit the budget. A paid always-on plan would fit, but
pays to keep an idle database awake for a personal project. Batch-only scheduling with no live
mode is cheaper and simpler still, but a new target would sit unchecked for up to 15 minutes and
the dashboard would barely move while someone watched it. The cost of the chosen design is
detection delay while nobody is watching: an outage can take up to 15 minutes to be noticed and
alerted on. In production it uses about 2.2 compute-unit-hours a day. See
`docs/adr/004-viewer-aware-scheduling.md` for the full reasoning.

### Row-claiming for coordination, not a message queue

Once more than one worker process exists, whether that's horizontal scaling within a region or
a second region entirely, something has to stop two of them from grabbing the same due target
at the same moment and racing on the result. I used `SELECT ... FOR UPDATE SKIP LOCKED` against
a schedule row, stamped with a `claimed_at` timestamp, released the instant the claim is stamped
(not held for the actual HTTP request, which can take seconds). `SKIP LOCKED` means a concurrent
claim attempt on the same row doesn't block waiting for the first one. It just skips that row
and checks whatever else is due, so there's no retry loop or deadlock risk to reason about. A
claim older than 120 seconds, roughly double the worst realistic single-check duration, is
treated as abandoned and becomes claimable again, so a worker that crashes mid-check doesn't
leave its targets stuck. I considered Postgres advisory locks and a dedicated leases table
first; both would have worked, but `SKIP LOCKED` gets the same guarantee out of row locks the
database already provides, for two extra columns on an existing table rather than a second
mechanism with its own visibility and cleanup story. See
`docs/adr/003-multi-region-coordination.md` for the full comparison.

### Per-region results, never collapsed into one boolean

Scheduling state (`next_check_at`, `consecutive_failures`, `claimed_at`) lives per
`(target, region)`, not per target. Each region tracks its own independent view of whether a
target is healthy. The API and the real-time push both report every region's latest result
side by side; there is no derived "is this target up" field anywhere. I considered the two
obvious shortcuts, down if down in *any* region, or down only if down in *every* region, and
rejected both: the first turns a single region's transient blip into a false alarm for an
otherwise-healthy target, and the second hides a real regional outage until it happens to also
fail everywhere else, which is exactly the signal multi-region checking exists to surface. This
is a genuine audience-dependent call, not an obviously correct one. A public status page
serving third parties would probably make the opposite choice, collapsing to one verdict because
that's what its audience actually needs. This is a private tool built for its own owner, where
the diagnostic detail is the point.

### Alert cooldowns: suppress on state, not on time alone

Downtime alerting could have been "email on every failed check," which would be useless spam for
anything that stays down for more than a few minutes. Instead, a dedicated table tracks the last
alerted state per `(target, region, alert_type)`: a downtime alert fires once on the transition
into "down," is suppressed while it stays down, and a cooldown (900 seconds, matching the
worker's own backoff cap) additionally gates how soon a *new* down transition can re-alert after
a recovery. That's what actually dampens a flapping target, since recovery itself has no
cooldown of its own. Cert-expiry alerts follow a related but distinct shape: they fire once when
a certificate first crosses a 14-day warning window, then re-remind at most every 3 days while
still unrenewed, and a renewed certificate (a changed expiry date) resets eligibility
immediately regardless of the reminder cooldown, since that's a genuinely new expiry window
worth its own first alert. Both evaluators are structured so a *failed* send is never recorded
as "already alerted." I found and fixed a real version of this bug during development: a
delivery failure was silently treated the same as a success, which would have permanently
suppressed the real alert with no retry, even after whatever broke delivery got fixed.

### Webhooks: re-validated at send time, signed, never chased through a redirect

Webhook alerting reuses the exact SSRF check target URLs get, applied again immediately before
every delivery attempt and not just at webhook creation. That's the same DNS-rebinding defense
the worker already applies to monitored targets. Delivery is deliberately thin: one attempt, a
5 second timeout, no redirect-following (a `3xx` is treated as a failed delivery outright,
since a webhook receiver essentially never has a legitimate reason to redirect), log-and-swallow
on failure so a broken webhook can never corrupt or delay the real-time dashboard push that
fires from the same code path. Every payload is signed with HMAC-SHA256 over the exact raw JSON
body, using a secret generated once at creation and shown to the caller exactly one time, the
same "shown once, never again" pattern this project already used for password-reset tokens and
API keys, applied consistently to a third kind of secret.

### API keys: scoped, hashed, and structurally unable to manage themselves

Programmatic access needed its own credential, not a reuse of the session cookie's JWT. A
cookie has no revocation story, and a script holding a long-lived session token is a different
risk profile than a browser holding an `HttpOnly` cookie it never touches directly. API keys
are hashed at rest (SHA-256, not a slow password hash, since a 32-byte random key has no
dictionary to defend against) and scoped `read` or `full`. The rule I consider the most
important part of the design: **an API key can never be used to create, list, or revoke other
API keys**, regardless of its own scope. Every key-management endpoint depends on the
cookie-only auth path directly, never the key-accepting one, so this isn't a policy check that
could be gotten wrong at one call site. It's structural. See
`docs/adr/001-jwt-cookie-sessions.md` for why the session mechanism and the API-key mechanism
ended up as two deliberately separate systems rather than one extended to cover both cases.

## Quantified Results

Real figures produced by this project's own testing and live verification, not modeled or
estimated:

| Measurement | Value |
|---|---|
| Backoff curve (failures → next retry) | 30s → 60s → 120s → 240s → 480s → capped at 900s, each ±20% jitter |
| Claim staleness TTL (crashed-worker self-heal) | 120s |
| Live-mode claim pass interval | 5s |
| Idle-mode batch interval | 900s, aligned to the clock so both regions wake together; first pass includes targets due within 60s, in-batch retries capped at 90s |
| Database compute in production | about 2.2 compute-unit-hours a day, measured over roughly 19 hours |
| Concurrent checks per worker process | 15 |
| Default per-target check interval | 300s (configurable per target, 30s floor) |
| Downtime alert cooldown | 900s |
| Cert-expiry warning window / repeat-reminder cadence | 14 days / 3 days |
| Checks-table retention window | 90 days |
| Minimum observed gap between two checks of the same `(target, region)` under forced same-region contention | ~3.85 seconds, consistent with two independent due-cycles and never the sub-second gap an actual double-claim would produce |
| Schema migrations | 14, applied cleanly against both local Postgres and the production Neon instance |
| REST/SSE endpoints | ~34, across auth, targets (including request customization, pause/resume, tags, analytics, export), webhooks, and API keys |
| Automated test suite | 449 tests (348 backend, 101 worker), all passing against a real Postgres database, no mocked database layer |
| Regions actually running in production | 2, on independently deployed Railway services, coordinating through nothing but the shared database |

## What This Project Deliberately Is Not

This isn't a public status-page product. There's no page anywhere listing what anyone else is
monitoring, and there's no concept of a shared or demo account with real data. Every visitor
registers their own account and sees only their own targets. It isn't built for a fleet of
monitored URLs either: the scheduling, claiming, and rate-limiting choices here (an in-memory,
per-process rate limiter; two regions, not twenty; a synchronous CSV export rather than a
streamed or background-generated one) are sized for a personal tool watching a personal list of
services, not thousands of targets across dozens of tenants. Several of those choices, a shared
rate-limit store among them, are called out explicitly in code as needing a different answer
before that would be true. Alert delivery doesn't retry per channel: if email succeeds but a
webhook fails for the same event, that webhook isn't individually retried on the next check.
Tracking "was this transition alerted at all" was the right amount of complexity for this
project's actual use, not "did every channel confirm delivery." Monitoring while nobody is
signed in is deliberately coarse: everything is checked once every 15 minutes, so an outage can
take up to 15 minutes to be noticed. The load characteristics here
are honest, not benchmarked against real production traffic. The request-flow design
(claim-then-release-the-lock-before-the-network-call, bounded concurrency, connections opened
only for as long as they're needed) is built the way I'd want it built at a larger scale, but it hasn't
been proven at one.
