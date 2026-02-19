"use client";

import { useCallback, useEffect, useState } from "react";
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

type TableRow = TargetStatus | (TargetOnly & { is_up?: null; checked_at?: null });

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return "—";
  }
}

function isValidUrl(s: string): boolean {
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

export default function DashboardPage() {
  const router = useRouter();
  const [items, setItems] = useState<TableRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [authFailed, setAuthFailed] = useState(false);

  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState("");

  const loadStatus = useCallback(async () => {
    setError("");
    try {
      const statusRes = await apiFetch("/targets/status");
      if (statusRes.status === 401) {
        setAuthFailed(true);
        return;
      }
      if (statusRes.ok) {
        const data = (await statusRes.json()) as TargetStatus[];
        setItems(data);
        return;
      }
      if (statusRes.status === 404) {
        const targetsRes = await apiFetch("/targets");
        if (targetsRes.status === 401) {
          setAuthFailed(true);
          return;
        }
        if (!targetsRes.ok) throw new Error("Failed to load targets");
        const targets = (await targetsRes.json()) as TargetOnly[];
        setItems(
          targets.map((t) => ({
            ...t,
            is_up: undefined,
            checked_at: undefined,
          }))
        );
        return;
      }
      throw new Error(`Status ${statusRes.status}`);
    } catch (err) {
      const res = await apiFetch("/auth/me").catch(() => null);
      if (res?.status === 401) setAuthFailed(true);
      else setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadStatus();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadStatus]);

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

  async function handleAddTarget(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    const rawUrl = url.trim();
    if (!rawUrl) {
      setFormError("URL is required.");
      return;
    }
    if (!isValidUrl(rawUrl)) {
      setFormError("Please enter a valid http or https URL.");
      return;
    }
    setSubmitting(true);
    try {
      await apiJson("/targets", {
        method: "POST",
        body: JSON.stringify({ url: rawUrl, name: name.trim() || undefined }),
      });
      setUrl("");
      setName("");
      await loadStatus();
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes("401") || err.message.includes("Not authenticated")) {
          router.replace("/login");
          return;
        }
        setFormError(err.message);
      } else {
        setFormError("Network error. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    setDeleteError("");
    setDeletingId(id);
    try {
      const res = await apiFetch(`/targets/${id}`, { method: "DELETE" });
      if (res.status === 401) {
        router.replace("/login");
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = typeof data.detail === "string" ? data.detail : "Delete failed.";
        setDeleteError(msg);
        return;
      }
      await loadStatus();
    } catch {
      setDeleteError("Network error. Try again.");
    } finally {
      setDeletingId(null);
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

      <section className="add-target-form">
        <h2>Add target</h2>
        <form onSubmit={handleAddTarget}>
          <div className="form-group">
            <label htmlFor="target-url">URL (required)</label>
            <input
              id="target-url"
              type="url"
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={submitting}
            />
          </div>
          <div className="form-group">
            <label htmlFor="target-name">Name (optional)</label>
            <input
              id="target-name"
              type="text"
              placeholder="My site"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
            />
          </div>
          {formError && <p className="error-message">{formError}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Adding…" : "Add target"}
          </button>
        </form>
      </section>

      {deleteError && <p className="error-message">{deleteError}</p>}
      {error && <p className="error-message">{error}</p>}
      {loading ? (
        <p>Loading…</p>
      ) : (
        <>
          {items.length === 0 ? (
            <p>No targets yet. Add one above.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Last checked</th>
                  <th></th>
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
                    <td>
                      <button
                        type="button"
                        className="btn btn-danger"
                        onClick={() => handleDelete(row.id)}
                        disabled={deletingId !== null}
                        aria-label={`Delete ${row.name || row.url}`}
                      >
                        {deletingId === row.id ? "…" : "Delete"}
                      </button>
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
