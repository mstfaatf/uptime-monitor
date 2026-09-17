"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, apiJson } from "@/lib/api";
import { SignalLight } from "@/components/signal-light";
import { WebhookSettings } from "@/components/webhook-settings";
import { ApiKeySettings } from "@/components/api-key-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

type Me = {
  id: number;
  email: string;
  alert_on_downtime: boolean;
  alert_on_cert_expiry: boolean;
};

type PrefKey = "alert_on_downtime" | "alert_on_cert_expiry";

export default function SettingsPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [authFailed, setAuthFailed] = useState(false);

  const [prefsError, setPrefsError] = useState("");
  const [savingPref, setSavingPref] = useState<PrefKey | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  // Delete account: type-to-confirm rather than a modal dialog — this project has no Dialog
  // primitive yet (would mean pulling in a new Radix component for one single use), and
  // requiring the exact email to be typed is a stronger deliberate-action barrier for an
  // irreversible operation than clicking through a modal's own confirm button.
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deletingAccount, setDeletingAccount] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await apiFetch("/auth/me");
      if (res.status === 401) {
        setAuthFailed(true);
        setLoading(false);
        return;
      }
      if (res.ok) setMe((await res.json()) as Me);
      setLoading(false);
    })();
  }, []);

  useEffect(() => {
    if (authFailed) router.replace("/login");
  }, [authFailed, router]);

  async function togglePref(key: PrefKey, value: boolean) {
    if (!me) return;
    setPrefsError("");
    const previous = me[key];
    setMe({ ...me, [key]: value }); // optimistic
    setSavingPref(key);
    try {
      const updated = await apiJson<Me>("/auth/preferences", {
        method: "PATCH",
        body: JSON.stringify({ [key]: value }),
      });
      setMe(updated);
    } catch (err) {
      setMe((m) => (m ? { ...m, [key]: previous } : m)); // revert on failure
      setPrefsError(err instanceof Error ? err.message : "Failed to save preference.");
    } finally {
      setSavingPref(null);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess("");
    if (!currentPassword || !newPassword) {
      setPasswordError("Both fields are required.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New password and confirmation don't match.");
      return;
    }
    setChangingPassword(true);
    try {
      await apiJson("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setPasswordSuccess("Password changed.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Failed to change password.");
    } finally {
      setChangingPassword(false);
    }
  }

  async function handleLogout() {
    try {
      await apiJson("/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  async function handleDeleteAccount() {
    if (!me || deleteConfirmText !== me.email) return;
    setDeleteError("");
    setDeletingAccount(true);
    try {
      const res = await apiFetch("/auth/me", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = typeof data.detail === "string" ? data.detail : "Failed to delete account.";
        setDeleteError(msg);
        setDeletingAccount(false);
        return;
      }
      router.replace("/");
      router.refresh();
    } catch {
      setDeleteError("Network error. Try again.");
      setDeletingAccount(false);
    }
  }

  if (authFailed) return null;

  return (
    <>
      <header className="border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-2 px-6 py-4">
          <Link href="/dashboard" className="flex items-center gap-3">
            <SignalLight state="up" size="sm" />
            <span className="font-semibold">Uptime Monitor</span>
          </Link>
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="font-mono text-sm hover:underline" style={{ color: "var(--text-secondary)" }}>
              ← Back to dashboard
            </Link>
            <Button type="button" variant="outline" size="sm" onClick={handleLogout}>
              Log out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-2xl font-semibold">Settings</h1>

        {loading ? (
          <p className="mt-6" style={{ color: "var(--text-secondary)" }}>
            Loading…
          </p>
        ) : !me ? (
          <p className="mt-6 text-sm" style={{ color: "var(--signal-down)" }}>
            Failed to load your account.
          </p>
        ) : (
          <>
            <p className="mt-2 font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
              {me.email}
            </p>

            <section
              className="mt-8 rounded border p-5"
              style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
            >
              <h2 className="text-lg font-semibold">Alert preferences</h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                Choose which events send you an email. Sending isn't wired up yet, so these
                toggles just save your preference for when it is.
              </p>

              <div className="mt-5 flex flex-col gap-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium">Downtime alerts</div>
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      Email me when one of my targets goes down.
                    </div>
                  </div>
                  <Switch
                    checked={me.alert_on_downtime}
                    disabled={savingPref === "alert_on_downtime"}
                    onCheckedChange={(checked) => togglePref("alert_on_downtime", checked)}
                    aria-label="Toggle downtime alerts"
                  />
                </div>

                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium">Certificate expiry alerts</div>
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      Email me when a target's TLS certificate is expiring soon.
                    </div>
                  </div>
                  <Switch
                    checked={me.alert_on_cert_expiry}
                    disabled={savingPref === "alert_on_cert_expiry"}
                    onCheckedChange={(checked) => togglePref("alert_on_cert_expiry", checked)}
                    aria-label="Toggle certificate expiry alerts"
                  />
                </div>
              </div>

              {prefsError && (
                <p className="mt-4 text-sm" style={{ color: "var(--signal-down)" }}>
                  {prefsError}
                </p>
              )}
            </section>

            <WebhookSettings onAuthFailed={() => setAuthFailed(true)} />

            <ApiKeySettings onAuthFailed={() => setAuthFailed(true)} />

            <section
              className="mt-6 rounded border p-5"
              style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
            >
              <h2 className="text-lg font-semibold">Account</h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                Change your password.
              </p>

              <form onSubmit={handleChangePassword} className="mt-4 flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="current-password">Current password</Label>
                  <Input
                    id="current-password"
                    type="password"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    autoComplete="current-password"
                    disabled={changingPassword}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="new-password">New password</Label>
                  <Input
                    id="new-password"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    autoComplete="new-password"
                    disabled={changingPassword}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm-password">Confirm new password</Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                    disabled={changingPassword}
                  />
                </div>
                {passwordError && (
                  <p className="text-sm" style={{ color: "var(--signal-down)" }}>
                    {passwordError}
                  </p>
                )}
                {passwordSuccess && (
                  <p className="text-sm" style={{ color: "var(--signal-up)" }}>
                    {passwordSuccess}
                  </p>
                )}
                <Button type="submit" disabled={changingPassword} className="self-start">
                  {changingPassword ? "Changing…" : "Change password"}
                </Button>
              </form>
            </section>

            <section
              className="mt-6 rounded-sm border p-5"
              style={{ borderColor: "var(--signal-down)", background: "var(--bg-surface)" }}
            >
              <h2 className="text-lg font-semibold" style={{ color: "var(--signal-down)" }}>
                Danger zone
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                Permanently delete your account, every target you've added, and their full
                check history. This cannot be undone.
              </p>

              {!showDeleteConfirm ? (
                <Button
                  type="button"
                  variant="outline"
                  className="mt-4"
                  style={{ borderColor: "var(--signal-down)", color: "var(--signal-down)" }}
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  Delete account
                </Button>
              ) : (
                <div className="mt-4 flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="delete-confirm">
                      Type <span className="font-mono">{me.email}</span> to confirm
                    </Label>
                    <Input
                      id="delete-confirm"
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                      autoComplete="off"
                      disabled={deletingAccount}
                    />
                  </div>
                  {deleteError && (
                    <p className="text-sm" style={{ color: "var(--signal-down)" }}>
                      {deleteError}
                    </p>
                  )}
                  <div className="flex gap-3">
                    <Button
                      type="button"
                      variant="destructive"
                      disabled={deleteConfirmText !== me.email || deletingAccount}
                      onClick={handleDeleteAccount}
                    >
                      {deletingAccount ? "Deleting…" : "Permanently delete account"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={deletingAccount}
                      onClick={() => {
                        setShowDeleteConfirm(false);
                        setDeleteConfirmText("");
                        setDeleteError("");
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
