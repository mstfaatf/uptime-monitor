"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Shared shell for /login and /register — the two pages were near-identical hand-rolled forms
// (same email/password fields, same error/submit shape) with only the endpoint, copy, and
// autoComplete hint differing. This owns the field markup and local field state; the pages own
// the actual API call, error, and loading state, since that's real per-page behavior, not
// visual duplication.
export interface AuthFormProps {
  submitLabel: string;
  loadingLabel: string;
  passwordAutoComplete: "current-password" | "new-password";
  error: string;
  loading: boolean;
  onSubmit: (email: string, password: string) => void | Promise<void>;
}

export function AuthForm({
  submitLabel,
  loadingLabel,
  passwordAutoComplete,
  error,
  loading,
  onSubmit,
}: AuthFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit(email, password);
  }

  return (
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
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete={passwordAutoComplete}
          disabled={loading}
        />
      </div>
      {error && (
        <p className="text-sm" style={{ color: "var(--signal-down)" }}>
          {error}
        </p>
      )}
      <Button type="submit" disabled={loading} className="mt-2">
        {loading ? loadingLabel : submitLabel}
      </Button>
    </form>
  );
}
