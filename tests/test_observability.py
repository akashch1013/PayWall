import json
import logging
import sys
from collections.abc import Iterator

import pytest

from paywall.config import Settings
from paywall.observability import JsonFormatter, RequestIdFilter, configure_logging, request_id_var


def _record(**extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "paywall.api", "levelname": "INFO", "msg": "hi %s"})
    record.args = ("there",)
    record.__dict__.update(extra)
    RequestIdFilter().filter(record)
    return record


def test_json_lines_carry_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req_abc")
    try:
        line = JsonFormatter().format(_record(status=201, path="/v1/wallets/me"))
    finally:
        request_id_var.reset(token)

    entry = json.loads(line)
    assert entry["message"] == "hi there"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "paywall.api"
    assert entry["request_id"] == "req_abc"
    assert (entry["status"], entry["path"]) == (201, "/v1/wallets/me")
    assert entry["ts"].endswith("+00:00")


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record()
        record.exc_info = sys.exc_info()

    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc_info"]


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


@pytest.mark.usefixtures("restore_root_logger")
@pytest.mark.parametrize("log_json", [True, False])
def test_configure_logging(log_json: bool) -> None:
    configure_logging(Settings(database_url="postgresql+asyncpg://x/y", log_json=log_json))

    [handler] = logging.getLogger().handlers
    assert isinstance(handler.formatter, JsonFormatter) is log_json
    assert logging.getLogger().level == logging.INFO
