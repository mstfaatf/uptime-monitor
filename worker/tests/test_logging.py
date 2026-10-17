"""logging_setup.configure_logging: INFO to stdout, WARNING+ to stderr, and the watching poll
produces no INFO lines while its own warnings still appear."""

import logging

import httpx

import logging_setup
from logging_setup import configure_logging
from watching import WatchingProbe

SECRET = "a-very-distinctive-internal-secret"


def _probe(status: int, body=None) -> WatchingProbe:
    def handler(request):
        return httpx.Response(status, json=body if body is not None else {"watching": False})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WatchingProbe("http://backend.test", SECRET, client, clock=lambda: 0.0)


def test_info_goes_to_stdout_and_warning_to_stderr(capsys):
    configure_logging()
    log = logging.getLogger("tests.logging_split")
    log.info("routine-info-line")
    log.warning("real-warning-line")

    out, err = capsys.readouterr()
    assert out.count("routine-info-line") == 1 and "routine-info-line" not in err
    assert err.count("real-warning-line") == 1 and "real-warning-line" not in out
    assert "[INFO] routine-info-line" in out  # existing format kept


def test_calling_configure_twice_adds_no_extra_handlers(capsys):
    configure_logging()
    configure_logging()
    ours = [h for h in logging.getLogger().handlers if isinstance(h, logging_setup._CurrentStreamHandler)]
    assert len(ours) == 2
    logging.getLogger("tests.logging_twice").info("only-once")
    out, _ = capsys.readouterr()
    assert out.count("only-once") == 1


async def test_the_watching_poll_produces_no_info_lines(capsys):
    configure_logging()

    # Control: with httpx at INFO this same poll does log a request line, so the assertion
    # below would catch a regression.
    logging.getLogger("httpx").setLevel(logging.INFO)
    await _probe(200)()
    out, _ = capsys.readouterr()
    assert "HTTP Request: GET http://backend.test/internal/watching" in out

    configure_logging()  # back to WARNING for httpx/httpcore
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert await _probe(200, {"watching": True})() is True
    assert await _probe(200)() is False
    out, err = capsys.readouterr()
    assert out == "" and err == ""


async def test_watching_poll_warnings_still_appear_on_stderr(capsys):
    configure_logging()
    assert await _probe(401)() is False
    assert await _probe(404)() is False

    def timeout(request):
        raise httpx.ReadTimeout("timed out")

    timing_out = WatchingProbe(
        "http://backend.test", SECRET, httpx.AsyncClient(transport=httpx.MockTransport(timeout)), clock=lambda: 0.0
    )
    assert await timing_out() is False

    out, err = capsys.readouterr()
    assert out == ""
    assert "returned HTTP 401" in err
    assert "returned HTTP 404" in err
    assert "timed out" in err
    assert SECRET not in err
