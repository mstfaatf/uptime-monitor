import { cn } from "@/lib/utils";
import { LATENCY_GOOD_MS, LATENCY_WARN_MS, LATENCY_MAX_MS } from "@/lib/thresholds";

// Speedometer gauge for response time only — the one deliberate borrow from a second metaphor,
// used in exactly two places (dashboard summary tile, target detail view). See CLAUDE.md's
// Phase 3 design tokens for the locked geometry/threshold decisions.

const VIEWBOX_WIDTH = 220;
const VIEWBOX_HEIGHT = 170;
const CX = 110;
const CY = 110;
const ARC_R = 75;
const ARC_STROKE_WIDTH = 14;
const NEEDLE_LEN = ARC_R - 10;
const NEEDLE_BASE_HALF_WIDTH = 5;
const HUB_R = 7;

// 270° sweep opening at the bottom: 135° (lower-left) clockwise through the top to 45°/405°
// (lower-right), in the SVG y-down angle convention (0deg = +x, 90deg = +y/down).
const START_ANGLE = 135;
const SWEEP = 270;
const END_ANGLE = START_ANGLE + SWEEP;

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number): string {
  const start = polarToCartesian(cx, cy, r, startDeg);
  const end = polarToCartesian(cx, cy, r, endDeg);
  const largeArcFlag = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
}

function angleForValue(value: number, maxMs: number): number {
  const clamped = Math.min(Math.max(value, 0), maxMs);
  return START_ANGLE + (SWEEP * clamped) / maxMs;
}

const SIZE_PX: Record<"sm" | "md" | "lg", number> = {
  sm: 90,
  md: 140,
  lg: 190,
};

export interface LatencyGaugeProps {
  /** Latency in ms, or null for no data yet (pending). */
  value: number | null;
  /** Green-zone ceiling. Default matches the locked "healthy" latency. */
  goodMs?: number;
  /** Amber-zone ceiling — must match the degraded-state threshold (see CLAUDE.md). */
  warnMs?: number;
  /** Red-zone ceiling / needle full-scale value. */
  maxMs?: number;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function LatencyGauge({
  value,
  goodMs = LATENCY_GOOD_MS,
  warnMs = LATENCY_WARN_MS,
  maxMs = LATENCY_MAX_MS,
  size = "md",
  className,
}: LatencyGaugeProps) {
  const px = SIZE_PX[size];

  const goodAngle = angleForValue(goodMs, maxMs);
  const warnAngle = angleForValue(warnMs, maxMs);

  const needleAngle = value == null ? START_ANGLE : angleForValue(value, maxMs);
  const rotationDeg = needleAngle - START_ANGLE;

  const needleTip = polarToCartesian(CX, CY, NEEDLE_LEN, START_ANGLE);
  const needleBaseLeft = polarToCartesian(CX, CY, NEEDLE_BASE_HALF_WIDTH, START_ANGLE + 90);
  const needleBaseRight = polarToCartesian(CX, CY, NEEDLE_BASE_HALF_WIDTH, START_ANGLE - 90);

  const zoneColor =
    value == null
      ? "var(--signal-pending-text)" // small text — see globals.css's contrast note
      : value <= goodMs
        ? "var(--signal-up)"
        : value <= warnMs
          ? "var(--signal-warning)"
          : "var(--signal-down)";

  return (
    <span className={cn("inline-flex flex-col items-center gap-1", className)}>
      <svg
        width={px}
        height={(px * VIEWBOX_HEIGHT) / VIEWBOX_WIDTH}
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label={value == null ? "Latency: no data" : `Latency: ${Math.round(value)} milliseconds`}
      >
        <path
          d={arcPath(CX, CY, ARC_R, START_ANGLE, goodAngle)}
          fill="none"
          stroke="var(--signal-up)"
          strokeWidth={ARC_STROKE_WIDTH}
          strokeLinecap="butt"
        />
        <path
          d={arcPath(CX, CY, ARC_R, goodAngle, warnAngle)}
          fill="none"
          stroke="var(--signal-warning)"
          strokeWidth={ARC_STROKE_WIDTH}
          strokeLinecap="butt"
        />
        <path
          d={arcPath(CX, CY, ARC_R, warnAngle, END_ANGLE)}
          fill="none"
          stroke="var(--signal-down)"
          strokeWidth={ARC_STROKE_WIDTH}
          strokeLinecap="butt"
        />
        <g
          className="gauge-needle"
          style={{ transform: `rotate(${rotationDeg}deg)`, transformOrigin: `${CX}px ${CY}px` }}
          opacity={value == null ? 0.4 : 1}
        >
          <polygon
            points={`${needleBaseLeft.x},${needleBaseLeft.y} ${needleTip.x},${needleTip.y} ${needleBaseRight.x},${needleBaseRight.y}`}
            fill="var(--text-primary)"
          />
        </g>
        <circle cx={CX} cy={CY} r={HUB_R} fill="var(--bg-surface-raised)" stroke="var(--border)" strokeWidth={1} />
      </svg>
      <span className="font-mono text-sm" style={{ color: zoneColor }}>
        {value == null ? "—" : `${Math.round(value)} ms`}
      </span>
    </span>
  );
}
