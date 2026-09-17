import { EmptyState } from "@/components/empty-state";
import type { LatestCheck } from "@/lib/types";

// Design approach (stated in the prompt-3.6 report): rather than inventing four new brand
// colors for DNS/TCP/TLS/TTFB, the bar uses ONE token (--text-primary) at four fixed opacity
// steps to distinguish phases — stays inside the locked palette entirely, and the descending
// intensity reads as a sequence (earliest phase most prominent) without implying severity the
// way the signal colors would. Segments are proportional to each phase's real ms, separated by
// a 1px --bg-base seam for a crisp, sharp boundary (no rounded/blurred segment edges). A phase
// the check never reached is null, not 0 — it's omitted from the bar entirely, not rendered as
// a zero-width sliver.
const PHASES = [
  { key: "dns_ms", label: "DNS" },
  { key: "tcp_ms", label: "TCP" },
  { key: "tls_ms", label: "TLS" },
  { key: "ttfb_ms", label: "TTFB" },
] as const;

const OPACITY_STEPS = [0.9, 0.7, 0.5, 0.3];

export function TimingWaterfall({ check }: { check: LatestCheck | null | undefined }) {
  const phases = PHASES.map((p, i) => ({
    ...p,
    ms: check?.[p.key] ?? null,
    opacity: OPACITY_STEPS[i],
  })).filter((p) => p.ms != null && p.ms > 0);

  if (!check || phases.length === 0) {
    return <EmptyState size="sm" title="Waiting on the first check" />;
  }

  return (
    <div>
      <div className="flex h-7 overflow-hidden rounded border" style={{ borderColor: "var(--border)" }}>
        {phases.map((p) => (
          <div
            key={p.key}
            title={`${p.label}: ${p.ms}ms`}
            style={{
              flexGrow: p.ms ?? 0,
              flexBasis: 0,
              background: "var(--text-primary)",
              opacity: p.opacity,
              borderRight: "1px solid var(--bg-base)",
            }}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-4">
        {phases.map((p) => (
          <div key={p.key} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5"
              style={{ background: "var(--text-primary)", opacity: p.opacity }}
            />
            <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              {p.label}
            </span>
            <span className="font-mono text-xs" style={{ color: "var(--text-primary)" }}>
              {p.ms}ms
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
