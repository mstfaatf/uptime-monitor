"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export type AuthStatus = { loading: boolean; authenticated: boolean };

// Every page that needs to know whether the session cookie is currently valid already does
// its own /auth/me check (dashboard, settings) — this factors out just that fetch+state shape
// so the public pages (site header, landing page, login, register) don't each reinvent it.
// Each caller still fires its own request; no shared auth context exists yet, and with at most
// two callers on the same page today that's not worth a global provider.
export function useAuthStatus(): AuthStatus {
  const [status, setStatus] = useState<AuthStatus>({ loading: true, authenticated: false });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/auth/me");
        if (!cancelled) setStatus({ loading: false, authenticated: res.ok });
      } catch {
        if (!cancelled) setStatus({ loading: false, authenticated: false });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
