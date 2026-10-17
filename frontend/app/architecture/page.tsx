import { SiteHeader } from "@/components/site-header";
import { SignalLight } from "@/components/signal-light";
import { RegionBadge } from "@/components/region-badge";
import { CellTowerIllustration, DataCenterIllustration } from "@/components/network-glyphs";
import { SectionHeading } from "@/components/section-heading";

function DiagramBox({
  title,
  caption,
  illustration,
  className,
}: {
  title: string;
  caption?: string;
  illustration?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center gap-2 rounded border px-5 py-4 text-center ${className ?? ""}`}
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      {illustration}
      <p className="font-medium">{title}</p>
      {caption && (
        <p className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
          {caption}
        </p>
      )}
    </div>
  );
}

function FlowArrow({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-1" aria-hidden="true">
      <span className="text-lg" style={{ color: "var(--text-secondary)" }}>
        ↓
      </span>
      {label && (
        <span className="max-w-xs text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
          {label}
        </span>
      )}
    </div>
  );
}

interface Step {
  title: string;
  body: string;
  tone?: "up" | "down";
}

function FlowStep({ step, isLast }: { step: Step; isLast: boolean }) {
  const titleColor =
    step.tone === "down" ? "var(--signal-down)" : step.tone === "up" ? "var(--signal-up)" : "var(--text-primary)";
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <span
          className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ background: step.tone === "down" ? "var(--signal-down)" : "var(--signal-up)" }}
          aria-hidden="true"
        />
        {!isLast && <span className="mt-1 w-px flex-1" style={{ background: "var(--border)" }} aria-hidden="true" />}
      </div>
      <div className={isLast ? "pb-0" : "pb-6"}>
        <p className="font-medium" style={{ color: titleColor }}>
          {step.title}
        </p>
        <p className="mt-1 max-w-xl text-sm" style={{ color: "var(--text-secondary)" }}>
          {step.body}
        </p>
      </div>
    </div>
  );
}

interface TimelineRow {
  at: string;
  what: string;
}

const BURST_TIMELINE: TimelineRow[] = [
  { at: "-10s", what: "The backend opens its LISTEN connection and replays any check it hasn't handled yet." },
  { at: "0s", what: "Both regions open a fresh pool, claim everything due (or due within the next 60s), check it, and write the results." },
  { at: "~+1s", what: "The last check commits. Each one has already been pushed to any open dashboard and evaluated for alerts." },
  { at: "+60s", what: "The backend closes LISTEN, unless a batch is still retrying a fresh failure." },
  { at: "up to +90s", what: "Extra passes run only to retry a target on its first or second consecutive failure, then the pools close. LISTEN stays open until 30s after the cap." },
  { at: "+5 min", what: "With no connections left, the database suspends until the next batch or the next visitor." },
];

const CHECK_FLOW: Step[] = [
  {
    title: "A schedule row comes due",
    body: "In live mode a worker region looks for due targets every 5 seconds; in idle mode it looks at each 15-minute batch. Either way it claims its own due, unclaimed targets in one short transaction, then releases the lock immediately, before making any network request.",
  },
  {
    title: "The URL is validated",
    body: "Resolved and checked against the SSRF blocklist off the event loop, so one slow lookup can't stall every other in-flight check.",
    tone: "up",
  },
  {
    title: "Blocked: recorded as down",
    body: "A blocked hostname never reaches the network. It's written to the checks table as a real, honest down result with a clear reason, the same as any other failure.",
    tone: "down",
  },
  {
    title: "The request goes out",
    body: "The target's configured method, headers, and basic-auth credentials (if any) are sent on the request. Redirects are followed manually, one hop at a time.",
  },
  {
    title: "Redirect target blocked, or too many hops",
    body: "Each Location header is re-validated before it's followed, and headers/auth are dropped the moment a redirect crosses to a different host. Either failure closes the check as down rather than continuing.",
    tone: "down",
  },
  {
    title: "Timing and certificate captured",
    body: "DNS, TCP, TLS, and TTFB are each timed off the connection already open for the final response; the TLS certificate is read off the same handshake.",
  },
  {
    title: "Keyword match failed",
    body: "If the target requires or forbids a string in the response body and that condition doesn't hold, the check is still recorded as down, with its own distinct reason.",
    tone: "down",
  },
  {
    title: "Written, scheduled, and notified in one transaction",
    body: "The check row, the next due time (backoff on failure, normal or custom cadence on success), and a Postgres NOTIFY all commit together. A rolled-back attempt notifies nothing.",
  },
  {
    title: "Pushed to the browser",
    body: "The backend's listener resolves the notified target to its owner, evaluates downtime/cert-expiry alerts, and pushes the full result to that user's open dashboard, with no reload and no polling. A check that landed while the listener was closed is replayed the next time it opens, so its alerts still go out.",
    tone: "up",
  },
];

export default function ArchitecturePage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-5xl px-6 py-16">
        <h1 className="text-3xl font-semibold leading-tight">How it fits together</h1>
        <p className="mt-4 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Two worker regions, one shared database, a backend that pushes results to the
          dashboard as they land, and a frontend that never talks to Postgres directly. The
          whole system runs inside a serverless Postgres free tier by letting the database sleep
          whenever nobody is using the site. This is the map of how those pieces connect, how
          the checkers decide how often to run, and what happens end to end when a single check
          runs.
        </p>

        <section className="mt-16">
          <SectionHeading>System overview</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Each worker region only ever reads and writes its own region's rows. The two never
            talk to each other directly. They're connected only through the database, and from
            there, through whatever the backend chooses to push out.
          </p>

          <div className="mt-8 flex flex-col items-center">
            <div className="grid w-full max-w-2xl grid-cols-2 gap-4">
              <DiagramBox
                title="worker (us-east)"
                caption="asyncio + httpx + asyncpg"
                illustration={<CellTowerIllustration size={64} />}
              />
              <DiagramBox
                title="worker-eu-west"
                caption="same image, REGION=eu-west"
                illustration={<CellTowerIllustration size={64} />}
              />
            </div>
            <p className="mt-3 max-w-md text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              Each worker asks the backend whether anyone is watching, and picks live or idle
              mode from the answer
            </p>
            <FlowArrow label="INSERT checks, UPDATE schedule, NOTIFY: same transaction" />
            <DiagramBox
              title="Postgres (Neon)"
              caption="targets, checks, target_region_schedule, users, tags, webhooks, api_keys"
              illustration={<DataCenterIllustration size={92} />}
              className="w-full max-w-sm"
            />
            <FlowArrow label="NOTIFY checks_inserted: direct, non-pooled connection" />
            <div className="w-full max-w-sm rounded border px-5 py-4" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <p className="text-center font-medium">backend (Railway)</p>
              <p className="mt-1 text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                FastAPI, cookie or API-key auth
              </p>
              <div className="mt-3 rounded border px-3 py-2" style={{ borderColor: "var(--border)" }}>
                <p className="text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                  realtime.py: LISTEN held around each batch and while someone is watching,
                  catches up on every open, resolves target to owner, publishes to that user's
                  queue only
                </p>
              </div>
            </div>
            <FlowArrow label="SSE: check_update events" />
            <DiagramBox title="frontend (Vercel)" caption="Next.js dashboard" className="w-full max-w-sm" />
            <p className="mt-3 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
              ↑ REST, cookie or API-key auth, one short database connection per request
            </p>
          </div>

          <p className="mx-auto mt-6 max-w-2xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Two kinds of database connection matter here. Each ordinary request opens one
            connection through Neon's pooled endpoint and closes it when the request ends. The
            LISTEN session uses Neon's direct endpoint instead: a pooled connection's underlying
            backend can be swapped between queries, so a NOTIFY sent while a different backend
            is attached would never be delivered.
          </p>
        </section>

        <section className="mt-16">
          <SectionHeading>Live mode and idle mode</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            The database only accrues compute while it's awake, and it suspends after five idle
            minutes. So the checkers run in one of two modes, chosen by whether anyone is using
            the site. The backend counts the site as watched while a live dashboard is open, or
            for 5 minutes after any signed-in request. Requests made with an API key don't count.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div className="rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <div className="flex items-center gap-3">
                <SignalLight state="up" size="sm" />
                <p className="font-medium" style={{ color: "var(--signal-up)" }}>
                  Live mode
                </p>
              </div>
              <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
                Someone is watching. Each worker holds a connection pool and looks for due
                targets every 5 seconds, so every target is checked on its own interval (5
                minutes by default) and each result reaches the dashboard as it lands. Workers
                switch in within about 15 seconds of someone signing in, and switch back out
                five to six minutes after the last activity.
              </p>
            </div>
            <div className="rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <div className="flex items-center gap-3">
                <SignalLight state="pending" size="sm" />
                <p className="font-medium">Idle mode</p>
              </div>
              <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
                Nobody is watching. Workers hold no database connections at all. Both regions
                wake on the same clock-aligned boundary every 15 minutes, check everything in
                one batch, and close their connections again, so the database sleeps in between.
                An outage can take up to 15 minutes to be noticed in this mode.
              </p>
            </div>
          </div>

          <h3 className="mt-10 text-lg font-medium">One idle batch, from the database's point of view</h3>
          <div className="mt-4 overflow-x-auto rounded border" style={{ borderColor: "var(--border)" }}>
            <table className="w-full min-w-[420px] text-sm">
              <tbody>
                {BURST_TIMELINE.map((row) => (
                  <tr key={row.at} className="border-b last:border-b-0" style={{ borderColor: "var(--border)" }}>
                    <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-xs" style={{ color: "var(--signal-up)" }}>
                      {row.at}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-secondary)" }}>
                      {row.what}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 max-w-2xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The LISTEN connection follows the same rhythm. It opens shortly before each batch
            and whenever someone starts watching, and every time it opens it replays any check
            above the last one it handled, through the same handler a live notification uses.
            Nothing is lost while it's closed, including across a restart. Measured in
            production, the whole system uses about 2.2 compute-unit-hours of database time a
            day.
          </p>
        </section>

        <section className="mt-16">
          <SectionHeading>Deployment targets</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Every service reads its configuration from environment variables only. Nothing is
            hardcoded per environment.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <div className="rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <p className="font-medium">Vercel</p>
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                The frontend. Builds from the repository on every push to the main branch.
              </p>
            </div>
            <div className="rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <p className="font-medium">Railway</p>
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                Three services: the backend API, and one worker instance per region. The
                worker's image is identical across both; only its region setting differs.
              </p>
            </div>
            <div className="rounded border p-5" style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}>
              <p className="font-medium">Neon</p>
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                Serverless Postgres that sleeps after five idle minutes. A pooled endpoint for
                ordinary traffic, a direct one for the backend's listener and for schema
                migrations.
              </p>
            </div>
          </div>
        </section>

        <section className="mt-16">
          <SectionHeading>A check, end to end</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            What actually happens between a target becoming due and a browser updating with no
            reload. Every branch that closes a check as down is marked in red, the same color a
            failed check already renders everywhere else in this app.
          </p>
          <div className="mt-8">
            {CHECK_FLOW.map((step, i) => (
              <FlowStep key={step.title} step={step} isLast={i === CHECK_FLOW.length - 1} />
            ))}
          </div>
        </section>

        <section className="mt-16">
          <SectionHeading>Multi-region coordination, visually</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Scheduling state lives per target, per region, in its own table. Each tower below is
            a genuinely independent worker instance, claiming and rescheduling only its own
            region's rows, and each one's signal light reflects a real, separately observed
            result for the same target, not a shared or averaged one.
          </p>
          <div className="mt-8 flex flex-col items-center gap-8 sm:flex-row sm:items-start sm:justify-center">
            <div className="flex flex-col items-center gap-3">
              <CellTowerIllustration size={100} />
              <RegionBadge region="us-east" />
              <SignalLight state="up" size="sm" showLabel />
            </div>
            <div className="flex flex-col items-center gap-3">
              <CellTowerIllustration size={100} />
              <RegionBadge region="eu-west" />
              <SignalLight state="degraded" size="sm" showLabel />
            </div>
          </div>
          <p className="mx-auto mt-6 max-w-md text-center font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
            Illustrative reading: same target, two regions, two honest results
          </p>

          <div className="mt-8 overflow-x-auto rounded border" style={{ borderColor: "var(--border)" }}>
            <table className="w-full min-w-[420px] font-mono text-xs">
              <thead>
                <tr style={{ color: "var(--text-secondary)" }}>
                  {["target_id", "region", "next_check_at", "consecutive_failures", "claimed_at"].map((col) => (
                    <th key={col} className="border-b px-3 py-2 text-left font-normal" style={{ borderColor: "var(--border)" }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="px-3 py-2">42</td>
                  <td className="px-3 py-2">us-east</td>
                  <td className="px-3 py-2">09:05:00</td>
                  <td className="px-3 py-2" style={{ color: "var(--signal-up)" }}>
                    0
                  </td>
                  <td className="px-3 py-2">null</td>
                </tr>
                <tr>
                  <td className="px-3 py-2">42</td>
                  <td className="px-3 py-2">eu-west</td>
                  <td className="px-3 py-2">09:01:30</td>
                  <td className="px-3 py-2" style={{ color: "var(--signal-warning)" }}>
                    2
                  </td>
                  <td className="px-3 py-2">null</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-2 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
            Same target, id 42, two independent schedule rows, one per region
          </p>

          <div className="mt-8 max-w-xl overflow-hidden rounded border" style={{ borderColor: "var(--border)" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/screenshots/dashboard.png"
              alt="Dashboard showing multiple targets, each with independent per-region status"
              className="w-full"
            />
          </div>
        </section>

        <p className="mt-16 max-w-2xl text-sm" style={{ color: "var(--text-secondary)" }}>
          The full write-up, including the file-by-file layout of each service, lives in{" "}
          <a
            href="https://github.com/mstfaatf/uptime-monitor/blob/main/ARCHITECTURE.md"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
            style={{ color: "var(--text-primary)" }}
          >
            ARCHITECTURE.md
          </a>{" "}
          on GitHub.
        </p>
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
