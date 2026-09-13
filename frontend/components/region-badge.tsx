export function RegionBadge({ region }: { region: string }) {
  return (
    <span
      className="rounded border px-1.5 py-0.5 font-mono text-xs"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
    >
      {region}
    </span>
  );
}
