# API Reference

The full REST + Server-Sent Events surface, grouped by resource. Explore it live at the
deployed backend's `/docs` (interactive Swagger UI) — this document exists for a version you
can read without the server running, and to spell out reasoning the OpenAPI schema alone
doesn't capture (why a field is nullable, what "region required" actually means, etc.).

## Authentication

Two independent ways to authenticate, and most endpoints only accept one of them:

- **Session cookie** (`session`, HTTP-only, signed JWT). Set by `/auth/register` and
  `/auth/login`, read by every endpoint that depends on `get_current_user`. This is what the
  web dashboard uses. In production the cookie is `Secure` and `SameSite=None` (the frontend
  and backend are on different origins); locally it's `SameSite=Lax` over plain HTTP.
- **API key** (`Authorization: Bearer <key>`), issued via `POST /api-keys`. Only the specific
  endpoints marked **API-key-eligible** below accept one — everything else, including the
  `/api-keys` endpoints themselves, is cookie-only by design: a key can never be used to mint
  or revoke other keys. A key has a **scope** of `read` or `full`; `full` is a strict superset
  of `read`. Presenting a header that doesn't resolve to a valid, unrevoked key is a `401`;
  presenting a valid key whose scope is too low for the operation is a `403`. If no
  `Authorization` header is present at all, an API-key-eligible endpoint falls back to the
  session cookie exactly as if the feature didn't exist.

Ownership is enforced identically regardless of which auth method resolved the caller: every
query is filtered by the resolved user's id, and a resource that exists but belongs to someone
else returns `404`, not `403` — a caller can't distinguish "doesn't exist" from "isn't yours."

## Rate limiting

Every write endpoint is rate-limited; every limit returns `429` with a
`{"detail": "Too many requests — rate limit is <limit>. Please try again shortly."}` body once
exceeded. Two independent kinds of limit can apply to the same route:

- **IP-keyed limits** — the classic abuse targets (login, register, forgot-password) and every
  resource-creation endpoint (targets, tags, webhooks, API keys) carry a stricter limit, usually
  `10/minute`, keyed by client IP regardless of auth method.
- **Per-key limits** — every API-key-eligible endpoint also carries a `60/minute` limit keyed by
  the API key itself (or by IP, for a cookie-authenticated request to the same route). This
  gives programmatic traffic its own budget, independent of whatever else might share that
  key owner's IP, without loosening the stricter IP-keyed creation limits above.

## Auth

### `POST /auth/register`

Create a new account and start a session.

**Request:**

| Field | Type | Notes |
|---|---|---|
| `email` | string | must be a valid email address |
| `password` | string | hashed, never stored or returned |

**Response:** `200`
```json
{
  "id": 1,
  "email": "you@example.com",
  "alert_on_downtime": true,
  "alert_on_cert_expiry": true
}
```
Also sets the `session` cookie.

**Notes:** `3/minute`, IP-keyed. `400` if the email is already registered.

---

### `POST /auth/login`

Authenticate and start a session.

**Request:** `{"email": "...", "password": "..."}`

**Response:** `200`, same `UserResponse` shape as register. Sets the `session` cookie.

**Notes:** `5/minute`, IP-keyed. `401` on a wrong email or password — the two cases are
indistinguishable in the response, so a caller can't use this endpoint to enumerate accounts.

---

### `POST /auth/logout`

Clear the session cookie.

**Request:** none. **Response:** `200`, `{"ok": true}`. **Notes:** no rate limit; always
succeeds, whether or not a session was actually present.

---

### `GET /auth/me`

Return the authenticated user.

**Request:** none (cookie only). **Response:** `200`, `UserResponse` (same shape as register).
**Notes:** `401` if not authenticated. Used by the frontend to check session validity on load.

---

### `POST /auth/change-password`

Change the authenticated user's password.

**Request:** `{"current_password": "...", "new_password": "..."}`

**Response:** `200`, `{"ok": true}`

**Notes:** `5/minute`. `401` if `current_password` is wrong — same response shape as
`/auth/login`'s failure, so this endpoint can't be used to probe how close a guess is.

---

### `PATCH /auth/preferences`

Update the two global alert toggles.

**Request:** `{"alert_on_downtime": true, "alert_on_cert_expiry": false}` — either field
optional; an omitted field is left unchanged.

**Response:** `200`, `UserResponse`.

**Notes:** no rate limit. These toggles gate email *and* webhook delivery for their respective
alert type (a webhook's own `alert_on_downtime`/`alert_on_cert_expiry` toggle applies on top of
this, not instead of it).

---

### `DELETE /auth/me`

Permanently delete the authenticated account and everything it owns.

**Request:** none. **Response:** `204`.

