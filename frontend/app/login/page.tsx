"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";
import { AuthForm } from "@/components/auth-form";
import { SiteHeader } from "@/components/site-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(email: string, password: string) {
    setError("");
    setLoading(true);
    try {
      await apiJson("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
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
            <CardTitle>Log in</CardTitle>
            <CardDescription>Access your monitored targets.</CardDescription>
          </CardHeader>
          <CardContent>
            <AuthForm
              submitLabel="Log in"
              loadingLabel="Logging in…"
              passwordAutoComplete="current-password"
              error={error}
              loading={loading}
              onSubmit={handleSubmit}
            />
            <p className="mt-6 text-sm" style={{ color: "var(--text-secondary)" }}>
              No account?{" "}
              <Link href="/register" className="underline" style={{ color: "var(--text-primary)" }}>
                Register
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    </>
  );
}
