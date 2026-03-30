"""
Structured logging for backend operations.
Makes it easy to trace issues across Supabase and AWS.
"""
import logging
import json
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("arkhe.backends")


class BackendLogger:
    """Structured logger for backend operations with context."""

    def __init__(self, backend_name: str):
        self.backend_name = backend_name
        self.logger = logging.getLogger(f"arkhe.backends.{backend_name}")

    def _format_context(self, **kwargs) -> str:
        """Format context data as JSON."""
        try:
            return json.dumps(kwargs)
        except (TypeError, ValueError):
            # Handle non-serializable objects
            sanitized = {}
            for k, v in kwargs.items():
                try:
                    json.dumps(v)
                    sanitized[k] = v
                except (TypeError, ValueError):
                    sanitized[k] = str(v)
            return json.dumps(sanitized)

    def info(self, message: str, **context):
        """Log info with context."""
        ctx = self._format_context(**context) if context else ""
        self.logger.info(f"[{self.backend_name}] {message} {ctx}")

    def warning(self, message: str, **context):
        """Log warning with context."""
        ctx = self._format_context(**context) if context else ""
        self.logger.warning(f"[{self.backend_name}] ⚠️  {message} {ctx}")

    def error(self, message: str, exception: Optional[Exception] = None, **context):
        """Log error with exception and context."""
        ctx = self._format_context(**context) if context else ""
        exc_info = str(exception) if exception else ""
        self.logger.error(f"[{self.backend_name}] ❌ {message} {ctx} {exc_info}")

    def debug(self, message: str, **context):
        """Log debug with context."""
        ctx = self._format_context(**context) if context else ""
        self.logger.debug(f"[{self.backend_name}] {message} {ctx}")

    def operation_start(self, operation: str, **context):
        """Log start of operation."""
        context["timestamp"] = datetime.utcnow().isoformat()
        self.debug(f"→ {operation}", **context)

    def operation_success(self, operation: str, duration_ms: float = None, **context):
        """Log successful operation."""
        if duration_ms:
            context["duration_ms"] = round(duration_ms, 2)
        self.info(f"✓ {operation}", **context)

    def operation_error(self, operation: str, exception: Exception, **context):
        """Log failed operation."""
        context["error_type"] = type(exception).__name__
        context["error_message"] = str(exception)
        self.error(f"✗ {operation}", exception=exception, **context)


def get_logger(backend_name: str) -> BackendLogger:
    """Get a logger for a specific backend."""
    return BackendLogger(backend_name)
