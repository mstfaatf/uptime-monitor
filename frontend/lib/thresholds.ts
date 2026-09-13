// Locked degraded-state contract (see CLAUDE.md's Phase 3 design tokens): latency_ms > 800 OR
// tls_cert_days_remaining <= 14 -> degraded. Both LatencyGauge's default zone boundaries and
// the dashboard's per-region state derivation read from here, so the two can't silently drift
// apart the way two independently-hardcoded "800"s could.
export const LATENCY_GOOD_MS = 200;
export const LATENCY_WARN_MS = 800;
export const LATENCY_MAX_MS = 2000;
export const CERT_EXPIRY_WARN_DAYS = 14;
