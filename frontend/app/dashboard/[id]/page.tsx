"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API_BASE, apiFetch } from "@/lib/api";
import { SignalLight } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";
import { LatencyChart } from "@/components/latency-chart";
import { TimingWaterfall } from "@/components/timing-waterfall";
import { UptimeHeatmap } from "@/components/uptime-heatmap";
import { IncidentTimeline } from "@/components/incident-timeline";
import { RegionBadge } from "@/components/region-badge";
import { EmptyState } from "@/components/empty-state";
import { TargetSettingsModal } from "@/components/target-settings-modal";
import { Button } from "@/components/ui/button";
import {
  Skeleton,
  SignalLightSkeleton,
  LatencyGaugeSkeleton,
  LatencyChartSkeleton,
  TimingWaterfallSkeleton,
  UptimeHeatmapSkeleton,
} from "@/components/skeleton";
import { deriveState, formatTimestamp } from "@/lib/status";
import type { TargetDetail, CheckHistoryEntry, TargetAnalytics } from "@/lib/types";

// Matches backend/analytics.py's ALLOWED_WINDOWS exactly.
const ANALYTICS_WINDOWS = ["24h", "7d", "30d", "90d"] as const;
type AnalyticsWindow = (typeof ANALYTICS_WINDOWS)[number];

