"""Process-wide logging: DEBUG and INFO to stdout, WARNING and above to stderr.

Railway (like most log viewers) shows everything written to stderr as an error, so routine INFO
lines must go to stdout. configure_logging() puts one stdout handler (records below WARNING)
and one stderr handler (WARNING and above) on the root logger, so every record reaches exactly
one of them and nothing is printed twice.

httpx and httpcore are limited to WARNING. At INFO, httpx logs a line for every request,
including the /internal/watching poll every 15 to 30 seconds; the worker's own per-check line
("[region=...] Target N: ...") already records every check, and the watching probe logs its own
warnings (401, 404, timeouts), so nothing useful is lost. Neither logs request headers, so the
internal secret can't appear.

backend/logging_setup.py is the API's copy of the level-splitting part (the services are
deployed separately), kept in sync by hand like the other cross-service duplicates.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

QUIET_LIBRARY_LOGGERS = ("httpx", "httpcore")


class _BelowWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


class _CurrentStreamHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout / sys.stderr is at emit time, not at setup time, so
    output captured or redirected later (pytest, a supervisor) still receives it."""

    def __init__(self, stream_name: str):
        super().__init__()
        self._stream_name = stream_name

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = getattr(sys, self._stream_name)
        super().emit(record)


def _is_replaceable(handler: logging.Handler) -> bool:
    """Plain console handlers (from basicConfig or an earlier call to this function) are
    replaced. Anything else, such as pytest's capture handlers, is left."""
    return type(handler) is logging.StreamHandler or isinstance(handler, _CurrentStreamHandler)


def configure_logging(log_format: str = LOG_FORMAT) -> None:
    """Idempotent: safe to call more than once."""
    formatter = logging.Formatter(log_format)

    stdout_handler = _CurrentStreamHandler("stdout")
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_BelowWarning())
    stdout_handler.setFormatter(formatter)

    stderr_handler = _CurrentStreamHandler("stderr")
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    root = logging.getLogger()
    for handler in [h for h in root.handlers if _is_replaceable(h)]:
        root.removeHandler(handler)
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)
    root.setLevel(logging.INFO)

    for name in QUIET_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