**Notes:** no rate limit. Cascades at the database level — every target, check, schedule row,
tag, webhook, and API key belonging to this user is removed along with it. Clears the session
cookie. Irreversible.

---

### `POST /auth/forgot-password`

Request a password-reset email.

**Request:** `{"email": "..."}`

**Response:** `200`, `{"detail": "If that email is registered, a password reset link has been sent."}`
— **always this exact message**, whether or not the account exists.

**Notes:** `3/minute`. The reset link is valid for 60 minutes and single-use. A failed email
send is logged but never changes the response (anti-enumeration takes priority over surfacing
a delivery failure to the caller).

---

### `POST /auth/reset-password`

Consume a reset token and set a new password.

**Request:** `{"token": "...", "new_password": "..."}`

**Response:** `200`, `{"ok": true}`

**Notes:** `5/minute`. `400` if the token is unknown, already used, or expired. Redeeming one
token invalidates every other outstanding reset token for the same account. Does **not**
invalidate other already-logged-in sessions (sessions are stateless JWTs with no server-side
revocation list) — a known, accepted limitation.

## Targets

A target is a URL to monitor, owned by exactly one user, checked independently from every
worker region.

### `GET /targets`

List the authenticated user's targets, each with its full configuration and tags.

**Request (query):** `tag` (optional) — filter to targets carrying a tag with this exact name.

**Response:** `200`, array of:
```json
{
  "id": 42,
  "url": "https://example.com",
  "name": "Example",
  "created_at": "2026-06-01T12:00:00+00:00",
  "request_method": null,
  "request_headers": null,
  "basic_auth_username": null,
  "keyword_match": null,
  "keyword_match_mode": "contains",
  "paused": false,
  "check_interval_seconds": null,
  "tags": [{"id": 3, "name": "production", "created_at": "..."}]
}
```
`basic_auth_username` is shown; the password never is, in this or any other response.

**Notes:** API-key-eligible at `read`. No rate limit beyond the per-key limit.

---

### `POST /targets`

Create a new target.

**Request:**

| Field | Type | Notes |
|---|---|---|
| `url` | string | required; must be `http`/`https`, must not resolve to a blocked (SSRF) range |
| `name` | string \| null | optional label |
| `request_method` | `"GET"` \| `"POST"` \| `"HEAD"` \| null | null = HEAD-then-GET-on-failure (the default) |
| `request_headers` | object \| null | sent on every check |
| `basic_auth_username` / `basic_auth_password` | string \| null | both or neither; password is encrypted at rest and never returned |
| `keyword_match` | string \| null | require (or forbid) this substring in the response body |
| `keyword_match_mode` | `"contains"` \| `"not_contains"` | default `"contains"` |
| `check_interval_seconds` | int \| null | null = use the global default; minimum 30 if set |

**Response:** `201`, same shape as one `GET /targets` entry, `tags: []`.

**Notes:** `10/minute` IP-keyed (on top of the per-key limit — API-key-eligible at `full`).
`400` on an invalid/blocked URL, an unsupported method, `HEAD` combined with a `keyword_match`
(HEAD has no body to match against), a lone username or password with no pair, or an interval
below the floor. `409` if the normalized URL already exists for this user (uniqueness is
per-user, not global).

---

### `PATCH /targets/{id}`

Update a target's name and/or request-customization fields.

**Request:** any subset of `name`, `request_method`, `request_headers`, `basic_auth_username`,
`basic_auth_password`, `keyword_match`, `keyword_match_mode`, `check_interval_seconds`. Only
fields actually present in the request body are changed. `basic_auth_password` is the one
exception to "omit to leave unchanged, send `null` to clear": a blank or omitted password
always means "keep the existing one" — clear basic auth entirely by clearing
`basic_auth_username` instead. Does not support editing `url` or `paused` (see `/pause`/`/resume`
below).

**Response:** `200`, same shape as `POST /targets`.

**Notes:** per-key limit only, cookie-only (not API-key-eligible). `404` if the target doesn't
exist or isn't owned by the caller. Same `400` validation as create, run against the resulting
merged state, not just the fields touched by this request.

---

### `POST /targets/{id}/pause`

Exclude a target from scheduling in every region until resumed.

**Request:** none. **Response:** `200`, target with `paused: true`.

**Notes:** API-key-eligible at `full`. Idempotent. `404` on an unowned/missing target.

---

### `POST /targets/{id}/resume`

Un-pause a target and force an immediate recheck.

**Request:** none. **Response:** `200`, target with `paused: false`.

**Notes:** cookie-only. Idempotent — safe to call on a target that isn't paused (still forces a
prompt recheck). Directly resets `next_check_at` on every region's schedule row for this
target, the one deliberate exception to that table being worker-owned everywhere else.

---

### `POST /targets/{id}/tags`

