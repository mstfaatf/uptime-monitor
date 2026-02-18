"""Perform a single HTTP check: HEAD with GET fallback, measure latency, return result dict."""

import time
from datetime import datetime, timezone

import requests

from config import settings


def check_url(url: str) -> dict:
    """
    Perform HTTP HEAD (fallback GET), measure latency.
    Return dict: checked_at, status_code (int|None), latency_ms (int|None), is_up (bool), error (str|None).
    """
    checked_at = datetime.now(timezone.utc)
    timeout = settings.HTTP_TIMEOUT_SECONDS
    result = {
        "checked_at": checked_at,
        "status_code": None,
        "latency_ms": None,
        "is_up": False,
        "error": None,
    }
    try:
        # Prefer HEAD; fallback to GET on exception or 405 Method Not Allowed
        start = time.perf_counter()
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 405:
                resp = requests.get(url, timeout=timeout, allow_redirects=True)
        except (requests.RequestException, OSError):
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["status_code"] = resp.status_code
        result["latency_ms"] = elapsed_ms
        result["is_up"] = 200 <= resp.status_code < 400
    except requests.RequestException as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result
