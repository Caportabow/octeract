"""Turn a prompt template + any LLM SDK client into a typed Endpoint.

Octeract doesn't hardcode a provider. Instead it expects a small adapter
object implementing `LLMClient` (`complete` for single-shot, `stream` for
token streaming) - trivial to write around the Anthropic SDK, OpenAI SDK,
or anything else.
"""

from __future__ import annotations

import inspect
from typing import Any, AsyncIterator, Callable, Optional, Protocol, Type, runtime_checkable

from ..core import Endpoint
from ..exceptions import TransportError
from ..types import coerce


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface Octeract expects from an LLM SDK adapter."""

    async def complete(self, *, prompt: str, model: str, **kwargs: Any) -> str: ...

    async def stream(self, *, prompt: str, model: str, **kwargs: Any) -> AsyncIterator[str]: ...


def llm(
    client: LLMClient,
    model: str,
    prompt_template: str,
    *,
    response_model: Optional[Type] = None,
    parse: Optional[Callable[[str], Any]] = None,
    name: Optional[str] = None,
    **default_kwargs: Any,
) -> Callable[[Callable], Endpoint]:
    """Decorator factory for a single-shot LLM call.

    `prompt_template` is formatted with the stub's bound arguments
    (`str.format(**kwargs)`), so template placeholders must match parameter
    names. `parse` (e.g. `json.loads`) runs on the raw text before typed
    coercion into `response_model`.

        @llm(my_client, "claude-sonnet-4-6", "Summarize: {text}", parse=json.loads, response_model=Summary)
        async def summarize(text: str) -> Summary: ...
    """

    def decorator(stub: Callable) -> Endpoint:
        sig = inspect.signature(stub)
        endpoint_name = name or stub.__name__

        async def implementation(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            prompt = prompt_template.format(**bound.arguments)
            try:
                raw = await client.complete(prompt=prompt, model=model, **default_kwargs)
            except Exception as exc:  # noqa: BLE001
                raise TransportError(f"{endpoint_name}: LLM call failed: {exc}") from exc

            data = parse(raw) if parse else raw
            return coerce(data, response_model)

        implementation.__name__ = endpoint_name
        implementation.__doc__ = stub.__doc__
        return Endpoint(implementation, name=endpoint_name)

    return decorator


def llm_stream(
    client: LLMClient,
    model: str,
    prompt_template: str,
    *,
    name: Optional[str] = None,
    **default_kwargs: Any,
) -> Callable[[Callable], Endpoint]:
    """Decorator factory for a streaming LLM call; yields text chunks.

        @llm_stream(my_client, "claude-sonnet-4-6", "Write a poem about {topic}")
        async def poem_about(topic: str): ...

        async for chunk in poem_about.stream(topic="the sea"):
            print(chunk, end="")
    """

    def decorator(stub: Callable) -> Endpoint:
        sig = inspect.signature(stub)
        endpoint_name = name or stub.__name__

        async def implementation(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            prompt = prompt_template.format(**bound.arguments)
            try:
                async for chunk in client.stream(prompt=prompt, model=model, **default_kwargs):
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                raise TransportError(f"{endpoint_name}: LLM stream failed: {exc}") from exc

        implementation.__name__ = endpoint_name
        implementation.__doc__ = stub.__doc__
        return Endpoint(implementation, name=endpoint_name)

    return decorator
