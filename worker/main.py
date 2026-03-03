"""Worker: periodic HTTP checks for all targets, results stored in checks table."""

import logging
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from config import settings
from checker import check_url
from ssrf import is_url_blocked

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_targets(conn) -> list[dict]:
    """Return list of {id, url} for all targets."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, url FROM targets")
        return cur.fetchall()


def insert_check(conn, target_id: int, checked_at: datetime, status_code: int | None, latency_ms: int | None, is_up: bool, error: str | None) -> None:
    """Insert one row into checks."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (target_id, checked_at, status_code, latency_ms, is_up, error or None),
        )
    conn.commit()


def run_cycle(conn) -> None:
    """Fetch all targets, perform check (with SSRF guard), record each result."""
    targets = get_targets(conn)
    if not targets:
        logger.debug("No targets to check")
        return
    for row in targets:
        target_id = row["id"]
        url = row["url"]
        blocked, reason = is_url_blocked(url)
        if blocked:
            insert_check(
                conn,
                target_id=target_id,
                checked_at=datetime.now(timezone.utc),
                status_code=None,
                latency_ms=None,
                is_up=False,
                error=reason,
            )
            logger.info("Target %s blocked (SSRF): %s", target_id, reason)
            continue
        result = check_url(url)
        insert_check(
            conn,
            target_id=target_id,
            checked_at=result["checked_at"],
            status_code=result["status_code"],
            latency_ms=result["latency_ms"],
            is_up=result["is_up"],
            error=result["error"],
        )
        logger.info(
            "Target %s: %s %s ms is_up=%s %s",
            target_id,
            result["status_code"],
            result["latency_ms"],
            result["is_up"],
            result["error"] or "",
        )


def main() -> None:
    logger.info(
        "Worker starting (interval=%ss, timeout=%ss)",
        settings.CHECK_INTERVAL_SECONDS,
        settings.HTTP_TIMEOUT_SECONDS,
    )
    while True:
        try:
            conn = psycopg2.connect(settings.sync_database_url)
            try:
                run_cycle(conn)
            finally:
                conn.close()
        except Exception as e:
            logger.exception("Cycle failed: %s", e)
        time.sleep(settings.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
