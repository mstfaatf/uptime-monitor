"""Coverage for backend/export.py (SLA/incident computation, CSV building) and
GET /targets/{id}/export (prompt 4.8)."""

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from database import engine
from export import build_csv, compute_incidents, compute_sla


class _FakeCheck:
    """A tiny stand-in for the SQLAlchemy Check model — compute_sla/compute_incidents/build_csv
    only ever touch these attributes, so a plain object avoids needing a real DB row for the
    pure-function unit tests below."""

    def __init__(self, checked_at, is_up, **kwargs):
        self.checked_at = checked_at
        self.is_up = is_up
        self.status_code = kwargs.get("status_code")
        self.latency_ms = kwargs.get("latency_ms")
        self.dns_ms = kwargs.get("dns_ms")
        self.tcp_ms = kwargs.get("tcp_ms")
        self.tls_ms = kwargs.get("tls_ms")
        self.ttfb_ms = kwargs.get("ttfb_ms")
        self.tls_cert_expires_at = kwargs.get("tls_cert_expires_at")
        self.error = kwargs.get("error")


def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _parse_sections(csv_text: str) -> dict[str, list[list[str]]]:
    """Split an exported CSV into its named sections (Summary/Incidents/Checks) — the "clean
    separation" structure prompt 6.9 introduced. Each section is led by a single-cell title
    row and separated from its neighbors by a blank line; returns {section_name: [rows...]},
    excluding the title row itself. Used so tests assert against the real section structure
    instead of hardcoded row indices, which would silently drift every time a summary field
    is added/removed."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    sections: dict[str, list[list[str]]] = {}
    current_name: str | None = None
    current_rows: list[list[str]] = []
    for row in rows:
        if not row:
            if current_name is not None:
                sections[current_name] = current_rows
            current_name = None
            current_rows = []
            continue
        if current_name is None:
            current_name = row[0]
            continue
        current_rows.append(row)
    if current_name is not None:
        sections[current_name] = current_rows
    return sections


def test_compute_sla_empty_is_none():
    assert compute_sla([]) is None


def test_compute_sla_all_up_is_100():
    checks = [_FakeCheck(_t(i), True) for i in range(5)]
    assert compute_sla(checks) == 100.0


def test_compute_sla_mixed():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False), _FakeCheck(_t(2), True), _FakeCheck(_t(3), True)]
    assert compute_sla(checks) == 75.0


def test_compute_incidents_none_when_always_up():
    checks = [_FakeCheck(_t(i), True) for i in range(3)]
    assert compute_incidents(checks) == []


def test_compute_incidents_closed_incident():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False), _FakeCheck(_t(2), False), _FakeCheck(_t(3), True)]
    incidents = compute_incidents(checks)
    assert len(incidents) == 1
    assert incidents[0]["start"] == _t(1)
    assert incidents[0]["end"] == _t(3)
    assert incidents[0]["duration"] == timedelta(minutes=2)


def test_compute_incidents_ongoing_when_still_down():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False)]
    incidents = compute_incidents(checks)
    assert len(incidents) == 1
    assert incidents[0]["end"] is None
    assert incidents[0]["duration"] is None


def test_compute_incidents_chronological_order_multiple():
    checks = [
        _FakeCheck(_t(0), True),
        _FakeCheck(_t(1), False),
        _FakeCheck(_t(2), True),
        _FakeCheck(_t(3), True),
        _FakeCheck(_t(4), False),
        _FakeCheck(_t(5), True),
    ]
    incidents = compute_incidents(checks)
    assert len(incidents) == 2
    assert incidents[0]["start"] == _t(1)  # earliest first — chronological, not reversed
    assert incidents[1]["start"] == _t(4)


def test_build_csv_days_remaining_is_relative_to_checked_at_not_now():
    """The core correctness property flagged in the implementation: a historical row's
    days-remaining must reflect what was true when it was checked, not now()."""
    checked_at = datetime.now(timezone.utc) - timedelta(days=100)
    expires_at = checked_at + timedelta(days=10)  # had 10 days left AT THE TIME
    check = _FakeCheck(checked_at, True, status_code=200, latency_ms=100, tls_cert_expires_at=expires_at)

    csv_text = build_csv("My Target", "https://example.com", "local", None, None, [check])
    rows = list(csv.reader(io.StringIO(csv_text)))
    data_row = rows[-1]
    assert data_row[8] == "10"  # TLS Cert Days Remaining column, not a huge negative number


def test_build_csv_has_three_cleanly_separated_sections():
    """The core 6.9 structural fix: Summary/Incidents/Checks are each their own title-rowed,
    blank-line-separated, uniformly-shaped sub-table — not one section (Incidents) singled out
    with a title while the other two aren't."""
    checks = [
        _FakeCheck(_t(0), True, status_code=200, latency_ms=120),
        _FakeCheck(_t(1), False, error="Connection timed out"),
        _FakeCheck(_t(2), True, status_code=200, latency_ms=95),
    ]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    sections = _parse_sections(csv_text)

    assert set(sections) == {"Summary", "Incidents", "Checks"}

    summary = {row[0]: row[1] for row in sections["Summary"]}
    assert summary["Target"] == "My Target"
    assert summary["URL"] == "https://example.com"
    assert summary["Region"] == "local"
    assert summary["Range Start"] == ""
    assert summary["Range End"] == ""
    assert summary["Total Checks"] == "3"
    assert summary["SLA (%)"] == "66.67"

    # The down check at _t(1) recovers at _t(2) — a resolved, not ongoing, incident.
    incidents_header, *incident_rows = sections["Incidents"]
    assert incidents_header == ["Start", "End", "Ongoing", "Duration (minutes)"]
    assert len(incident_rows) == 1
    assert incident_rows[0][0] == _t(1).isoformat(timespec="seconds")
    assert incident_rows[0][1] == _t(2).isoformat(timespec="seconds")
    assert incident_rows[0][2] == "false"
    assert incident_rows[0][3] == "1"

    checks_header, *check_rows = sections["Checks"]
    assert checks_header == [
        "Checked At", "Is Up", "Status Code", "Latency (ms)", "DNS (ms)", "TCP (ms)",
        "TLS (ms)", "TTFB (ms)", "TLS Cert Days Remaining", "Error",
    ]
    assert len(check_rows) == 3
    assert check_rows[0][1] == "true"  # lowercase, not Python's "True"
    assert check_rows[0][3] == "120"  # a plain number, never "120ms"
    assert check_rows[1][1] == "false"
    assert check_rows[1][9] == "Connection timed out"


