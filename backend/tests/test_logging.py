"""logging_setup.configure_logging: INFO to stdout, WARNING+ to stderr, no duplicates, uvicorn
routed the same way, and the workers' /internal/watching polls kept out of the access log."""

import logging
import logging.config

import uvicorn.config

import logging_setup
from config import settings
from logging_setup import configure_logging


def _access_line(path: str) -> None:
    """Log exactly what uvicorn's access logger logs for a request."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "203.0.113.7:51000", "GET", path, "1.1", 200
    )


def test_info_goes_to_stdout_and_warning_to_stderr(capsys):
    configure_logging()
    log = logging.getLogger("tests.logging_split")
    log.info("routine-info-line")
    log.warning("real-warning-line")
    log.error("real-error-line")

    out, err = capsys.readouterr()
    assert out.count("routine-info-line") == 1 and "routine-info-line" not in err
    assert err.count("real-warning-line") == 1 and "real-warning-line" not in out
    assert err.count("real-error-line") == 1 and "real-error-line" not in out
    assert "[INFO] tests.logging_split: routine-info-line" in out  # existing format kept


def test_uvicorns_own_loggers_follow_the_same_split_without_duplicates(capsys):
    # Uvicorn applies its own logging config (handlers that send its INFO lines to stderr)
    # before importing the app; configure_logging runs after that, at app import.
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    configure_logging()

    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("uvicorn.error").warning("uvicorn-warning-line")
    _access_line("/health")

    out, err = capsys.readouterr()
    assert out.count("Application startup complete.") == 1
    assert "Application startup complete." not in err
    assert err.count("uvicorn-warning-line") == 1
    assert out.count('"GET /health HTTP/1.1" 200') == 1


def test_calling_configure_twice_adds_no_extra_handlers(capsys):
    configure_logging()
    configure_logging()
    root_handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging_setup._CurrentStreamHandler)]
    assert len(root_handlers) == 2
    access_filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, logging_setup.QuietAccessPathFilter)]
    assert len(access_filters) == 1

    logging.getLogger("tests.logging_twice").info("only-once")
    out, _ = capsys.readouterr()
    assert out.count("only-once") == 1


def test_internal_watching_is_left_out_of_the_access_log(capsys):
    configure_logging()
    _access_line("/internal/watching")
    _access_line("/internal/watching?probe=1")
    _access_line("/targets/status")
    _access_line("/internal/watching-something-else")

    out, err = capsys.readouterr()
    assert "/internal/watching HTTP" not in out + err
    assert "/internal/watching?probe=1" not in out + err
    assert out.count('"GET /targets/status HTTP/1.1" 200') == 1
    assert out.count("/internal/watching-something-else") == 1  # only the exact path is quiet


async def test_polling_the_endpoint_never_logs_the_secret_or_headers(client, monkeypatch, capsys, caplog):
    secret = "a-very-distinctive-internal-secret"
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", secret)
    configure_logging()
    caplog.set_level(logging.DEBUG)

    assert (await client.get("/internal/watching", headers={"X-Internal-Secret": secret})).status_code == 200
    assert (await client.get("/internal/watching", headers={"X-Internal-Secret": "wrong"})).status_code == 401

    out, err = capsys.readouterr()
    everything = out + err + caplog.text
    assert secret not in everything
    assert "X-Internal-Secret" not in everything
    # The endpoint itself logs nothing at INFO or above.
    assert not [r for r in caplog.records if r.name.startswith(("routers", "realtime", "activity"))]
