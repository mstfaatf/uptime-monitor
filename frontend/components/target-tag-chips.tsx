"use client";

import { useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import type { Tag } from "@/lib/types";

export interface TargetTagChipsProps {
  targetId: number;
  tags: Tag[];
  // Every tag the user owns — used to compute which ones aren't attached to this target yet,
  // for the "attach" picker. Deliberately not fetched by this component itself: the dashboard
  // already loads the full tag list once for the filter bar, and every row on the page needs
  // the same list, so fetching it per-row would mean one request per target instead of one.
  allTags: Tag[];
  onAttached: (tag: Tag) => void;
  onDetached: (tagId: number) => void;
  onAuthFailed: () => void;
}

// Small radius, mono tag-name text — matching RegionBadge's own treatment (rounded, not
// rounded-full/pill), the same instrument-panel convention every other small label on this
// page already uses. No new colors: the chip is a plain --border-bordered box on
// --text-secondary, identical to RegionBadge.
export function TargetTagChips({ targetId, tags, allTags, onAttached, onDetached, onAuthFailed }: TargetTagChipsProps) {
  const [error, setError] = useState("");
  const [pendingTagId, setPendingTagId] = useState<number | null>(null);

  const attachedIds = new Set(tags.map((t) => t.id));
  const available = allTags.filter((t) => !attachedIds.has(t.id));

  async function handleAttach(tagId: number) {
    if (!tagId) return;
    setPendingTagId(tagId);
    setError("");
    try {
      const updated = await apiJson<{ tags: Tag[] }>(`/targets/${targetId}/tags`, {
        method: "POST",
        body: JSON.stringify({ tag_id: tagId }),
      });
      const attached = updated.tags.find((t) => t.id === tagId);
      if (attached) onAttached(attached);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to attach tag.";
      if (message.includes("401") || message.includes("Not authenticated")) {
        onAuthFailed();
        return;
      }
      setError(message);
    } finally {
      setPendingTagId(null);
    }
  }

  async function handleDetach(tagId: number) {
    setPendingTagId(tagId);
    setError("");
    try {
      const res = await apiFetch(`/targets/${targetId}/tags/${tagId}`, { method: "DELETE" });
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok && res.status !== 404) throw new Error("Failed to detach tag.");
      onDetached(tagId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to detach tag.");
    } finally {
      setPendingTagId(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => (
        <span
          key={tag.id}
          className="inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-xs"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          {tag.name}
          <button
            type="button"
            onClick={() => handleDetach(tag.id)}
            disabled={pendingTagId !== null}
            aria-label={`Remove tag ${tag.name}`}
            className="leading-none opacity-70 hover:opacity-100 focus-visible:outline-none"
            style={{ color: "var(--text-secondary)" }}
          >
            ×
          </button>
        </span>
      ))}
      {available.length > 0 && (
        <select
          value=""
          onChange={(e) => handleAttach(Number(e.target.value))}
          disabled={pendingTagId !== null}
          aria-label="Attach a tag"
          className="rounded-sm border bg-transparent px-1.5 py-0.5 font-mono text-xs"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          <option value="" disabled>
            + tag
          </option>
          {available.map((tag) => (
            <option key={tag.id} value={tag.id} style={{ background: "var(--bg-surface)", color: "var(--text-primary)" }}>
              {tag.name}
            </option>
          ))}
        </select>
      )}
      {error && (
        <span className="text-xs" style={{ color: "var(--signal-down)" }}>
          {error}
        </span>
      )}
    </div>
  );
}
