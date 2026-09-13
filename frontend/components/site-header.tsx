import Link from "next/link";
import { SignalLight } from "@/components/signal-light";

// Shared header for the public/auth pages (/, /about, /login, /register). The dashboard has
// its own separate header/actions bar — untouched here, that's a later prompt's job.
export function SiteHeader() {
  return (
    <header className="border-b" style={{ borderColor: "var(--border)" }}>
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-3">
          <SignalLight state="up" size="sm" />
          <span className="font-semibold">Uptime Monitor</span>
        </Link>
        <nav className="flex items-center gap-6 font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
          <Link href="/about" className="transition-colors hover:text-fg-primary">
            About
          </Link>
          <Link href="/login" className="transition-colors hover:text-fg-primary">
            Log in
          </Link>
        </nav>
      </div>
    </header>
  );
}
