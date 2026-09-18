# ADR 001: JWT-in-Cookie Sessions, Not Server-Side Session Storage

## Status

Accepted. Implemented in `backend/auth/cookies.py`, `backend/auth/deps.py`, and
`backend/config.py`.

## Context

Every request that touches a user's own data (their targets, checks, tags, webhooks, API keys)
needs to know who's asking, and that identity has to survive normal browser behavior, including
page reloads, new tabs, and a week between visits, without the user re-authenticating
constantly. Two
broad shapes were available: a server-side session (a session id in the cookie, the actual
session data held in a database or an in-memory store like Redis), or a self-contained,
cryptographically signed token that carries its own claims and needs no server-side lookup to
validate.

Whatever the mechanism, it had to reach the browser exclusively through an HTTP-only cookie,
never through anything JavaScript can read. A token sitting in `localStorage` is reachable by
any script that runs on the page, which turns an ordinary XSS bug into full session theft. That
much wasn't really a decision. It's the one non-negotiable constraint this project holds
everywhere.

## Decision

Sessions are a signed JWT (`HS256`, one shared `JWT_SECRET`), carrying the user's id and email
as claims, set as the value of an `HttpOnly` cookie. There is no server-side session table and
no session store of any kind. A request is authenticated the moment its cookie's signature and
expiry check out, with a single `SELECT` to confirm the referenced user still exists. Nothing
about validating a session touches Redis, a sessions table, or any other piece of shared state.

The cookie's other flags are environment-aware rather than fixed: `COOKIE_SECURE` and
`COOKIE_SAMESITE` are both forced to `True` / `"none"` whenever `ENVIRONMENT=production`,
regardless of what those two settings are otherwise configured to. Production means the
frontend and backend sit on different origins (Vercel and Railway), and a `SameSite=Lax` cookie
is silently dropped on exactly that kind of cross-site request, which would break login with no
visible error rather than fail loudly. Local development keeps a plain `Lax`, `Secure=false`
cookie over HTTP, since there's no cross-origin request to defend against there.

## Alternatives considered

- **Token in `localStorage`, read and attached by client-side JavaScript.** Rejected outright.
  This is exactly the XSS-to-session-theft path described above, and there's no compelling
  reason for a same-product frontend and backend to need it.
- **Server-side sessions (a `sessions` table or a Redis store, cookie holds only an opaque
  session id).** The real advantage this would buy is revocation: killing a session server-side
  (on logout everywhere, on password change, on suspected compromise) becomes a single row
  delete instead of "wait for the token to expire." That's a genuine gap in the JWT approach,
  covered under Consequences below, but it was judged not worth the operational cost at this
  project's scale. A session store is another piece of shared state every backend instance and,
  later, a horizontally-scaled deployment would need to agree on, for a single-user-per-account
  personal tool that doesn't currently need instant cross-device revocation.
- **Short-lived JWT + refresh token pair.** Considered for the added benefit of a short blast
  radius on a leaked access token. Rejected as unnecessary complexity for now. A single
  7-day-lived cookie, `HttpOnly` and never exposed to JavaScript, already has a narrow leak
  surface, since it would need to be exfiltrated at the network or infrastructure level rather
  than via a script running on the page, and refresh-token rotation is a meaningful amount of
  additional logic and failure modes for a threat model this project doesn't face today.

## Consequences

- **No server-side revocation.** A logout clears the cookie client-side, but the token itself
  remains cryptographically valid until it expires (7 days) if it were somehow replayed from
  elsewhere. Concretely, this project's own password-reset flow inherits the same limitation:
  resetting a password does not invalidate any other already-logged-in session for that
  account. This is documented plainly at the one endpoint where it's most likely to matter
  (`POST /auth/reset-password`), rather than silently assumed away.
- **Rate limiting on auth-adjacent endpoints ends up keyed by IP, not by user.** The rate
  limiter's key function only ever sees the raw incoming request, before any FastAPI dependency
  (including the one that decodes the session cookie) has run. Keying by user would mean
  re-implementing cookie decoding a second time inside the limiter, duplicating real auth logic
  for a benefit (catching an attacker who rotates IPs but reuses one account) that IP-keying
  already covers well enough in practice.
- **A stateless token doesn't fit a programmatic, non-browser client well.** This became
  concrete once API keys were introduced for external integrations. A key is deliberately its
  own separate, database-backed credential (hashed at rest, individually revocable, scoped
  read/full) rather than a long-lived JWT handed to a script, giving it exactly the revocation
  property a session JWT itself doesn't have. The two mechanisms coexist on purpose: cookies
  for the browser, keys for everything else, each suited to what actually authenticates it.
- **Horizontal scaling of the backend needs no session-affinity or shared session store.** Any
  backend instance can validate any request's cookie on its own, since validation is pure
  signature/expiry verification against one shared secret, not a lookup against instance-local
  or even shared mutable state. The one thing that *does* need coordinating at that point is the
  rate limiter's own in-memory counters, which is a separate, already-documented limitation
  unrelated to how sessions work.
