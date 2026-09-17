import { cn } from "@/lib/utils";

// A single pulsing placeholder block — the one shape every skeleton on this page composes
// from. Motion is an opacity pulse, not a gradient sweep: this app's only established motion
// primitive is opacity (SignalLight's dot flip, LatencyGauge's needle sweep both work this
// way), so a shimmer here would introduce a second, unrelated animation technique for no real
// benefit. Wrapped in the same `prefers-reduced-motion: no-preference` gate every other
// animated rule in globals.css uses (see `.skeleton-pulse`) — collapses to a static muted
// block, not a spinning/moving one, under reduced motion.
//
// Fill color: --border, not --bg-surface-raised. Both are already-locked tokens, but
// --bg-surface-raised sits only one small step above the --bg-surface background most rows
// render on (see globals.css) — confirmed via a real screenshot that a skeleton filled with it
// was nearly invisible, not just theoretically low-contrast. --border is the next token up and
// reads as a clear, distinct block while staying inside the locked palette (no new color).
export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      aria-hidden="true"
      className={cn("skeleton-pulse rounded-sm", className)}
      style={{ background: "var(--border)", ...style }}
    />
  );
}

// Shaped like SignalLight's own housing (rounded-rect, same width/height per size — see
// signal-light.tsx's SIZE_PX) so a loading row's silhouette doesn't jump once real data
// replaces it. Deliberately not the real SignalLight component rendered in some placeholder
// state: a skeleton is a "this hasn't loaded yet" signal, not a real app state, and reusing
// SignalLight would conflate the two (its "pending" state already means something specific —
// a region with no check yet — which isn't what's happening while the page itself is loading).
const SIGNAL_LIGHT_SIZE_PX: Record<"sm" | "md" | "lg", { width: number; height: number }> = {
  sm: { width: 14, height: 38 },
  md: { width: 20, height: 54 },
  lg: { width: 28, height: 76 },
};

export function SignalLightSkeleton({ size = "sm" }: { size?: "sm" | "md" | "lg" }) {
  const { width, height } = SIGNAL_LIGHT_SIZE_PX[size];
  return <Skeleton className="rounded-[3px]" style={{ width, height }} />;
}

// Shaped like LatencyGauge's own footprint (see latency-gauge.tsx's SIZE_PX + aspect ratio) —
// a plain rounded block standing in for the arc+needle artwork, not a traced outline of it.
// Replicating the exact arc geometry in a placeholder would be effort spent on a shape no one
// looks at for more than a second; matching the bounding box is enough to keep the layout
// stable once the real gauge mounts.
const LATENCY_GAUGE_SIZE_PX: Record<"sm" | "md" | "lg", number> = { sm: 90, md: 140, lg: 190 };
const LATENCY_GAUGE_ASPECT = 170 / 220;

export function LatencyGaugeSkeleton({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const width = LATENCY_GAUGE_SIZE_PX[size];
  return (
    <span className="inline-flex flex-col items-center gap-2">
      <Skeleton className="rounded-full" style={{ width, height: width * LATENCY_GAUGE_ASPECT }} />
      <Skeleton className="h-4 w-12" />
    </span>
  );
}

// Matches LatencyChart's fixed 260px wrapper height (components/latency-chart.tsx).
export function LatencyChartSkeleton() {
  return <Skeleton className="w-full" style={{ height: 260 }} />;
}

// Matches TimingWaterfall's h-7 bar (components/timing-waterfall.tsx).
export function TimingWaterfallSkeleton() {
  return <Skeleton className="h-7 w-full rounded border" style={{ borderColor: "var(--border)" }} />;
}

// A loose grid of CELL_PX squares approximating UptimeHeatmap's real grid
// (components/uptime-heatmap.tsx) — a fixed count standing in for "however many days," since
// the real count depends on data that hasn't loaded yet.
const HEATMAP_CELL_PX = 12;

export function UptimeHeatmapSkeleton() {
  return (
    <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(auto-fill, ${HEATMAP_CELL_PX}px)` }}>
      {Array.from({ length: 90 }).map((_, i) => (
        <Skeleton
          key={i}
          className="rounded-[var(--radius-sm)]"
          style={{ width: HEATMAP_CELL_PX, height: HEATMAP_CELL_PX }}
        />
      ))}
    </div>
  );
}
