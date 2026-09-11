"""Turn a plain async stub function into a GraphQL-backed Endpoint."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, Type

import httpx

from ..core import Endpoint
from ..exceptions import TransportError
from ..types import coerce


def graphql(
    url: str,
    query: str,
    *,
    response_model: Optional[Type] = None,
    unwrap: Optional[str] = None,  # dotted path into the response, e.g. "user.profile"
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    client: Optional[httpx.AsyncClient] = None,
    name: Optional[str] = None,
) -> Callable[[Callable], Endpoint]:
    """Decorator factory. The stub's arguments become GraphQL `variables`.

        @graphql(URL, QUERY, response_model=User, unwrap="user")
        async def get_user(user_id: str) -> User: ...
    """

    def decorator(stub: Callable) -> Endpoint:
        sig = inspect.signature(stub)
        endpoint_name = name or stub.__name__

        async def implementation(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            variables = dict(bound.arguments)

            owns_client = client is None
            http_client = client or httpx.AsyncClient()
            try:
                response = await http_client.post(
                    url,
                    timeout=timeout,
                    headers=headers,
                    json={"query": query, "variables": variables},
                )
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise TransportError(f"{endpoint_name}: GraphQL call failed: {exc}") from exc
            finally:
                if owns_client:
                    await http_client.aclose()

            if payload.get("errors"):
                raise TransportError(f"{endpoint_name}: GraphQL errors: {payload['errors']}")

            data = payload.get("data")
            for key in (unwrap.split(".") if unwrap else []):
                data = data.get(key) if isinstance(data, dict) else None

            return coerce(data, response_model)

        implementation.__name__ = endpoint_name
        implementation.__doc__ = stub.__doc__
        return Endpoint(implementation, name=endpoint_name)

    return decorator
