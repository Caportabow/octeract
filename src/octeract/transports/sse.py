"""Turn a plain async stub function into an SSE-backed streaming Endpoint.

Endpoints built this way are streaming: call `.stream(...)` on them (never
call them directly) to get an `AsyncIterator` of parsed events.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, AsyncIterator, Callable, Dict, Optional, Type

import httpx

from ..core import Endpoint
from ..exceptions import TransportError
from ..types import coerce


async def _iter_sse_events(response: httpx.Response) -> AsyncIterator[Dict[str, str]]:
    """Minimal Server-Sent-Events line parser: groups lines into events on
    blank-line boundaries, per the SSE spec."""
    event_type = "message"
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\n")
        if line == "":
            if data_lines:
                yield {"event": event_type, "data": "\n".join(data_lines)}
            event_type, data_lines = "message", []
            continue
        if line.startswith(":"):  # comment/heartbeat
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    if data_lines:
        yield {"event": event_type, "data": "\n".join(data_lines)}


def sse(
    url: str,
    *,
    method: str = "GET",
    response_model: Optional[Type] = None,
    headers: Optional[Dict[str, str]] = None,
    parse_json: bool = True,
    stop_on: Optional[str] = "[DONE]",
    name: Optional[str] = None,
) -> Callable[[Callable], Endpoint]:
    """Decorator factory producing a streaming Endpoint.

        @sse("https://api.example.com/events?topic={topic}")
        async def watch_topic(topic: str): ...

        async for event in watch_topic.stream(topic="orders"):
            print(event)
    """

    def decorator(stub: Callable) -> Endpoint:
        sig = inspect.signature(stub)
        endpoint_name = name or stub.__name__

        async def implementation(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)

            resolved_url = url
            for key, value in list(params.items()):
                token = "{" + key + "}"
                if token in resolved_url:
                    resolved_url = resolved_url.replace(token, str(value))
                    params.pop(key)

            async with httpx.AsyncClient() as http_client:
                try:
                    async with http_client.stream(
                        method.upper(),
                        resolved_url,
                        params=params if method.upper() == "GET" else None,
                        json=params if method.upper() != "GET" else None,
                        headers={**(headers or {}), "Accept": "text/event-stream"},
                        timeout=None,
                    ) as response:
                        response.raise_for_status()
                        async for event in _iter_sse_events(response):
                            raw = event["data"]
                            if stop_on is not None and raw.strip() == stop_on:
                                break
                            payload = json.loads(raw) if parse_json else raw
                            yield coerce(payload, response_model)
                except httpx.HTTPError as exc:
                    raise TransportError(f"{endpoint_name}: SSE stream failed: {exc}") from exc

        implementation.__name__ = endpoint_name
        implementation.__doc__ = stub.__doc__
        return Endpoint(implementation, name=endpoint_name)

    return decorator
