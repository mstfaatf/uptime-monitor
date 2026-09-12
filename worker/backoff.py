"""Exponential backoff with jitter for per-target check scheduling.

Only used to decide how long to wait before *retrying* a target after a failed check. A
successful check always returns the target to the normal CHECK_INTERVAL_SECONDS cadence —
see main.py's reschedule_target().
"""

import random

# Curve: BASE_SECONDS * MULTIPLIER^(failures-1), capped at MAX_SECONDS, then jittered by
# +/- JITTER_FRACTION. With the defaults below: 1 failure -> 30s, 2 -> 60s, 3 -> 120s,
# 4 -> 240s, 5 -> 480s, 6+ -> capped at 900s (15 min), each +/- 20%.
BASE_SECONDS = 30
MULTIPLIER = 2
MAX_SECONDS = 900
JITTER_FRACTION = 0.2


def compute_backoff_seconds(consecutive_failures: int) -> float:
    """
    Return the number of seconds to wait before the next check, given how many checks in a
    row have failed (including the one that just failed — must be >= 1).

    Exponential growth capped at MAX_SECONDS, then jittered by +/- JITTER_FRACTION so that
    targets which start failing around the same time (e.g. a shared upstream DNS blip) don't
    all retry in lockstep forever, and so a single down target doesn't get hammered on a
    perfectly predictable schedule.
    """
    if consecutive_failures < 1:
        raise ValueError("consecutive_failures must be >= 1")
    exp_delay = min(BASE_SECONDS * (MULTIPLIER ** (consecutive_failures - 1)), MAX_SECONDS)
    jitter = exp_delay * JITTER_FRACTION
    return exp_delay + random.uniform(-jitter, jitter)
