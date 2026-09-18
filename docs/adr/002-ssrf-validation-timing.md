# ADR 002: SSRF Validation at Both Creation Time and Check Time

## Status

Accepted. Implemented in `backend/security/ssrf.py`, `worker/ssrf.py`, and the redirect
revalidation in `worker/checker.py`.

## Context

Every target this app monitors is a URL a user supplies, and the worker's whole job is to make
outbound HTTP requests to it on a schedule from infrastructure that also happens to have network
access to things it has no business reaching: cloud metadata endpoints, other services on the
same private network, `localhost` on the worker's own container. A URL like
`http://169.254.169.254/latest/meta-data/` or `http://10.0.0.5:6379/` isn't a hypothetical
monitoring target — it's a classic SSRF payload, and this app's worker is exactly the kind of
"makes requests on a schedule, on your behalf" component that SSRF attacks are built around.

Blocking loopback, RFC1918 private ranges, and link-local addresses is the easy part. The harder
question is *when* to check: once, at the moment a URL is submitted, or every time the worker is
about to actually use it.

## Decision

Both, and neither replaces the other:

1. **At target creation** (`POST /targets`), the submitted URL is resolved and checked against
   the blocklist before the row is ever written. This gives a user immediate, synchronous
   feedback (a `400` with a clear reason) rather than silently accepting a bad URL that would
   only ever fail quietly on the worker's own schedule.
2. **At check time**, independently, the worker re-resolves and re-checks the URL immediately
   before making the request — and, since a check can involve following redirects, **every
   individual redirect hop's `Location` header is re-validated the same way before it's
   followed**, not just the original URL.

The two live in genuinely separate code paths (`backend/security/ssrf.py` and `worker/ssrf.py`),
duplicated by hand rather than factored into a shared package, since the backend and worker are
independently deployed services with their own Dockerfiles — a shared installable module for
roughly fifty lines of blocklist logic would add real versioning and deployment coordination for
very little benefit.

## Alternatives considered

- **Creation-time validation only.** Rejected: this defends nothing against DNS rebinding — a
  hostname that resolves to a public IP at the moment a user adds it, then gets repointed at a
  private or metadata address later (either by an attacker who controls the DNS record, or by
  perfectly ordinary infrastructure changes on a target the user doesn't control). A worker that
  only ever validated at creation would happily keep making requests to whatever the hostname
  resolves to today, forever.
- **Check-time validation only.** Rejected on the product side, not just the security side: a
  user who submits a bad URL would get a silent, delayed failure on the worker's next cycle
  instead of the immediate, actionable `400` a synchronous creation-time check provides. Fast
  feedback at the point of input is worth keeping even though it can never be the *only* line of
  defense.
- **Following redirects with the HTTP client's own built-in `follow_redirects=True` and
  validating only the original URL.** This was the worker's actual first implementation, and it
  has a direct, exploitable gap: a URL that passes every check can still return a `3xx` pointing
  at a blocked address, and a client configured to auto-follow redirects will happily request it
  without the blocklist ever seeing that second address. The fix was to disable automatic
  redirect-following entirely and walk the chain manually, re-running the SSRF check against
  each `Location` header before following it — caught and fixed directly in this codebase, not
  a hypothetical concern.
- **A single shared SSRF-checking package imported by both services.** Considered and rejected,
  as noted above — the duplication cost (keeping two files in sync by hand) was judged smaller
  than the deployment cost (a versioned internal package two independently-deployed services
  both depend on) at this project's size.

## Consequences

- A URL that's genuinely fine today but gets DNS-rebound to a private address tomorrow is still
  caught, on the very next check, not just at submission — this is the property creation-time
  validation alone cannot provide.
- **A real credential-leak variant of this same problem was found and fixed after the initial
  redirect-revalidation logic shipped.** Manually walking a redirect chain (required for the
  per-hop SSRF check above) also bypasses an HTTP client's own default behavior of stripping
  `Authorization` on a cross-origin redirect — so a target's basic-auth password or a
  secret-bearing custom header would otherwise have been forwarded to whatever third-party host
  a `3xx` response happened to name, not just the host the user actually configured credentials
  for. The fix mirrors what the client library would have done automatically: a target's
  configured headers and basic-auth credentials are dropped the moment a redirect crosses to a
  different host, and never restored even if a later hop redirects back to the original host.
  This is the direct cost of having taken on manual redirect-following in the first place — every
  behavior the client's own redirect machinery would have handled safely has to be re-implemented
  deliberately, not assumed.
- Two blocklists, hand-kept in sync, is a real maintenance seam: a future change to the blocked
  ranges (say, adding IPv6 unique-local addresses to the list) has to be remembered on both
  sides, with nothing enforcing that beyond a comment in each file pointing at the other.
- The backend's own outbound container needs working DNS resolution for the creation-time check
  to function at all — a check that only ever needs to happen on the worker before this decision
  became a new, real requirement on the API service's own network configuration once
  creation-time validation was added.
