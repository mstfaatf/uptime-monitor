"use client";

import { useEffect, useState } from "react";
import { SignalLight, type SignalState } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";

const TIMING_SAMPLE = [
  { label: "DNS", ms: 12 },
  { label: "TCP", ms: 34 },
  { label: "TLS", ms: 58 },
  { label: "TTFB", ms: 71 },
];

// The landing page's one deliberate motion moment (per CLAUDE.md's locked motion spec — at
// most one across the auth/static pages): the hero's SignalLight starts pending and powers on
// to "up" shortly after mount, reusing SignalLight's own opacity-flip transition rather than
// any new animation code.
export function HeroPanel() {
  const [state, setState] = useState<SignalState>("pending");

  useEffect(() => {
    const t = setTimeout(() => setState("up"), 500);
    return () => clearTimeout(t);
  }, []);

  return (
    <div
      className="w-full max-w-sm rounded border p-6"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <div className="flex items-center gap-4">
        <SignalLight state={state} size="lg" showLabel />
      </div>
      <div className="mt-6 flex justify-center">
        <LatencyGauge value={180} size="md" />
      </div>
      <div className="mt-6 grid grid-cols-4 gap-2 border-t pt-4" style={{ borderColor: "var(--border)" }}>
        {TIMING_SAMPLE.map((t) => (
          <div key={t.label} className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              {t.label}
            </span>
            <span className="font-mono text-sm" style={{ color: "var(--text-primary)" }}>
              {t.ms}ms
            </span>
          </div>
        ))}
      </div>
      <p className="mt-4 text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
        Illustrative reading
      </p>
    </div>
  );
}