function formatMttr(seconds: number | null): string {
  if (seconds == null) return "—";
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}m`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

function computeSla(checks: CheckHistoryEntry[]): number | null {
  if (checks.length === 0) return null;
  const upCount = checks.filter((c) => c.is_up).length;
  return (upCount / checks.length) * 100;
}

function slaColor(sla: number | null): string {
  if (sla == null) return "var(--signal-pending)";
  if (sla >= 99.9) return "var(--signal-up)";
  if (sla >= 99) return "var(--signal-warning)";
  return "var(--signal-down)";
}

export default function TargetDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const targetId = params.id;

  const [detail, setDetail] = useState<TargetDetail | null>(null);
  const [checksByRegion, setChecksByRegion] = useState<Record<string, CheckHistoryEntry[]>>({});
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [authFailed, setAuthFailed] = useState(false);
  const [error, setError] = useState("");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  // `detail` (TargetDetail, from GET /targets/{id}) has no `paused` field — that's part of the
  // full TargetResponse shape the settings modal fetches separately (see its own comment on
  // why). Tracked here just so this page can show a small "Paused" badge without re-fetching
  // the full settings shape itself.
  const [paused, setPaused] = useState(false);

  const [analyticsWindow, setAnalyticsWindow] = useState<AnalyticsWindow>("7d");
  const [analytics, setAnalytics] = useState<TargetAnalytics | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await apiFetch(`/targets/${targetId}`);
      if (res.status === 401) {
        setAuthFailed(true);
        return;
      }
      if (res.status === 404) {
        setNotFound(true);
        return;
      }
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const data = (await res.json()) as TargetDetail;
      setDetail(data);

      // GET /targets/{id} doesn't carry `paused` (see this component's own state comment) —
      // a light best-effort fetch just for that one field, not treated as fatal if it fails.
      apiFetch("/targets")
        .then((r) => (r.ok ? r.json() : null))
        .then((targets: { id: number; paused: boolean }[] | null) => {
          const match = targets?.find((t) => t.id === Number(targetId));
          if (match) setPaused(match.paused);
        })
        .catch(() => {});

      const regions = Object.keys(data.latest_checks).sort((a, b) => a.localeCompare(b));
      if (regions.length > 0) {
        setSelectedRegion((prev) => prev ?? regions[0]);
        const entries = await Promise.all(
          regions.map(async (region) => {
            const r = await apiFetch(`/targets/${targetId}/checks?region=${encodeURIComponent(region)}&limit=500`);
            if (!r.ok) return [region, []] as const;
            return [region, (await r.json()) as CheckHistoryEntry[]] as const;
          })
        );
        setChecksByRegion(Object.fromEntries(entries));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, [targetId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await load();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  useEffect(() => {
    if (authFailed) router.replace("/login");
  }, [authFailed, router]);

  // Analytics is fetched independently of the region-tab logic above — the endpoint returns
  // every region's figures in one response (see lib/types.ts's TargetAnalytics), so switching
  // the window re-fetches once, and switching the selected region tab below just re-reads the
  // already-fetched response rather than triggering a new request.
  useEffect(() => {
    if (loading || authFailed || notFound) return;
    let cancelled = false;
    setAnalyticsLoading(true);
    (async () => {
      const res = await apiFetch(`/targets/${targetId}/analytics?window=${analyticsWindow}`);
      if (cancelled) return;
      if (res.status === 401) {
        setAuthFailed(true);
        return;
      }
      if (res.ok) setAnalytics((await res.json()) as TargetAnalytics);
      setAnalyticsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [targetId, analyticsWindow, loading, authFailed, notFound]);

  function handleSettingsOpen(e: React.MouseEvent<HTMLButtonElement>) {
    settingsTriggerRef.current = e.currentTarget;
    setSettingsOpen(true);
  }

  // Same explicit-focus-restore need documented at length in the dashboard's own quick-add/
  // tag-manager modals (6.12/6.13) — this button is a plain external trigger too, not a
  // <DialogTrigger>.
  function handleSettingsOpenChange(next: boolean) {
    setSettingsOpen(next);
    if (!next) {
      requestAnimationFrame(() => settingsTriggerRef.current?.focus());
    }
  }

  function handleSettingsSaved(patch: { name: string | null; paused: boolean }) {
    setDetail((prev) => (prev ? { ...prev, name: patch.name } : prev));
    setPaused(patch.paused);
  }

  if (authFailed) return null;

  if (loading) {
    // Shaped like the real page below (region cards, tabs, Latency/Timing/Uptime sections) so
    // there's no layout jump once real data replaces it — same bordered-panel treatment as the
    // actual sections use, just filled with placeholder blocks instead of real content. Kept to
    // the header returning bare (no site header/nav) exactly like the pre-existing "Loading…"
    // state did — not a structural change, just what fills the one <main> that already existed.
    return (
      <main className="mx-auto max-w-5xl px-6 py-10" aria-busy="true" aria-label="Loading target detail">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-40" />
          </div>
          <Skeleton className="h-10 w-32 rounded" />
        </div>

        <div className="mt-6 flex flex-wrap gap-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="flex flex-col items-start gap-2 rounded border p-4"
              style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
            >
              <Skeleton className="h-5 w-14 rounded" />
              <SignalLightSkeleton size="md" />
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>

        <div className="mt-8 flex gap-2">
          <Skeleton className="h-8 w-20 rounded" />
          <Skeleton className="h-8 w-20 rounded" />
        </div>

        <section
          className="mt-6 rounded border p-5"
          style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
        >
          <Skeleton className="h-5 w-20" />
          <div className="mt-4 flex flex-col items-stretch gap-6 md:flex-row md:items-start">
            <LatencyGaugeSkeleton size="md" />
            <div className="min-w-0 flex-1">
              <LatencyChartSkeleton />
            </div>
          </div>
        </section>

        <section
          className="mt-6 rounded border p-5"
          style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
        >
          <Skeleton className="h-5 w-36" />
          <Skeleton className="mt-2 h-3 w-40" />
          <div className="mt-4">
            <TimingWaterfallSkeleton />
          </div>
        </section>

        <section
          className="mt-6 rounded border p-5"
          style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
        >
          <Skeleton className="h-5 w-16" />
          <div className="mt-4">
            <UptimeHeatmapSkeleton />
          </div>
        </section>

        <section className="mt-10 border-t pt-6" style={{ borderColor: "var(--border)" }}>
          <Skeleton className="h-5 w-20" />
          <Skeleton className="mt-4 h-4 w-56" />
        </section>

        <section className="mt-8 border-t pt-6" style={{ borderColor: "var(--border)" }}>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="mt-4 h-4 w-48" />
        </section>
      </main>
    );
  }

  if (notFound) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="font-semibold">Target not found.</p>
        <Link href="/dashboard" className="mt-2 inline-block text-sm underline" style={{ color: "var(--text-primary)" }}>
          Back to dashboard
        </Link>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        {error && (
          <p className="text-sm" style={{ color: "var(--signal-down)" }}>
            {error}
          </p>
        )}
      </main>
    );
  }

  const regions = Object.keys(detail.latest_checks).sort((a, b) => a.localeCompare(b));
  const selectedChecks = selectedRegion ? checksByRegion[selectedRegion] ?? [] : [];
  const selectedLatest = selectedRegion ? detail.latest_checks[selectedRegion] : undefined;

  return (
    <>
      <header className="border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-2 px-6 py-4">
          <Link href="/dashboard" className="flex items-center gap-3">
            <SignalLight state="up" size="sm" />
            <span className="font-semibold">Uptime Monitor</span>
          </Link>
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="font-mono text-sm hover:underline" style={{ color: "var(--text-secondary)" }}>
              ← Back to dashboard
            </Link>
            <Link href="/settings" className="font-mono text-sm hover:underline" style={{ color: "var(--text-secondary)" }}>
              Settings
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold">{detail.name || detail.url}</h1>
              {paused && (
                <span
                  className="rounded-sm border px-1.5 py-0.5 font-mono text-xs"
                  style={{ borderColor: "var(--signal-warning)", color: "var(--signal-warning)" }}
                >
                  Paused
                </span>
              )}
            </div>
            {detail.name && (
              <a
                href={detail.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-sm hover:underline"
                style={{ color: "var(--text-secondary)" }}
              >
                {detail.url}
              </a>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" onClick={handleSettingsOpen} ref={settingsTriggerRef}>
              Edit settings
            </Button>
            {selectedRegion ? (
              // A plain <a> to the export endpoint, not a fetch-and-blob dance: the browser
              // already sends the session cookie on a top-level navigation like this (SameSite=
              // lax allows it), and the backend's Content-Disposition: attachment header is what
              // actually triggers a download instead of navigating away from the app — no client
              // JS needed to make that happen. Exports the currently-selected region's full
              // history (no date-range picker UI yet — the endpoint supports from/to, but this
              // prompt's scope was wiring the button, not building range controls).
              <Button asChild variant="outline">
                <a href={`${API_BASE}/targets/${targetId}/export?region=${encodeURIComponent(selectedRegion)}&format=csv`}>
                  Export CSV ({selectedRegion})
                </a>
              </Button>
            ) : (
              <Button type="button" variant="outline" disabled title="No check history yet to export.">
                Export CSV
              </Button>
            )}
          </div>
        </div>

        {regions.length === 0 ? (
          <EmptyState
            className="mt-8"
            size="md"
            title="Waiting on the first check"
            description="This target hasn't been checked by any monitoring region yet. Its latency chart, uptime heatmap, and incident history will appear here as soon as results start coming in."
          />
        ) : (
          <>
            {/* Per-region header blocks: each region's signal + SLA stays entirely its own —
                there is no combined/collapsed number anywhere on this page. */}
            <div className="mt-6 flex flex-wrap gap-4">
              {regions.map((region) => {
                const latest = detail.latest_checks[region];
                const sla = computeSla(checksByRegion[region] ?? []);
                return (
                  <div
                    key={region}
                    className="flex flex-col items-start gap-2 rounded border p-4"
                    style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
                  >
                    <RegionBadge region={region} />
                    <SignalLight state={deriveState(latest)} size="md" showLabel />
                    <div className="font-mono text-3xl" style={{ color: slaColor(sla) }}>
                      {sla != null ? `${sla.toFixed(1)}%` : "—"}
                    </div>
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      SLA ({(checksByRegion[region] ?? []).length} checks)
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Region tabs — everything below picks one region at a time. */}
            <div className="mt-8 flex flex-wrap gap-2">
              {regions.map((region) => (
                <Button
                  key={region}
                  type="button"
                  size="sm"
                  variant={region === selectedRegion ? "default" : "outline"}
                  onClick={() => setSelectedRegion(region)}
                >
                  {region}
                </Button>
              ))}
            </div>

            {/* Windowed analytics (Phase 6, prompt 6.5's backend, surfaced here in 6.14) — the
                fetch covers every region at once (see the effect above), so switching the
                window re-fetches once and switching the region tab above just re-reads the
                already-fetched response; only the *display* below is scoped to selectedRegion,
                same as every other section on this page. */}
            <section className="mt-6 rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">Analytics</h2>
                <div className="flex gap-1.5">
                  {ANALYTICS_WINDOWS.map((w) => (
                    <Button
                      key={w}
                      type="button"
                      size="sm"
                      variant={w === analyticsWindow ? "default" : "outline"}
                      onClick={() => setAnalyticsWindow(w)}
                    >
                      {w}
                    </Button>
                  ))}
                </div>
              </div>
              {(() => {
                const stats = selectedRegion ? analytics?.regions[selectedRegion] : undefined;
                if (analyticsLoading && !analytics) {
                  return (
                    <p className="mt-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                      Loading…
                    </p>
                  );
                }
                if (!stats) {
                  return (
                    <p className="mt-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                      No checks for this region in the selected window.
                    </p>
                  );
                }
                return (
                  <>
                    <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                      <div className="flex flex-col">
                        <span className="font-mono text-2xl" style={{ color: slaColor(stats.uptime_percent) }}>
                          {stats.uptime_percent != null ? `${stats.uptime_percent.toFixed(1)}%` : "—"}
                        </span>
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          uptime
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="font-mono text-2xl" style={{ color: "var(--text-primary)" }}>
                          {stats.latency_p50_ms != null ? `${stats.latency_p50_ms} ms` : "—"}
                        </span>
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          p50 latency
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="font-mono text-2xl" style={{ color: "var(--text-primary)" }}>
                          {stats.latency_p99_ms != null ? `${stats.latency_p99_ms} ms` : "—"}
                        </span>
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          p99 latency
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="font-mono text-2xl" style={{ color: "var(--text-primary)" }}>
                          {formatMttr(stats.mttr_seconds)}
                        </span>
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          MTTR ({stats.incident_count} incident{stats.incident_count === 1 ? "" : "s"})
                        </span>
                      </div>
                    </div>
                    <p className="mt-3 text-xs" style={{ color: "var(--text-secondary)" }}>
                      Based on {stats.total_checks} check{stats.total_checks === 1 ? "" : "s"} in this window.
                    </p>
                  </>
                );
              })()}
            </section>

            <section className="mt-6 rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <h2 className="text-lg font-semibold">Latency</h2>
              <div className="mt-4 flex flex-col items-stretch gap-6 md:flex-row md:items-start">
                <LatencyGauge value={selectedLatest?.latency_ms ?? null} size="md" />
                <div className="min-w-0 flex-1">
                  <LatencyChart checks={selectedChecks} />
                </div>
              </div>
            </section>

            <section className="mt-6 rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <h2 className="text-lg font-semibold">Timing breakdown</h2>
              <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                Latest check, {formatTimestamp(selectedLatest?.checked_at)}
              </p>
              <div className="mt-4">
                <TimingWaterfall check={selectedLatest} />
              </div>
            </section>

            <section className="mt-6 rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <h2 className="text-lg font-semibold">Uptime</h2>
              <div className="mt-4">
                <UptimeHeatmap checks={selectedChecks} />
              </div>
            </section>

            {/* Incidents and TLS certificate are read as documentation, not instrument panels
                (a short list and a couple of lines of text, not a dense visual module) — a
                divider instead of the full bordered surface used above keeps the page's boldness
                on the actual data-dense panels (chart, waterfall, heatmap) rather than framing
                every section identically regardless of what it holds. */}
            <section className="mt-10 border-t pt-6" style={{ borderColor: "var(--border)" }}>
              <h2 className="text-lg font-semibold">Incidents</h2>
              <div className="mt-4">
                <IncidentTimeline checks={selectedChecks} />
              </div>
            </section>

            <section className="mt-8 border-t pt-6" style={{ borderColor: "var(--border)" }}>
              <h2 className="text-lg font-semibold">TLS certificate</h2>
              <div className="mt-4">
                {selectedLatest?.tls_cert_expires_at ? (
                  <div className="flex flex-col gap-1">
                    <div
                      className="font-mono text-lg"
                      style={{
                        color:
                          selectedLatest.tls_cert_days_remaining != null && selectedLatest.tls_cert_days_remaining <= 0
                            ? "var(--signal-down)"
                            : selectedLatest.tls_cert_days_remaining != null && selectedLatest.tls_cert_days_remaining <= 14
                              ? "var(--signal-warning)"
                              : "var(--signal-up)",
                      }}
                    >
                      {selectedLatest.tls_cert_days_remaining != null && selectedLatest.tls_cert_days_remaining <= 0
                        ? "Expired"
                        : `${selectedLatest.tls_cert_days_remaining} days remaining`}
                    </div>
                    <div className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                      Expires {formatTimestamp(selectedLatest.tls_cert_expires_at)}
                    </div>
                    {selectedLatest.tls_cert_issuer && (
                      <div className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                        {selectedLatest.tls_cert_issuer}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    No certificate data (plain http, or no successful check yet).
                  </p>
                )}
              </div>
            </section>
          </>
        )}

        {error && (
          <p className="mt-6 text-sm" style={{ color: "var(--signal-down)" }}>
            {error}
          </p>
        )}
      </main>

      <TargetSettingsModal
        open={settingsOpen}
        onOpenChange={handleSettingsOpenChange}
        targetId={Number(targetId)}
        onSaved={handleSettingsSaved}
        onAuthFailed={() => router.replace("/login")}
      />
    </>
  );
}
