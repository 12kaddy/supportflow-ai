import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

request_id = ContextVar("supportflow_request_id", default=None)
logger = logging.getLogger("supportflow.telemetry")


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def emit(event, **fields):
    logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "request_id": request_id.get(),
                **fields,
            }
        )
    )
