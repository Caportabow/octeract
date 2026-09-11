"""Resilience building blocks: retry, timeout, and fallback middleware.

All middleware follow the same shape: `Middleware.wrap(call) -> call`, where
`call` is an async callable. This lets Octeract stack them in any order and
apply them uniformly to REST, GraphQL, SSE, and LLM endpoints.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence, Type

from .exceptions import RetryExhaustedError


@dataclass
class RetryPolicy:
    """Declarative retry configuration with exponential backoff + jitter."""

    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 5.0
    multiplier: float = 2.0
    jitter: bool = True
    retry_on: Sequence[Type[BaseException]] = field(default_factory=lambda: (Exception,))

    def compute_delay(self, attempt: int) -> float:
        """Delay (seconds) to wait before the given attempt number (1-indexed)."""
        delay = min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random()
        return delay


class Middleware:
    """Base class: wraps an async callable with additional behavior."""

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Any]:
        raise NotImplementedError


class RetryMiddleware(Middleware):
    """Retries the wrapped call according to a RetryPolicy."""

    def __init__(self, policy: RetryPolicy, on_retry: Callable[[int, BaseException], None] | None = None):
        self.policy = policy
        self.on_retry = on_retry

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Any]:
        policy = self.policy

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    return await call(*args, **kwargs)
                except tuple(policy.retry_on) as exc:
                    last_exc = exc
                    if attempt == policy.max_attempts:
                        break
                    if self.on_retry:
                        self.on_retry(attempt, exc)
                    await asyncio.sleep(policy.compute_delay(attempt))
            raise RetryExhaustedError(policy.max_attempts, last_exc)

        return wrapped


class TimeoutMiddleware(Middleware):
    """Bounds the wrapped call's execution time."""

    def __init__(self, seconds: float):
        self.seconds = seconds

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.wait_for(call(*args, **kwargs), timeout=self.seconds)

        return wrapped


class FallbackMiddleware(Middleware):
    """Swallows matching exceptions and returns a fallback value/callable instead.

    `fallback` may be:
    - a plain value, returned as-is
    - a callable taking the raised exception and returning a (possibly awaitable) value
    - a zero-arg callable, used if the exception-arg call raises TypeError
    """

    def __init__(self, fallback: Any, exceptions: Sequence[Type[BaseException]] = (Exception,)):
        self.fallback = fallback
        self.exceptions = tuple(exceptions)

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return await call(*args, **kwargs)
            except self.exceptions as exc:
                if callable(self.fallback):
                    try:
                        result = self.fallback(exc)
                    except TypeError:
                        result = self.fallback()
                    if asyncio.iscoroutine(result):
                        result = await result
                    return result
                return self.fallback

        return wrapped
