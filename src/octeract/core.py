"""Core abstractions: `Endpoint` (a resilient, observable, composable async
function) and `Pipeline` (chaining endpoints so output -> next input).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Generic,
    List,
    Optional,
    TypeVar,
    Union,
)

from .observability import LoggingMiddleware
from .resilience import FallbackMiddleware, Middleware, RetryMiddleware, RetryPolicy, TimeoutMiddleware

R = TypeVar("R")


def _build_chain(func: Callable[..., Any], middlewares: List[Middleware]) -> Callable[..., Any]:
    call = func
    for mw in reversed(middlewares):
        call = mw.wrap(call)
    return call


def _build_stream_chain(func: Callable[..., Any], middlewares: List[Middleware]) -> Callable[..., Any]:
    """Streaming endpoints pass through unchanged for now: retry/timeout/fallback
    are designed for single-shot calls. Logging middleware still applies per-item
    via a thin wrapper below (see Endpoint.stream)."""

    async def wrapped(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async for item in func(*args, **kwargs):
            yield item

    return wrapped


class Endpoint(Generic[R]):
    """A composable, resilient, observable, typed async wrapper around a callable.

    Endpoints are immutable: `.with_retry(...)`, `.with_timeout(...)`, etc. each
    return a *new* Endpoint with the extra middleware appended, so you can safely
    branch configurations from a shared base endpoint.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: Optional[str] = None,
        middlewares: Optional[List[Middleware]] = None,
    ):
        if not (inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)):
            raise TypeError(f"{func!r} must be an async function or async generator function")
        self.func = func
        self.name = name or getattr(func, "__name__", "endpoint")
        self._middlewares: List[Middleware] = list(middlewares or [])
        try:
            self.__signature__ = inspect.signature(func)
        except (TypeError, ValueError):
            self.__signature__ = None
        self.__doc__ = func.__doc__
        self._is_stream = inspect.isasyncgenfunction(func)

    # ---- middleware application (returns a new Endpoint) ----
    def _cloned(self, extra: Middleware) -> "Endpoint[R]":
        return Endpoint(self.func, name=self.name, middlewares=self._middlewares + [extra])

    def with_retry(self, policy: Optional[RetryPolicy] = None, **kwargs: Any) -> "Endpoint[R]":
        """Attach retry-with-backoff. Pass a RetryPolicy or kwargs for one."""
        policy = policy or RetryPolicy(**kwargs)
        return self._cloned(RetryMiddleware(policy))

    def with_timeout(self, seconds: float) -> "Endpoint[R]":
        """Bound the call's execution time; raises asyncio.TimeoutError past it."""
        return self._cloned(TimeoutMiddleware(seconds))

    def with_fallback(self, fallback: Any, exceptions: tuple = (Exception,)) -> "Endpoint[R]":
        """Return `fallback` (value or callable(exc)) instead of raising."""
        return self._cloned(FallbackMiddleware(fallback, exceptions))

    def with_logging(self, logger: Any = None) -> "Endpoint[R]":
        """Turn on structured call logging for this endpoint."""
        return self._cloned(LoggingMiddleware(logger, name=self.name))

    def with_middleware(self, middleware: Middleware) -> "Endpoint[R]":
        """Attach any custom Middleware subclass."""
        return self._cloned(middleware)

    # ---- invocation ----
    async def __call__(self, *args: Any, **kwargs: Any) -> R:
        if self._is_stream:
            raise TypeError(f"{self.name} is a streaming endpoint; use `.stream(...)` instead of calling it")
        chain = _build_chain(self.func, self._middlewares)
        return await chain(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[R]:
        """Invoke a streaming endpoint (SSE, LLM token stream, ...) as an async iterator."""
        if not self._is_stream:
            raise TypeError(f"{self.name} is not a streaming endpoint; call it directly instead")
        chain = _build_stream_chain(self.func, self._middlewares)
        return chain(*args, **kwargs)

    # ---- composition ----
    def __or__(self, other: Union["Endpoint", "Pipeline", Callable]) -> "Pipeline":
        return Pipeline([self]) | other

    def __ror__(self, other: Callable) -> "Pipeline":
        # Supports `plain_function | endpoint`, where `other` is a plain
        # callable that doesn't itself define `__or__`.
        return Pipeline([other]) | self

    def __repr__(self) -> str:
        mw = ", ".join(type(m).__name__ for m in self._middlewares)
        kind = "stream" if self._is_stream else "call"
        return f"<Endpoint {self.name} kind={kind} middlewares=[{mw}]>"


class Pipeline(Generic[R]):
    """Chains endpoints/callables so each step's output feeds the next step's
    single input: `a | b | c` is roughly `c(await b(await a(*args)))`.

    The first step receives the original call arguments; every later step
    receives exactly one positional argument (the previous result).
    """

    def __init__(self, steps: List[Callable[..., Any]]):
        if not steps:
            raise ValueError("Pipeline requires at least one step")
        self.steps = steps

    async def __call__(self, *args: Any, **kwargs: Any) -> R:
        result = await self._invoke(self.steps[0], args, kwargs)
        for step in self.steps[1:]:
            result = await self._invoke(step, (result,), {})
        return result

    @staticmethod
    async def _invoke(step: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
        result = step(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def __or__(self, other: Union["Endpoint", "Pipeline", Callable]) -> "Pipeline":
        if isinstance(other, Pipeline):
            return Pipeline(self.steps + other.steps)
        return Pipeline(self.steps + [other])

    def __ror__(self, other: Callable) -> "Pipeline":
        return Pipeline([other] + self.steps)

    def __repr__(self) -> str:
        names = " | ".join(getattr(s, "name", getattr(s, "__name__", repr(s))) for s in self.steps)
        return f"<Pipeline {names}>"


def endpoint(func: Optional[Callable] = None, *, name: Optional[str] = None):
    """Generic decorator: turn any async function (or async generator) into
    an Endpoint, without any particular transport attached.

        @endpoint
        async def add_one(x: int) -> int:
            return x + 1
    """

    def decorator(f: Callable) -> Endpoint:
        return Endpoint(f, name=name)

    if func is not None:
        return decorator(func)
    return decorator
