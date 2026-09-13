"use client";

import { useEffect, useState } from "react";
import { SignalLight, type SignalState } from "@/components/signal-light";
import { LatencyGauge } from "@/components/latency-gauge";

// Scratch verification route for the bespoke primitives built in this prompt — not linked from
// anywhere in the app. DELETE THIS ROUTE before Phase 3's wrap-up/verification prompt; it's
// kept around through 3.5/3.6 as a visual reference while those pages get built.

const STATES: SignalState[] = ["up", "degraded", "down", "pending"];
const SIZES = ["sm", "md", "lg"] as const;
const GAUGE_VALUES: (number | null)[] = [0, 100, 200, 400, 800, 1200, 2000, null];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default function ComponentDevPage() {
  const [cycleIndex, setCycleIndex] = useState(0);
  const [sweepValue, setSweepValue] = useState(0);

  // Live demo: cycles the signal light through every state and sweeps the gauge needle across
  // its full range on a timer, so the opacity-flip and needle-sweep transitions actually fire
  // (a static grid alone only proves each end state renders correctly, not that the CSS
  // transition wired to it does anything).
  useEffect(() => {
    const stateTimer = setInterval(() => {
      setCycleIndex((i) => (i + 1) % STATES.length);
    }, 1800);
    const sweepTimer = setInterval(() => {
      setSweepValue((v) => (v >= 2000 ? 0 : v + 250));
    }, 500);
    return () => {
      clearInterval(stateTimer);
      clearInterval(sweepTimer);
    };
  }, []);

  return (
    <main className="font-sans" style={{ color: "var(--text-primary)" }}>
      <h1 className="mb-2 text-2xl font-semibold">Component dev scratch page</h1>
      <p className="mb-8 font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
        Not part of the app — verification only. Delete before Phase 3 wraps up.
      </p>

      <Section title="SignalLight — every state × size">
        <div className="flex flex-col gap-6">
          {SIZES.map((size) => (
            <div key={size} className="flex items-center gap-8">
              <span className="w-10 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                {size}
              </span>
              {STATES.map((state) => (
                <div key={state} className="flex flex-col items-center gap-2">
                  <SignalLight state={state} size={size} />
                  <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                    {state}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Section>

      <Section title="SignalLight — with label (showLabel)">
        <div className="flex flex-wrap gap-8">
          {STATES.map((state) => (
            <SignalLight key={state} state={state} size="md" showLabel />
          ))}
        </div>
      </Section>

      <Section title="SignalLight — live flip demo (cycles every 1.8s)">
        <SignalLight state={STATES[cycleIndex]} size="lg" showLabel />
      </Section>

      <Section title="LatencyGauge — across its full range (goodMs=200, warnMs=800, maxMs=2000)">
        <div className="flex flex-wrap items-end gap-8">
          {GAUGE_VALUES.map((v, i) => (
            <div key={i} className="flex flex-col items-center gap-1">
              <LatencyGauge value={v} />
              <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                {v == null ? "null" : v}
              </span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="LatencyGauge — sizes (value=350ms)">
        <div className="flex flex-wrap items-end gap-8">
          {SIZES.map((size) => (
            <div key={size} className="flex flex-col items-center gap-1">
              <LatencyGauge value={350} size={size} />
              <span className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                {size}
              </span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="LatencyGauge — live sweep demo (0→2000ms, loops)">
        <LatencyGauge value={sweepValue} size="lg" />
      </Section>
    </main>
  );
}
