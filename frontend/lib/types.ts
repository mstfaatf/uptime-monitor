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

// Matches backend/routers/tags.py's TagResponse (Phase 6, prompt 6.4/6.13).
export type Tag = {
  id: number;
  name: string;
  created_at: string;
};

// Matches backend/routers/targets.py's TargetResponse (Phase 6, prompts 6.2-6.4) — the full
// configuration shape, distinct from TargetDetail above (which is the live check-status shape
// GET /targets/{id} actually returns). There's no single-target endpoint for this shape today;
// the target-settings modal gets it by fetching GET /targets and finding the matching id — see
// that component's own comment on why a new backend endpoint wasn't worth adding for this.
export type TargetSettings = {
  id: number;
  url: string;
  name: string | null;
  created_at: string;
  request_method: string | null;
  request_headers: Record<string, string> | null;
  basic_auth_username: string | null;
  keyword_match: string | null;
  keyword_match_mode: string;
  paused: boolean;
  check_interval_seconds: number | null;
  tags: Tag[];
};

// Matches backend/routers/webhooks.py's WebhookResponse (Phase 6, prompt 6.6). `secret` only
// ever appears on the create response (WebhookCreatedResponse), never here or in any later
// GET — see webhook-settings.tsx for how the create flow handles that one-time value.
export type Webhook = {
  id: number;
  url: string;
  alert_on_downtime: boolean;
  alert_on_cert_expiry: boolean;
  enabled: boolean;
  created_at: string;
};

// Matches backend/routers/api_keys.py's ApiKeyResponse (Phase 6, prompt 6.7). Same one-time-
// secret shape as Webhook above: the raw `key` only ever appears on the create response.
export type ApiKey = {
  id: number;
  name: string;
  key_prefix: string;
  scope: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

// Matches backend/routers/targets.py's RegionAnalyticsResponse/TargetAnalyticsResponse (Phase
// 6, prompt 6.5).
export type RegionAnalytics = {
  uptime_percent: number | null;
  total_checks: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  mttr_seconds: number | null;
  incident_count: number;
};

export type TargetAnalytics = {
  window: string;
  window_start: string;
  regions: Record<string, RegionAnalytics>;
};
