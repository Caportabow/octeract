"""Exception hierarchy used across Octeract."""

from __future__ import annotations

from typing import Any, Sequence


class OctaractError(Exception):
    """Base class for all Octeract errors."""


class RetryExhaustedError(OctaractError):
    """Raised when a retried call fails on every attempt."""

    def __init__(self, attempts: int, last_exception: BaseException | None):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"Retry exhausted after {attempts} attempt(s); "
            f"last error: {last_exception!r}"
        )


class ValidationError(OctaractError):
    """Raised when response data cannot be coerced into the declared type."""

    def __init__(self, message: str, data: Any = None, model: Any = None):
        self.data = data
        self.model = model
        super().__init__(message)


class TransportError(OctaractError):
    """Raised when the underlying REST/GraphQL/SSE/LLM call fails."""


class CompositionError(OctaractError):
    """Raised when a Pipeline is misconfigured (e.g. empty)."""