Attach an existing tag to a target.

**Request:** `{"tag_id": 3}`

**Response:** `200`, the target with its updated `tags` list.

**Notes:** cookie-only. Ownership enforced on both sides — the target and the tag must both
belong to the caller, or `404`. Idempotent — attaching an already-attached tag is a no-op.

---

### `DELETE /targets/{id}/tags/{tag_id}`

Detach a tag from a target.

**Request:** none. **Response:** `204`.

**Notes:** cookie-only. Same both-sides ownership check as attach. Idempotent — detaching a tag
that isn't currently attached is not an error.

---

### `GET /targets/{id}`

Fetch one target's configuration plus its latest check per region — the single-target
equivalent of `GET /targets/status` below.

**Response:** `200`, `TargetStatusResponse` (see `/targets/status`).

**Notes:** API-key-eligible at `read`. `404` if the target doesn't exist or isn't owned by the
caller.

---

### `GET /targets/{id}/checks`

Raw check history for one region, oldest first.

**Request (query):** `region` (required), `limit` (default 500, max 2000), `cursor` (optional,
API-key callers only — see Notes).

**Response:** `200`, array of check entries (same shape as one region's entry in
`latest_checks`, plus `"region"`).

**Notes:** API-key-eligible at `read`. `region` is required — there is no "every region merged"
option, matching every other per-region endpoint in this app. Cursor-based pagination
(`cursor` = the last-seen check id; a further page is signaled via an `X-Next-Cursor` response
header) is honored **only for API-key-authenticated requests** — a cookie-authenticated
request's behavior is completely unaffected by these params, since the dashboard fetches this
once per region on page load and has no use for paging.

---

### `GET /targets/{id}/analytics`

Windowed uptime %, latency percentiles, and MTTR, per region.

**Request (query):** `window` — one of `24h`, `7d`, `30d`, `90d` (default `7d`).

**Response:** `200`
```json
{
  "window": "7d",
  "window_start": "2026-05-25T12:00:00+00:00",
  "regions": {
    "us-east": {
      "uptime_percent": 99.42,
      "total_checks": 2016,
      "latency_p50_ms": 58,
      "latency_p95_ms": 210,
      "latency_p99_ms": 480,
      "mttr_seconds": 340.0,
      "incident_count": 2
    }
  }
}
```

**Notes:** `400` if `window` isn't one of the four allowed values, `404` on an unowned/missing
target. Unlike `/checks` and `/export`, **every region comes back at once** here — the point of
this endpoint is comparing regions side by side, so requiring one call per region would work
against its own purpose. A region absent entirely from `regions` had zero checks in the window,
which is different from an in-progress incident that's still counted (see the Engineering page
for how an unresolved incident's duration is handled).

---

### `GET /targets/{id}/export`

Download a compliance CSV: a summary section (SLA %, incident list), then the raw check rows.

**Request (query):** `region` (required), `format` (only `"csv"` is implemented today), `from`,
`to` (optional ISO 8601 bounds).

**Response:** `200`, `text/csv`, `Content-Disposition: attachment`.

**Notes:** API-key-eligible at `read`. `400` if `format` isn't `"csv"` (an honest error rather
than silently returning CSV under a different label — PDF export is planned, not built). If the
requested range predates what the retention sweep could still have on disk, the summary
includes a `Note` row saying so.

---

### `GET /targets/status`

List every owned target with its latest check per region — the dashboard's main read.

**Response:** `200`, array of:
```json
{
  "id": 42,
  "url": "https://example.com",
  "name": "Example",
  "created_at": "2026-06-01T12:00:00+00:00",
  "latest_checks": {
    "us-east": {
      "checked_at": "2026-06-08T09:00:03+00:00",
      "is_up": true,
      "status_code": 200,
      "latency_ms": 58,
      "error": null,
      "dns_ms": 4, "tcp_ms": 12, "tls_ms": 20, "ttfb_ms": 22,
      "tls_cert_expires_at": "2026-09-01T00:00:00+00:00",
      "tls_cert_issuer": "CN=R3, O=Let's Encrypt, C=US",
      "tls_cert_days_remaining": 85,
      "consecutive_failures": 0
    }
  }
}
```

**Notes:** `latest_checks` is keyed by region; a target with no checks yet in any region
returns `{}`, not `null`. There is deliberately no derived "overall status" field anywhere —
see `docs/adr/003-multi-region-coordination.md`. `consecutive_failures` is `null` when no
schedule row exists yet for that region.

---

### `GET /targets/stream`

Server-Sent Events stream of live check updates for the authenticated user's own targets.

