"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { API_BASE, apiFetch, apiJson } from "@/lib/api";
import { SignalLight, SIGNAL_STATE_LABELS, type SignalState } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";
import { Skeleton, SignalLightSkeleton, LatencyGaugeSkeleton } from "@/components/skeleton";
import { EmptyState } from "@/components/empty-state";
import { QuickAddTargetModal, type QuickAddCreatedTarget } from "@/components/quick-add-target-modal";
import { TargetFilterBar, type SortKey } from "@/components/target-filter-bar";
import { TagManagerModal } from "@/components/tag-manager-modal";
import { TargetTagChips } from "@/components/target-tag-chips";
import { Button } from "@/components/ui/button";
import { LATENCY_WARN_MS, CERT_EXPIRY_WARN_DAYS, CONSECUTIVE_FAILURES_DOWN_THRESHOLD } from "@/lib/thresholds";
import type { Tag } from "@/lib/types";

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
  consecutive_failures?: number | null;
};

// Keyed by region — see backend/routers/targets.py's TargetStatusResponse (since prompt 2.6).
// A target with no checks yet in any region reports an empty object, not null. `tags` isn't
// part of that response at all (see loadStatus below) — merged in client-side from GET /targets
// instead, since carrying tags through the SSE push/poll hot path for something that changes
// rarely wasn't worth the extra join on every single check-update notification.
type TargetStatusRow = {
  id: number;
  url: string;
  name: string | null;
  created_at: string;
  latest_checks: Record<string, LatestCheck>;
  tags: Tag[];
};

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "—";
  }
}

