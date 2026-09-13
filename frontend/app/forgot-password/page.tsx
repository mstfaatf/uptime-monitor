"use client";

import { useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { SiteHeader } from "@/components/site-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Its own small form rather than a reuse of AuthForm (email + password shaped) — this page is
// email-only, so forcing that shared component to fit would mean threading an unused password
// field through it, per the prompt's explicit call.
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await apiFetch("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.");
      }
      // Always shows the same success state regardless of whether the account exists — the
      // backend's response is deliberately identical either way (anti-enumeration), and the
      // UI shouldn't undo that by branching on anything client-side.
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <SiteHeader />
      <main className="mx-auto flex max-w-5xl justify-center px-6 py-16">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Forgot password</CardTitle>
            <CardDescription>We&apos;ll email you a link to reset it.</CardDescription>
          </CardHeader>
          <CardContent>
            {submitted ? (
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                If that email is registered, a password reset link has been sent. Check your inbox.
              </p>
            ) : (
              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    disabled={loading}
                  />
                </div>
                {error && (
                  <p className="text-sm" style={{ color: "var(--signal-down)" }}>
                    {error}
                  </p>
                )}
                <Button type="submit" disabled={loading} className="mt-2">
                  {loading ? "Sending…" : "Send reset link"}
                </Button>
              </form>
            )}
            <p className="mt-6 text-sm" style={{ color: "var(--text-secondary)" }}>
              <Link href="/login" className="underline" style={{ color: "var(--text-primary)" }}>
                Back to log in
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    </>
  );
}
