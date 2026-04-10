# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Structured logging setup with correlation IDs."""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
job_id: ContextVar[Optional[str]] = ContextVar('job_id', default=None)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
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


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for development/debugging."""

    def format(self, record: logging.LogRecord) -> str:
        # Simple colored output for TTY
        level = record.levelname
        msg = record.getMessage()

        # Add correlation/job context if present
        corr_id = correlation_id.get()
        j_id = job_id.get()

        parts = [
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            f'[{level:8}]',
        ]

        if j_id:
            parts.append(f'[{j_id[:8]}...]')
        if corr_id:
            parts.append(f'[{corr_id[:8]}...]')

        parts.append(msg)

        return ' '.join(parts)


def setup_logging(level: str = None, log_format: str = None) -> logging.Logger:
    """Setup logging with configurable format.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to LOG_LEVEL env or INFO.
        log_format: Log format (json, console). Defaults to LOG_FORMAT env or auto-detect.
                    Use 'json' for production/JSON logs, 'console' for human-readable output.
                    When not set, automatically uses console if running in TTY, JSON otherwise.
    """
    # Get config from env if not provided
    if level is None:
        level = os.environ.get('LOG_LEVEL', 'INFO')

    if log_format is None:
        log_format = os.environ.get('LOG_FORMAT', '')

    # Auto-detect format: console for TTY, JSON for non-TTY (production)
    if not log_format:
        log_format = 'console' if sys.stdout.isatty() else 'json'

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)

    # Select formatter based on log_format
    if log_format.lower() == 'console':
        handler.setFormatter(ConsoleFormatter())
    else:
        # Default to JSON (including 'json' or any other value)
        handler.setFormatter(JSONFormatter())

    logger.addHandler(handler)

    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('fastapi').setLevel(logging.WARNING)

    # Suppress health check polling from uvicorn access logs — these fire
    # every 30s from the Docker healthcheck and drown out real traffic.
    class _HealthCheckFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return '/health' not in record.getMessage()

    logging.getLogger('uvicorn.access').addFilter(_HealthCheckFilter())

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
