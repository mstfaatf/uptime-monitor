import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import {
  DataCenterGlyph,
  AntennaGlyph,
  RouterGlyph,
  SignalBarsGlyph,
  SignalPulseIllustration,
} from "@/components/network-glyphs";

const CHECK_PHASES = ["DNS", "TCP", "TLS", "TTFB"];

interface FeatureItem {
  title: string;
  body: string;
}

function FeatureGroup({
  glyph,
  heading,
  intro,
  items,
  screenshotSrc,
  screenshotAlt,
  extra,
}: {
  glyph?: React.ReactNode;
  heading: string;
  intro: string;
  items: FeatureItem[];
  screenshotSrc: string;
  screenshotAlt: string;
  extra?: React.ReactNode;
}) {
  return (
    <section className="mt-16">
      <div className="flex items-center gap-3">
        {glyph}
        <h2 className="text-xl font-semibold" style={{ color: "var(--signal-up)" }}>
          {heading}
        </h2>
      </div>
      <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
        {intro}
      </p>
      {extra}
      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        {items.map((item) => (
          <div key={item.title}>
            <h3 className="font-medium">{item.title}</h3>
            <p className="mt-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
              {item.body}
            </p>
          </div>
        ))}
      </div>
      <div className="mt-6 max-w-xl overflow-hidden rounded border" style={{ borderColor: "var(--border)" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={screenshotSrc} alt={screenshotAlt} className="w-full" />
      </div>
    </section>
  );
}

export default function FeaturesPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-5xl px-6 py-16">
        <h1 className="text-3xl font-semibold leading-tight">Everything that's actually built</h1>
        <p className="mt-4 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          A walkthrough of what this project does, grouped the way it was actually built: the
          security and ownership rules every request has to pass, the worker that does the
          real network-level checking, the coordination that lets two regions check
          independently without stepping on each other, the alerting and export layer, and the
          feature set on top of it all. See{" "}
          <Link href="/architecture" className="hover:underline" style={{ color: "var(--text-primary)" }}>
            Architecture
          </Link>{" "}
          for how the pieces fit together, or{" "}
          <Link href="/engineering" className="hover:underline" style={{ color: "var(--text-primary)" }}>
            Engineering
          </Link>{" "}
          for the reasoning behind the decisions below.
        </p>

        <FeatureGroup
          glyph={<DataCenterGlyph />}
          heading="Security & foundation"
          intro="Every request that touches a user's data goes through the same ownership and
            abuse-prevention rules, before any feature was built on top of them."
          screenshotSrc="/screenshots/settings.png"
          screenshotAlt="Settings page showing alert preferences, webhooks, API keys, and the account danger zone"
          items={[
            {
              title: "Ownership enforced on every endpoint",
              body: "Every query is filtered by the authenticated user's own id, and a target, tag, webhook, or key that belongs to someone else returns a plain 404, never a 403 that would confirm it exists at all.",
            },
            {
              title: "SSRF protection at two checkpoints",
              body: "A submitted URL is checked once at creation for fast feedback, then independently again on every worker check, including every hop of a redirect chain, so a hostname that starts safe and later resolves somewhere private is still caught.",
            },
            {
              title: "No insecure defaults",
              body: "The session secret and the credential-encryption key both have no fallback value: the app refuses to start rather than silently run with a known-weak default.",
            },
            {
              title: "Cookie-only sessions",
              body: "Authentication lives in an HTTP-only cookie, never in localStorage, so a script running on the page can't read or steal it.",
            },
            {
              title: "Rate limiting on every write",
              body: "Login, registration, password reset, and every resource-creation endpoint carry their own limits, with a separate, more generous budget for API-key traffic that never loosens the stricter ones.",
            },
            {
              title: "A real automated test suite",
              body: "362 tests across the backend and worker, run against a real Postgres database rather than a mocked one, covering the ownership rules above directly.",
            },
          ]}
        />

        <FeatureGroup
          heading="Worker & network observability"
          intro="The part of this project that goes deepest: checks don't just report up or down,
            they report exactly where time was spent getting an answer."
          screenshotSrc="/screenshots/target-detail.png"
          screenshotAlt="Target detail page showing per-region analytics, a latency chart, timing breakdown, uptime heatmap, and incident timeline"
          extra={
            <div
              className="mt-6 flex flex-col items-center gap-6 rounded border p-6 sm:flex-row sm:items-center sm:justify-between"
              style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
            >
              <SignalPulseIllustration size={110} />
              <div className="flex flex-col gap-2">
                <div
                  className="flex items-center gap-3 font-mono text-sm"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {CHECK_PHASES.map((phase, i) => (
                    <span key={phase} className="flex items-center gap-3">
                      <span>{phase}</span>
                      {i < CHECK_PHASES.length - 1 && <span aria-hidden="true">→</span>}
                    </span>
                  ))}
                </div>
                <p className="max-w-sm text-sm" style={{ color: "var(--text-secondary)" }}>
                  Each phase is timed on its own, off the same connection the check already
                  opened: no second request, no estimate.
                </p>
              </div>
            </div>
          }
          items={[
            {
              title: "A fully async worker",
              body: "Rewritten from a synchronous, sequential loop onto httpx.AsyncClient and asyncpg: a batch of due targets is checked concurrently, bounded by a semaphore, instead of one at a time.",
            },
            {
              title: "Per-target backoff with jitter",
              body: "A failing target retries on an exponential curve, capped and jittered so multiple targets that start failing together don't retry in perfect lockstep. A single success resets it immediately.",
            },
            {
              title: "DNS, TCP, TLS, and TTFB, each timed separately",
              body: "Captured off httpx's own low-level trace hooks on the connection the check is already making, not a second lookup or a guess.",
            },
            {
              title: "TLS certificate capture",
              body: "Expiry date and issuer, read straight off the same TLS handshake for every HTTPS target, with days-remaining computed at read time so it's never stale.",
            },
            {
              title: "Real-time push, not polling",
              body: "A check landing triggers a Postgres NOTIFY the instant it commits; the backend forwards it to that user's connected browser over Server-Sent Events. The dashboard has no polling loop anywhere.",
            },
          ]}
        />

        <FeatureGroup
          glyph={<AntennaGlyph />}
          heading="Multi-region coordination"
          intro="Two independent worker regions check every target on their own schedule against
            one shared database, without a message queue or a shared lock service between them."
          screenshotSrc="/screenshots/dashboard.png"
          screenshotAlt="Dashboard showing multiple targets, each with independent per-region status, latency, and tags"
          items={[
            {
              title: "Row-claiming, not a queue",
              body: "A short, self-releasing database transaction claims a due target before checking it, so two worker instances can never grab the same target at the same moment.",
            },
            {
              title: "Scheduling state per target, per region",
              body: "Each region tracks its own due time and its own failure streak independently, since reachability from one region genuinely doesn't imply anything about another.",
            },
            {
              title: "Results shown side by side, never collapsed",
              body: "There's no single 'is this target up' boolean anywhere. If one region is down and another isn't, both facts are visible at once, not averaged away.",
            },
            {
              title: "Proven under real contention",
              body: "Verified against genuinely concurrent worker processes, not just mocks: the smallest observed gap between two checks of the same target and region was consistent with two independent schedules, never a race.",
            },
          ]}
        />

        <FeatureGroup
          glyph={<RouterGlyph />}
          heading="Alerting & compliance export"
          intro="Downtime and certificate problems reach you without flooding your inbox, and
            every target's history can leave the app as a real report."
          screenshotSrc="/screenshots/settings.png"
          screenshotAlt="Settings page showing alert preferences and webhook configuration"
          items={[
            {
              title: "Downtime and recovery email",
              body: "Fires once on the transition into down, stays quiet while it's still down, and sends a separate recovery email the moment it comes back, with a cooldown that stops a flapping target from re-triggering too often.",
            },
            {
              title: "Certificate-expiry alerts",
              body: "Fires once a certificate enters its expiry window, re-reminds on a slower cadence while it stays unrenewed, and resets the moment a genuinely new certificate is seen.",
            },
            {
              title: "Webhooks alongside email",
              body: "Every alert type can also fire an HMAC-signed webhook, independently of whether email is enabled for that user. A receiver can verify the payload actually came from this app.",
            },
            {
              title: "Password reset by email",
              body: "A single-use, time-limited link, with a response that never reveals whether an email address is actually registered.",
            },
            {
              title: "CSV compliance export",
              body: "A summary of uptime and every incident, followed by the raw check history for a chosen region and date range: one file, readable as a report or as data.",
            },
            {
              title: "Bounded history",
              body: "Raw check rows older than the retention window are pruned automatically, by a background task that never competes with the scheduling it runs alongside.",
            },
          ]}
        />

        <FeatureGroup
          glyph={<SignalBarsGlyph />}
          heading="Configuring what and how to check"
          intro="Past the basic 'is this URL reachable,' a target can be shaped to match what's
            actually being monitored."
          screenshotSrc="/screenshots/target-settings-modal.png"
          screenshotAlt="Target settings modal showing request method, custom headers, basic auth, keyword match, and check interval fields"
          items={[
            {
              title: "Custom method, headers, and basic auth",
              body: "A target can be checked with GET, POST, or HEAD, carry custom request headers, and authenticate with HTTP Basic Auth, with the password encrypted at rest and never returned by any endpoint.",
            },
            {
              title: "Keyword / content monitoring",
              body: "Require or forbid a specific string in the response body, since a 200 status alone doesn't always mean the page rendered correctly.",
            },
            {
              title: "Pause, resume, and a custom interval",
              body: "Any target can be paused without deleting it, resumed with an immediate recheck, or given its own faster or slower check cadence than the default.",
            },
            {
              title: "Tags",
              body: "Free-form, per-account labels attached many-to-many, with dashboard filtering by tag.",
            },
            {
              title: "Windowed analytics",
              body: "Uptime percentage, p50/p95/p99 latency, and mean time to recovery, computed per region over 24 hours, 7, 30, or 90 days.",
            },
            {
              title: "Scoped API keys",
              body: "Read-only or full-access keys for programmatic use, hashed at rest, individually revocable, and structurally unable to create or revoke other keys, no matter their own scope.",
            },
          ]}
        />
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
