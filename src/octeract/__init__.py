"""Octeract: turn any API into an async, typed, composable, resilient,
observable, streamable Python function.

    from octeract import rest, RetryPolicy

    @rest("GET", "https://api.example.com/users/{user_id}", response_model=User)
    async def get_user(user_id: int) -> User: ...

    get_user = get_user.with_retry(RetryPolicy(max_attempts=3)).with_timeout(5.0)

    user = await get_user(user_id=42)
"""

from .core import Endpoint, Pipeline, endpoint
from .resilience import FallbackMiddleware, Middleware, RetryMiddleware, RetryPolicy, TimeoutMiddleware
from .observability import LoggingMiddleware
from .exceptions import CompositionError, OctaractError, RetryExhaustedError, TransportError, ValidationError
from .transports.rest import rest
from .transports.graphql import graphql
from .transports.sse import sse
from .transports.llm import LLMClient, llm, llm_stream

__version__ = "0.1.0"

__all__ = [
    # core
    "Endpoint",
    "Pipeline",
    "endpoint",
    # resilience
    "RetryPolicy",
    "RetryMiddleware",
    "TimeoutMiddleware",
    "FallbackMiddleware",
    "Middleware",
    # observability
    "LoggingMiddleware",
    # exceptions
    "OctaractError",
    "RetryExhaustedError",
    "ValidationError",
    "TransportError",
    "CompositionError",
    # transports
    "rest",
    "graphql",
    "sse",
    "llm",
    "llm_stream",
    "LLMClient",
]
