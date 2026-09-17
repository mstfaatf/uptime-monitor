"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { Webhook } from "@/lib/types";

function isValidWebhookUrl(s: string): boolean {
  // Mirrors backend/routers/webhooks.py's _validate_webhook_url: a well-formed http(s) URL
  // with a hostname. The backend also runs a real SSRF check the client obviously can't
  // replicate — this is just the fast, obviously-wrong-input rejection, not full validation.
  try {
    const u = new URL(s);
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname.length > 0;
  } catch {
    return false;
  }
}

export interface WebhookSettingsProps {
  onAuthFailed: () => void;
}

export function WebhookSettings({ onAuthFailed }: WebhookSettingsProps) {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [url, setUrl] = useState("");
  const [alertOnDowntime, setAlertOnDowntime] = useState(true);
  const [alertOnCertExpiry, setAlertOnCertExpiry] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  // The one place a webhook's real secret is ever available — shown exactly once, right after
  // creation, never fetchable again afterward (see lib/types.ts's own comment on Webhook).
  const [revealedSecret, setRevealedSecret] = useState<{ webhookId: number; secret: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [togglingId, setTogglingId] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      const res = await apiFetch("/webhooks");
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (res.ok) setWebhooks((await res.json()) as Webhook[]);
      else setListError("Failed to load webhooks.");
      setLoading(false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    const trimmed = url.trim();
    if (!trimmed) {
      setCreateError("URL is required.");
      return;
    }
    if (!isValidWebhookUrl(trimmed)) {
      setCreateError("Please enter a valid http or https URL.");
      return;
    }
    setCreating(true);
    try {
      const created = await apiJson<Webhook & { secret: string }>("/webhooks", {
        method: "POST",
        body: JSON.stringify({
          url: trimmed,
          alert_on_downtime: alertOnDowntime,
          alert_on_cert_expiry: alertOnCertExpiry,
        }),
      });
      const { secret, ...webhook } = created;
      setWebhooks((prev) => [webhook, ...prev]);
      setRevealedSecret({ webhookId: webhook.id, secret });
      setCopied(false);
      setUrl("");
      setAlertOnDowntime(true);
      setAlertOnCertExpiry(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create webhook.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setCreateError(message);
    } finally {
      setCreating(false);
    }
  }

  // Optimistic, revert-on-failure — same pattern the alert-preference switches elsewhere on
  // this page already use.
  async function handleToggle(
    webhook: Webhook,
    field: "alert_on_downtime" | "alert_on_cert_expiry" | "enabled",
    value: boolean
  ) {
    setTogglingId(webhook.id);
    setListError("");
    setWebhooks((prev) => prev.map((w) => (w.id === webhook.id ? { ...w, [field]: value } : w)));
    try {
      const updated = await apiJson<Webhook>(`/webhooks/${webhook.id}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value }),
      });
      setWebhooks((prev) => prev.map((w) => (w.id === webhook.id ? updated : w)));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to update webhook.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setWebhooks((prev) => prev.map((w) => (w.id === webhook.id ? { ...w, [field]: !value } : w)));
      setListError(message);
    } finally {
      setTogglingId(null);
    }
  }

  async function handleDelete(webhook: Webhook) {
    setDeletingId(webhook.id);
    try {
      const res = await apiFetch(`/webhooks/${webhook.id}`, { method: "DELETE" });
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok) throw new Error("Failed to delete webhook.");
      setWebhooks((prev) => prev.filter((w) => w.id !== webhook.id));
      if (revealedSecret?.webhookId === webhook.id) setRevealedSecret(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to delete webhook.");
    } finally {
      setDeletingId(null);
    }
  }

  async function copySecret() {
    if (!revealedSecret) return;
    try {
      await navigator.clipboard.writeText(revealedSecret.secret);
      setCopied(true);
    } catch {
      // Clipboard access can be denied by the browser — the secret stays visible either way,
      // so this isn't a dead end, just a missed convenience.
    }
  }

  return (
    <section
      className="mt-6 rounded border p-5"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <h2 className="text-lg font-semibold">Webhooks</h2>
      <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
        Send a signed HTTP POST to your own endpoint on downtime and certificate-expiry events, independent
        of email.
      </p>

      <form onSubmit={handleCreate} className="mt-4 flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="webhook-url">Webhook URL</Label>
          <Input
            id="webhook-url"
            type="url"
            placeholder="https://example.com/hooks/uptime-monitor"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={creating}
          />
        </div>
        <div className="flex flex-wrap gap-5">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={alertOnDowntime}
              onChange={(e) => setAlertOnDowntime(e.target.checked)}
              disabled={creating}
            />
            Downtime alerts
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={alertOnCertExpiry}
              onChange={(e) => setAlertOnCertExpiry(e.target.checked)}
              disabled={creating}
            />
            Certificate expiry alerts
          </label>
        </div>
        {createError && (
          <p className="text-sm" style={{ color: "var(--signal-down)" }}>
            {createError}
          </p>
        )}
        <Button type="submit" disabled={creating} className="self-start">
          {creating ? "Adding…" : "Add webhook"}
        </Button>
      </form>

      {revealedSecret && (
        <div
          className="mt-4 flex flex-col gap-2 rounded-sm border p-3"
          style={{ borderColor: "var(--signal-warning)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--signal-warning)" }}>
            Copy this signing secret now. It won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code
              className="flex-1 overflow-x-auto rounded-sm border px-2 py-1.5 font-mono text-xs"
              style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
            >
              {revealedSecret.secret}
            </code>
            <Button type="button" variant="outline" size="sm" onClick={copySecret}>
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

      <div className="mt-5 flex flex-col gap-3">
        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Loading…
          </p>
        ) : webhooks.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No webhooks configured.
          </p>
        ) : (
          webhooks.map((webhook) => (
            <div key={webhook.id} className="rounded-sm border p-3" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-start justify-between gap-4">
                <code className="break-all font-mono text-sm" style={{ color: "var(--text-primary)" }}>
                  {webhook.url}
                </code>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => handleDelete(webhook)}
                  disabled={deletingId !== null}
                >
                  {deletingId === webhook.id ? "…" : "Delete"}
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-5">
                <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                  <Switch
                    checked={webhook.enabled}
                    disabled={togglingId === webhook.id}
                    onCheckedChange={(v) => handleToggle(webhook, "enabled", v)}
                    aria-label={`Enabled for ${webhook.url}`}
                  />
                  Enabled
                </label>
                <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                  <Switch
                    checked={webhook.alert_on_downtime}
                    disabled={togglingId === webhook.id}
                    onCheckedChange={(v) => handleToggle(webhook, "alert_on_downtime", v)}
                    aria-label={`Downtime alerts for ${webhook.url}`}
                  />
                  Downtime
                </label>
                <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                  <Switch
                    checked={webhook.alert_on_cert_expiry}
                    disabled={togglingId === webhook.id}
                    onCheckedChange={(v) => handleToggle(webhook, "alert_on_cert_expiry", v)}
                    aria-label={`Certificate expiry alerts for ${webhook.url}`}
                  />
                  Cert expiry
                </label>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
