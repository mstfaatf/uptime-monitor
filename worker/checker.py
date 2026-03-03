"""Perform a single HTTP check: HEAD first, retry once with GET if HEAD fails or status >= 400."""

import time
from datetime import datetime, timezone

import certifi
import requests

from config import settings


def check_url(url: str) -> dict:
    """
    Attempt HEAD first; if HEAD fails or returns >= 400, retry once with GET.
    Record latency_ms and status_code from the successful attempt.
    Return dict: checked_at, status_code (int|None), latency_ms (int|None), is_up (bool), error (str|None).
    """
    checked_at = datetime.now(timezone.utc)
    timeout = settings.HTTP_TIMEOUT_SECONDS
    verify = certifi.where()
    result = {
        "checked_at": checked_at,
        "status_code": None,
        "latency_ms": None,
        "is_up": False,
        "error": None,
    }
    try:
        start = time.perf_counter()
        resp = None
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True, verify=verify)
            if resp.status_code >= 400:
                resp = requests.get(url, timeout=timeout, allow_redirects=True, verify=verify)
        except (requests.RequestException, OSError):
            resp = requests.get(url, timeout=timeout, allow_redirects=True, verify=verify)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["status_code"] = resp.status_code
        result["latency_ms"] = elapsed_ms
        result["is_up"] = 200 <= resp.status_code < 400
    except requests.RequestException as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result
