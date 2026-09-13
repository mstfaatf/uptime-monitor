# ADR 001: Multi-Region Check Coordination

## Status

Accepted. Implemented in `worker/main.py`, `backend/routers/targets.py`, `backend/realtime.py`,
and the schema in `backend/alembic/versions/005_add_targets_claimed_at.py` and
`006_add_region_and_target_schedule.py`.

## Context

The worker originally ran as a single instance, checking every due target on a flat cadence
with no coordination logic at all — there was only ever one process touching the schedule, so
none was needed. Two things changed that:

1. **Horizontal scaling within a single vantage point.** Even one checking region might
   eventually run more than one worker process (for throughput or availability). Nothing
   stopped two instances from selecting and checking the same due target at the same moment,
   racing on the scheduling write afterward (a lost update).
2. **Multi-region checking.** A target's reachability and latency can genuinely differ
   depending on where the check originates — that's the entire point of checking from more
   than one region. A single global `next_check_at` / `consecutive_failures` per target can't
   represent "reachable from one region, backing off in another" at the same time.

These two problems have to be solved together: region-scoping alone doesn't stop two
same-region instances from double-checking a row, and row-claiming alone doesn't give each
region its own independent view of a target's health.

## Decision

### 1. Row-claiming: `SELECT ... FOR UPDATE SKIP LOCKED` + a `claimed_at` lease

A due row is claimed via a short, self-contained transaction: `SELECT ... FOR UPDATE SKIP
LOCKED` against due, unclaimed-or-stale-claimed rows, then an `UPDATE` stamping
`claimed_at = now()` on whatever was selected, then an immediate commit. The actual HTTP check
happens afterward, entirely outside any transaction or lock.

- `SKIP LOCKED` means a second instance's concurrent claim attempt on the same row doesn't
  block waiting for the first transaction — it simply doesn't see that row and moves on to
  whatever else is due. No polling, no retry loop, no deadlock risk.
- The lock is held only for the claim stamp (milliseconds), not for the network I/O of the
  actual check (which can take seconds) — a lock is never the bottleneck for check latency.
- `claimed_at` is a plain, visible timestamp column, not an in-memory or session-scoped lock —
  if the worker that claimed a row crashes or is killed mid-check, the claim simply ages out:
  a row is due again once `claimed_at` is older than a fixed TTL (120 seconds — chosen with
  roughly 2x headroom over the worst realistic single-check duration: up to 5 redirect hops,
  each capped at a 10-second HTTP timeout). No heartbeat or lease-renewal mechanism was needed.
  Verified directly by simulating a crash: aging a live claim's `claimed_at` past the 120s
  window causes the very next scheduling tick to reclaim and successfully check that row,
  while a claim younger than the window is correctly left untouched.
- The claim query joins `target_region_schedule` to `targets` (to return the target's URL
  alongside its schedule row), so the lock is scoped with `FOR UPDATE OF <schedule-table-alias>
  SKIP LOCKED` rather than a bare `FOR UPDATE SKIP LOCKED` — locking (and skip-contending on)
  only the schedule row, not the joined `targets` row, which nothing else has any reason to
  contend with.

### 2. Scheduling state lives per `(target_id, region)`, not per target

Scheduling state (`next_check_at`, `consecutive_failures`, `claimed_at`) was moved off
`targets` entirely and into a new table, `target_region_schedule`, keyed by a composite primary
key on `(target_id, region)`. Each checking region's worker instance only ever reads and
writes rows for its own region — two workers in different regions never contend for the same
row at all, since they're never even querying the same rows; two workers in the *same* region
still rely on the claiming mechanism above.

A target with no schedule row yet for some region (freshly created, or a brand-new region
running for the first time against pre-existing targets) is lazily backfilled — due
immediately — the moment any worker for that region next looks for due work. The alternative,
creating a schedule row per known region at target-creation time, isn't available: the API
has no concept of which regions exist (`REGION` is worker-only configuration, never written
anywhere the API could read it), so the worker — the only thing that actually knows its own
region — is the right place to self-register interest in a target it hasn't seen yet.

### 3. Per-region results are displayed independently; no aggregate boolean

