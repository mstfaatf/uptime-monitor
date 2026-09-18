"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { SignalLight } from "@/components/signal-light";
import { apiJson } from "@/lib/api";
import { useAuthStatus } from "@/lib/use-auth-status";

// Shared header for the public/auth pages (/, /features, /architecture, /engineering, /about,
// /login, /register). The dashboard has its own separate header/actions bar — untouched here.
//
// /architecture and /engineering don't exist as routes yet — linked ahead of themselves so the
// nav's final shape is in place before every page behind it is built; each link resolves once
// its own page lands.
//
// Auth-aware: the brand link previously always pointed at "/", so an authenticated user
// clicking it while on e.g. /about landed back on the signed-out landing page — not because
// the session was cleared, but because this header (and the landing page itself) never
// checked auth state at all. Fixed by checking /auth/me here and routing accordingly.
export function SiteHeader() {
  const router = useRouter();
  const { authenticated } = useAuthStatus();

  async function handleSignOut() {
    try {
      await apiJson("/auth/logout", { method: "POST" });
    } finally {
      router.push("/");
      router.refresh();
    }
  }

  return (
    <header className="border-b" style={{ borderColor: "var(--border)" }}>
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-2 px-6 py-4">
        <Link href={authenticated ? "/dashboard" : "/"} className="flex items-center gap-3">
          <SignalLight state="up" size="sm" />
          <span className="font-semibold">Uptime Monitor</span>
        </Link>
        <nav
          className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-sm sm:gap-x-6"
          style={{ color: "var(--text-secondary)" }}
        >
          <Link href="/features" className="transition-colors hover:text-fg-primary">
            Features
          </Link>
          <Link href="/architecture" className="transition-colors hover:text-fg-primary">
            Architecture
          </Link>
          <Link href="/engineering" className="transition-colors hover:text-fg-primary">
            Engineering
          </Link>
          <Link href="/about" className="transition-colors hover:text-fg-primary">
            About
          </Link>
          {authenticated ? (
            <button
              type="button"
              onClick={handleSignOut}
              className="bg-transparent p-0 transition-colors hover:text-fg-primary"
            >
              Sign out
            </button>
          ) : (
            <Link href="/login" className="transition-colors hover:text-fg-primary">
              Log in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
