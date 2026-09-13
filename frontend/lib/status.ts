import type { SignalState } from "@/components/signal-light";
import type { LatestCheck } from "@/lib/types";
import { LATENCY_WARN_MS, CERT_EXPIRY_WARN_DAYS, CONSECUTIVE_FAILURES_DOWN_THRESHOLD } from "@/lib/thresholds";

// The locked degraded-state contract (see CLAUDE.md's Phase 3 design tokens, extended in
// prompt 4.4), applied to any single check row:
//   no check yet -> pending
//   is_up == false -> consecutive_failures < threshold -> degraded (still retrying, not
//     confirmed down yet), else -> down. Authoritative and evaluated first: latency/cert
//     thresholds never apply to a failed check.
//   is_up == true -> slow or a soon-to-expire cert -> degraded; everything else -> up.
export function deriveState(check: LatestCheck | null | undefined): SignalState {
  if (!check || check.checked_at == null) return "pending";
  if (!check.is_up) {
    const failures = check.consecutive_failures ?? 0;
    return failures < CONSECUTIVE_FAILURES_DOWN_THRESHOLD ? "degraded" : "down";
  }
  const slow = check.latency_ms != null && check.latency_ms > LATENCY_WARN_MS;
  const certExpiringSoon =
    check.tls_cert_days_remaining != null && check.tls_cert_days_remaining <= CERT_EXPIRY_WARN_DAYS;
  return slow || certExpiringSoon ? "degraded" : "up";
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "—";
  }
}
