"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, apiJson } from "@/lib/api";

type TargetStatus = {
  id: number;
  url: string;
  name?: string | null;
  is_up: boolean;
  checked_at?: string | null;
  status_code?: number | null;
  error?: string | null;
};

type TargetOnly = {
  id: number;
  url: string;
  name?: string | null;
  created_at: string;
};

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return "—";
  }
}

export default function DashboardPage() {
  const router = useRouter();
  const [items, setItems] = useState<(TargetStatus | (TargetOnly & { is_up?: null; checked_at?: null }))[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authFailed, setAuthFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const statusRes = await apiFetch("/targets/status");
        if (statusRes.status === 401) {
          setAuthFailed(true);
          setLoading(false);
          return;
        }
        if (statusRes.ok) {
          const data = (await statusRes.json()) as TargetStatus[];
          if (!cancelled) setItems(data);
          setLoading(false);
          return;
        }
        if (statusRes.status === 404) {
          const targetsRes = await apiFetch("/targets");
          if (targetsRes.status === 401) {
            setAuthFailed(true);
            setLoading(false);
            return;
          }
          if (!targetsRes.ok) throw new Error("Failed to load targets");
          const targets = (await targetsRes.json()) as TargetOnly[];
          if (!cancelled) {
            setItems(
              targets.map((t) => ({
                ...t,
                is_up: undefined,
                checked_at: undefined,
              }))
            );
          }
          setLoading(false);
          return;
        }
        throw new Error(`Status ${statusRes.status}`);
      } catch (err) {
        if (cancelled) return;
        const res = await apiFetch("/auth/me").catch(() => null);
        if (res?.status === 401) {
          setAuthFailed(true);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (authFailed) router.replace("/login");
  }, [authFailed, router]);

  async function handleLogout() {
    try {
      await apiJson("/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch {
      router.replace("/login");
    }
  }

  if (authFailed) return null;

  return (
    <main>
      <div className="dashboard-actions">
        <Link href="/dashboard">Dashboard</Link>
        <button type="button" className="btn" onClick={handleLogout}>
          Log out
        </button>
      </div>
      <h1>Dashboard</h1>
      {error && <p className="error-message">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : (
        <>
          {items.length === 0 ? (
            <p>No targets yet. Add URLs via the API or a future form.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Last checked</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <a href={row.url} target="_blank" rel="noopener noreferrer">
                        {row.name || row.url}
                      </a>
                      {row.name && (
                        <span style={{ display: "block", fontSize: "0.875rem", color: "#666" }}>
                          {row.url}
                        </span>
                      )}
                    </td>
                    <td>
                      {"is_up" in row && row.is_up === true && (
                        <span className="status-up">Up</span>
                      )}
                      {"is_up" in row && row.is_up === false && (
                        <span className="status-down">Down</span>
                      )}
                      {!("is_up" in row) || row.is_up === undefined ? (
                        <span className="status-unknown">—</span>
                      ) : null}
                    </td>
                    <td>
                      {formatTimestamp(
                        "checked_at" in row ? row.checked_at : undefined
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </main>
  );
}
