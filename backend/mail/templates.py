"""Plain-text email templates: three functions, no templating engine. Three short bodies
don't justify a Jinja dependency — matches this project's existing "don't add a dependency
you don't need" calls (e.g. no react-hook-form on the frontend for a two-field form).

Voice matches the product's own (plain, factual — "Reporting up", "No signal" — no marketing
chrome, no exclamation points, no filler greeting). Each function returns (subject, body);
callers (alerting logic, forgot-password) are responsible for building any full URLs passed
in here (detail_url, settings_url, reset_url) — these templates only format text, they don't
know the frontend's base URL or anything about routing.
"""


def _target_description(target_label: str, target_url: str) -> str:
    """"{label} ({url})", or just the URL if the target has no name (label == url) — avoids
    printing the same URL twice."""
    if target_label == target_url:
        return target_url
    return f"{target_label} ({target_url})"


def downtime_alert_email(
    target_label: str,
    target_url: str,
    region: str,
    checked_at: str,
    error: str | None,
    detail_url: str,
    settings_url: str,
) -> tuple[str, str]:
    """Sent when a target's region goes from reporting up to confirmed down."""
    target = _target_description(target_label, target_url)
    subject = f"{target_label} is down ({region})"
    body = (
        f"{target} is not responding, checked from {region}.\n"
        f"\n"
        f"Checked at: {checked_at}\n"
        f"Error: {error or 'No response'}\n"
        f"\n"
        f"View details: {detail_url}\n"
        f"\n"
        f"Manage alert preferences: {settings_url}\n"
    )
    return subject, body


def downtime_recovery_email(
    target_label: str,
    target_url: str,
    region: str,
    checked_at: str,
    detail_url: str,
    settings_url: str,
) -> tuple[str, str]:
    """Sent when a target's region recovers after a confirmed downtime alert — the "back up"
    counterpart to downtime_alert_email, added in prompt 4.6 alongside the alerting logic that
    actually needs both directions of the transition, not just the down side."""
    target = _target_description(target_label, target_url)
    subject = f"{target_label} is back up ({region})"
    body = (
        f"{target} is responding again, checked from {region}.\n"
        f"\n"
        f"Checked at: {checked_at}\n"
        f"\n"
        f"View details: {detail_url}\n"
        f"\n"
        f"Manage alert preferences: {settings_url}\n"
    )
    return subject, body


def cert_expiry_alert_email(
    target_label: str,
    target_url: str,
    region: str,
    days_remaining: int,
    expires_at: str,
    issuer: str | None,
    detail_url: str,
    settings_url: str,
) -> tuple[str, str]:
    """Sent when a target's TLS certificate (checked from a given region) is expiring soon."""
    target = _target_description(target_label, target_url)
    subject = f"TLS certificate for {target_label} expires in {days_remaining} days"
    body = (
        f"The TLS certificate for {target}, checked from {region}, is expiring soon.\n"
        f"\n"
        f"Days remaining: {days_remaining}\n"
        f"Expires: {expires_at}\n"
        f"Issuer: {issuer or 'Unknown'}\n"
        f"\n"
        f"View details: {detail_url}\n"
        f"\n"
        f"Manage alert preferences: {settings_url}\n"
    )
    return subject, body


def password_reset_email(reset_url: str, expires_in_minutes: int = 60) -> tuple[str, str]:
    """Sent when a user requests a password reset. No settings link (not an alert type) —
    ends with the standard "ignore if you didn't request this" line instead."""
    subject = "Reset your Uptime Monitor password"
    body = (
        f"A password reset was requested for your Uptime Monitor account.\n"
        f"\n"
        f"Reset your password: {reset_url}\n"
        f"\n"
        f"This link expires in {expires_in_minutes} minutes. If you didn't request this, "
        f"you can ignore this email and your password will stay the same.\n"
    )
    return subject, body
