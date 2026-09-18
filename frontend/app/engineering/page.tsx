import { SiteHeader } from "@/components/site-header";
import {
  RouterGlyph,
  AntennaGlyph,
  DataCenterGlyph,
  SignalBarsGlyph,
  TowerGlyph,
} from "@/components/network-glyphs";

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xl font-semibold" style={{ color: "var(--signal-up)" }}>
      {children}
    </h2>
  );
}

interface Decision {
  glyph: React.ReactNode;
  title: string;
  body: React.ReactNode;
}

function DecisionBlock({ decision }: { decision: Decision }) {
  return (
    <div className="mt-12 first:mt-8">
      <div className="flex items-center gap-3">
        {decision.glyph}
        <h3 className="text-lg font-medium">{decision.title}</h3>
      </div>
      <div className="mt-3 max-w-2xl space-y-3 text-sm" style={{ color: "var(--text-secondary)" }}>
        {decision.body}
      </div>
    </div>
  );
}

function StatCallout({ value, label, tone = "up" }: { value: string; label: string; tone?: "up" | "down" }) {
  return (
    <div
      className="flex flex-col items-center gap-1.5 rounded border px-4 py-5 text-center"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <span
        className="font-mono text-2xl font-semibold"
        style={{ color: tone === "down" ? "var(--signal-down)" : "var(--signal-up)" }}
      >
        {value}
      </span>
      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
        {label}
      </span>
    </div>
  );
}

interface Issue {
  title: string;
  body: string;
}

const ISSUES: Issue[] = [
  {
    title: "Real-time push went silent in production, with no error anywhere",
    body: "Checks landed correctly and a client was genuinely connected to the live-update stream the whole time, but the push never arrived. The cause: the database's pooled connection string doesn't reliably deliver a notification to a long-held listening session, since the pool can swap which physical connection is behind it between queries. Locally, the database has no pooling at all, so this never had a chance to show up until it was live. Fixed with a second, direct (non-pooled) connection string reserved for that one listener.",
  },
  {
    title: "Rate limiting did nothing at all once deployed",
    body: "Eight straight failed logins against the live backend, zero rate-limit responses, despite the same test passing locally every time. The web server only trusts a forwarded-IP header from a directly-connecting peer at the loopback address by default, and in production that direct peer is the hosting platform's own edge, not the visitor. Every request's rate-limit key was collapsing to the same non-representative value. Fixed by explicitly trusting proxy headers from the one edge that can reach the container.",
  },
  {
    title: "One worker region was silently running old code for months",
    body: "A security fix appeared to still be broken in one region during a routine re-check, while the other region passed cleanly. The committed code was correct in both places; the container for one region had simply never been rebuilt, because the two regions' local Docker services had their own independent build targets under the same name, and rebuilding one never touched the other. Fixed by pointing both at one shared image tag, so a rebuild of one now always rebuilds both.",
  },
  {
    title: "A target's credentials could leak to a host it was never configured for",
    body: "Following redirects by hand, which the SSRF defense above requires, also quietly disabled the HTTP client's own habit of stripping an Authorization header on a cross-origin redirect. A target's basic-auth password or a secret-bearing custom header would have been sent to whatever third party a redirect happened to name. Found by reading through what manual redirect-following gives up versus what the client does for free, not from a report. Fixed by dropping a target's credentials the moment a redirect crosses to a different host.",
  },
  {
    title: "Keyword monitoring silently failed on its own default configuration",
    body: "A target with a keyword condition but no explicitly chosen request method defaulted to trying a bodyless request first, which can never satisfy a keyword check regardless of its status code, so the most common configuration failed every single time. Fixed by treating an unset method as a full request whenever a keyword condition is configured.",
  },
  {
    title: "A failed alert was recorded as if it had sent",
    body: "Neither alert path checked whether the send actually succeeded before writing it down as delivered. A real failure, whatever the cause, would have permanently suppressed that alert going forward with no retry, even after the underlying problem was fixed. Fixed by only recording an alert as delivered once at least one channel genuinely confirms it went out.",
  },
  {
    title: "The live site was gated behind a login screen for every visitor",
    body: "The production frontend URL redirected anonymous traffic to the hosting platform's own sign-in page. It would have silently blocked every real visitor, including anyone reviewing this project. Caught by loading the live URL as a stranger would, not by anything in the deploy pipeline itself.",
  },
  {
    title: "A password-reset email pointed at localhost, from an unlabeled sender",
    body: "Two settings that build links and sender identity into outgoing email were never updated when the frontend actually went live, so the one real password-reset email sent from production contained a dead link. Found by triggering a real reset email against a live account and reading what actually arrived, not by reviewing configuration.",
  },
];

