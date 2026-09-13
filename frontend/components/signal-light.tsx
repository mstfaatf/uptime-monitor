import { cn } from "@/lib/utils";

export type SignalState = "up" | "degraded" | "down" | "pending";

const LABELS: Record<SignalState, string> = {
  up: "Reporting up",
  degraded: "Degraded",
  down: "No signal",
  pending: "Pending",
};

// Which dot is lit for a given state — top=red/down, middle=amber/degraded,
// bottom=green/up, none lit for pending. See CLAUDE.md's Phase 3 design tokens.
const HOT_DOT: Record<SignalState, "top" | "middle" | "bottom" | null> = {
  down: "top",
  degraded: "middle",
  up: "bottom",
  pending: null,
};

const SIZE_PX: Record<"sm" | "md" | "lg", { width: number; height: number }> = {
  sm: { width: 14, height: 38 },
  md: { width: 20, height: 54 },
  lg: { width: 28, height: 76 },
};

// Fixed internal geometry — every size scales the same artwork via the SVG's width/height
// rather than redrawing it, so the three-dot proportions never drift between sizes.
const VIEWBOX_WIDTH = 24;
const VIEWBOX_HEIGHT = 68;
const CX = 12;
const DOT_R = 6;
const DOT_CY = { top: 15, middle: 34, bottom: 53 } as const;

const DIM_OPACITY = 0.22;
const LIT_OPACITY = 1;

export interface SignalLightProps {
  state: SignalState;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
  className?: string;
}

export function SignalLight({ state, size = "md", showLabel = false, className }: SignalLightProps) {
  const hot = HOT_DOT[state];
  const { width, height } = SIZE_PX[size];

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label={LABELS[state]}
      >
        <rect
          x={1}
          y={1}
          width={VIEWBOX_WIDTH - 2}
          height={VIEWBOX_HEIGHT - 2}
          rx={3}
          ry={3}
          fill="var(--bg-surface-raised)"
          stroke="var(--border)"
          strokeWidth={1}
        />
        <circle
          className="signal-dot"
          cx={CX}
          cy={DOT_CY.top}
          r={DOT_R}
          fill="var(--signal-down)"
          style={{ opacity: hot === "top" ? LIT_OPACITY : DIM_OPACITY }}
        />
        <circle
          className="signal-dot"
          cx={CX}
          cy={DOT_CY.middle}
          r={DOT_R}
          fill="var(--signal-warning)"
          style={{ opacity: hot === "middle" ? LIT_OPACITY : DIM_OPACITY }}
        />
        <circle
          className="signal-dot"
          cx={CX}
          cy={DOT_CY.bottom}
          r={DOT_R}
          fill="var(--signal-up)"
          style={{ opacity: hot === "bottom" ? LIT_OPACITY : DIM_OPACITY }}
        />
      </svg>
      {showLabel && (
        <span className="font-mono text-sm" style={{ color: "var(--text-secondary)" }}>
          {LABELS[state]}
        </span>
      )}
    </span>
  );
}