**Request:** none (cookie only — not API-key-eligible, since a long-lived streaming connection
doesn't fit the per-request auth model cleanly).

**Response:** `text/event-stream`. A `: connected` comment on open, then either
`data: {"type": "check_update", "region": "us-east", "target": {...}}` (same shape as one
`GET /targets/status` entry) whenever a check for one of this user's targets lands, or a
`: keep-alive` comment roughly every 15 seconds when there's nothing new.

**Notes:** never delivers another user's data — the notification is resolved to its owning user
before anything is published, so a user's queue structurally cannot receive a target it doesn't
own.

---

### `DELETE /targets/{id}`

Delete a target.

**Request:** none. **Response:** `204`.

**Notes:** API-key-eligible at `full`. `404` on an unowned/missing target. Checks and schedule
rows are removed via cascade.

## Tags

Free-form per-user labels, attached to targets many-to-many. A name is unique per user, not
globally — two users can each have their own tag named "production."

### `GET /tags`

List the authenticated user's tags, alphabetically. **Request:** none. **Response:** `200`,
array of `{"id": 3, "name": "production", "created_at": "..."}`. **Notes:** cookie-only, no
rate limit.

---

### `POST /tags`

Create a tag. **Request:** `{"name": "production"}`. **Response:** `201`, the created tag.
**Notes:** `10/minute` IP-keyed. `400` on an empty or over-length name, `409` on a duplicate
name for this user.

---

### `PATCH /tags/{id}`

Rename a tag. **Request:** `{"name": "new-name"}`. **Response:** `200`, the updated tag.
**Notes:** per-key-magnitude limit, cookie-only. `404` on an unowned/missing tag, `409` on a
name collision with another of this user's tags. Every target already carrying this tag keeps
it.

---

### `DELETE /tags/{id}`

Delete a tag. **Request:** none. **Response:** `204`. **Notes:** same limit as rename. `404`
on an unowned/missing tag. Detached from every target it was attached to, via cascade.

## Webhooks

Outbound HTTP notifications on downtime, recovery, and cert-expiry events — see the
Engineering page for the delivery/signing design.

### `GET /webhooks`

List the authenticated user's webhooks. Never includes `secret`. **Notes:** API-key-eligible
at `full`.

---

### `POST /webhooks`

Create a webhook.

**Request:** `{"url": "https://...", "alert_on_downtime": true, "alert_on_cert_expiry": true}`

**Response:** `201`
```json
{
  "id": 7,
  "url": "https://hooks.example.com/uptime",
  "alert_on_downtime": true,
  "alert_on_cert_expiry": true,
  "enabled": true,
  "created_at": "2026-06-01T12:00:00+00:00",
  "secret": "a1b2c3..."
}
```
`secret` is shown **only in this response** — record it now; it's never returned again.

**Notes:** `10/minute` IP-keyed on top of the per-key limit. `400` on a malformed URL or one
that resolves to a blocked (SSRF) range — the same check `POST /targets` runs, re-applied
again immediately before every actual delivery attempt.

---

### `PATCH /webhooks/{id}`

Update a webhook's URL and/or its toggles.

**Request:** any subset of `url`, `alert_on_downtime`, `alert_on_cert_expiry`, `enabled`.

**Response:** `200`, updated webhook (no `secret`).

**Notes:** API-key-eligible at `full`. A changed URL is re-validated exactly like creation.
The signing secret itself is never rotated by this endpoint — delete and recreate for a new
one.

---

### `DELETE /webhooks/{id}`

Delete a webhook. **Response:** `204`. **Notes:** API-key-eligible at `full`. `404` on an
unowned/missing webhook.

## API Keys

Cookie-authenticated only — a key can never be used to manage other keys.

### `GET /api-keys`

List the authenticated user's keys, including revoked ones (as an audit trail). Never includes
the hash or raw key. **Notes:** no rate limit.

---

### `POST /api-keys`

Create a key.

**Request:** `{"name": "prometheus-exporter", "scope": "read"}` — `scope` is `"read"` or
`"full"`, default `"read"`.

**Response:** `201`
```json
{
  "id": 5,
  "name": "prometheus-exporter",
  "key_prefix": "um_AbCdEfGh",
  "scope": "read",
  "created_at": "2026-06-01T12:00:00+00:00",
  "last_used_at": null,
  "revoked_at": null,
  "key": "um_AbCdEfGh12345..."
}
```
`key` is shown **only in this response**; only its SHA-256 hash is ever stored, so it cannot be
recovered later even by this app.

**Notes:** `10/minute` IP-keyed. `400` on an empty name or an unrecognized scope.

---

### `DELETE /api-keys/{id}`

Revoke a key (soft-delete — the row is kept, `revoked_at` is stamped). **Response:** `204`.
**Notes:** per-key-magnitude limit, IP-keyed. Idempotent. `404` on an unowned/missing key.