// The locked degraded-state contract, applied per region (extended in prompt 4.4): a region
// that hasn't reported yet is "pending"; a failed check is "degraded" until
// consecutive_failures crosses the threshold (still retrying, not confirmed down yet), then
// "down" — authoritative and evaluated first, latency/cert thresholds never apply to a failed
// check; a successful check that's slow or has a soon-to-expire cert is "degraded"; everything
// else is "up". See lib/thresholds.ts.
function deriveState(check: LatestCheck | undefined): SignalState {
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

// A real-time state change is worth interrupting the user for even if they're not looking at
// the row that changed — that's the whole point of a toast here, as opposed to the row's own
// SignalLight flip, which only helps if they're already looking at it.
function notifyTransition(
  target: Pick<TargetStatusRow, "name" | "url">,
  region: string,
  from: SignalState,
  to: SignalState
) {
  const label = target.name || target.url;
  const description = `${region}: ${SIGNAL_STATE_LABELS[from]} → ${SIGNAL_STATE_LABELS[to]}`;
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

// Same 99.9/99 breakpoints as the detail page's own slaColor (app/dashboard/[id]/page.tsx) —
// one consistent "what counts as healthy/degraded/bad uptime" convention across the app,
// rather than two independently-chosen thresholds that could silently drift apart.
function uptimeColor(pct: number | null): string {
  if (pct == null) return "var(--signal-pending-text)";
  if (pct >= 99.9) return "var(--signal-up)";
  if (pct >= 99) return "var(--signal-warning)";
  return "var(--signal-down)";
}

export default function DashboardPage() {
  const router = useRouter();
  const [items, setItems] = useState<TargetStatusRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authFailed, setAuthFailed] = useState(false);

  const [quickAddOpen, setQuickAddOpen] = useState(false);
  // Which button opened the modal, so focus can be explicitly returned to it on close — see
  // handleQuickAddOpenChange below for why this can't be left to Radix's own default behavior.
  const quickAddTriggerRef = useRef<HTMLButtonElement | null>(null);

  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState("");

  // Filter/search/sort bar state — pure view state, never mutates `items` itself. The visible
  // row list is recomputed fresh from `items` + this state on every render (see visibleItems
  // below), so a live SSE update to `items` always flows straight through the current filter/
  // sort with no separate "filtered copy" to keep in sync and no risk of it going stale.
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SignalState | "all">("all");
  const [regionFilter, setRegionFilter] = useState("all");
  const [tagFilter, setTagFilter] = useState<number | "all">("all");
  const [sortBy, setSortBy] = useState<SortKey>("default");

  // All of the user's tags (not just the ones currently attached to something) — used by the
  // filter bar's own Tag dropdown and by each row's "attach a tag" picker. Loaded once
  // alongside targets/status (see loadStatus) and kept in sync afterward by the tag manager
  // modal's own callbacks, rather than refetched on every mutation.
  const [allTags, setAllTags] = useState<Tag[]>([]);

  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const tagManagerTriggerRef = useRef<HTMLButtonElement | null>(null);

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

  // GET /targets is the authoritative source of which targets exist (id/url/name/tags) — it
  // never reports partial/missing data the way a defensive fallback would need to guess at.
  // GET /targets/status supplies the live latest_checks overlay on top of that; if it's ever
  // unavailable for some reason, every target still renders correctly as "pending" rather than
  // not rendering at all.
  const loadStatus = useCallback(async () => {
    setError("");
    try {
      const [targetsRes, tagsRes] = await Promise.all([apiFetch("/targets"), apiFetch("/tags")]);
      if (targetsRes.status === 401 || tagsRes.status === 401) {
        setAuthFailed(true);
        return;
      }
      if (!targetsRes.ok) throw new Error(`Status ${targetsRes.status}`);
      const targets = (await targetsRes.json()) as {
        id: number;
        url: string;
        name: string | null;
        created_at: string;
        tags: Tag[];
      }[];
      if (tagsRes.ok) setAllTags((await tagsRes.json()) as Tag[]);

      const statusRes = await apiFetch("/targets/status");
      if (statusRes.status === 401) {
        setAuthFailed(true);
        return;
      }
      let checksById = new Map<number, Record<string, LatestCheck>>();
      if (statusRes.ok) {
        const data = (await statusRes.json()) as TargetStatusRow[];
        checksById = new Map(data.map((d) => [d.id, d.latest_checks]));
      }

      setItems(targets.map((t) => ({ ...t, latest_checks: checksById.get(t.id) ?? {} })));
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
        // The real push payload never includes `tags` (see TargetStatusRow's own comment) —
        // typed without it here so the compiler can't paper over the merge below forgetting
        // that.
        const message = JSON.parse(event.data) as { type: string; target: Omit<TargetStatusRow, "tags"> };
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

        // message.target never carries `tags` (see TargetStatusRow's own comment on why) — a
        // bare replace here would silently wipe a target's tags on every single live update.
        setItems((prev) =>
          prev.map((item) =>
            item.id === message.target.id ? { ...item, ...message.target, tags: item.tags } : item
          )
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

  // The new row shows up immediately (no full-list refetch, no page navigation) with
  // latest_checks empty — it renders "pending" exactly like any other not-yet-checked target
  // until the worker actually claims and checks it, at which point the existing SSE subscription
  // above (already wired to update `items` by id for any target) picks it up and updates the row
  // live, with zero new wiring needed for that part. Prepended, matching GET /targets/status'
  // own newest-first ordering.
  function handleTargetCreated(target: QuickAddCreatedTarget) {
    setItems((prev) => [{ ...target, latest_checks: {}, tags: [] }, ...prev]);
  }

  // Two different buttons can open the quick-add modal (the toolbar button next to the h1, and
  // the empty state's own CTA) — this remembers whichever one actually triggered it.
  function handleOpenQuickAdd(e: React.MouseEvent<HTMLButtonElement>) {
    quickAddTriggerRef.current = e.currentTarget;
    setQuickAddOpen(true);
  }

  // Confirmed empirically (not assumed): Radix Dialog's usual "return focus to the trigger on
  // close" behavior only reliably fires for a <DialogTrigger>-wrapped element inside the
  // Dialog's own component tree. This modal is controlled and opened by a plain external
  // <Button> the Dialog never sees as its trigger, and without this, closing it (Escape or a
  // successful submit) silently leaves focus on <body> instead of somewhere visible/usable —
  // a real keyboard-accessibility regression, not a cosmetic one. Restoring it explicitly here
  // closes that gap for every way the modal can close.
  function handleQuickAddOpenChange(next: boolean) {
    setQuickAddOpen(next);
    if (!next) {
      requestAnimationFrame(() => quickAddTriggerRef.current?.focus());
    }
  }

  function handleOpenTagManager() {
    setTagManagerOpen(true);
  }

  // Same explicit-focus-restore need as the quick-add modal above — the "Manage tags" button
  // is a plain external trigger too, not a <DialogTrigger>.
  function handleTagManagerOpenChange(next: boolean) {
    setTagManagerOpen(next);
    if (!next) {
      requestAnimationFrame(() => tagManagerTriggerRef.current?.focus());
    }
  }

  // Deleting a tag in the manager doesn't know which targets had it attached — strip it out of
  // every row's own `tags` list here instead, so a row's chips never show a tag that no longer
  // exists.
  function handleTagDeletedGlobally(tagId: number) {
    setItems((prev) => prev.map((item) => ({ ...item, tags: item.tags.filter((t) => t.id !== tagId) })));
    setTagFilter((prev) => (prev === tagId ? "all" : prev));
  }

  // Same reasoning as handleTagDeletedGlobally: the manager only knows tags in the abstract,
  // not which target rows already carry a copy of one — a rename has to be pushed into every
  // row's own `tags` list explicitly, or an already-attached chip would keep showing the old
  // name until the next full reload.
  function handleTagRenamedGlobally(tag: Tag) {
    setItems((prev) =>
      prev.map((item) => ({
        ...item,
        tags: item.tags.map((t) => (t.id === tag.id ? tag : t)),
      }))
    );
  }

  function handleTagAttached(targetId: number, tag: Tag) {
    setItems((prev) =>
      prev.map((item) =>
        item.id === targetId && !item.tags.some((t) => t.id === tag.id)
          ? { ...item, tags: [...item.tags, tag].sort((a, b) => a.name.localeCompare(b.name)) }
          : item
      )
    );
  }

  function handleTagDetached(targetId: number, tagId: number) {
    setItems((prev) =>
      prev.map((item) => (item.id === targetId ? { ...item, tags: item.tags.filter((t) => t.id !== tagId) } : item))
    );
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
      isUp: check.is_up,
    }))
  );
  const pendingTargetsWithNoRegions = items.filter((i) => Object.keys(i.latest_checks).length === 0).length;
  const counts = { up: 0, degraded: 0, down: 0, pending: pendingTargetsWithNoRegions };
  for (const e of regionEntries) counts[e.state]++;
  const latencies = regionEntries.map((e) => e.latencyMs).filter((v): v is number => v != null);
  const avgLatency = latencies.length > 0 ? latencies.reduce((a, b) => a + b, 0) / latencies.length : null;

  // Aggregate uptime %: the fraction of (target, region) pairs that have reported at least one
  // check and are currently is_up — averaged flat across every pair, not per-target (a target
  // with 2 regions and a target with 1 region each contribute their own pairs equally, rather
  // than being weighted as "one target" apiece). This is a deliberate choice given the Phase 2
  // independent-per-region design: there's no single "is this target up" boolean anywhere else
  // in the app, so an aggregate figure has to pick a base rate to average over, and per-pair is
  // the one that matches how every other count on this strip is already computed (regionEntries
  // itself). A pair with no check yet (pending) is excluded from both the numerator and
  // denominator — it hasn't reported anything to average in either direction. This is
  // deliberately a live snapshot ("what fraction of monitored surface is up right now"), not a
  // time-windowed SLA % — that already exists per-region on the detail page
  // (app/dashboard/[id]/page.tsx's computeSla), computed from real historical check history
  // rather than one instant's latest_checks payload, which is all this list page ever fetches.
  const reportedEntries = regionEntries; // every entry here already has a real check, see above
  const upEntries = reportedEntries.filter((e) => e.isUp).length;
  const aggregateUptimePercent =
    reportedEntries.length > 0 ? (upEntries / reportedEntries.length) * 100 : null;

  const degradedOrDownCount = regionEntries.filter((e) => e.state === "degraded" || e.state === "down").length;
  const anyDown = regionEntries.some((e) => e.state === "down");

  // Every region name currently seen across any target, for the filter bar's Region dropdown —
  // computed fresh from live data rather than a fixed list, so a newly-active region shows up
  // on its own the moment anything reports from it.
  const allRegions = Array.from(new Set(items.flatMap((item) => Object.keys(item.latest_checks)))).sort();

  const hasActiveFilters =
    search.trim() !== "" || statusFilter !== "all" || regionFilter !== "all" || tagFilter !== "all";

  function resetFilters() {
    setSearch("");
    setStatusFilter("all");
    setRegionFilter("all");
    setTagFilter("all");
  }

  // Filtering/sorting is recomputed fresh from `items` on every render — never a separate
  // "filtered items" state array kept in sync imperatively. That's what makes this correct
  // under live SSE updates for free: `items` changing (a check landing, a tag being attached)
  // re-renders the page, which re-runs this block against the new data, so a row updates in
  // place, disappears, or reappears exactly according to the current filter with no special
  // "reconcile the filtered copy" logic anywhere.
  type VisibleRow = TargetStatusRow & { visibleRegions: [string, LatestCheck][] };
  const visibleItems: VisibleRow[] = items
    .filter((item) => {
      if (tagFilter !== "all" && !item.tags.some((t) => t.id === tagFilter)) return false;
      const q = search.trim().toLowerCase();
      if (q && !((item.name ?? "").toLowerCase().includes(q) || item.url.toLowerCase().includes(q))) return false;
      return true;
    })
    .map((item) => {
      const entries = Object.entries(item.latest_checks);
      const visibleRegions = entries.filter(
        ([region, check]) =>
          (regionFilter === "all" || region === regionFilter) &&
          (statusFilter === "all" || deriveState(check) === statusFilter)
      );
      return { item, entries, visibleRegions };
    })
    .filter(({ entries, visibleRegions }) => {
      // A target with zero regions at all (nothing has checked it yet) only "belongs" to a
      // status/region combination of "all regions" + ("all statuses" or specifically
      // "pending") — it doesn't have a region to match a specific region filter against, and
      // its only honest status is pending.
      if (entries.length === 0) {
        return regionFilter === "all" && (statusFilter === "all" || statusFilter === "pending");
      }
      return visibleRegions.length > 0;
    })
    .map(({ item, visibleRegions }) => ({ ...item, visibleRegions }));

  function severityRank(state: SignalState): number {
    return { down: 3, degraded: 2, pending: 1, up: 0 }[state];
  }
  function targetWorstState(row: TargetStatusRow): SignalState {
    const states = Object.values(row.latest_checks).map(deriveState);
    if (states.length === 0) return "pending";
    return states.reduce((worst, s) => (severityRank(s) > severityRank(worst) ? s : worst), states[0]);
  }
  function targetAvgLatency(row: TargetStatusRow): number | null {
    const vals = Object.values(row.latest_checks)
      .map((c) => c.latency_ms)
      .filter((v): v is number => v != null);
    return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  }
  function targetLastChecked(row: TargetStatusRow): number | null {
    const vals = Object.values(row.latest_checks)
      .map((c) => (c.checked_at ? new Date(c.checked_at).getTime() : null))
      .filter((v): v is number => v != null);
    return vals.length > 0 ? Math.max(...vals) : null;
  }
  // Nulls (no reading yet) always sort last, regardless of direction, for both numeric sorts —
  // "unknown" isn't meaningfully "worse" or "better" than a real number, it's just not
  // comparable, so it belongs at the edge rather than wherever a bare numeric comparison would
  // otherwise place it.
  function sortRows(rows: VisibleRow[]): VisibleRow[] {
    const sorted = [...rows];
    if (sortBy === "name") {
      sorted.sort((a, b) => (a.name || a.url).localeCompare(b.name || b.url));
    } else if (sortBy === "status") {
      // Worst-first: the point of sorting by status is almost always "show me what's broken",
      // matching this dashboard's own severity language (down > degraded > pending > up).
      sorted.sort((a, b) => severityRank(targetWorstState(b)) - severityRank(targetWorstState(a)));
    } else if (sortBy === "latency") {
      sorted.sort((a, b) => {
        const la = targetAvgLatency(a);
        const lb = targetAvgLatency(b);
        if (la == null) return lb == null ? 0 : 1;
        if (lb == null) return -1;
        return lb - la; // slowest first — the readings worth noticing
      });
    } else if (sortBy === "lastChecked") {
      sorted.sort((a, b) => {
        const ta = targetLastChecked(a);
        const tb = targetLastChecked(b);
        if (ta == null) return tb == null ? 0 : 1;
        if (tb == null) return -1;
        return tb - ta; // most recently checked first
      });
    }
    return sorted;
  }
  const sortedVisibleItems = sortRows(visibleItems);

  return (
    <>
      <header className="border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-2 px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <SignalLight state="up" size="sm" />
            <span className="font-semibold">Uptime Monitor</span>
          </Link>
          <div className="flex items-center gap-6">
            <span
              className="font-mono text-xs"
              title={live ? "Live updates connected" : "Live updates disconnected, retrying"}
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
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <Button type="button" onClick={handleOpenQuickAdd}>
            Add target
          </Button>
        </div>

        {/* Persistent banner: only rendered while at least one region is degraded/down, gone
            the moment nothing is — this is a status alert, not a standing UI element. Severity
            (border/text color, which SignalLight state is shown) escalates to --signal-down the
            moment any region is actually down, not just degraded, matching the two-tier
            severity already used everywhere else (summary-strip counts, row latency color). */}
        {!loading && degradedOrDownCount > 0 && (
          <div
            role="status"
            className="mt-6 flex items-center gap-3 rounded border px-4 py-3"
            style={{
              borderColor: anyDown ? "var(--signal-down)" : "var(--signal-warning)",
              background: "var(--bg-surface)",
            }}
          >
            <SignalLight state={anyDown ? "down" : "degraded"} size="sm" />
            <span
              className="text-sm font-medium"
              style={{ color: anyDown ? "var(--signal-down)" : "var(--signal-warning)" }}
            >
              {degradedOrDownCount} {degradedOrDownCount === 1 ? "region" : "regions"} reporting
              degraded/down
            </span>
          </div>
        )}

        {loading && (
          <div
            className="mt-6 flex flex-wrap items-center gap-8 rounded border p-4"
            style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
          >
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-7 w-10" />
              <Skeleton className="h-3 w-14" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-7 w-16" />
              <Skeleton className="h-3 w-20" />
            </div>
            <div className="flex items-center gap-5">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <SignalLightSkeleton size="sm" />
                  <Skeleton className="h-4 w-4" />
                </div>
              ))}
            </div>
            <div className="ml-auto">
              <LatencyGaugeSkeleton size="sm" />
            </div>
          </div>
        )}

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
            <div className="flex flex-col">
              <span
                className="font-mono text-2xl"
                style={{ color: uptimeColor(aggregateUptimePercent) }}
                title="Percentage of target-region pairs currently reporting up. A live snapshot across every monitored region, not a time-windowed SLA. See a target's detail page for windowed SLA % per region."
              >
                {aggregateUptimePercent != null ? `${aggregateUptimePercent.toFixed(1)}%` : "—"}
              </span>
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                uptime (live)
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

        {!loading && items.length > 0 && (
          <TargetFilterBar
            search={search}
            onSearchChange={setSearch}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            regionFilter={regionFilter}
            onRegionFilterChange={setRegionFilter}
            regions={allRegions}
            tagFilter={tagFilter}
            onTagFilterChange={setTagFilter}
            tags={allTags}
            sortBy={sortBy}
            onSortByChange={setSortBy}
            onManageTags={handleOpenTagManager}
            manageTagsButtonRef={tagManagerTriggerRef}
            onReset={resetFilters}
            hasActiveFilters={hasActiveFilters}
          />
        )}

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
            <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading targets">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="rounded border p-4"
                  style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <Skeleton className="h-5 w-48" />
                    <div className="flex items-center gap-2">
                      <Skeleton className="h-8 w-24 rounded" />
                      <Skeleton className="h-8 w-16 rounded" />
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
                    {Array.from({ length: 2 }).map((__, j) => (
                      <div key={j} className="flex items-center gap-3">
                        <Skeleton className="h-5 w-14 rounded" />
                        <SignalLightSkeleton size="sm" />
                        <Skeleton className="h-4 w-12" />
                        <Skeleton className="h-3 w-28" />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              size="lg"
              title="Nothing to monitor yet. Add a URL to get started."
              action={
                <Button type="button" onClick={handleOpenQuickAdd}>
                  Add target
                </Button>
              }
            />
          ) : sortedVisibleItems.length === 0 ? (
            <EmptyState
              size="md"
              title="No targets match the current filters"
              description="Try a different status, region, or tag, or clear the search."
              action={
                <Button type="button" variant="outline" onClick={resetFilters}>
                  Reset filters
                </Button>
              }
            />
          ) : (
            <div className="flex flex-col gap-4">
              {sortedVisibleItems.map((row, index) => {
                const revealed = revealComplete || index < revealedCount;
                const regions = [...row.visibleRegions].sort(([a], [b]) => a.localeCompare(b));

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

                    <div className="mt-3">
                      <TargetTagChips
                        targetId={row.id}
                        tags={row.tags}
                        allTags={allTags}
                        onAttached={(tag) => handleTagAttached(row.id, tag)}
                        onDetached={(tagId) => handleTagDetached(row.id, tagId)}
                        onAuthFailed={() => router.replace("/login")}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>

      <QuickAddTargetModal
        open={quickAddOpen}
        onOpenChange={handleQuickAddOpenChange}
        onCreated={handleTargetCreated}
        onAuthFailed={() => router.replace("/login")}
      />

      <TagManagerModal
        open={tagManagerOpen}
        onOpenChange={handleTagManagerOpenChange}
        onTagsChanged={setAllTags}
        onTagDeleted={handleTagDeletedGlobally}
        onTagRenamed={handleTagRenamedGlobally}
        onAuthFailed={() => router.replace("/login")}
      />
    </>
  );
}
