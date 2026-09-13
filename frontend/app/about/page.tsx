import { SiteHeader } from "@/components/site-header";

export default function AboutPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-2xl font-semibold">About</h1>
        <p className="mt-6" style={{ color: "var(--text-secondary)" }}>
          Uptime Monitor is a personal project built to go deeper on the networking side most
          monitoring tools abstract away: DNS, TCP, and TLS timing per check, certificate
          expiry, and multi-region checks with real coordination between worker instances
          rather than a single cron job. It's a private tool, and there's no public page listing
          what anyone else is watching.
        </p>
        <p className="mt-4" style={{ color: "var(--text-secondary)" }}>
          Built and documented end to end by Mustafa Atif as a portfolio project.
        </p>

        <h2 className="mt-10 text-lg font-semibold">Stack</h2>
        <p className="mt-2 font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
          Next.js, FastAPI, an async Python worker, and PostgreSQL.
        </p>

        <h2 className="mt-10 text-lg font-semibold">Source</h2>
        <p className="mt-2">
          <a
            href="https://github.com/mstfaatf/uptime-monitor"
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-sm hover:underline"
            style={{ color: "var(--text-primary)" }}
          >
            github.com/mstfaatf/uptime-monitor
          </a>
        </p>
      </main>
    </>
  );
}
