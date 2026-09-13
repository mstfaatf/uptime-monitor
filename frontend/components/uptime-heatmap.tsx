import { deriveState } from "@/lib/status";
import type { CheckHistoryEntry } from "@/lib/types";

// Hand-rolled CSS grid, not a calendar-heatmap library (see the 3.1 report): dedicated
// heatmap packages default to soft rounded cells, fighting the instrument-panel look. Cells
// are laid out in simple chronological (row-major) order rather than true Sun-Sat calendar
// alignment — a deliberate simplification, since aligning to real weekdays adds real
// complexity for no benefit on what is, in this project's dev data, a history of at most a
// few days.
const DAYS = 90;
const CELL_PX = 12;
const GAP_PX = 3;

function dayKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function buildDayBuckets(checks: CheckHistoryEntry[], days: number): Map<string, CheckHistoryEntry[]> {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const buckets = new Map<string, CheckHistoryEntry[]>();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    buckets.set(dayKey(d), []);
  }
  for (const c of checks) {
    if (!c.checked_at) continue;
    const key = c.checked_at.slice(0, 10);
    buckets.get(key)?.push(c);
  }
  return buckets;
}

function dayColor(dayChecks: CheckHistoryEntry[]): string {
  if (dayChecks.length === 0) return "var(--signal-pending)";
  if (dayChecks.some((c) => deriveState(c) === "down")) return "var(--signal-down)";
  if (dayChecks.some((c) => deriveState(c) === "degraded")) return "var(--signal-warning)";
  return "var(--signal-up)";
}

const LEGEND = [
  { label: "Up", color: "var(--signal-up)" },
  { label: "Degraded", color: "var(--signal-warning)" },
  { label: "Down", color: "var(--signal-down)" },
  { label: "No data", color: "var(--signal-pending)" },
];

export function UptimeHeatmap({ checks }: { checks: CheckHistoryEntry[] }) {
  const buckets = buildDayBuckets(checks, DAYS);
  const days = Array.from(buckets.entries());

  return (
    <div>
      <div
        className="grid"
        style={{
          gridTemplateColumns: `repeat(auto-fill, ${CELL_PX}px)`,
          gap: GAP_PX,
        }}
      >
        {days.map(([key, dayChecks]) => (
          <div
            key={key}
            title={`${key}: ${dayChecks.length === 0 ? "no data" : `${dayChecks.length} check${dayChecks.length === 1 ? "" : "s"}`}`}
            style={{
              width: CELL_PX,
              height: CELL_PX,
              borderRadius: "var(--radius-sm)",
              background: dayColor(dayChecks),
            }}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-4">
        {LEGEND.map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span
              className="inline-block"
              style={{ width: CELL_PX, height: CELL_PX, borderRadius: "var(--radius-sm)", background: l.color }}
            />
            <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              {l.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
