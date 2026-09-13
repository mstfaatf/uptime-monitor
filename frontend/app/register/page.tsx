"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";
import { useAuthStatus } from "@/lib/use-auth-status";
import { AuthForm } from "@/components/auth-form";
import { SiteHeader } from "@/components/site-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function RegisterPage() {
  const router = useRouter();
  const { authenticated, loading: authChecking } = useAuthStatus();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // An already-authenticated user hitting /register directly should land on the dashboard,
  // not be shown the form again.
  useEffect(() => {
    if (!authChecking && authenticated) router.replace("/dashboard");
  }, [authChecking, authenticated, router]);

  async function handleSubmit(email: string, password: string) {
    setError("");
    setLoading(true);
    try {
      await apiJson("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  if (authChecking || authenticated) return null;

  return (
    <>
      <SiteHeader />
      <main className="mx-auto flex max-w-5xl justify-center px-6 py-16">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Register</CardTitle>
            <CardDescription>Start tracking the URLs you care about.</CardDescription>
          </CardHeader>
          <CardContent>
            <AuthForm
              submitLabel="Register"
              loadingLabel="Registering…"
              passwordAutoComplete="new-password"
              error={error}
              loading={loading}
              onSubmit={handleSubmit}
            />
            <p className="mt-6 text-sm" style={{ color: "var(--text-secondary)" }}>
              Already have an account?{" "}
              <Link href="/login" className="underline" style={{ color: "var(--text-primary)" }}>
                Log in
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    </>
  );
}
