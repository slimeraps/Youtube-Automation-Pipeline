import structlog

from yt_auto.logging import configure_logging, get_logger


def test_get_logger_returns_structlog_bound_logger() -> None:
    configure_logging(level="INFO")
    log = get_logger("test")
    assert isinstance(log, structlog.stdlib.BoundLogger) or hasattr(log, "info")


def test_configure_logging_is_idempotent() -> None:
    configure_logging(level="INFO")
    configure_logging(level="DEBUG")
    log = get_logger("test")
    log.info("hello", x=1)  # must not raise
