# Load Test

Real results from running load against the actual deployed backend on Railway, not the local
Docker Compose stack: `https://uptime-monitor-production-cff9.up.railway.app`, a single Railway
service instance talking to a single Neon Postgres instance, exactly the infrastructure this
project is deployed on. Nothing here is scaled up or specially provisioned for the test. The
read and write path tests ran on 2026-09-18; the SSE concurrency test ran on 2026-10-17.

## Tool and methodology

[k6](https://k6.io) drove all three tests, run through Docker rather than installed on the host.
The two HTTP tests use the stock `grafana/k6` image. The SSE test uses a k6 binary built with
[xk6](https://github.com/grafana/xk6) and the [`xk6-sse`](https://github.com/phymbert/xk6-sse)
extension, since SSE support isn't part of the stock image. Each SSE virtual user opens one
`text/event-stream` connection, holds it for a fixed window using the client's own timeout, and
records whether the `: connected` comment arrived, how long that took, and every event received.

A throwaway account was registered against the live API for each test (`POST /auth/register`),
never a real account. All targets created during testing, and the account itself, were deleted
afterward via `DELETE /auth/me` (which cascades to every target and check it owns), confirmed by
a later login attempt with the same credentials returning `401`. After the 2026-09-18 run, the
very first login attempt right after the `204` from `DELETE /auth/me` returned a stale `200`,
and a retry two seconds later correctly returned `401`. That reads as a brief read-after-write
lag across Neon's pooled endpoint, since the account was gone on the retry; the 2026-10-17 cleanup
returned `401` on the first attempt.

## Test 1: Read path (`GET /targets/status`)

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

## Test 2: Write path (`POST /targets`), under its rate limit

`POST /targets` carries a `10/minute` IP-keyed limit, the abuse protection
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
of the 40-second window. This matches the documented `10/minute` limit precisely, not
approximately. A `429` response is meaningfully faster than a `201` (it never reaches the
SSRF-resolution/DB-write path a real creation does), which is why the all-requests average sits
well below the successful-only average.

## Test 3: SSE concurrency (`GET /targets/stream`)

Stepped concurrency levels, each run opening N connections at once from one client, all as the
same authenticated user, holding every connection open for 35 seconds, then closing them. The
account had one real target set to a 30 second check interval, and with a signed-in user
streaming, both worker regions were in live mode. So every run had real checks landing during
the window, and each stream's received events show whether pushes actually reached every open
connection.

**Results:**

| Concurrent connections | Opened (`200` + `: connected`) | Failed | Time to `: connected`, median | p95 | max | Streams that received at least one real `check_update` |
|---|---|---|---|---|---|---|
| 5 | 5 | 0 | 985ms | 1.01s | 1.01s | 5 of 5 |
| 10 | 10 | 0 | 920ms | 947ms | 947ms | 10 of 10 |
| 15 | 15 | 0 | 1.13s | 1.17s | 1.17s | 15 of 15 |
| 16 | 16 | 0 | 942ms | 1.00s | 1.00s | 16 of 16 |
| 17 | 17 | 0 | 1.07s | 1.13s | 1.14s | 17 of 17 |
| 20 | 20 | 0 | 985ms | 1.01s | 1.01s | 20 of 20 |
| 25 | 25 | 0 | 985ms | 1.08s | 1.09s | 25 of 25 |
| 50 | 50 | 0 | 1.11s | 1.39s | 1.42s | 50 of 50 |
| 100 | 100 | 0 | 2.02s | 2.54s | 2.62s | 100 of 100 |
| 200 | 200 | 0 | 2.51s | 3.66s | 3.81s | 200 of 200 |
| 400 | 400 | 0 | 4.60s | 7.36s | 7.60s | 400 of 400 |
| 600 | 600 | 0 | 6.14s | 10.36s | 10.71s | 600 of 600 |
| 800 (first run) | 786 | 14 (`500` after about 11.7s) | 8.21s | 12.49s | 12.60s | 786 of 786 |
| 800 (repeat) | 799 | 1 (no response) | 7.56s | 13.15s | 13.65s | 799 of 799 |

Every connection that opened received at least one real `check_update` push inside its 35
second window, at every level, including 799 simultaneous streams. Through 600 simultaneous
opens nothing failed. Where a window caught checks from both regions, a stream received two
pushes, one per region, each carrying the target's complete per-region status.

**Where it tops out.** The limit shows up first as slower opens, and failures come later. Up to about 50
simultaneous opens, a stream is connected in about a second. Past that, open time grows roughly
in proportion to how many streams open at once: a median of 2s at 100, 4.6s at 400, and 7.5 to
8s at 800, with the slowest connections taking over 13 seconds. At 800 the first failures
appear, and they aren't consistent from run to run: 14 connections came back `500` after about
11.7 seconds in the first run, one connection got no response at all in the repeat. Opening a
stream does one database lookup to resolve the session cookie to a user, on its own short-lived
connection, so 800 simultaneous opens means 800 near-simultaneous database connections from a
single API process. That's the most likely place the queueing builds up, though this test
doesn't separate it from the Railway edge or the single uvicorn process accepting the
connections. Once a stream is open it holds no database connection, which is why holding 800
open streams and pushing to all of them stayed healthy once they were connected. The backend's
`/health` endpoint answered in about 0.2 seconds immediately after the largest runs.

For scale: this is a personal monitoring tool where one dashboard tab is one stream. Hundreds of
simultaneous opens from a single account is far outside its real use, so the numbers above are
a ceiling measurement.

## What this does and doesn't show

The read and write paths hold up cleanly at moderate concurrency (tens of requests per second,
well within what a single Railway instance and a personal project's real traffic would ever
see), and the write-path rate limit enforces exactly what it's documented to. The SSE endpoint
opens hundreds of concurrent streams from one client with every stream receiving live pushes,
starts to slow down noticeably past about 50 simultaneous opens, and starts to drop a small
number of connections at around 800. The tests don't cover sustained load over minutes or
hours, don't exercise many different user accounts at once (every test ran as a single
authenticated user), and don't push either HTTP path hard enough to find its own breaking
point. Those would be reasonable next steps.
