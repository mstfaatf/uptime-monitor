import { SignalLight } from "@/components/signal-light";

/**
 * A clearly-marked stand-in for a real product screenshot, used on pages built before the
 * screenshot pass. Deliberately unambiguous — a dashed border and "pending" microcopy, reusing
 * SignalLight's own "pending" state rather than inventing a second placeholder icon, so nobody
 * mistakes this for a broken image or real content.
 */
export function ScreenshotPlaceholder({ caption }: { caption: string }) {
  return (
    <div
      className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded border border-dashed px-6 text-center"
      style={{ borderColor: "var(--border)", background: "var(--bg-surface)" }}
    >
      <SignalLight state="pending" size="sm" />
      <p className="font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
        Screenshot pending: {caption}
      </p>
    </div>
  );
}