def test_build_csv_incident_ongoing_has_blank_end_and_duration():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False, error="timeout")]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    sections = _parse_sections(csv_text)
    _, *incident_rows = sections["Incidents"]
    assert len(incident_rows) == 1
    assert incident_rows[0][1] == ""  # End: blank, never the literal word "ongoing"
    assert incident_rows[0][2] == "true"  # Ongoing
    assert incident_rows[0][3] == ""  # Duration: blank, not a stringified guess


def test_build_csv_range_start_and_end_are_plain_iso_timestamps_not_english_words():
    range_from = _t(-60)
    range_to = _t(60)
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv("My Target", "https://example.com", "local", range_from, range_to, checks)
    sections = _parse_sections(csv_text)
    summary = {row[0]: row[1] for row in sections["Summary"]}
    assert summary["Range Start"] == range_from.isoformat(timespec="seconds")
    assert summary["Range End"] == range_to.isoformat(timespec="seconds")


def test_build_csv_unbounded_range_is_blank_not_a_word():
    """Previously rendered as the English words "all time"/"now" mixed into a timestamp
    column — now genuinely empty, matching every other unset value in the file."""
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    sections = _parse_sections(csv_text)
    summary = {row[0]: row[1] for row in sections["Summary"]}
    assert summary["Range Start"] == ""
    assert summary["Range End"] == ""


