"""Request ids and logging.

``request_id_var`` holds the id of the API request being handled. It is set by the API layer and
read wherever a record should be traceable back to that request: ledger entries, outbox events
and log lines. Outside a request (Python API, CLI) it is None.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from paywall.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("paywall_request_id", default=None)

# Attributes every LogRecord has; anything else on a record came from ``extra=``.
_RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class RequestIdFilter(logging.Filter):
    """Stamp each record with the current request id, so any formatter can print it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message, plus any ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS})
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(settings: Settings) -> None:
    """Send all logs to stderr, as JSON lines unless ``PAYWALL_LOG_JSON=false``.

    Used by the standalone server. An embedding host keeps its own logging setup; PayWall's
    records still carry ``request_id`` as an attribute for its formatters to use.
    """
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if settings.log_json
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
