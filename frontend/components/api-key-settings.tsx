"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatTimestamp } from "@/lib/status";
import type { ApiKey } from "@/lib/types";

// Mirrors backend/auth/api_key.py's SCOPE_LEVELS exactly.
const SCOPES = [
  { value: "read", description: "View targets, checks, and exports." },
  { value: "full", description: "Also create, pause, and delete targets, and manage webhooks." },
] as const;

export interface ApiKeySettingsProps {
  onAuthFailed: () => void;
}

export function ApiKeySettings({ onAuthFailed }: ApiKeySettingsProps) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "full">("read");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  // Shown exactly once, right after creation — see lib/types.ts's own comment on ApiKey for why
  // no endpoint ever returns the raw value again.
  const [revealedKey, setRevealedKey] = useState<{ id: number; key: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const [revokingId, setRevokingId] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      const res = await apiFetch("/api-keys");
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (res.ok) setKeys((await res.json()) as ApiKey[]);
      else setListError("Failed to load API keys.");
      setLoading(false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError("Name is required.");
      return;
    }
    setCreating(true);
    try {
      const created = await apiJson<ApiKey & { key: string }>("/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: trimmed, scope }),
      });
      const { key, ...apiKey } = created;
      setKeys((prev) => [apiKey, ...prev]);
      setRevealedKey({ id: apiKey.id, key });
      setCopied(false);
      setName("");
      setScope("read");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create API key.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setCreateError(message);
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(apiKey: ApiKey) {
    setRevokingId(apiKey.id);
    setListError("");
    try {
      const res = await apiFetch(`/api-keys/${apiKey.id}`, { method: "DELETE" });
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok) throw new Error("Failed to revoke key.");
      // Soft-deleted server-side (see backend/routers/api_keys.py) — refresh the row in place
      // so it keeps showing as an audit entry rather than disappearing, matching what a
      // fresh GET /api-keys would show.
      setKeys((prev) =>
        prev.map((k) => (k.id === apiKey.id ? { ...k, revoked_at: new Date().toISOString() } : k))
      );
      if (revealedKey?.id === apiKey.id) setRevealedKey(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to revoke key.");
    } finally {
      setRevokingId(null);
    }
  }

  async function copyKey() {
    if (!revealedKey) return;
    try {
      await navigator.clipboard.writeText(revealedKey.key);
      setCopied(true);
    } catch {
      // Clipboard access can be denied — the key stays visible either way.
    }
  }

  return (
    <section
      className="mt-6 rounded border p-5"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <h2 className="text-lg font-semibold">API keys</h2>
      <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
        Bearer tokens for programmatic access to your own targets and checks. A key can never manage other
        keys, at any scope.
      </p>

      <form onSubmit={handleCreate} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="apikey-name">Name</Label>
          <Input
            id="apikey-name"
            placeholder="e.g. Prometheus exporter"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={creating}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="apikey-scope">Scope</Label>
          <select
            id="apikey-scope"
            value={scope}
            onChange={(e) => setScope(e.target.value as "read" | "full")}
            disabled={creating}
            className="rounded-sm border bg-transparent px-2 py-1.5 font-mono text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          >
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value} style={{ background: "var(--bg-surface)" }}>
                {s.value}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={creating}>
          {creating ? "Creating…" : "Create key"}
        </Button>
      </form>
      {SCOPES.map((s) => (
        <p key={s.value} className="mt-1 flex gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          <span className="font-mono" style={{ color: "var(--text-primary)" }}>
            {s.value}
          </span>
          <span>{s.description}</span>
        </p>
      ))}
      {createError && (
        <p className="mt-2 text-sm" style={{ color: "var(--signal-down)" }}>
          {createError}
        </p>
      )}

      {revealedKey && (
        <div
          className="mt-4 flex flex-col gap-2 rounded-sm border p-3"
          style={{ borderColor: "var(--signal-warning)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--signal-warning)" }}>
            Copy this key now. It won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code
              className="flex-1 overflow-x-auto rounded-sm border px-2 py-1.5 font-mono text-xs"
              style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
            >
              {revealedKey.key}
            </code>
            <Button type="button" variant="outline" size="sm" onClick={copyKey}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      )}

      {listError && (
        <p className="mt-4 text-sm" style={{ color: "var(--signal-down)" }}>
          {listError}
        </p>
      )}

      <div className="mt-5 flex flex-col gap-2">
        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Loading…
          </p>
        ) : keys.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No API keys yet.
          </p>
        ) : (
          keys.map((key) => (
            <div
              key={key.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-sm border p-3"
              style={{ borderColor: "var(--border)" }}
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{key.name}</span>
                  <span
                    className="rounded-sm border px-1.5 py-0.5 font-mono text-xs"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                  >
                    {key.scope}
                  </span>
                  {key.revoked_at && (
                    <span
                      className="rounded-sm border px-1.5 py-0.5 font-mono text-xs"
                      style={{ borderColor: "var(--signal-down)", color: "var(--signal-down)" }}
                    >
                      Revoked
                    </span>
                  )}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                  <span>{key.key_prefix}…</span>
                  <span>created {formatTimestamp(key.created_at)}</span>
                  <span>last used {key.last_used_at ? formatTimestamp(key.last_used_at) : "never"}</span>
                </div>
              </div>
              {!key.revoked_at && (
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => handleRevoke(key)}
                  disabled={revokingId !== null}
                >
                  {revokingId === key.id ? "…" : "Revoke"}
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
