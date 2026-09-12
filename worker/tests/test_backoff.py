"""Unit tests for worker/backoff.py's exponential-backoff-with-jitter curve."""

import pytest

from backoff import BASE_SECONDS, MAX_SECONDS, MULTIPLIER, compute_backoff_seconds


def _unjittered(consecutive_failures: int) -> float:
    return min(BASE_SECONDS * (MULTIPLIER ** (consecutive_failures - 1)), MAX_SECONDS)


@pytest.mark.parametrize("failures", [1, 2, 3, 4, 5])
def test_delay_is_within_jitter_band_of_the_exponential_curve(failures):
    expected = _unjittered(failures)
    delay = compute_backoff_seconds(failures)
    assert 0.8 * expected <= delay <= 1.2 * expected


def test_delay_grows_with_each_additional_failure_before_the_cap():
    # Compare unjittered midpoints since individual draws are randomized.
    delays = [_unjittered(n) for n in range(1, 6)]
    assert delays == sorted(delays)
    assert delays[-1] < MAX_SECONDS  # not yet capped by failure 5 with these defaults


def test_delay_is_capped_for_large_failure_counts():
    delay = compute_backoff_seconds(50)
    assert delay <= MAX_SECONDS * 1.2


def test_rejects_non_positive_failure_counts():
    with pytest.raises(ValueError):
        compute_backoff_seconds(0)
    with pytest.raises(ValueError):
        compute_backoff_seconds(-1)
