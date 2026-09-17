"""CSV compliance export (Phase 4, prompt 4.8; formatting fixed in Phase 6, prompt 6.9):
SLA %/incident-list computation re-implemented in Python, plus the CSV-building logic itself.

The SLA/incident math already exists in TypeScript, client-side only — app/dashboard/[id]/
page.tsx's computeSla and components/incident-timeline.tsx's computeIncidents, used to render
the detail page in the browser. Re-implementing it here is the same deliberate cross-service
duplication already established for backend/security/ssrf.py vs worker/ssrf.py: export
generation happens server-side in Python, the frontend's logic runs in the browser in
TypeScript, and there's no shared runtime between them to import one from the other. Kept in
sync by hand, not import — if the frontend's incident/SLA definition ever changes, this file
needs the same change made separately.

**Prompt 6.9 formatting fix — what was wrong, concretely**: the original export packed three
differently-shaped mini-tables (a 2-column key/value summary, a 3-column incident table, a
10-column check-row table) into one physical CSV with only a blank line between them and no
section titles beyond a bare "Incidents" row — a properly-typed CSV parser reading the whole
file as one table (csv.DictReader, pandas.read_csv, most compliance tooling) would misread or
choke on it, not just a human eyeballing it. Concrete, provable bugs, not just "could be
nicer":
  1. Timestamps were inconsistently formatted: bare datetime.isoformat() omits the fractional-
     seconds part entirely when microsecond happens to be exactly 0 and includes 6 digits
     otherwise, so two rows could render with different string lengths/shapes in the same
     column depending on what microsecond a check happened to land on, not on any real
     distinction. Fixed by formatting every timestamp-shaped cell with isoformat(timespec=
     "seconds") — a single call site (_format_timestamp below), always the same shape.
  2. The "Date range" summary field mixed a real ISO timestamp with literal English words
     ("all time", "now") depending on whether a bound was given, and the Incidents section's
     "End" column did the same thing for an unresolved incident ("ongoing" in the timestamp
     column itself). Fixed: "Range Start"/"Range End" are now two separate cells, each either
     a real timestamp or genuinely empty — never a word standing in for one — and the
     Incidents section gained its own explicit "Ongoing" column instead of overloading "End".
  3. The Incidents "Duration" column was a hand-formatted string like "20m" or "2h 15m" — a
     number with its unit baked directly into the text, unparseable as a number without first
     stripping/interpreting the unit suffix. Fixed: "Duration (minutes)" is now a plain
     integer (blank while an incident is ongoing, matching "End" — a stable export shouldn't
     report a duration that would change every time the same range is re-exported).
  4. No section actually announced itself except "Incidents" (a bare title row with no
     equivalent for the summary or the check rows) — an asymmetric, easy-to-miss structure.
     Fixed: every section now opens with the same single-cell title convention ("Summary",
     "Incidents", "Checks"), so the file's own structure is self-describing and a parser can
     split on blank lines + read each section's title unambiguously.
  5. Minor internal inconsistencies: "Is Up" used Python's capitalized True/False while
     nothing else in the file used that casing; "SLA %" didn't follow the "(unit)" bracketing
     convention every other unit-bearing header uses ("Latency (ms)", etc.); "Total checks"
     wasn't Title Case like its sibling summary labels. Fixed by normalizing all of these —
     true/false lowercase everywhere a boolean-shaped value appears, "SLA (%)", "Total Checks".

None of this changes what data is in the export or who can request it — same checks, same
ownership enforcement (GET /targets/{id}/export's own query/auth is untouched), same SLA/
incident math. Only how it's written to the page changed.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

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


def _format_timestamp(dt: datetime | None) -> str:
    """The one place every timestamp-shaped cell in this file goes through — see the module
    docstring's bug #1. timespec="seconds" forces a fixed shape regardless of whether the
    value's microsecond component happens to be zero, so two timestamps in the same column
    always render with the same format. None (an unbounded range boundary, or an unresolved
    incident's end) becomes a genuinely empty cell, never a word like "now"/"ongoing" standing
    in for a timestamp — see bug #2."""
    if dt is None:
        return ""
    return dt.isoformat(timespec="seconds")


def _format_bool(value: bool) -> str:
    """Lowercase "true"/"false" — the one boolean convention used everywhere in this file
    (Is Up, Ongoing), instead of Python's capitalized True/False the original export leaked
    through unchanged from str(bool) — see the module docstring's bug #5."""
    return "true" if value else "false"


def build_csv(
    target_label: str,
    target_url: str,
    region: str,
    range_from: datetime | None,
    range_to: datetime | None,
    checks: list[Check],
    retention_days: int | None = None,
) -> str:
    """Build the full export file as three cleanly separated sections — Summary, Incidents,
    Checks — each opening with its own single-cell title row and separated from its neighbors
    by a blank line (see the module docstring's bug #4 for why every section needs one, not
    just Incidents as before). A caller that wants to read this programmatically should split
    on blank lines and treat each section as its own small, uniformly-shaped table — every row
    within one section has the same column count, so a section read in isolation is a
    perfectly well-formed CSV; it's only the *whole file* that mixes shapes, and only because
    it's genuinely three different reports concatenated into one download, not one table.

    retention_days (Phase 6, prompt 6.8): when given, and the *requested* range_from predates
    the retention cutoff (now() - retention_days) — including range_from=None, "all time",
    which trivially predates any cutoff — a Note row is added to the summary saying so. This
    compares the requested range, not the actual earliest row present, per that prompt's own
    framing: the point is to warn a caller who asked for more history than the retention
    policy could possibly still have, not to describe exactly what happened to be pruned by
    the time this particular export ran. Optional (default None = no note).
    """
    sla = compute_sla(checks)
    incidents = compute_incidents(checks)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # --- Summary ---
    writer.writerow(["Summary"])
    writer.writerow(["Target", target_label])
    writer.writerow(["URL", target_url])
    writer.writerow(["Region", region])
    writer.writerow(["Range Start", _format_timestamp(range_from)])
    writer.writerow(["Range End", _format_timestamp(range_to)])
    writer.writerow(["Total Checks", len(checks)])
    writer.writerow(["SLA (%)", f"{sla:.2f}" if sla is not None else ""])
    if retention_days is not None:
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        if range_from is None or range_from < retention_cutoff:
            writer.writerow(
                [
                    "Note",
                    f"Raw check data older than {retention_days} days is periodically pruned; "
                    f"rows before approximately {retention_cutoff.date().isoformat()} may be "
                    "missing from this export, even though the requested range starts earlier.",
                ]
            )
    writer.writerow([])

    # --- Incidents ---
    writer.writerow(["Incidents"])
    writer.writerow(["Start", "End", "Ongoing", "Duration (minutes)"])
    for incident in incidents:
        ongoing = incident["end"] is None
        duration_minutes = "" if incident["duration"] is None else round(incident["duration"].total_seconds() / 60)
        writer.writerow(
            [
                _format_timestamp(incident["start"]),
                _format_timestamp(incident["end"]),
                _format_bool(ongoing),
                duration_minutes,
            ]
        )
    writer.writerow([])

    # --- Checks ---
    writer.writerow(["Checks"])
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
                _format_timestamp(c.checked_at),
                _format_bool(c.is_up),
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
