// Shared with app/dashboard/page.tsx's own local copy of this shape (not consolidated there —
// that page is out of scope for prompt 3.6). New code (the detail page) imports from here.
export type LatestCheck = {
  checked_at: string | null;
  is_up: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  dns_ms?: number | null;
  tcp_ms?: number | null;
  tls_ms?: number | null;
  ttfb_ms?: number | null;
  tls_cert_expires_at?: string | null;
  tls_cert_issuer?: string | null;
  tls_cert_days_remaining?: number | null;
  // From target_region_schedule, not the check row itself — resets to 0 the moment a check
  // succeeds, so it's only meaningful (non-null) on a check that itself failed. Null when no
  // schedule row exists yet for this region. See lib/thresholds.ts's
  // CONSECUTIVE_FAILURES_DOWN_THRESHOLD.
  consecutive_failures?: number | null;
};

export type TargetDetail = {
  id: number;
  url: string;
  name: string | null;
  created_at: string;
  latest_checks: Record<string, LatestCheck>;
};

// One entry from GET /targets/{id}/checks?region=... — same fields as LatestCheck, plus which
// region it's from (the endpoint already filters to one region, but the field rides along for
// clarity/type reuse).
export type CheckHistoryEntry = LatestCheck & { region: string };
