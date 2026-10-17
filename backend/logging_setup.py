"""Process-wide logging: DEBUG and INFO to stdout, WARNING and above to stderr.

Railway (like most log viewers) shows everything written to stderr as an error, so routine INFO
lines must go to stdout. configure_logging() puts one stdout handler (records below WARNING)
and one stderr handler (WARNING and above) on the root logger, and points uvicorn's own
loggers at them instead of uvicorn's default handlers, which send all of uvicorn's INFO lines
to stderr. Every logger then reaches exactly one handler, so nothing is printed twice.

The uvicorn access log skips GET /internal/watching: the workers poll it every 15 to 30
seconds, and those lines would drown out real traffic. Access lines contain only the client
address, method, path and status, never request headers, so the internal secret can't appear.

worker/logging_setup.py is a deliberate copy of the level-splitting part (the services are
deployed separately), kept in sync by hand like the other cross-service duplicates.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Excluded from the uvicorn access log; see the module docstring.
QUIET_ACCESS_PATHS = frozenset({"/internal/watching"})

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


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


class QuietAccessPathFilter(logging.Filter):
    """Drops uvicorn access log records for QUIET_ACCESS_PATHS. Uvicorn logs each request as
    ('%s - "%s %s HTTP/%s" %d', client, method, path_with_query, http_version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            return args[2].split("?", 1)[0] not in QUIET_ACCESS_PATHS
        return True


def _is_replaceable(handler: logging.Handler) -> bool:
    """Plain console handlers (from basicConfig, Alembic's fileConfig, or an earlier call to
    this function) are replaced. Anything else, such as pytest's capture handlers, is left."""
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

    # Uvicorn configures these before importing the app; send them through the root handlers
    # instead, so its INFO lines go to stdout too.
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        for handler in [h for h in uvicorn_logger.handlers if _is_replaceable(h)]:
            uvicorn_logger.removeHandler(handler)
        uvicorn_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietAccessPathFilter) for f in access_logger.filters):
        access_logger.addFilter(QuietAccessPathFilter())
