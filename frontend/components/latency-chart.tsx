"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { EmptyState } from "@/components/empty-state";
import type { CheckHistoryEntry } from "@/lib/types";

function computeP95(latencies: number[]): number | null {
  if (latencies.length === 0) return null;
  const sorted = [...latencies].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1);
  return sorted[index];
}

export function LatencyChart({ checks }: { checks: CheckHistoryEntry[] }) {
  const points = checks
    .filter((c) => c.checked_at != null && c.latency_ms != null)
    .map((c) => ({ t: new Date(c.checked_at as string).getTime(), latency: c.latency_ms as number }));

  if (points.length === 0) {
    return <EmptyState size="sm" title="Waiting on the first check" />;
  }

  const p95 = computeP95(points.map((p) => p.latency));

  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          {/* Solid, fine-interval gridlines (no dasharray) for the graph-paper feel — Recharts'
              own examples usually dash these, which reads as a generic chart-library default. */}
          <CartesianGrid stroke="var(--border)" vertical={true} />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            stroke="var(--text-secondary)"
            tick={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            stroke="var(--text-secondary)"
            tick={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
            tickLine={false}
            width={44}
            unit="ms"
          />
          {p95 != null && (
            <ReferenceLine
              y={p95}
              stroke="var(--signal-warning)"
              strokeDasharray="4 4"
              label={{ value: `p95 ${p95}ms`, position: "insideTopRight", fill: "var(--signal-warning)", fontSize: 11 }}
            />
          )}
          {/* type="linear", not the smoothed "monotone" default most Recharts examples use —
              sharp, non-smoothed lines per the locked telemetry/oscilloscope spec. */}
          <Line type="linear" dataKey="latency" stroke="var(--signal-up)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
