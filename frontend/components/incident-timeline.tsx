import { formatTimestamp } from "@/lib/status";
import type { CheckHistoryEntry } from "@/lib/types";

type Incident = {
  start: string;
  end: string | null; // null = still ongoing (most recent check in this region is still down)
  durationMs: number | null;
};

// Scans the ordered (oldest-first) check history for runs of consecutive is_up=false checks.
// A run's start is its first failing check's timestamp; its end is the next successful check
// after it, or null if the run hasn't recovered by the most recent check we have.
function computeIncidents(checks: CheckHistoryEntry[]): Incident[] {
  const incidents: Incident[] = [];
  let openStart: string | null = null;
  for (const c of checks) {
    if (!c.is_up && openStart === null && c.checked_at) {
      openStart = c.checked_at;
    } else if (c.is_up && openStart !== null && c.checked_at) {
      incidents.push({
        start: openStart,
        end: c.checked_at,
        durationMs: new Date(c.checked_at).getTime() - new Date(openStart).getTime(),
      });
      openStart = null;
    }
  }
  if (openStart !== null) {
    incidents.push({ start: openStart, end: null, durationMs: null });
  }
  return incidents.reverse(); // most recent first
}

function formatDuration(ms: number): string {
  const totalMinutes = Math.round(ms / 60000);
  if (totalMinutes < 60) return `${totalMinutes}m`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}

export function IncidentTimeline({ checks }: { checks: CheckHistoryEntry[] }) {
  if (checks.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        No checks recorded yet for this region.
      </p>
    );
  }

  const incidents = computeIncidents(checks);

  if (incidents.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--signal-up)" }}>
        No downtime recorded.
      </p>
    );
  }

  // The one place a numbered/ordered marker earns its place — this is a genuine chronological
  // sequence, not a feature list dressed up as one.
  return (
    <ol className="flex flex-col gap-3">
      {incidents.map((incident, i) => (
        <li key={incident.start} className="flex items-start gap-3">
          <span
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded border font-mono text-xs"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            {incidents.length - i}
          </span>
          <div>
            <div className="font-mono text-sm">
              <span style={{ color: "var(--signal-down)" }}>{formatTimestamp(incident.start)}</span>
              {" → "}
              {incident.end ? (
                <span style={{ color: "var(--text-primary)" }}>{formatTimestamp(incident.end)}</span>
              ) : (
                <span style={{ color: "var(--signal-down)" }}>ongoing</span>
              )}
            </div>
            <div className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              {incident.durationMs != null ? formatDuration(incident.durationMs) : "duration unknown"}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