def test_build_csv_timestamps_are_consistently_formatted_regardless_of_microseconds():
    """The concrete bug this prompt fixes: bare datetime.isoformat() omits the fractional-
    seconds part only when microsecond happens to be exactly 0, so two otherwise-identical-
    shaped timestamps would render with different string lengths depending on data, not
    intent. timespec="seconds" makes every timestamp in the file the same shape."""
    exact_second = datetime(2026, 1, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
    with_micros = datetime(2026, 1, 1, 12, 0, 1, 123456, tzinfo=timezone.utc)
    checks = [
        _FakeCheck(exact_second, True, status_code=200, latency_ms=100),
        _FakeCheck(with_micros, True, status_code=200, latency_ms=100),
    ]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    sections = _parse_sections(csv_text)
    _, *check_rows = sections["Checks"]
    assert check_rows[0][0] == "2026-01-01T12:00:00+00:00"
    assert check_rows[1][0] == "2026-01-01T12:00:01+00:00"
    assert len(check_rows[0][0]) == len(check_rows[1][0])


def _note_row(rows):
    return next((r for r in rows if r and r[0] == "Note"), None)


def test_build_csv_omits_retention_note_when_retention_days_not_given():
    """Backward-compatible default: no retention_days passed -> no note, regardless of range —
    every pre-6.8 caller keeps getting exactly the same output as before."""
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert _note_row(rows) is None


def test_build_csv_includes_retention_note_when_requested_range_predates_cutoff():
    old_from = datetime.now(timezone.utc) - timedelta(days=120)  # older than a 90-day window
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv(
        "My Target", "https://example.com", "local", old_from, None, checks, retention_days=90
    )
    rows = list(csv.reader(io.StringIO(csv_text)))
    note = _note_row(rows)
    assert note is not None
    assert "90 days" in note[1]


def test_build_csv_includes_retention_note_when_range_from_is_unbounded():
    """range_from=None ('all time') trivially predates any retention cutoff."""
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv(
        "My Target", "https://example.com", "local", None, None, checks, retention_days=90
    )
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert _note_row(rows) is not None


def test_build_csv_omits_retention_note_when_requested_range_is_within_cutoff():
    recent_from = datetime.now(timezone.utc) - timedelta(days=10)
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    csv_text = build_csv(
        "My Target", "https://example.com", "local", recent_from, None, checks, retention_days=90
    )
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert _note_row(rows) is None


def test_build_csv_note_boundary_is_the_retention_cutoff_itself():
    """A range_from exactly at the cutoff does not predate it (strict '<', not '<=') — the
    boundary is inclusive of the cutoff day itself."""
    checks = [_FakeCheck(_t(0), True, status_code=200, latency_ms=100)]
    at_cutoff = datetime.now(timezone.utc) - timedelta(days=90) + timedelta(minutes=5)
    csv_text = build_csv(
        "My Target", "https://example.com", "local", at_cutoff, None, checks, retention_days=90
    )
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert _note_row(rows) is None


async def _insert_check(target_id: int, region: str, checked_at: datetime, is_up: bool, **overrides) -> None:
    values = {
        "target_id": target_id,
        "checked_at": checked_at,
        "status_code": 200 if is_up else None,
        "latency_ms": 100 if is_up else None,
        "is_up": is_up,
        "error": None if is_up else "Connection timed out",
        "region": region,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region)
                VALUES (:target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region)
                """
            ),
            values,
        )


async def test_export_requires_authentication(client):
    resp = await client.get("/targets/1/export?region=local")
    assert resp.status_code == 401


async def test_export_404s_for_another_users_target(client):
    await client.post("/auth/register", json={"email": "exporta@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-a"})
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    await client.post("/auth/register", json={"email": "exportb@example.com", "password": "pw"})
    resp = await client.get(f"/targets/{target_id}/export?region=local")
    assert resp.status_code == 404


async def test_export_rejects_unsupported_format(client):
    await client.post("/auth/register", json={"email": "exportfmt@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-fmt"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}/export?region=local&format=pdf")
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


async def test_export_requires_region_query_param(client):
    await client.post("/auth/register", json={"email": "exportnoregion@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-no-region"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}/export")
    assert resp.status_code == 422


async def test_export_returns_csv_with_correct_headers_and_content(client):
    await client.post("/auth/register", json={"email": "exportok@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-ok"})
    target_id = created.json()["id"]

    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    resp = await client.get(f"/targets/{target_id}/export?region=local")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f'target-{target_id}-local-checks.csv' in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["Summary"]
    assert rows[3] == ["Region", "local"]


async def test_export_scopes_to_the_requested_region_only(client):
    await client.post("/auth/register", json={"email": "exportregions@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-regions"})
    target_id = created.json()["id"]

    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)
    await _insert_check(target_id, "eu-west", datetime.now(timezone.utc), False)

    resp = await client.get(f"/targets/{target_id}/export?region=local")
    header_row_idx = resp.text.splitlines().index("Checked At,Is Up,Status Code,Latency (ms),DNS (ms),TCP (ms),TLS (ms),TTFB (ms),TLS Cert Days Remaining,Error")
    data_lines = resp.text.splitlines()[header_row_idx + 1:]
    assert len(data_lines) == 1
    assert ",true," in data_lines[0]  # the local (up) check, not eu-west's down one


async def test_export_filters_by_date_range(client):
    await client.post("/auth/register", json={"email": "exportrange@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-range"})
    target_id = created.json()["id"]

    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(days=10), True)
    await _insert_check(target_id, "local", now - timedelta(days=1), True)

    from_param = (now - timedelta(days=2)).isoformat()
    resp = await client.get(f"/targets/{target_id}/export", params={"region": "local", "from": from_param})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    total_row = next(r for r in rows if r and r[0] == "Total Checks")
    assert total_row[1] == "1"  # only the check inside the range


async def test_export_includes_retention_note_when_from_predates_the_retention_window(client):
    await client.post("/auth/register", json={"email": "exportretentionnote@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-retention-note"})
    target_id = created.json()["id"]
    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    old_from = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    resp = await client.get(f"/targets/{target_id}/export", params={"region": "local", "from": old_from})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert any(r and r[0] == "Note" for r in rows)


async def test_export_omits_retention_note_when_from_is_within_the_retention_window(client):
    await client.post("/auth/register", json={"email": "exportnoretentionnote@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-no-retention-note"})
    target_id = created.json()["id"]
    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    recent_from = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    resp = await client.get(f"/targets/{target_id}/export", params={"region": "local", "from": recent_from})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert not any(r and r[0] == "Note" for r in rows)


async def test_export_includes_retention_note_when_from_is_omitted(client):
    """No `from` at all means 'all time,' which trivially predates the retention cutoff."""
    await client.post("/auth/register", json={"email": "exportnofromnote@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-no-from-note"})
    target_id = created.json()["id"]
    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    resp = await client.get(f"/targets/{target_id}/export", params={"region": "local"})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert any(r and r[0] == "Note" for r in rows)