const LIMITATIONS: string[] = [
  "Built and priced for a personal tool, not a fleet: the rate limiter's counters live in one process's memory, and two regions is a deliberate, small number, not a ceiling being approached.",
  "Outgoing email uses the mail provider's shared sandbox sender, since no custom domain is verified yet, so delivery can land in spam.",
  "Compliance export is CSV only. PDF was designed for but never built.",
  "An alert that succeeds on one channel and fails on another isn't retried per channel. The system tracks whether a transition was alerted at all, not whether every channel confirmed delivery.",
  "There's no rotation story for a webhook's signing secret or an API key. Getting a new one means deleting and recreating it.",
  "One dependency lockfile is intentionally held a major version behind its latest release, since the fixes past that point are breaking changes not yet worth taking on for this project's stable UI.",
  "The request-flow design (claim-then-release-before-the-network-call, bounded concurrency, background retention pruning) is built the way it should be at a larger scale, but it has never actually been load-tested at one.",
];

export default function EngineeringPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-5xl px-6 py-16">
        <h1 className="text-3xl font-semibold leading-tight">The reasoning behind it</h1>
        <p className="mt-4 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Every non-obvious decision in this project, why it was made that way instead of the
          simpler alternative, the real bugs that decision surfaced along the way, and an honest
          list of what this project deliberately doesn't try to do.
        </p>

        <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCallout value="30s → 900s" label="backoff range, ±20% jitter" />
          <StatCallout value="120s" label="stale-claim window before a crashed worker's target is reclaimed" />
          <StatCallout value="~3.85s" label="smallest gap seen between two checks of the same target and region, under forced contention" />
          <StatCallout value="362" label="automated tests, against a real database" />
          <StatCallout value="8" label="real bugs found and fixed along the way, below" tone="down" />
        </div>

        <section className="mt-16">
          <SectionHeading>Key decisions</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            The choices that shaped this project, and the alternative each one was weighed
            against.
          </p>

          <DecisionBlock
            decision={{
              glyph: <RouterGlyph />,
              title: "SSRF defense at two checkpoints, not one",
              body: (
                <>
                  <p>
                    A worker that fetches user-supplied URLs on a schedule is a textbook target
                    for SSRF: a cloud metadata address, or an internal service the worker can
                    reach but the public internet can't. Blocking those ranges is the easy part.
                    Deciding when to check is the real decision: checking only at submission
                    misses a hostname that resolves safely today and unsafely tomorrow. Checking
                    only at request time means a bad URL sits unrejected until the next cycle,
                    instead of failing fast for the person who just typed it in. This project
                    does both: a synchronous check the moment a URL is submitted, and an
                    independent check before every single request the worker makes, including
                    every hop of a redirect chain.
                  </p>
                  <p>
                    Re-validating each redirect hop meant disabling the HTTP client's own
                    automatic redirect handling and following the chain by hand, which also
                    disabled its default behavior of stripping credentials on a cross-origin
                    redirect. See the issues list below for what that surfaced.
                  </p>
                </>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <AntennaGlyph />,
              title: "An async worker with per-target backoff, not a flat polling loop",
              body: (
                <p>
                  Every target is checked on the schedule it's individually earned, not a single
                  global interval. A batch of due targets is checked concurrently, bounded by a
                  limit, instead of one at a time. A failing target backs off on an exponential
                  curve with random jitter mixed in, so several targets that start failing
                  together don't all retry in lockstep forever. A single success resets the
                  streak immediately. The scheduler itself polls far more often than any single
                  target's own interval, specifically so a fast early-stage backoff step doesn't
                  get flattened back down to "retry every five minutes regardless."
                </p>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <DataCenterGlyph />,
              title: "Row-claiming for coordination, not a message queue",
              body: (
                <p>
                  Once more than one worker process exists, whether that's scaling within a
                  region or a second region entirely, something has to stop two of them from
                  grabbing the same due target at once and racing on the result. A short
                  database transaction claims a row and releases the lock immediately, well
                  before the actual network request starts, using a lock mode that lets a
                  concurrent claim attempt simply skip a row that's already taken rather than
                  wait for it. A claim that's gone stale, most likely a crashed worker, becomes
                  claimable again on its own. Two heavier alternatives, a dedicated leases table
                  and Postgres advisory locks, would have worked too; this gets the same
                  guarantee out of locking machinery the database already provides, for two
                  extra columns on an existing table.
                </p>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <TowerGlyph />,
              title: "Per-region results, never collapsed into one boolean",
              body: (
                <p>
                  Scheduling state lives per target, per region, not per target alone, and every
                  result is reported region by region, side by side. There's no derived "is this
                  target up" field anywhere. Collapsing to down-if-down-anywhere turns one
                  region's transient blip into a false alarm; collapsing to
                  down-only-if-down-everywhere hides a real regional outage until it happens to
                  spread. Both were considered and rejected. This is an audience-dependent call,
                  not an obviously correct one: a status page built for third parties would
                  likely choose the opposite, a single collapsed verdict, because that's what
                  its audience actually needs. This is a private tool built for its own owner,
                  where the diagnostic detail is the entire point.
                </p>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <SignalBarsGlyph />,
              title: "Alert cooldowns that suppress on state, not on time alone",
              body: (
                <p>
                  Alerting on every failed check would be useless spam for anything down more
                  than a few minutes. A downtime alert fires once on the transition into down,
                  stays quiet while it's still down, and a cooldown additionally governs how
                  soon a new down transition can re-alert after a recovery, which is what
                  actually dampens a target that flaps. Recovery itself has no cooldown of its
                  own. Certificate-expiry alerts follow a related shape: one alert on first
                  entering the warning window, a slower repeat cadence while still unrenewed,
                  and an immediate reset the moment a genuinely new certificate shows up. Both
                  are built so a failed send is never recorded as delivered, which turned out to
                  matter for a real reason documented below.
                </p>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <RouterGlyph />,
              title: "Webhooks re-validated at send time, signed, never chased through a redirect",
              body: (
                <p>
                  Webhook delivery reuses the same SSRF check target URLs get, re-run
                  immediately before every attempt, not just at creation, the same
                  defense against a URL that resolves safely now and unsafely later. Delivery is
                  deliberately thin: one attempt, a short timeout, no redirect-following at all,
                  since a webhook receiver essentially never has a legitimate reason to redirect.
                  A failure is logged and swallowed, never allowed to corrupt or delay the
                  real-time dashboard push that fires from the same code path. Every payload is
                  signed over its exact raw body, with a secret shown to the caller exactly once,
                  the same "shown once, never again" pattern already used for password-reset
                  links and API keys.
                </p>
              ),
            }}
          />

          <DecisionBlock
            decision={{
              glyph: <DataCenterGlyph />,
              title: "API keys, scoped and structurally unable to manage themselves",
              body: (
                <p>
                  Programmatic access needed its own credential, not a reuse of the session
                  cookie, since a cookie has no real revocation story and a script holding a
                  long-lived token is a different risk than a browser holding one it never
                  touches directly. Keys are hashed at rest, scoped read or full, and, the rule
                  worth calling out specifically, a key can never be used to create, list, or
                  revoke other keys, regardless of its own scope. Every key-management endpoint
                  depends on the cookie-only path directly, never the key-accepting one, so this
                  isn't a policy check that could be gotten wrong at one call site. It's
                  structural.
                </p>
              ),
            }}
          />
        </section>

        <section className="mt-16">
          <SectionHeading>Issues found along the way</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Named plainly, the way they were actually found, not smoothed over. Every one of
            these was a real bug in a real running system, not a hypothetical.
          </p>
          <div className="mt-6 grid gap-6 sm:grid-cols-2">
            {ISSUES.map((issue) => (
              <div key={issue.title}>
                <h3 className="font-medium" style={{ color: "var(--signal-down)" }}>
                  {issue.title}
                </h3>
                <p className="mt-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {issue.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-16">
          <SectionHeading>Known limitations</SectionHeading>
          <p className="mt-3 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Stated as fixed, load-bearing facts about what this project is, not as gaps waiting
            to be closed.
          </p>
          <ul className="mt-6 flex max-w-2xl flex-col gap-2.5 text-sm" style={{ color: "var(--text-secondary)" }}>
            {LIMITATIONS.map((item) => (
              <li key={item} className="list-disc pl-0.5" style={{ marginLeft: "1.1em" }}>
                {item}
              </li>
            ))}
          </ul>
        </section>

        <p className="mt-16 max-w-2xl text-sm" style={{ color: "var(--text-secondary)" }}>
          The full write-up, with quantified results and what this project deliberately isn't,
          lives in{" "}
          <a
            href="https://github.com/mstfaatf/uptime-monitor/blob/main/CASE_STUDY.md"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
            style={{ color: "var(--text-primary)" }}
          >
            CASE_STUDY.md
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
