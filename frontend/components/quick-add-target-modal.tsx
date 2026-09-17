"use client";

import { useState } from "react";
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
import { apiJson } from "@/lib/api";

// The subset of POST /targets' real response this modal actually needs to hand back to
// whichever page opened it — not the full TargetResponse shape (request_method, tags, etc.),
// since a quick-add target is always created with every optional field at its default and the
// caller only needs enough to insert a new row into its own list locally.
export type QuickAddCreatedTarget = {
  id: number;
  url: string;
  name: string | null;
  created_at: string;
};

function isValidUrl(s: string): boolean {
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

export interface QuickAddTargetModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (target: QuickAddCreatedTarget) => void;
  // Mirrors the same 401-handling every other write action on the dashboard already does
  // (see handleAddTarget/handleDelete in app/dashboard/page.tsx) — kept as a callback rather
  // than this component calling useRouter itself, so navigation stays owned by the page.
  onAuthFailed: () => void;
}

// Name/URL only — no advanced fields (request method, headers, basic auth, keyword match,
// check interval, tags) yet. Those stay on the full target-edit surface; this is deliberately
// the fast path for "just start watching a URL," matching the prompt's explicit scope.
export function QuickAddTargetModal({ open, onOpenChange, onCreated, onAuthFailed }: QuickAddTargetModalProps) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function reset() {
    setUrl("");
    setName("");
    setError("");
    setSubmitting(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const rawUrl = url.trim();
    if (!rawUrl) {
      setError("URL is required.");
      return;
    }
    if (!isValidUrl(rawUrl)) {
      setError("Please enter a valid http or https URL.");
      return;
    }
    setSubmitting(true);
    try {
      const created = await apiJson<QuickAddCreatedTarget>("/targets", {
        method: "POST",
        body: JSON.stringify({ url: rawUrl, name: name.trim() || undefined }),
      });
      onCreated(created);
      reset();
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Network error. Try again.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setError(message);
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add target</DialogTitle>
          <DialogDescription>
            Start monitoring a URL. Request customization, tags, and check interval can be set from the
            target&apos;s own page afterward.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="quick-add-url">URL (required)</Label>
            <Input
              id="quick-add-url"
              type="url"
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={submitting}
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="quick-add-name">Name (optional)</Label>
            <Input
              id="quick-add-name"
              type="text"
              placeholder="My site"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
            />
          </div>
          {error && (
            <p className="text-sm" style={{ color: "var(--signal-down)" }}>
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Adding…" : "Add target"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
