"use client";

import { SIGNAL_STATE_LABELS, type SignalState } from "@/components/signal-light";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Tag } from "@/lib/types";

export type SortKey = "default" | "name" | "status" | "latency" | "lastChecked";

const SORT_LABELS: Record<SortKey, string> = {
  default: "Default order",
  name: "Name",
  status: "Status",
  latency: "Latency",
  lastChecked: "Last checked",
};

// Plain native <select>s, styled to match Input's own border/token treatment, rather than
// pulling in a second Radix dependency (a Select primitive) for what's a handful of small
// dropdowns — Dialog earned its dependency in 6.12 by being genuinely hard to build correctly
// by hand (focus trap, portal, Escape handling); a <select> has none of that difficulty.
function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border bg-transparent px-2 py-1.5 font-mono text-sm"
        style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} style={{ background: "var(--bg-surface)", color: "var(--text-primary)" }}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export interface TargetFilterBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: SignalState | "all";
  onStatusFilterChange: (value: SignalState | "all") => void;
  regionFilter: string;
  onRegionFilterChange: (value: string) => void;
  regions: string[];
  tagFilter: number | "all";
  onTagFilterChange: (value: number | "all") => void;
  tags: Tag[];
  sortBy: SortKey;
  onSortByChange: (value: SortKey) => void;
  onManageTags: () => void;
  manageTagsButtonRef: React.RefObject<HTMLButtonElement>;
  onReset: () => void;
  hasActiveFilters: boolean;
}

export function TargetFilterBar({
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  regionFilter,
  onRegionFilterChange,
  regions,
  tagFilter,
  onTagFilterChange,
  tags,
  sortBy,
  onSortByChange,
  onManageTags,
  manageTagsButtonRef,
  onReset,
  hasActiveFilters,
}: TargetFilterBarProps) {
  return (
    <div
      className="mt-3 flex flex-wrap items-end gap-4 rounded border p-4"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
        Search
        <Input
          type="search"
          placeholder="Name or URL"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="h-auto py-1.5 text-sm"
        />
      </label>

      <FilterSelect
        label="Status"
        value={statusFilter}
        onChange={(v) => onStatusFilterChange(v as SignalState | "all")}
        options={[
          { value: "all", label: "All statuses" },
          ...(["up", "degraded", "down", "pending"] as SignalState[]).map((s) => ({
            value: s,
            label: SIGNAL_STATE_LABELS[s],
          })),
        ]}
      />

      <FilterSelect
        label="Region"
        value={regionFilter}
        onChange={onRegionFilterChange}
        options={[{ value: "all", label: "All regions" }, ...regions.map((r) => ({ value: r, label: r }))]}
      />

      <FilterSelect
        label="Tag"
        value={tagFilter === "all" ? "all" : String(tagFilter)}
        onChange={(v) => onTagFilterChange(v === "all" ? "all" : Number(v))}
        options={[
          { value: "all", label: "All tags" },
          ...tags.map((t) => ({ value: String(t.id), label: t.name })),
        ]}
      />

      <FilterSelect
        label="Sort by"
        value={sortBy}
        onChange={(v) => onSortByChange(v as SortKey)}
        options={(Object.keys(SORT_LABELS) as SortKey[]).map((key) => ({ value: key, label: SORT_LABELS[key] }))}
      />

      <div className="ml-auto flex items-center gap-3">
        {hasActiveFilters && (
          <Button type="button" variant="outline" size="sm" onClick={onReset}>
            Reset
          </Button>
        )}
        <Button type="button" variant="outline" size="sm" onClick={onManageTags} ref={manageTagsButtonRef}>
          Manage tags
        </Button>
      </div>
    </div>
  );
}
