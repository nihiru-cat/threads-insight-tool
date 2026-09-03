"""Logging setup for app.log with secret masking.

Access tokens / API keys must never reach the log file. `SecretMaskingFilter`
redacts any configured secret values, plus common bearer-token patterns, from
every record before it is formatted.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

_MASK = "***MASKED***"
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
_ACCESS_TOKEN_PARAM_RE = re.compile(r"(access_token=)[^&\s]+", re.IGNORECASE)


def mask_secret(value: str) -> str:
    """Return a fixed-length mask, never the original secret."""
    return _MASK


class SecretMaskingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        record.msg = self._redact(msg)
        record.args = ()
        return True

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, _MASK)
        text = _BEARER_RE.sub(f"Bearer {_MASK}", text)
        text = _ACCESS_TOKEN_PARAM_RE.sub(rf"\1{_MASK}", text)
        return text


def setup_logging(log_dir: Path, level: str = "INFO", secrets: list[str] | None = None) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    logger = logging.getLogger("threads_tool")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        # Already configured (e.g. Streamlit re-imports modules on rerun).
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    secret_filter = SecretMaskingFilter(secrets)
    file_handler.addFilter(secret_filter)
    stream_handler.addFilter(secret_filter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("threads_tool")
