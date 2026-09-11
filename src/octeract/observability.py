"""Optional observability: structured logging around endpoint calls."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Optional

from .resilience import Middleware


class LoggingMiddleware(Middleware):
    """Logs call start/end, latency, and errors. Purely additive (opt-in)."""

    def __init__(self, logger: Optional[logging.Logger] = None, name: str = "octeract"):
        self.logger = logger or logging.getLogger("octeract")
        self.name = name

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_id = uuid.uuid4().hex[:8]
            start = time.perf_counter()
            self.logger.info("[%s:%s] -> args=%r kwargs=%r", self.name, call_id, args, kwargs)
            try:
                result = await call(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - intentional passthrough logging
                elapsed_ms = (time.perf_counter() - start) * 1000
                self.logger.warning(
                    "[%s:%s] <- error in %.1fms: %r", self.name, call_id, elapsed_ms, exc
                )
                raise
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.logger.info("[%s:%s] <- ok in %.1fms", self.name, call_id, elapsed_ms)
            return result

        return wrapped
