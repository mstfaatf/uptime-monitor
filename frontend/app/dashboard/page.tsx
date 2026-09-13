"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { API_BASE, apiFetch, apiJson } from "@/lib/api";
import { SignalLight, SIGNAL_STATE_LABELS, type SignalState } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LATENCY_WARN_MS, CERT_EXPIRY_WARN_DAYS } from "@/lib/thresholds";

type LatestCheck = {
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
};

// Keyed by region — see backend/routers/targets.py's TargetStatusResponse (since prompt 2.6).
// A target with no checks yet in any region reports an empty object, not null.
type TargetStatusRow = {
  id: number;
  url: string;
  name: string | null;
  created_at: string;
  latest_checks: Record<string, LatestCheck>;
};

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "—";
  }
}

function isValidUrl(s: string): boolean {
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

// The locked degraded-state contract, applied per region: a region that hasn't reported yet
// is "pending"; a failed check is "down"; a successful check that's slow or has a
// soon-to-expire cert is "degraded"; everything else is "up". See lib/thresholds.ts.
function deriveState(check: LatestCheck | undefined): SignalState {
  if (!check || check.checked_at == null) return "pending";
  if (!check.is_up) return "down";
  const slow = check.latency_ms != null && check.latency_ms > LATENCY_WARN_MS;
  const certExpiringSoon =
    check.tls_cert_days_remaining != null && check.tls_cert_days_remaining <= CERT_EXPIRY_WARN_DAYS;
  return slow || certExpiringSoon ? "degraded" : "up";
}

// A real-time state change is worth interrupting the user for even if they're not looking at
// the row that changed — that's the whole point of a toast here, as opposed to the row's own
// SignalLight flip, which only helps if they're already looking at it.
function notifyTransition(target: TargetStatusRow, region: string, from: SignalState, to: SignalState) {
  const label = target.name || target.url;
  const description = `${region} — ${SIGNAL_STATE_LABELS[from]} → ${SIGNAL_STATE_LABELS[to]}`;
  if (to === "down") {
    toast.error(label, { description });
  } else if (to === "degraded") {
    toast.warning(label, { description });
  } else if (to === "up") {
    toast.success(label, { description });
  } else {
    toast(label, { description });
  }
}

function RegionBadge({ region }: { region: string }) {
  return (
    <span
      className="rounded border px-1.5 py-0.5 font-mono text-xs"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
    >
      {region}
    </span>
  );
}

// Only down/degraded latency gets an accent color, matching the LatencyGauge's own zone
// coloring (lib/thresholds.ts) — an "up" reading stays the default text color so color
// reads as a signal worth noticing, not decoration applied to every number on the page.
function latencyColor(state: SignalState): string {
  if (state === "down") return "var(--signal-down)";
  if (state === "degraded") return "var(--signal-warning)";
  if (state === "pending") return "var(--signal-pending-text)";
  return "var(--text-primary)";
}

export default function DashboardPage() {
  const router = useRouter();
  const [items, setItems] = useState<TargetStatusRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authFailed, setAuthFailed] = useState(false);

  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState("");

  const [live, setLive] = useState(false);

  // The one deliberate motion moment on this page: rows light up top-to-bottom once on initial
  // load, then stay revealed for the rest of the session (including rows added later) — never
  // a per-row hover effect, never scroll-triggered.
  const [revealedCount, setRevealedCount] = useState(0);
  const [revealComplete, setRevealComplete] = useState(false);

  // Tracks the last known state per "targetId:region", so an incoming SSE push can be compared
  // against what we actually knew before — not re-derived from nothing — to tell a real
  // transition (up -> down) from just a fresh timestamp on an unchanged state. Seeded once
  // after initial load (see the effect below), not on every render.
  const prevStatesRef = useRef<Record<string, SignalState>>({});

  const loadStatus = useCallback(async () => {
    setError("");
    try {
      const statusRes = await apiFetch("/targets/status");
      if (statusRes.status === 401) {
        setAuthFailed(true);
        return;
      }
      if (statusRes.ok) {
        const data = (await statusRes.json()) as TargetStatusRow[];
        setItems(data);
        return;
      }
      if (statusRes.status === 404) {
        const targetsRes = await apiFetch("/targets");
        if (targetsRes.status === 401) {
          setAuthFailed(true);
          return;
        }
        if (!targetsRes.ok) throw new Error("Failed to load targets");
        const targets = (await targetsRes.json()) as { id: number; url: string; name: string | null; created_at: string }[];
        setItems(
          targets.map((t) => ({
            ...t,
            latest_checks: {},
          }))
        );
        return;
      }
      throw new Error(`Status ${statusRes.status}`);
    } catch (err) {
      const res = await apiFetch("/auth/me").catch(() => null);
      if (res?.status === 401) setAuthFailed(true);
      else setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadStatus();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadStatus]);

  useEffect(() => {
    if (authFailed) router.replace("/login");
  }, [authFailed, router]);

  useEffect(() => {
    if (loading || items.length === 0 || revealComplete) return;
    const prefersReducedMotion =
      typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      setRevealComplete(true);
      return;
    }
    let i = 0;
    const total = items.length;
    const id = setInterval(() => {
      i += 1;
      setRevealedCount(i);
      if (i >= total) {
        clearInterval(id);
        setRevealComplete(true);
      }
    }, 90);
    return () => clearInterval(id);
    // Deliberately only depends on `loading`: this sequence should fire once, right after the
    // initial load, not re-run every time `items` changes (SSE updates, add/delete).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  useEffect(() => {
    if (loading) return;
    // Seed the transition-tracking baseline from whatever the initial load returned, exactly
    // once — so the first SSE push compares against real prior state instead of nothing (which
    // would otherwise either toast a false "transition" from undefined, or never toast at all).
    const next: Record<string, SignalState> = {};
    for (const item of items) {
      for (const [region, check] of Object.entries(item.latest_checks)) {
        next[`${item.id}:${region}`] = deriveState(check);
      }
    }
    prevStatesRef.current = next;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // Real-time push: once the initial poll has confirmed we're authenticated, open an SSE
  // subscription for check-result updates on our own targets. The browser's EventSource
  // auto-reconnects on its own after a drop (with backoff), so no manual retry loop is needed
  // here; withCredentials is required since the API is on a different origin in dev and the
  // session lives in an HttpOnly cookie, not anything JS can attach itself. Each event carries
  // the target's full latest_checks map (every region, not just the one that changed — see
  // backend/realtime.py), so replacing the whole row is correct and never loses another
  // region's data.
  useEffect(() => {
    if (loading || authFailed) return;

    const es = new EventSource(`${API_BASE}/targets/stream`, { withCredentials: true });

    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as { type: string; target: TargetStatusRow };
        if (message.type !== "check_update") return;

        // Compare each region's new state against what we last knew, and toast on a genuine
        // transition — only when there was a real prior state to transition from (the first
        // reading for a region is "new data," not a "change" worth interrupting anyone for).
        for (const [region, check] of Object.entries(message.target.latest_checks)) {
          const key = `${message.target.id}:${region}`;
          const newState = deriveState(check);
          const prevState = prevStatesRef.current[key];
          if (prevState && prevState !== newState) {
            notifyTransition(message.target, region, prevState, newState);
          }
          prevStatesRef.current[key] = newState;
        }

        setItems((prev) =>
          prev.map((item) => (item.id === message.target.id ? message.target : item))
        );
      } catch {
        // Ignore malformed/unrecognized messages rather than breaking the whole subscription.
      }
    };

    return () => {
      es.close();
      setLive(false);
    };
  }, [loading, authFailed]);

  async function handleLogout() {
    try {
      await apiJson("/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch {
      router.replace("/login");
    }
  }

  async function handleAddTarget(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    const rawUrl = url.trim();
    if (!rawUrl) {
      setFormError("URL is required.");
      return;
    }
    if (!isValidUrl(rawUrl)) {
      setFormError("Please enter a valid http or https URL.");
      return;
    }
    setSubmitting(true);
    try {
      await apiJson("/targets", {
        method: "POST",
        body: JSON.stringify({ url: rawUrl, name: name.trim() || undefined }),
      });
      setUrl("");
      setName("");
      await loadStatus();
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes("401") || err.message.includes("Not authenticated")) {
          router.replace("/login");
          return;
        }
        setFormError(err.message);
      } else {
        setFormError("Network error. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    setDeleteError("");
    setDeletingId(id);
    try {
      const res = await apiFetch(`/targets/${id}`, { method: "DELETE" });
      if (res.status === 401) {
        router.replace("/login");
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = typeof data.detail === "string" ? data.detail : "Delete failed.";
        setDeleteError(msg);
        return;
      }
      await loadStatus();
    } catch {
      setDeleteError("Network error. Try again.");
    } finally {
      setDeletingId(null);
    }
  }

  if (authFailed) return null;

  // Flatten every (target, region) pair that has a check yet, for the summary strip. Targets
  // are deliberately never collapsed into one boolean per the Phase 2 design — this counts
  // per-region results, not per-target.
  const regionEntries = items.flatMap((item) =>
    Object.entries(item.latest_checks).map(([region, check]) => ({
      state: deriveState(check),
      latencyMs: check.latency_ms,
    }))
  );
  const pendingTargetsWithNoRegions = items.filter((i) => Object.keys(i.latest_checks).length === 0).length;
  const counts = { up: 0, degraded: 0, down: 0, pending: pendingTargetsWithNoRegions };
  for (const e of regionEntries) counts[e.state]++;
  const latencies = regionEntries.map((e) => e.latencyMs).filter((v): v is number => v != null);
  const avgLatency = latencies.length > 0 ? latencies.reduce((a, b) => a + b, 0) / latencies.length : null;

  return (
    <>
      <header className="border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <SignalLight state="up" size="sm" />
            <span className="font-semibold">Uptime Monitor</span>
          </Link>
          <div className="flex items-center gap-6">
            <span
              className="font-mono text-xs"
              title={live ? "Live updates connected" : "Live updates disconnected — retrying"}
              style={{ color: live ? "var(--signal-up)" : "var(--signal-pending-text)" }}
            >
              ● {live ? "live" : "reconnecting…"}
            </span>
            <Link href="/settings" className="font-mono text-sm hover:underline" style={{ color: "var(--text-secondary)" }}>
              Settings
            </Link>
            <Button type="button" variant="outline" size="sm" onClick={handleLogout}>
              Log out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold">Dashboard</h1>

        {!loading && items.length > 0 && (
          <div
            className="mt-6 flex flex-wrap items-center gap-8 rounded border p-4"
            style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
          >
            <div className="flex flex-col">
              <span className="font-mono text-2xl" style={{ color: "var(--text-primary)" }}>
                {items.length}
              </span>
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                targets
              </span>
            </div>
            <div className="flex items-center gap-5">
              <div className="flex items-center gap-2">
                <SignalLight state="up" size="sm" />
                <span className="font-mono text-sm" style={{ color: "var(--signal-up)" }}>
                  {counts.up}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SignalLight state="degraded" size="sm" />
                <span className="font-mono text-sm" style={{ color: "var(--signal-warning)" }}>
                  {counts.degraded}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SignalLight state="down" size="sm" />
                <span className="font-mono text-sm" style={{ color: "var(--signal-down)" }}>
                  {counts.down}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SignalLight state="pending" size="sm" />
                <span className="font-mono text-sm" style={{ color: "var(--signal-pending-text)" }}>
                  {counts.pending}
                </span>
              </div>
            </div>
            <div className="ml-auto flex flex-col items-center">
              <LatencyGauge value={avgLatency} size="sm" />
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                avg latency
              </span>
            </div>
          </div>
        )}

        {!loading && items.length > 0 && (
          <div
            className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-sm border px-4 py-2"
            style={{ borderColor: "var(--border)" }}
          >
            {(["up", "degraded", "down", "pending"] as SignalState[]).map((state) => (
              <div key={state} className="flex items-center gap-2">
                <SignalLight state={state} size="sm" />
                <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                  {SIGNAL_STATE_LABELS[state]}
                </span>
              </div>
            ))}
          </div>
        )}

        <section
          className="mt-8 max-w-md rounded border p-5"
          style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
        >
          <h2 className="font-semibold">Add target</h2>
          <form onSubmit={handleAddTarget} className="mt-4 flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="target-url">URL (required)</Label>
              <Input
                id="target-url"
                type="url"
                placeholder="https://example.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={submitting}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="target-name">Name (optional)</Label>
              <Input
                id="target-name"
                type="text"
                placeholder="My site"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={submitting}
              />
            </div>
            {formError && (
              <p className="text-sm" style={{ color: "var(--signal-down)" }}>
                {formError}
              </p>
            )}
            <Button type="submit" disabled={submitting} className="self-start">
              {submitting ? "Adding…" : "Add target"}
            </Button>
          </form>
        </section>

        {deleteError && (
          <p className="mt-4 text-sm" style={{ color: "var(--signal-down)" }}>
            {deleteError}
          </p>
        )}
        {error && (
          <p className="mt-4 text-sm" style={{ color: "var(--signal-down)" }}>
            {error}
          </p>
        )}

        <div className="mt-8">
          {loading ? (
            <p style={{ color: "var(--text-secondary)" }}>Loading…</p>
          ) : items.length === 0 ? (
            <div
              className="flex flex-col items-center gap-3 rounded border border-dashed p-12 text-center"
              style={{ borderColor: "var(--border)" }}
            >
              <SignalLight state="pending" size="lg" />
              <p className="font-semibold">No targets yet</p>
              <p className="max-w-sm text-sm" style={{ color: "var(--text-secondary)" }}>
                Add a URL above and it'll show up here once the worker picks it up.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {items.map((row, index) => {
                const revealed = revealComplete || index < revealedCount;
                const regions = Object.entries(row.latest_checks).sort(([a], [b]) => a.localeCompare(b));

                return (
                  <div
                    key={row.id}
                    className="rounded border p-4"
                    style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <a
                          href={row.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-medium hover:underline"
                        >
                          {row.name || row.url}
                        </a>
                        {row.name && (
                          <span
                            className="block font-mono text-xs"
                            style={{ color: "var(--text-secondary)" }}
                          >
                            {row.url}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button asChild variant="outline" size="sm">
                          <Link href={`/dashboard/${row.id}`}>View details</Link>
                        </Button>
                        <Button
                          type="button"
                          variant="destructive"
                          size="sm"
                          onClick={() => handleDelete(row.id)}
                          disabled={deletingId !== null}
                          aria-label={`Delete ${row.name || row.url}`}
                        >
                          {deletingId === row.id ? "…" : "Delete"}
                        </Button>
                      </div>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
                      {regions.length === 0 ? (
                        <div className="flex items-center gap-2">
                          <SignalLight state="pending" size="sm" showLabel />
                        </div>
                      ) : (
                        regions.map(([region, check]) => {
                          const state = revealed ? deriveState(check) : "pending";
                          return (
                            <div key={region} className="flex items-center gap-3">
                              <RegionBadge region={region} />
                              <SignalLight state={state} size="sm" showLabel />
                              <span className="font-mono text-sm" style={{ color: latencyColor(state) }}>
                                {check.latency_ms != null ? `${check.latency_ms} ms` : "—"}
                              </span>
                              <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                                {formatTimestamp(check.checked_at)}
                              </span>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
