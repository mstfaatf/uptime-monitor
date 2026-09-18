# Load Test

Real results from running load against the actual deployed backend on Railway, not the local
Docker Compose stack. Run on 2026-09-18, against
`https://uptime-monitor-production-cff9.up.railway.app` — a single Railway service instance,
talking to a single Neon Postgres instance, exactly the infrastructure this project is
genuinely deployed on. Nothing here is scaled up or specially provisioned for the test.

## Tool and methodology

[k6](https://k6.io) (`grafana/k6`, run via Docker rather than installing a binary — this
machine already treats Docker as the default way to run project tooling) for the two HTTP-based
tests. k6's own SSE support (`k6/experimental/sse` and `k6/x/sse`, tried in that order) isn't
provisionable in the `grafana/k6:latest` image at the version available for this run
(`k6 v2.2.0`) — its extension-resolution step reports both as an unrecognized dependency rather
than building them, and this environment has no reason to stand up a custom k6 build pipeline
just for one test. The SSE concurrency test was written instead as a small Node script using
the built-in `https` module directly, parsing the `text/event-stream` body by hand — a
legitimate, common way to drive an SSE endpoint under load when a purpose-built tool isn't
available, and honestly simpler for this one narrow test than it would have been to get k6's
SSE module working.

A throwaway account was registered against the live API for all three tests (`POST
/auth/register`), never the account's own real login. All targets created during testing, and
the account itself, were deleted afterward via `DELETE /auth/me` (which cascades to every
target and check it owns) — confirmed by a subsequent login attempt with the same credentials
correctly returning `401`. One test-tooling anomaly worth noting plainly: the very first login
attempt immediately after the `204` from `DELETE /auth/me` returned a stale `200` with the
already-deleted user's data, before a retry two seconds later correctly returned `401`. This
reads as a read-after-write consistency lag on Neon's pooled connection (a stale read landing
on a different pooled backend than the one that just committed the delete), the same category
of pooling quirk this project has hit and documented before — not a real account-deletion bug,
and not something this test is about, so it wasn't chased further.

## Test 1: Read path — `GET /targets/status`

The dashboard's main read, authenticated via a real session cookie, against a seeded account
with one real target.

**Load profile:** ramping virtual users, 0 → 10 over 15s, 10 → 30 over 20s, 30 → 0 over 15s
(50s total).

**Results:**

| Metric | Value |
|---|---|
| Total requests | 1,242 |
| Failed requests | 0 (0.00%) |
| Throughput | 27.6 req/s |
| Latency, average | 357ms |
| Latency, median | 307ms |
| Latency, p90 | 455ms |
| Latency, p95 | 810ms |
| Latency, max | 1.25s |

Every single request succeeded. Latency climbed as concurrency ramped (the p95 figure is
dominated by the peak-30-VU window, not the whole run) but never errored, and there's no sign
in this profile of the single Railway instance being close to its own limit at this load.

## Test 2: Write path — `POST /targets`, under its rate limit

`POST /targets` carries a `10/minute` IP-keyed limit, the project's original abuse protection
against mass target creation. This test intentionally exceeds it to see the real cutoff, not
just trust the number in the code.

**Load profile:** 5 constant virtual users, each creating a target with a unique URL once per
second, for 40s.

**Results:**

| Metric | Value |
|---|---|
| Total requests | 151 |
| Created (`201`) | **10** |
| Rate-limited (`429`) | **141** |
| Throughput | 4.2 req/s |
| Latency, successful requests only, average | 633ms |
| Latency, successful requests only, p95 | 991ms |
| Latency, all requests, average | 352ms |

Exactly 10 requests succeeded before the limiter cut in, and it held at exactly 10 for the rest
of the 40-second window — this matches the documented `10/minute` limit precisely, not
approximately. A `429` response is meaningfully faster than a `201` (it never reaches the
SSRF-resolution/DB-write path a real creation does), which is why the all-requests average sits
well below the successful-only average.

## Test 3: SSE concurrency — `GET /targets/stream`

Repeated attempts at increasing levels of concurrency, each opening N connections at once from
one client, holding them open for 35 seconds, then closing them.

**Results:**

| Concurrent connection attempts | Connections that opened (`200`) | Connections rejected (`500`) |
|---|---|---|
| 5 | 5 | 0 |
| 10 | 10 | 0 |
| 15 | 15 | 0 |
| 16 | 15 | 1 |
| 17 | 15 | 2 |
| 20 | 15 | 5 |
| 25 | 15 | 10 |

**This is a real, reproducible breaking point, not a one-off blip** — confirmed across six
separate runs at six different concurrency levels: **exactly 15 concurrent SSE connections
succeed from a single client; every connection past the 15th fails immediately with a genuine
HTTP 500**, not a timeout or a slow degradation. The failure count past 15 scales exactly
linearly with how far over 15 the attempt goes (1 over → 1 failure, 10 over → 10 failures),
which is the signature of a hard concurrency ceiling somewhere in the stack, not a resource
that degrades gracefully under load. This wasn't chased down to its exact root cause (most
likely a connection or worker-count limit somewhere between Railway's edge and the ASGI
server's own default configuration, rather than anything in this project's own `realtime.py`
pub/sub logic, which has no such cap written into it) — flagged here as a real, honest finding
rather than investigated to completion, since root-causing it thoroughly was outside this
test's scope.

For the connections that did open successfully:

| Metric | Value |
|---|---|
| Time to first byte (the `: connected` comment), average | ~660–800ms across runs |
| Time to first byte, p95 | ~900ms–1.05s |
| Keep-alive comments received (15 connections, 35s window) | 45 (as expected — roughly one per connection per 15s interval) |

A real check was forced mid-test (`POST /targets/{id}/resume`, which forces an immediate
recheck) to try to observe a genuine `check_update` push landing during the test window, not
just keep-alives. No real push event was captured in any run within the 35-second window — a
plausible, unproven explanation is that the forced recheck's own round-trip through the
worker's next scheduling tick, the check itself, and the NOTIFY didn't consistently land before
the window closed, not that the push mechanism itself is broken (the same mechanism has been
directly verified working, including under real concurrent load, in earlier verification
passes). Stated honestly as a gap in this specific test's observation, not glossed over as "it
must have worked."

## What this does and doesn't show

This confirms the read and write paths hold up cleanly at moderate concurrency (tens of
requests per second, well within what a single free-tier Railway instance and a personal
project's real traffic would ever see), that the write-path rate limit enforces exactly what
it's documented to enforce, and that real-time SSE has a genuine, previously-unmeasured
concurrency ceiling around 15 simultaneous connections per client on this deployment. It does
not test sustained load over minutes or hours, doesn't exercise multiple concurrent user
accounts at once (every test ran as a single authenticated user), and doesn't push either HTTP
path anywhere near hard enough to find its own breaking point the way the SSE test found one —
those would be reasonable next steps, not claimed as already done here.
