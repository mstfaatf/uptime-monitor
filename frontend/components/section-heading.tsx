// Shared H2 treatment for a page's top-level content sections: --signal-up, the same "green
// means it's real and it works" vocabulary the dashboard already uses. Used by the landing
// page, /architecture, and /engineering; /features applies the identical style inline inside
// its own FeatureGroup heading row instead of importing this, since that component already
// owns its heading markup for other reasons.
export function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xl font-semibold" style={{ color: "var(--signal-up)" }}>
      {children}
    </h2>
  );
}
