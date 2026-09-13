"""CSV compliance export (Phase 4, prompt 4.8): SLA %/incident-list computation
re-implemented in Python, plus the CSV-building logic itself.

The SLA/incident math already exists in TypeScript, client-side only — app/dashboard/[id]/
page.tsx's computeSla and components/incident-timeline.tsx's computeIncidents, used to render
the detail page in the browser. Re-implementing it here is the same deliberate cross-service
duplication already established for backend/security/ssrf.py vs worker/ssrf.py: export
generation happens server-side in Python, the frontend's logic runs in the browser in
TypeScript, and there's no shared runtime between them to import one from the other. Kept in
sync by hand, not import — if the frontend's incident/SLA definition ever changes, this file
needs the same change made separately.
"""

import csv
import io
from datetime import datetime, timedelta

from models import Check


def compute_sla(checks: list[Check]) -> float | None:
    """Same math as app/dashboard/[id]/page.tsx's computeSla: percentage of checks that were
    up, over whatever range of checks is passed in. None (not 0) when there's no data at all,
    so a caller can render "—" instead of a misleading 0%."""
    if not checks:
        return None
    up_count = sum(1 for c in checks if c.is_up)
    return (up_count / len(checks)) * 100


def compute_incidents(checks: list[Check]) -> list[dict]:
    """Same algorithm as components/incident-timeline.tsx's computeIncidents: scans an
    oldest-first check history for runs of consecutive is_up=false checks. A run's start is
    its first failing check's timestamp; its end is the next successful check after it, or
    None if the run hasn't recovered by the last check in the list (still ongoing).

    Returned oldest-first (chronological), unlike the frontend's own most-recent-first
    ordering (it reverses for its own "newest incident at the top" UI purpose) — a CSV export
    reads more naturally chronologically, matching the raw check rows that follow it in the
    same file.
    """
    incidents: list[dict] = []
    open_start: datetime | None = None
    for c in checks:
        if not c.is_up and open_start is None:
            open_start = c.checked_at
        elif c.is_up and open_start is not None:
            incidents.append({"start": open_start, "end": c.checked_at, "duration": c.checked_at - open_start})
            open_start = None
    if open_start is not None:
        incidents.append({"start": open_start, "end": None, "duration": None})
    return incidents


def _format_duration(delta: timedelta | None) -> str:
    if delta is None:
        return "ongoing"
    total_minutes = round(delta.total_seconds() / 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def build_csv(
    target_label: str,
    target_url: str,
    region: str,
    range_from: datetime | None,
    range_to: datetime | None,
    checks: list[Check],
) -> str:
    """Build the full export file: a summary section (target/region/date range/SLA %/incident
    list), a blank-line separator, then the raw check rows — one CSV file, readable both as a
    human report (opened directly) and as tabular data (imported past the summary section)."""
    sla = compute_sla(checks)
    incidents = compute_incidents(checks)

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["Target", target_label])
    writer.writerow(["URL", target_url])
    writer.writerow(["Region", region])
    writer.writerow(
        [
            "Date range",
            f"{range_from.isoformat() if range_from else 'all time'} to "
            f"{range_to.isoformat() if range_to else 'now'}",
        ]
    )
    writer.writerow(["Total checks", len(checks)])
    writer.writerow(["SLA %", f"{sla:.2f}" if sla is not None else ""])
    writer.writerow([])

    writer.writerow(["Incidents"])
    writer.writerow(["Start", "End", "Duration"])
    for incident in incidents:
        writer.writerow(
            [
                incident["start"].isoformat(),
                incident["end"].isoformat() if incident["end"] else "ongoing",
                _format_duration(incident["duration"]),
            ]
        )
    writer.writerow([])

    writer.writerow(
        [
            "Checked At",
            "Is Up",
            "Status Code",
            "Latency (ms)",
            "DNS (ms)",
            "TCP (ms)",
            "TLS (ms)",
            "TTFB (ms)",
            "TLS Cert Days Remaining",
            "Error",
        ]
    )
    for c in checks:
        # Days-remaining computed relative to THIS check's own checked_at, not now() — unlike
        # the live API's _check_to_response_dict (routers/targets.py), which deliberately uses
        # now() because it's always describing the *latest* check. Most rows in a historical
        # export are not the latest check, so a now()-relative figure on an old row would be
        # misleading (e.g. reading negative for a cert that was fine at the time but has since
        # expired) — a compliance record should show what was true at the time of each check.
        days_remaining = (
            (c.tls_cert_expires_at - c.checked_at).days
            if c.tls_cert_expires_at is not None and c.checked_at is not None
            else ""
        )
        writer.writerow(
            [
                c.checked_at.isoformat() if c.checked_at else "",
                c.is_up,
                c.status_code if c.status_code is not None else "",
                c.latency_ms if c.latency_ms is not None else "",
                c.dns_ms if c.dns_ms is not None else "",
                c.tcp_ms if c.tcp_ms is not None else "",
                c.tls_ms if c.tls_ms is not None else "",
                c.ttfb_ms if c.ttfb_ms is not None else "",
                days_remaining,
                c.error or "",
            ]
        )

    return buf.getvalue()