`GET /targets/status` (and the equivalent SSE push) reports a target's `latest_checks` as a
map keyed by region, each with its own full result (status, latency, DNS/TCP/TLS/TTFB timing,
TLS cert info). No single derived "is this target up" field was added anywhere. If a
cross-region summary is ever needed, it should say something explicit like "2 of 3 regions
reporting down," not collapse the regions into one boolean silently.

## Alternatives considered

**Claiming:**

- *No claiming at all* — the status quo bug being fixed here. Rejected on its face.
- *Postgres advisory locks* (`pg_advisory_lock`) — considered. Rejected: requires inventing and
  managing a mapping from target IDs to lock key integers, has no built-in visibility (an
  advisory lock doesn't show up in a normal `SELECT` the way `claimed_at` does, making it
  harder to reason about or debug), and still needs a separate mechanism to detect and recover
  an abandoned lock from a crashed session.
- *A dedicated leases/queue table* — considered. Rejected as unnecessary: `SKIP LOCKED` gets
  the same single-claimer guarantee out of row locks the database already provides, for the
  cost of two extra columns on the existing schedule table, rather than a whole separate
  table plus the code to keep it in sync with what it's supposedly queuing.

**Scheduling state shape:**

- *Keep one shared `next_check_at` / `consecutive_failures` per target* — considered, rejected.
  This would require inventing a second coordination layer just to fairly rotate "whose turn"
  it is among regions to check a target, and it blends together failure signals that are
  semantically different measurements: a target's reachability from one region and from
  another are two different facts, not two samples of the same fact. Sharing state between
  them defeats the actual purpose of checking from multiple regions in the first place.
- *One row per target with a `regions jsonb` column* instead of a normalized
  `target_region_schedule` table — considered, rejected. A JSON blob can't be claimed
  per-region with `FOR UPDATE SKIP LOCKED` — locking the row still locks the whole document,
  so two regions sharing one JSON-column row would contend with each other exactly like the
  single-shared-state option above, just with worse ergonomics for querying "what's due."

**Result display:**

- *Aggregate boolean, down if down in any region* — rejected. A transient failure or blip in
  one region would flip the entire target red even while it's healthy and actually serving
  traffic from every other region — a false alarm for the person who owns this target.
- *Aggregate boolean, down only if down in every region* — rejected. This would hide a real,
  actionable regional outage (e.g. one edge/CDN region failing) until it happened to also fail
  everywhere else, which is exactly the kind of partial-outage signal multi-region checking
  exists to surface.
- *Independent per-region display* (chosen) — appropriate specifically because this is a
  personal monitoring tool built for its own targets' owner, not a public status-page product
  serving third parties who need one number to decide whether to trust a service. That
  audience difference is what tips the decision toward diagnostic detail over a collapsed
  verdict; a public-facing status page would likely make the opposite call.

## Consequences

- Two worker instances — whether in the same region or different ones — can run concurrently
  against the same database without ever double-checking a target or losing a scheduling
  update. This was verified against real, concurrently running Docker processes (not just
  mocked unit tests): a genuine second same-region process log-showed exactly the expected
  claim-splitting behavior with zero overlap, and a genuine second-region process backfilled
  and began independently scheduling every pre-existing target without disturbing the first
  region's schedule state at all. Verified precisely, not just by absence of visible overlap:
  under repeated forced contention, the smallest time gap between any two checks of the same
  `(target_id, region)` was ~3.85 seconds — consistent with two distinct due-cycles roughly a
  scheduling tick apart, never the sub-second/near-simultaneous gap an actual double-claim
  would produce.
- A target's per-region history (timing breakdown, TLS cert info, uptime) is preserved exactly
  as observed by each region, which is what the planned latency-chart, timing-waterfall, and
  SLA-percentage dashboard features need to work with per region rather than a blended average.
- `target_region_schedule` grows as *targets × regions* rather than just *targets*. At this
  project's scale (a personal tool, single-digit regions) that's immaterial; it would need
  revisiting only at a scale this project doesn't target.
- The dashboard now has to decide how to summarize potentially-divergent per-region data at a
  glance (e.g. a single row in a target list). That's deliberately left to the UI layer to
  solve visually — a badge per region, for instance — rather than solved here by collapsing
  the data before it ever reaches the frontend.
- A target briefly has zero schedule rows for a region it hasn't been seen by yet, until that
  region's worker's next scheduling tick backfills it. In exchange, the backend/API never
  needs to know what regions exist at all — an explicit, accepted tradeoff.
