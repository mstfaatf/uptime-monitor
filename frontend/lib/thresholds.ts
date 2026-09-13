// Locked degraded-state contract (see CLAUDE.md's Phase 3 design tokens): latency_ms > 800 OR
// tls_cert_days_remaining <= 14 -> degraded. Both LatencyGauge's default zone boundaries and
// the dashboard's per-region state derivation read from here, so the two can't silently drift
// apart the way two independently-hardcoded "800"s could.
export const LATENCY_GOOD_MS = 200;
export const LATENCY_WARN_MS = 800;
export const LATENCY_MAX_MS = 2000;
export const CERT_EXPIRY_WARN_DAYS = 14;

// A failed check isn't immediately "down" (red) — it's "degraded" (amber, still retrying)
// until consecutive_failures crosses this threshold. Debounces the down classification itself
// (a single blip doesn't flip the light red), it does not add a new trigger on the up path.
// Matches worker/backoff.py's curve: by the 3rd consecutive failure the backoff delay is
// already ~120s, a reasonable point to call it a real outage rather than a transient blip.
export const CONSECUTIVE_FAILURES_DOWN_THRESHOLD = 3;
