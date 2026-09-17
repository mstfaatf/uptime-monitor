import { SignalLight } from "@/components/signal-light";
import { cn } from "@/lib/utils";

// One shared "nothing here yet" treatment, used both for a brand-new account's empty dashboard
// and for the detail page's chart/heatmap/timeline sections before any check has landed — the
// same pending SignalLight + short copy vocabulary already established for the dashboard's own
// empty state (3.5), not a new visual pattern invented for this prompt.
//
// `size="sm"` is deliberately borderless: it's meant to sit inside a section that's already
// inside its own bordered panel (Latency/Timing breakdown/Uptime on the detail page) — wrapping
// it in a second dashed border would nest one box inside another for no reason. `"md"`/`"lg"`
// get the dashed-border treatment, for a standalone/page-level empty state with nothing else
// around it to frame it.
export interface EmptyStateProps {
  title: string;
  description?: string;
  size?: "sm" | "md" | "lg";
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, description, size = "md", action, className }: EmptyStateProps) {
  const iconSize = size === "sm" ? "sm" : size === "md" ? "md" : "lg";

  const content = (
    <>
      <SignalLight state="pending" size={iconSize} />
      <p className={size === "sm" ? "text-sm font-medium" : "font-semibold"}>{title}</p>
      {description && (
        <p
          className={cn("max-w-sm", size === "sm" ? "text-xs" : "text-sm")}
          style={{ color: "var(--text-secondary)" }}
        >
          {description}
        </p>
      )}
      {action}
    </>
  );

  if (size === "sm") {
    return <div className={cn("flex flex-col items-center gap-2 py-6 text-center", className)}>{content}</div>;
  }

  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded border border-dashed text-center",
        size === "lg" ? "p-12" : "p-8",
        className
      )}
      style={{ borderColor: "var(--border)" }}
    >
      {content}
    </div>
  );
}
