"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { SignalLight } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";
import { LatencyChart } from "@/components/latency-chart";
import { TimingWaterfall } from "@/components/timing-waterfall";
import { UptimeHeatmap } from "@/components/uptime-heatmap";
import { IncidentTimeline } from "@/components/incident-timeline";
import { RegionBadge } from "@/components/region-badge";
import { Button } from "@/components/ui/button";
import { deriveState, formatTimestamp } from "@/lib/status";
import type { TargetDetail, CheckHistoryEntry } from "@/lib/types";

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

  if (authFailed) return null;

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p style={{ color: "var(--text-secondary)" }}>Loading…</p>
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
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">{detail.name || detail.url}</h1>
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
          <Button type="button" variant="outline" disabled title="CSV/PDF export is coming in a future update.">
            Export (coming soon)
          </Button>
        </div>

        {regions.length === 0 ? (
          <p className="mt-8 text-sm" style={{ color: "var(--text-secondary)" }}>
            No checks recorded yet for this target.
          </p>
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
            <div className="mt-8 flex gap-2">
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
    </>
  );
}
