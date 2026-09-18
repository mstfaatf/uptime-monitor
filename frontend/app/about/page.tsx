import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { AntennaGlyph } from "@/components/network-glyphs";

export default function AboutPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-2xl px-6 py-16">
        <div className="flex items-center gap-3">
          <AntennaGlyph />
          <h1 className="text-2xl font-semibold">About</h1>
        </div>
        <p className="mt-6" style={{ color: "var(--text-secondary)" }}>
          Uptime Monitor is a personal project built to go deeper on the networking side most
          monitoring tools abstract away, and to practice the infrastructure discipline that
          comes with letting it check a stranger's URLs safely. It's a private tool: there's no
          public page listing what anyone else is watching, and no shared login, registering is
          free and immediate.
        </p>
        <p className="mt-4" style={{ color: "var(--text-secondary)" }}>
          Built and documented end to end by Mustafa Atif as a portfolio project.
        </p>

        <h2 className="mt-10 text-lg font-semibold" style={{ color: "var(--signal-up)" }}>
          Read more
        </h2>
        <ul className="mt-3 flex flex-col gap-1.5">
          <li>
            <Link href="/features" className="hover:underline">
              Features
            </Link>
            <span style={{ color: "var(--text-secondary)" }}>, what's actually built</span>
          </li>
          <li>
            <Link href="/architecture" className="hover:underline">
              Architecture
            </Link>
            <span style={{ color: "var(--text-secondary)" }}>, how the pieces fit together</span>
          </li>
          <li>
            <Link href="/engineering" className="hover:underline">
              Engineering
            </Link>
            <span style={{ color: "var(--text-secondary)" }}>, the decisions and the bugs behind them</span>
          </li>
        </ul>

        <h2 className="mt-10 text-lg font-semibold" style={{ color: "var(--signal-up)" }}>
          Source
        </h2>
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
