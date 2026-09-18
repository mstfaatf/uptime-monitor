import { cn } from "@/lib/utils";

/**
 * A small family of network/infrastructure glyphs used on the Features page to give each
 * feature group its own visual identity — an extension of the same instrument-panel
 * vocabulary SignalLight/LatencyGauge already established (a bordered housing on
 * --bg-surface-raised, muted --text-secondary linework, one --signal-up accent for "pop"),
 * not a new icon system. Kept deliberately small and schematic rather than illustrative —
 * simple geometric strokes, no gradients/shadows, only locked palette tokens.
 */

const HOUSING_VIEWBOX = 32;

interface GlyphProps {
  size?: number;
  className?: string;
}

function Housing({ size = 32, className, children }: GlyphProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${HOUSING_VIEWBOX} ${HOUSING_VIEWBOX}`}
      role="img"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <rect
        x={1}
        y={1}
        width={HOUSING_VIEWBOX - 2}
        height={HOUSING_VIEWBOX - 2}
        rx={4}
        fill="var(--bg-surface-raised)"
        stroke="var(--border)"
        strokeWidth={1}
      />
      {children}
    </svg>
  );
}

/** A small server rack — used for the foundation/security group. */
export function DataCenterGlyph({ size, className }: GlyphProps) {
  return (
    <Housing size={size} className={className}>
      {[9, 16, 23].map((y, i) => (
        <g key={y}>
          <rect
            x={8}
            y={y - 2.5}
            width={16}
            height={5}
            rx={1}
            fill="none"
            stroke="var(--text-secondary)"
            strokeWidth={1.3}
          />
          <circle cx={10.5} cy={y} r={1} fill={i === 2 ? "var(--signal-up)" : "var(--text-secondary)"} />
        </g>
      ))}
    </Housing>
  );
}

/** Two independent masts with a signal arc between them — used for multi-region coordination. */
export function AntennaGlyph({ size, className }: GlyphProps) {
  return (
    <Housing size={size} className={className}>
      <line x1={11} y1={23} x2={11} y2={11} stroke="var(--text-secondary)" strokeWidth={1.3} />
      <circle cx={11} cy={9.5} r={1.7} fill="var(--text-secondary)" />
      <line x1={21} y1={23} x2={21} y2={8} stroke="var(--text-secondary)" strokeWidth={1.3} />
      <circle cx={21} cy={6.5} r={1.7} fill="var(--text-secondary)" />
      <path
        d="M 13 10.5 Q 16 5.5 19 7.5"
        fill="none"
        stroke="var(--signal-up)"
        strokeWidth={1.3}
        strokeDasharray="1.5 2"
        strokeLinecap="round"
      />
    </Housing>
  );
}

/** A router body with radiating wifi arcs — used for alerting + compliance export (signals going out). */
export function RouterGlyph({ size, className }: GlyphProps) {
  return (
    <Housing size={size} className={className}>
      <rect x={9} y={18} width={14} height={6.5} rx={1.5} fill="none" stroke="var(--text-secondary)" strokeWidth={1.3} />
      <circle cx={12.5} cy={21.25} r={0.9} fill="var(--signal-up)" />
      <line x1={13} y1={18} x2={13} y2={13} stroke="var(--text-secondary)" strokeWidth={1.3} />
      <line x1={19} y1={18} x2={19} y2={12} stroke="var(--text-secondary)" strokeWidth={1.3} />
      <path d="M 9.5 11 A 7 7 0 0 1 16 8" fill="none" stroke="var(--signal-up)" strokeWidth={1.2} strokeLinecap="round" />
      <path d="M 6.5 8.5 A 11 11 0 0 1 16 4.5" fill="none" stroke="var(--text-secondary)" strokeWidth={1.1} strokeLinecap="round" opacity={0.7} />
    </Housing>
  );
}

/** A signal-strength meter (ascending bars) — used for the broader feature-addition group. */
export function SignalBarsGlyph({ size, className }: GlyphProps) {
  const bars = [
    { x: 9, h: 4 },
    { x: 13, h: 7.5 },
    { x: 17, h: 11 },
    { x: 21, h: 14.5 },
  ];
  return (
    <Housing size={size} className={className}>
      {bars.map((bar, i) => (
        <rect
          key={bar.x}
          x={bar.x}
          y={24 - bar.h}
          width={2.6}
          height={bar.h}
          rx={0.8}
          fill={i === bars.length - 1 ? "var(--signal-up)" : "var(--text-secondary)"}
          opacity={i === bars.length - 1 ? 1 : 0.6 + i * 0.1}
        />
      ))}
    </Housing>
  );
}

/**
 * The larger, standalone illustration for the networking-depth entry: a mast with a lit
 * beacon and three concentric pulse arcs, fading outward — the one deliberately bigger
 * illustration on this page, everything else stays small and marginal.
 */
export function SignalPulseIllustration({ size = 120, className }: GlyphProps) {
  const cx = 60;
  const beaconY = 34;
  const arcs = [
    { r: 16, opacity: 1 },
    { r: 27, opacity: 0.55 },
    { r: 38, opacity: 0.28 },
  ];
  return (
    <svg
      width={size}
      height={(size * 100) / 120}
      viewBox="0 0 120 100"
      role="img"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <line x1={cx} y1={90} x2={cx} y2={beaconY} stroke="var(--text-secondary)" strokeWidth={1.5} />
      <line x1={44} y1={90} x2={76} y2={90} stroke="var(--border)" strokeWidth={2} strokeLinecap="round" />
      {arcs.map((arc) => (
        <path
          key={arc.r}
          d={`M ${cx - arc.r} ${beaconY} A ${arc.r} ${arc.r} 0 0 1 ${cx + arc.r} ${beaconY}`}
          fill="none"
          stroke="var(--signal-up)"
          strokeWidth={1.6}
          opacity={arc.opacity}
        />
      ))}
      <circle cx={cx} cy={beaconY} r={4.5} fill="var(--signal-up)" />
      <circle cx={cx} cy={beaconY} r={4.5} fill="none" stroke="var(--bg-base)" strokeWidth={1} />
    </svg>
  );
}
