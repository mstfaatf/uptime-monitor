import { cn } from "@/lib/utils";

/**
 * A family of network/infrastructure glyphs and illustrations — an extension of the same
 * instrument-panel vocabulary SignalLight/LatencyGauge already established (a bordered housing
 * on --bg-surface-raised where relevant, muted --text-secondary linework, one --signal-up
 * accent for "pop"), not a new icon system. The small, housed glyphs (Data Center/Antenna/
 * Router/SignalBars) sit next to Features page headings; the larger standalone illustrations
 * (CellTower, DataCenter, SignalPulse) anchor specific concepts on the Architecture page.
 * Simple geometric strokes throughout — no gradients/shadows, only locked palette tokens.
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
 * A larger, standalone lattice cell tower — used on the Architecture page's multi-region
 * section, one per region, always paired with a real <SignalLight> next to it for that
 * region's actual live state (the tower itself stays neutral linework; it represents the
 * infrastructure, not the reading). The beacon at the top is a fixed --signal-up accent
 * (broadcasting), not a state indicator — deliberately not a second place this page encodes
 * up/down/degraded, so there's only ever one source of truth for state on the page.
 */
export function CellTowerIllustration({ size = 90, className }: GlyphProps) {
  const legTopX = 60;
  const legTopY = 46;
  const legBottomLeftX = 40;
  const legBottomRightX = 80;
  const baseY = 128;
  const braceYs = [112, 94, 76, 60];

  function xAtY(y: number, fromX: number) {
    const t = (baseY - y) / (baseY - legTopY);
    return fromX + (legTopX - fromX) * t;
  }

  return (
    <svg
      width={size}
      height={(size * 140) / 120}
      viewBox="0 0 120 140"
      role="img"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <line x1={legBottomLeftX} y1={baseY} x2={legTopX} y2={legTopY} stroke="var(--text-secondary)" strokeWidth={1.6} />
      <line x1={legBottomRightX} y1={baseY} x2={legTopX} y2={legTopY} stroke="var(--text-secondary)" strokeWidth={1.6} />
      {braceYs.map((y) => (
        <line
          key={y}
          x1={xAtY(y, legBottomLeftX)}
          y1={y}
          x2={xAtY(y, legBottomRightX)}
          y2={y}
          stroke="var(--border)"
          strokeWidth={1.3}
        />
      ))}
      <line x1={30} y1={baseY} x2={90} y2={baseY} stroke="var(--border)" strokeWidth={2.5} strokeLinecap="round" />
      <line x1={legTopX} y1={legTopY} x2={legTopX} y2={20} stroke="var(--text-secondary)" strokeWidth={1.6} />
      <line x1={46} y1={30} x2={74} y2={30} stroke="var(--text-secondary)" strokeWidth={1.6} strokeLinecap="round" />
      <line x1={50} y1={38} x2={70} y2={38} stroke="var(--text-secondary)" strokeWidth={1.6} strokeLinecap="round" />
      <circle cx={legTopX} cy={17} r={3.5} fill="var(--signal-up)" />
    </svg>
  );
}

/**
 * A larger, standalone server rack pair — anchors the Postgres/Neon node in the Architecture
 * page's system diagram. Two racks so it reads as "a data center," not one lone server.
 */
export function DataCenterIllustration({ size = 110, className }: GlyphProps) {
  function Rack({ x, litIndex }: { x: number; litIndex: number }) {
    const slots = [0, 1, 2, 3, 4];
    return (
      <g>
        <rect x={x} y={18} width={34} height={84} rx={2} fill="var(--bg-surface-raised)" stroke="var(--border)" strokeWidth={1.4} />
        {slots.map((i) => {
          const y = 26 + i * 15;
          return (
            <g key={i}>
              <line x1={x + 5} y1={y} x2={x + 29} y2={y} stroke="var(--border)" strokeWidth={1} />
              <circle cx={x + 8} cy={y + 7} r={1.4} fill={i === litIndex ? "var(--signal-up)" : "var(--text-secondary)"} />
            </g>
          );
        })}
      </g>
    );
  }

  return (
    <svg
      width={size}
      height={(size * 120) / 140}
      viewBox="0 0 140 120"
      role="img"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <Rack x={22} litIndex={2} />
      <Rack x={84} litIndex={4} />
      <line x1={39} y1={102} x2={101} y2={102} stroke="var(--border)" strokeWidth={1.4} />
      <line x1={39} y1={107} x2={39} y2={102} stroke="var(--border)" strokeWidth={1.4} />
      <line x1={101} y1={107} x2={101} y2={102} stroke="var(--border)" strokeWidth={1.4} />
    </svg>
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
