"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch, apiJson } from "@/lib/api";
import type { Tag } from "@/lib/types";

export interface TagManagerModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Fires after every create/rename/delete with the resulting full tag list, so the dashboard's
  // own filter-bar tag options and row-level "attach" list stay in sync without a second fetch.
  onTagsChanged: (tags: Tag[]) => void;
  // Fires only on a successful delete — separate from onTagsChanged because deleting a tag also
  // means scrubbing it out of every target row's own already-loaded `tags` list, which this
  // modal has no knowledge of (it only knows about tags in the abstract, not which targets
  // carry them).
  onTagDeleted: (tagId: number) => void;
  // Fires on a successful rename, for the same reason as onTagDeleted above: each target row
  // keeps its own copy of its attached tags (see TargetStatusRow's own comment on why), and
  // onTagsChanged alone only updates the dashboard's master tag list (the filter dropdown /
  // "attach" picker) — it doesn't reach into every row's already-loaded tags to relabel one
  // that's already attached there.
  onTagRenamed: (tag: Tag) => void;
  onAuthFailed: () => void;
}

export function TagManagerModal({
  open,
  onOpenChange,
  onTagsChanged,
  onTagDeleted,
  onTagRenamed,
  onAuthFailed,
}: TagManagerModalProps) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  // One editable value per tag id, seeded from the real name and reset on every open — lets
  // each tag's name render as a plain, always-editable input (save on blur/Enter) rather than
  // needing a separate edit-mode toggle per row.
  const [editValues, setEditValues] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    setLoading(true);
    (async () => {
      const res = await apiFetch("/tags");
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok) {
        setError("Failed to load tags.");
        setLoading(false);
        return;
      }
      const data = (await res.json()) as Tag[];
      setTags(data);
      setEditValues(Object.fromEntries(data.map((t) => [t.id, t.name])));
      onTagsChanged(data);
      setLoading(false);
      // Deliberately only depends on `open` — onTagsChanged/onAuthFailed are plain inline
      // callbacks from the parent, not memoized, so including them would refetch on every
      // parent re-render while this modal happens to be open. Same pattern the dashboard's own
      // reveal-animation effect already uses for the same reason.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [open]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError("");
    try {
      const created = await apiJson<Tag>("/tags", { method: "POST", body: JSON.stringify({ name }) });
      const next = [...tags, created].sort((a, b) => a.name.localeCompare(b.name));
      setTags(next);
      setEditValues((prev) => ({ ...prev, [created.id]: created.name }));
      onTagsChanged(next);
      setNewName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create tag.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRename(tag: Tag) {
    const value = (editValues[tag.id] ?? "").trim();
    if (!value || value === tag.name) {
      setEditValues((prev) => ({ ...prev, [tag.id]: tag.name })); // revert a blank/unchanged edit
      return;
    }
    setSavingId(tag.id);
    setError("");
    try {
      const updated = await apiJson<Tag>(`/tags/${tag.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: value }),
      });
      const next = tags.map((t) => (t.id === tag.id ? updated : t)).sort((a, b) => a.name.localeCompare(b.name));
      setTags(next);
      setEditValues((prev) => ({ ...prev, [tag.id]: updated.name }));
      onTagsChanged(next);
      onTagRenamed(updated);
    } catch (err) {
      setEditValues((prev) => ({ ...prev, [tag.id]: tag.name })); // revert on a rejected rename
      setError(err instanceof Error ? err.message : "Failed to rename tag.");
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(tag: Tag) {
    setDeletingId(tag.id);
    setError("");
    try {
      const res = await apiFetch(`/tags/${tag.id}`, { method: "DELETE" });
      if (res.status === 401) {
        onAuthFailed();
        return;
      }
      if (!res.ok && res.status !== 404) throw new Error("Failed to delete tag.");
      const next = tags.filter((t) => t.id !== tag.id);
      setTags(next);
      onTagsChanged(next);
      onTagDeleted(tag.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete tag.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Manage tags</DialogTitle>
          <DialogDescription>
            Rename or delete a tag here. Attach or detach one from a target directly on its row on the
            dashboard.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleCreate} className="flex gap-2">
          <Input
            placeholder="New tag name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={creating}
            aria-label="New tag name"
          />
          <Button type="submit" disabled={creating || !newName.trim()}>
            {creating ? "Adding…" : "Add"}
          </Button>
        </form>

        {error && (
          <p className="text-sm" style={{ color: "var(--signal-down)" }}>
            {error}
          </p>
        )}

        <div className="flex max-h-72 flex-col gap-2 overflow-y-auto">
          {loading ? (
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Loading…
            </p>
          ) : tags.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              No tags yet. Add one above.
            </p>
          ) : (
            tags.map((tag) => (
              <div
                key={tag.id}
                className="flex items-center gap-2 rounded-sm border p-2"
                style={{ borderColor: "var(--border)" }}
              >
                <Input
                  className="font-mono"
                  value={editValues[tag.id] ?? tag.name}
                  onChange={(e) => setEditValues((prev) => ({ ...prev, [tag.id]: e.target.value }))}
                  onBlur={() => handleRename(tag)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      (e.target as HTMLInputElement).blur();
                    } else if (e.key === "Escape") {
                      setEditValues((prev) => ({ ...prev, [tag.id]: tag.name }));
                      (e.target as HTMLInputElement).blur();
                    }
                  }}
                  disabled={savingId === tag.id}
                  aria-label={`Rename tag ${tag.name}`}
                />
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => handleDelete(tag)}
                  disabled={deletingId !== null}
                  aria-label={`Delete tag ${tag.name}`}
                >
                  {deletingId === tag.id ? "…" : "Delete"}
                </Button>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
