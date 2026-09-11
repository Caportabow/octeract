"""Turn a plain async stub function into a REST-backed Endpoint.

The stub's body is never executed - only its signature (parameter names,
used purely for binding) matters. Octeract fills `{placeholders}` in the URL
from matching arguments, sends the rest as query params or a JSON body
depending on the HTTP method, and coerces the JSON response into
`response_model` if one is given.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, Type

import httpx

from ..core import Endpoint
from ..exceptions import TransportError
from ..types import coerce


def rest(
    method: str,
    url: str,
    *,
    response_model: Optional[Type] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    client: Optional[httpx.AsyncClient] = None,
    param_in: str = "auto",  # "query" | "json" | "auto"
    name: Optional[str] = None,
) -> Callable[[Callable], Endpoint]:
    """Decorator factory: `@rest("GET", "https://api.example.com/users/{user_id}")`.

    - `param_in="auto"` sends GET/DELETE args as query params, and
      POST/PUT/PATCH args as a JSON body.
    - Pass a shared `client` (httpx.AsyncClient) to reuse connections across
      calls; otherwise a short-lived client is created per call.
    """

    def decorator(stub: Callable) -> Endpoint:
        sig = inspect.signature(stub)
        endpoint_name = name or stub.__name__

        async def implementation(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)

            resolved_url = url
            used_in_path = set()
            for key, value in params.items():
                token = "{" + key + "}"
                if token in resolved_url:
                    resolved_url = resolved_url.replace(token, str(value))
                    used_in_path.add(key)
            remaining = {k: v for k, v in params.items() if k not in used_in_path and v is not None}

            owns_client = client is None
            http_client = client or httpx.AsyncClient()
            try:
                request_kwargs: Dict[str, Any] = {"headers": headers}
                use_json = param_in == "json" or (param_in == "auto" and method.upper() in ("POST", "PUT", "PATCH"))
                if use_json:
                    request_kwargs["json"] = remaining
                else:
                    request_kwargs["params"] = remaining

                response = await http_client.request(method.upper(), resolved_url, timeout=timeout, **request_kwargs)
                response.raise_for_status()
                data = response.json() if response.content else None
            except httpx.HTTPError as exc:
                raise TransportError(f"{endpoint_name}: REST call failed: {exc}") from exc
            finally:
                if owns_client:
                    await http_client.aclose()

            return coerce(data, response_model)

        implementation.__name__ = endpoint_name
        implementation.__doc__ = stub.__doc__
        return Endpoint(implementation, name=endpoint_name)

    return decorator
