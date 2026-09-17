"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { apiFetch, apiJson } from "@/lib/api";
import type { TargetSettings } from "@/lib/types";

// Mirrors backend/routers/targets.py's own constants exactly — ALLOWED_REQUEST_METHODS,
// ALLOWED_KEYWORD_MATCH_MODES, MIN_CHECK_INTERVAL_SECONDS — so this form can validate the same
// rules client-side before ever sending a request, not just discover them from a 400 response.
const REQUEST_METHODS = ["GET", "POST", "HEAD"] as const;
const KEYWORD_MATCH_MODES = [
  { value: "contains", label: "contains" },
  { value: "not_contains", label: "does not contain" },
] as const;
const MIN_CHECK_INTERVAL_SECONDS = 30;

type HeaderRow = { key: string; value: string };

export interface TargetSettingsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetId: number;
  // Only the fields the detail page itself needs to reflect immediately (name, paused) — the
  // full settings object stays local to this modal, loaded fresh on every open.
  onSaved: (patch: { name: string | null; paused: boolean }) => void;
  onAuthFailed: () => void;
}

export function TargetSettingsModal({ open, onOpenChange, targetId, onSaved, onAuthFailed }: TargetSettingsModalProps) {
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [pausing, setPausing] = useState(false);

  const [name, setName] = useState("");
  const [method, setMethod] = useState<"auto" | (typeof REQUEST_METHODS)[number]>("auto");
  const [headerRows, setHeaderRows] = useState<HeaderRow[]>([]);
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  // Whether the loaded target already has basic-auth credentials stored — needed for client-
  // side validation (a kept/changed username needs *some* password, either the existing one or
  // a freshly typed one; an empty password field alone doesn't tell you which case you're in).
  const [hadStoredPassword, setHadStoredPassword] = useState(false);
  const [keywordMatch, setKeywordMatch] = useState("");
  const [keywordMatchMode, setKeywordMatchMode] = useState<"contains" | "not_contains">("contains");
  const [intervalSeconds, setIntervalSeconds] = useState("");
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoadError("");
    setSaveError("");
    setLoading(true);
    (async () => {
      const res = await apiFetch("/targets");
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok) {
        setLoadError("Failed to load target settings.");
        setLoading(false);
        return;
      }
      const targets = (await res.json()) as TargetSettings[];
      const target = targets.find((t) => t.id === targetId);
      if (!target) {
        setLoadError("Target not found.");
        setLoading(false);
        return;
      }
      setName(target.name ?? "");
      setMethod((target.request_method as (typeof REQUEST_METHODS)[number] | null) ?? "auto");
      setHeaderRows(
        target.request_headers
          ? Object.entries(target.request_headers).map(([key, value]) => ({ key, value }))
          : []
      );
      setAuthUsername(target.basic_auth_username ?? "");
      setAuthPassword("");
      setHadStoredPassword(target.basic_auth_username != null);
      setKeywordMatch(target.keyword_match ?? "");
      setKeywordMatchMode(target.keyword_match_mode === "not_contains" ? "not_contains" : "contains");
      setIntervalSeconds(target.check_interval_seconds != null ? String(target.check_interval_seconds) : "");
      setPaused(target.paused);
      setLoading(false);
      // Deliberately only depends on `open` — onAuthFailed is a plain inline callback from the
      // parent, not memoized (same reasoning as the tag manager modal's own load effect).
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [open, targetId]);

  function addHeaderRow() {
    setHeaderRows((prev) => [...prev, { key: "", value: "" }]);
  }
  function updateHeaderRow(index: number, field: "key" | "value", value: string) {
    setHeaderRows((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }
  function removeHeaderRow(index: number) {
    setHeaderRows((prev) => prev.filter((_, i) => i !== index));
  }

  // Mirrors _validate_request_customization/_validate_check_interval_seconds in
  // backend/routers/targets.py exactly (same rules, same order), so a client-side rejection
  // reads the same way a server-side 400 would have. Returns an error string, or null if valid.
  function clientValidationError(): string | null {
    if (method === "HEAD" && keywordMatch.trim()) {
      return "Keyword match requires a request method that returns a response body (GET, POST, or Auto). HEAD has no body to match against.";
    }
    const usernameSet = authUsername.trim() !== "";
    const passwordWillBeSet = authPassword.trim() !== "" || (usernameSet && hadStoredPassword);
    if (usernameSet && !passwordWillBeSet) {
      return "Basic auth username requires a password.";
    }
    if (!usernameSet && authPassword.trim() !== "") {
      return "Basic auth password requires a username.";
    }
    if (intervalSeconds.trim() !== "") {
      const parsed = Number(intervalSeconds);
      if (!Number.isFinite(parsed) || parsed < MIN_CHECK_INTERVAL_SECONDS) {
        return `Check interval must be at least ${MIN_CHECK_INTERVAL_SECONDS} seconds, or left blank for the default.`;
      }
    }
    const seenKeys = new Set<string>();
    for (const row of headerRows) {
      if (!row.key.trim()) continue;
      if (seenKeys.has(row.key.trim())) return `Duplicate header name "${row.key.trim()}".`;
      seenKeys.add(row.key.trim());
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaveError("");
    const validationError = clientValidationError();
    if (validationError) {
      setSaveError(validationError);
      return;
    }
    setSaving(true);
    try {
      const headers = Object.fromEntries(
        headerRows.filter((r) => r.key.trim() !== "").map((r) => [r.key.trim(), r.value])
      );
      const body: Record<string, unknown> = {
        name: name.trim() || null,
        request_method: method === "auto" ? null : method,
        request_headers: Object.keys(headers).length > 0 ? headers : null,
        basic_auth_username: authUsername.trim() || null,
        keyword_match: keywordMatch.trim() || null,
        keyword_match_mode: keywordMatchMode,
        check_interval_seconds: intervalSeconds.trim() ? Number(intervalSeconds) : null,
      };
      // "Blank means unchanged" — the same convention the backend's own PATCH handler
      // documents: only send a new password when one was actually typed.
      if (authPassword.trim()) body.basic_auth_password = authPassword.trim();

      const updated = await apiJson<TargetSettings>(`/targets/${targetId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      onSaved({ name: updated.name, paused });
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  }

  // Pause/resume is its own state transition (POST /targets/{id}/pause or /resume), not a PATCH
  // field — mirrors why the backend keeps it as a dedicated endpoint rather than a settable
  // field (see routers/targets.py's own PATCH docstring). Saved immediately on toggle, same
  // "optimistic, revert on failure" pattern the alert-preference switches on /settings already
  // use, rather than bundled into the form's own Save button.
  async function handlePauseToggle(next: boolean) {
    setPausing(true);
    setSaveError("");
    const previous = paused;
    setPaused(next);
    try {
      const res = await apiFetch(`/targets/${targetId}/${next ? "pause" : "resume"}`, { method: "POST" });
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok) throw new Error(next ? "Failed to pause." : "Failed to resume.");
      onSaved({ name: name.trim() || null, paused: next });
    } catch (err) {
      setPaused(previous);
      setSaveError(err instanceof Error ? err.message : "Failed to update pause state.");
    } finally {
      setPausing(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Target settings</DialogTitle>
          <DialogDescription>
            Request customization, basic auth, keyword matching, check interval, and pause state.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Loading…
          </p>
        ) : loadError ? (
          <p className="text-sm" style={{ color: "var(--signal-down)" }}>
            {loadError}
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="flex items-center justify-between gap-4 rounded-sm border p-3" style={{ borderColor: "var(--border)" }}>
              <div>
                <div className="font-medium">Paused</div>
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  A paused target is skipped by every checking region until resumed.
                </div>
              </div>
              <Switch checked={paused} disabled={pausing} onCheckedChange={handlePauseToggle} aria-label="Toggle paused" />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-name">Name</Label>
              <Input id="settings-name" value={name} onChange={(e) => setName(e.target.value)} disabled={saving} />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-method">HTTP method</Label>
              <select
                id="settings-method"
                value={method}
                onChange={(e) => setMethod(e.target.value as typeof method)}
                disabled={saving}
                className="rounded-sm border bg-transparent px-2 py-1.5 font-mono text-sm"
                style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
              >
                <option value="auto" style={{ background: "var(--bg-surface)" }}>
                  Auto (HEAD, falls back to GET)
                </option>
                {REQUEST_METHODS.map((m) => (
                  <option key={m} value={m} style={{ background: "var(--bg-surface)" }}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <Label>Custom headers</Label>
                <Button type="button" variant="outline" size="sm" onClick={addHeaderRow} disabled={saving}>
                  Add header
                </Button>
              </div>
              {headerRows.length === 0 ? (
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  None set.
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {headerRows.map((row, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        placeholder="Header-Name"
                        value={row.key}
                        onChange={(e) => updateHeaderRow(i, "key", e.target.value)}
                        disabled={saving}
                        className="font-mono text-sm"
                        aria-label={`Header ${i + 1} name`}
                      />
                      <Input
                        placeholder="value"
                        value={row.value}
                        onChange={(e) => updateHeaderRow(i, "value", e.target.value)}
                        disabled={saving}
                        className="font-mono text-sm"
                        aria-label={`Header ${i + 1} value`}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => removeHeaderRow(i)}
                        disabled={saving}
                        aria-label={`Remove header ${i + 1}`}
                      >
                        ×
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Basic auth</Label>
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Username"
                  value={authUsername}
                  onChange={(e) => setAuthUsername(e.target.value)}
                  disabled={saving}
                  autoComplete="off"
                  aria-label="Basic auth username"
                />
                <Input
                  placeholder={hadStoredPassword ? "Leave blank to keep the current password" : "Password"}
                  type="password"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                  disabled={saving}
                  autoComplete="new-password"
                  aria-label="Basic auth password"
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-keyword">Keyword match</Label>
              <div className="flex items-center gap-2">
                <select
                  value={keywordMatchMode}
                  onChange={(e) => setKeywordMatchMode(e.target.value as typeof keywordMatchMode)}
                  disabled={saving}
                  className="rounded-sm border bg-transparent px-2 py-1.5 font-mono text-sm"
                  style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
                  aria-label="Keyword match mode"
                >
                  {KEYWORD_MATCH_MODES.map((m) => (
                    <option key={m.value} value={m.value} style={{ background: "var(--bg-surface)" }}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <Input
                  id="settings-keyword"
                  placeholder="Text to look for in the response body"
                  value={keywordMatch}
                  onChange={(e) => setKeywordMatch(e.target.value)}
                  disabled={saving}
                />
              </div>
              {method === "HEAD" && keywordMatch.trim() && (
                <p className="text-xs" style={{ color: "var(--signal-warning)" }}>
                  HEAD has no response body. Pick GET, POST, or Auto to use keyword matching.
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-interval">Check interval override (seconds)</Label>
              <Input
                id="settings-interval"
                type="number"
                min={MIN_CHECK_INTERVAL_SECONDS}
                placeholder={`Default (leave blank; minimum ${MIN_CHECK_INTERVAL_SECONDS}s if set)`}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(e.target.value)}
                disabled={saving}
              />
            </div>

            {saveError && (
              <p className="text-sm" style={{ color: "var(--signal-down)" }}>
                {saveError}
              </p>
            )}

            <DialogFooter>
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save settings"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
