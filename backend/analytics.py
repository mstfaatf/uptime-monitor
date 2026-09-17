"""Windowed analytics: uptime %, latency percentiles (p50/p95/p99), and MTTR (Phase 6, prompt
6.5) — backs GET /targets/{id}/analytics?window=24h|7d|30d|90d, one stat block per region,
never collapsed across regions (the same "independent per-region display" rule the rest of
this app follows — see the Phase 2 design report and routers/targets.py's own
no-derived-overall-status precedent).

Uptime % reuses export.py's compute_sla() directly rather than reimplementing it — one
definition of "uptime %" for both the CSV export and this endpoint, kept in one place.
Incident detection reuses export.py's compute_incidents() the same way; MTTR here is a new
aggregate computed from its output — see _compute_mttr's docstring for exactly how window
boundaries and an unresolved incident are handled.
"""

import math
from datetime import datetime, timedelta, timezone

from export import compute_incidents, compute_sla
from models import Check

# window query-param values -> how far back from "now" to look. Always right-anchored at
# "now" — there's no "end date" concept here (unlike GET /targets/{id}/export's from/to),
# since this endpoint answers "how has this target performed recently," not an arbitrary
# historical range.
ALLOWED_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Linear interpolation between the two closest ranks — the same method numpy's default
    percentile() and Excel's PERCENTILE.INC use. `sorted_values` must already be sorted
    ascending. None if there's nothing to compute from (no checks with a recorded latency)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (p / 100)
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return round(sorted_values[int(k)])
    d0 = sorted_values[lower] * (upper - k)
    d1 = sorted_values[upper] * (k - lower)
    return round(d0 + d1)


def _compute_mttr(incidents: list[dict], window_start: datetime) -> tuple[float | None, int]:
    """Mean time to recovery, in seconds, over incidents that overlap [window_start, now].
    Returns (mttr_seconds, incident_count); (None, 0) if no incidents overlap the window.

    **An in-progress (unresolved) incident is counted up to "now," not excluded.**
    compute_incidents() reports an unresolved incident as {"end": None, "duration": None} — it
    is treated here as having lasted (now - start) so far. Justification: MTTR is meant to
    reflect real user-facing pain from downtime, and a monitoring tool's MTTR figure would be
    actively misleading if it quietly excluded whatever is currently down — that's exactly the
    moment the number matters most, and excluding it would make things look artificially
    healthy while a real outage is in progress. An unresolved incident's provisional duration
    also always overlaps the window by construction, since the window's right edge is always
    "now" itself — there's no boundary check needed for that case.

    A **resolved** incident is included if it recovered at or after window_start — i.e. any
    part of the outage fell inside the window — using the incident's own true duration, not one
    clipped to the window boundary, even when the incident actually started slightly before
    window_start (see compute_region_analytics' `context_check` for why an incident can
    legitimately have a start before the window at all). This is intentional: truncating a real
    outage's reported length at an arbitrary window edge would understate how long the target
    was actually unreachable. A resolved incident that recovered entirely before window_start
    has no overlap with the window at all and is excluded.
    """
    now = datetime.now(timezone.utc)
    durations_seconds: list[float] = []
    for incident in incidents:
        if incident["end"] is None:
            durations_seconds.append((now - incident["start"]).total_seconds())
        elif incident["end"] >= window_start:
            durations_seconds.append(incident["duration"].total_seconds())
    if not durations_seconds:
        return None, 0
    return sum(durations_seconds) / len(durations_seconds), len(durations_seconds)


def compute_region_analytics(
    window_checks: list[Check],
    context_check: Check | None,
    window_start: datetime,
) -> dict:
    """Compute one region's full analytics payload for the window.

    `window_checks` must be this region's checks with checked_at >= window_start, oldest
    first. `context_check` is the single most recent check strictly before window_start for
    this same region (or None if there isn't one) — included ONLY for incident-boundary
    detection, NOT for uptime %/latency percentiles below, which are computed strictly from
    window_checks: folding one extra pre-window data point into those would skew "uptime % over
    the window"/"latency distribution over the window" away from their literal, expected
    meaning. Incident detection needs the context check for a different reason — without it, a
    target that was already down when the window opened would look like its incident "started"
    exactly at the window boundary, understating the real incident duration MTTR reports.
    """
    incident_input = ([context_check] if context_check is not None else []) + window_checks
    incidents = compute_incidents(incident_input)
    mttr_seconds, incident_count = _compute_mttr(incidents, window_start)

    latencies = sorted(c.latency_ms for c in window_checks if c.latency_ms is not None)

    return {
        "uptime_percent": compute_sla(window_checks),
        "total_checks": len(window_checks),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "latency_p99_ms": _percentile(latencies, 99),
        "mttr_seconds": mttr_seconds,
        "incident_count": incident_count,
    }
