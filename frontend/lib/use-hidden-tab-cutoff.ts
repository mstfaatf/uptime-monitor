"use client";

import { useEffect, useState } from "react";

// How long a tab can stay hidden before the dashboard closes its live stream. An open stream
// tells the backend someone is watching, which keeps the checkers running continuously and the
// database awake; a tab left open in the background all day shouldn't count as watching. Short
// hides (switching tabs for a minute) keep the stream, so there's no reconnect churn.
export const HIDDEN_TAB_CUTOFF_MS = 3 * 60 * 1000;

// True while the page should hold its live connection: the tab is visible, or has been hidden
// for less than cutoffMs. Flips to false once the tab has been hidden past the cutoff, and back
// to true as soon as it's visible again. A page that first loads in a background tab starts
// the countdown immediately.
export function useHiddenTabCutoff(cutoffMs: number = HIDDEN_TAB_CUTOFF_MS): boolean {
  const [active, setActive] = useState(true);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };
    const onVisibilityChange = () => {
      clearTimer();
      if (document.visibilityState === "hidden") {
        timer = setTimeout(() => {
          timer = null;
          setActive(false);
        }, cutoffMs);
      } else {
        setActive(true);
      }
    };

    onVisibilityChange();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [cutoffMs]);

  return active;
}
