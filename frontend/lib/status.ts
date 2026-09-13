import type { SignalState } from "@/components/signal-light";
import type { LatestCheck } from "@/lib/types";
import { LATENCY_WARN_MS, CERT_EXPIRY_WARN_DAYS } from "@/lib/thresholds";

// The locked degraded-state contract (see CLAUDE.md's Phase 3 design tokens), applied to any
// single check row: no check yet -> pending; a failed check -> down; a successful check that's
// slow or has a soon-to-expire cert -> degraded; everything else -> up.
export function deriveState(check: LatestCheck | null | undefined): SignalState {
  if (!check || check.checked_at == null) return "pending";
  if (!check.is_up) return "down";
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
