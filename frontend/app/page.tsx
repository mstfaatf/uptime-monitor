"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/site-header";
import { HeroPanel } from "@/components/hero-panel";
import { RegionBadge } from "@/components/region-badge";
import { SignalLight } from "@/components/signal-light";
import { Button } from "@/components/ui/button";
import { apiJson } from "@/lib/api";
import { useAuthStatus } from "@/lib/use-auth-status";

const CHECK_PHASES = ["DNS", "TCP", "TLS", "TTFB"];

const PER_CHECK_ITEMS = [
  "Status code and latency",
  "DNS, TCP, TLS, and time-to-first-byte, each timed on its own",
  "TLS certificate issuer and days remaining until it expires",
];

const PER_TARGET_ITEMS = [
  "Uptime over the last 24 hours, 7 days, and 30 days",
  "A day-by-day uptime heatmap",
  "An incident timeline with a start and end time for every outage",
];

function RegionMockupRow({ region, state }: { region: string; state: "up" | "degraded" }) {
  return (
    <div className="flex items-center gap-3">
      <RegionBadge region={region} />
      <SignalLight state={state} size="sm" showLabel />
    </div>
  );
}

export default function LandingPage() {
  const router = useRouter();
  const { authenticated, loading } = useAuthStatus();

  async function handleSignOut() {
    try {
      await apiJson("/auth/logout", { method: "POST" });
    } finally {
      router.refresh();
    }
  }

  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-5xl px-6 py-16">
        <div className="flex flex-col items-center gap-12 md:flex-row md:items-start md:justify-between">
          <div className="max-w-md">
            <h1 className="text-3xl font-semibold leading-tight">
              Uptime monitoring that shows its work.
            </h1>
            <p className="mt-4" style={{ color: "var(--text-secondary)" }}>
              Add the URLs you care about, and it checks them from more than one region on a
              schedule. Every check keeps a private, per-target history: status, latency, and
              exactly where in the request a slowdown happened.
            </p>
            <div className="mt-8 flex gap-3">
              {!loading && authenticated ? (
                <>
                  <Button asChild>
                    <Link href="/dashboard">See my dashboard</Link>
                  </Button>
                  <Button type="button" variant="outline" onClick={handleSignOut}>
                    Sign out
                  </Button>
                </>
              ) : (
                <>
                  <Button asChild>
                    <Link href="/register">Register</Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link href="/login">Log in</Link>
                  </Button>
                </>
              )}
            </div>
          </div>
          <HeroPanel />
        </div>

        <div className="mt-24 border-t pt-12" style={{ borderColor: "var(--border)" }}>
          <section>
            <h2 className="text-xl font-semibold">How a check works</h2>
            <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
              On its schedule, the worker resolves the target's DNS, opens a TCP connection,
              negotiates TLS if the URL is HTTPS, and times how long the first byte takes to
              come back. Each of those four phases gets its own number instead of being folded
              into a single response time. A single failed check doesn't mark a target down
              right away: retries back off with some random jitter mixed in, so one bad request
              doesn't trigger a false alarm.
            </p>
            <div
              className="mt-5 flex items-center gap-3 font-mono text-sm"
              style={{ color: "var(--text-secondary)" }}
            >
              {CHECK_PHASES.map((phase, i) => (
                <span key={phase} className="flex items-center gap-3">
                  <span>{phase}</span>
                  {i < CHECK_PHASES.length - 1 && <span aria-hidden="true">→</span>}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-16">
            <h2 className="text-xl font-semibold">What gets measured</h2>
            <div className="mt-4 grid gap-10 md:grid-cols-2">
              <div>
                <h3 className="font-medium">Per check</h3>
                <ul className="mt-2 flex flex-col gap-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {PER_CHECK_ITEMS.map((item) => (
                    <li key={item} className="list-disc pl-0.5" style={{ marginLeft: "1.1em" }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="font-medium">Per target, over time</h3>
                <ul className="mt-2 flex flex-col gap-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {PER_TARGET_ITEMS.map((item) => (
                    <li key={item} className="list-disc pl-0.5" style={{ marginLeft: "1.1em" }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          <section className="mt-16">
            <h2 className="text-xl font-semibold">Multiple regions, independently</h2>
            <div className="mt-4 flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
              <p className="max-w-md" style={{ color: "var(--text-secondary)" }}>
                Checks run from more than one region, each on its own schedule. If one region is
                slow or can't reach a target and another can, you see both results instead of a
                single number that hides which region actually has the problem.
              </p>
              <div
                className="flex flex-col gap-3 rounded border p-4"
                style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
              >
                <RegionMockupRow region="local" state="up" />
                <RegionMockupRow region="eu-west" state="degraded" />
                <p className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                  Illustrative reading
                </p>
              </div>
            </div>
          </section>

          <section className="mt-16">
            <h2 className="text-xl font-semibold">Private by default</h2>
            <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
              Your targets and their history are yours. There's no page anywhere listing what
              anyone else is watching.
            </p>
          </section>
        </div>

        <div className="mt-20 border-t pt-12" style={{ borderColor: "var(--border)" }}>
          <h2 className="text-xl font-semibold">Built with</h2>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            The frontend is Next.js and TypeScript. The API is FastAPI with async SQLAlchemy and
            Alembic migrations. The worker that actually performs the checks is a Python asyncio
            service built on httpx. All of it reads and writes the same PostgreSQL database.
          </p>
        </div>
      </main>
      <footer className="mx-auto max-w-5xl px-6 py-10 font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
        <a
          href="https://github.com/mstfaatf/uptime-monitor"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
        >
          Source on GitHub
        </a>
      </footer>
    </>
  );
}
