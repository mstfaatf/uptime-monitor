"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/site-header";
import { HeroPanel } from "@/components/hero-panel";
import { Button } from "@/components/ui/button";
import { apiJson } from "@/lib/api";
import { useAuthStatus } from "@/lib/use-auth-status";

const BENEFITS = [
  {
    title: "Down to the network layer",
    body: "Every check breaks a request into DNS, TCP, TLS, and time-to-first-byte, plus TLS certificate expiry — not just a single up/down flag.",
  },
  {
    title: "Multiple regions, independently",
    body: "Targets are checked from more than one region, and each region's result is shown on its own — nothing gets collapsed into one misleading status.",
  },
  {
    title: "Private by default",
    body: "Your targets and history are yours. There's no public page listing what anyone else is watching.",
  },
];

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
              Add the URLs you care about and watch them from multiple regions on a schedule.
              Every check keeps a private, per-target history — status, latency, and where in
              the request a slowdown actually happened.
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

        <div className="mt-24 grid gap-10 border-t pt-12 md:grid-cols-3" style={{ borderColor: "var(--border)" }}>
          {BENEFITS.map((b) => (
            <div key={b.title}>
              <h2 className="font-semibold">{b.title}</h2>
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                {b.body}
              </p>
            </div>
          ))}
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
