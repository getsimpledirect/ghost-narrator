import logging
import sys
import json
from typing import Any, Dict, Optional
from contextvars import ContextVar
from datetime import datetime
import uuid

correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
job_id: ContextVar[Optional[str]] = ContextVar('job_id', default=None)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.name,
        }

        corr_id = correlation_id.get()
        if corr_id:
            log_data['correlation_id'] = corr_id

        j_id = job_id.get()
        if j_id:
            log_data['job_id'] = j_id

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        if hasattr(record, 'extra'):
            log_data.update(record.extra)

        return json.dumps(log_data)


def setup_logging(level: str = 'INFO') -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('fastapi').setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class CorrelationContext:
    def __init__(self, correlation_id: str):
        self.correlation_id = correlation_id
        self.prev = None

    def __enter__(self):
        self.prev = correlation_id.set(self.correlation_id)
        return self

    def __exit__(self, *args):
        correlation_id.set(self.prev)


class JobContext:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.prev = None

    def __enter__(self):
        self.prev = job_id.set(self.job_id)
        return self

    def __exit__(self, *args):
        job_id.set(self.prev)


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


class ContextLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, message: str, **kwargs):
        extra = {}
        if kwargs:
            extra['extra'] = kwargs
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs):
        self._logger.exception(message, extra=kwargs if kwargs else None)
