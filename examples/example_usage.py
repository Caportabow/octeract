"""End-to-end tour of Octeract: REST, GraphQL, SSE, and LLM transports,
each made resilient + observable + typed, then composed into a pipeline.

This file is illustrative; some endpoints point at example.com URLs and
won't actually resolve. Swap in real URLs/queries/clients to run it live.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from octeract import (
    Endpoint,
    LLMClient,
    RetryPolicy,
    endpoint,
    graphql,
    llm,
    llm_stream,
    rest,
    sse,
)

logging.basicConfig(level=logging.INFO)


# --------------------------------------------------------------------------
# 1. REST: a typed, resilient GET
# --------------------------------------------------------------------------

@dataclass
class User:
    id: int
    name: str
    email: str


@rest("GET", "https://api.example.com/users/{user_id}", response_model=User)
async def get_user(user_id: int) -> User: ...


# Compose resilience + observability without touching the original decorator.
get_user = (
    get_user
    .with_retry(RetryPolicy(max_attempts=3, base_delay=0.2))
    .with_timeout(5.0)
    .with_fallback(lambda exc: User(id=-1, name="unknown", email=""))
    .with_logging()
)


# --------------------------------------------------------------------------
# 2. GraphQL: typed query with response unwrapping
# --------------------------------------------------------------------------

GET_ORDER_QUERY = """
query GetOrder($order_id: ID!) {
  order(id: $order_id) {
    id
    total
    status
  }
}
"""


@dataclass
class Order:
    id: str
    total: float
    status: str


@graphql(
    "https://api.example.com/graphql",
    GET_ORDER_QUERY,
    response_model=Order,
    unwrap="order",
)
async def get_order(order_id: str) -> Order: ...


get_order = get_order.with_retry(RetryPolicy(max_attempts=2)).with_timeout(3.0)


# --------------------------------------------------------------------------
# 3. SSE: a live event stream
# --------------------------------------------------------------------------

@dataclass
class PriceTick:
    symbol: str
    price: float


@sse(
    "https://api.example.com/prices/stream?symbol={symbol}",
    response_model=PriceTick,
)
async def watch_price(symbol: str) -> AsyncIterator[PriceTick]: ...


# --------------------------------------------------------------------------
# 4. LLM: provider-agnostic, plug in any SDK behind the LLMClient protocol
# --------------------------------------------------------------------------

class AnthropicAdapter:
    """Thin adapter around the Anthropic SDK satisfying the LLMClient protocol.

    Swap this for an OpenAI/other adapter without touching endpoint code.
    """

    def __init__(self, api_key: str):
        # import kept local so this file doesn't hard-require the SDK
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, *, prompt: str, model: str, **kwargs) -> str:
        response = await self._client.messages.create(
            model=model,
            max_tokens=kwargs.pop("max_tokens", 1024),
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    async def stream(self, *, prompt: str, model: str, **kwargs) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=model,
            max_tokens=kwargs.pop("max_tokens", 1024),
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


@dataclass
class Sentiment:
    label: str
    score: float


def make_sentiment_endpoint(client: LLMClient) -> Endpoint:
    @llm(
        client,
        "claude-sonnet-4-6",
        'Classify the sentiment of this text as JSON {{"label": ..., "score": ...}}: {text}',
        parse=json.loads,
        response_model=Sentiment,
    )
    async def classify_sentiment(text: str) -> Sentiment: ...

    return classify_sentiment.with_retry(max_attempts=2).with_timeout(15.0)


def make_story_stream_endpoint(client: LLMClient) -> Endpoint:
    @llm_stream(client, "claude-sonnet-4-6", "Write a two-sentence story about {topic}")
    async def tell_story(topic: str) -> AsyncIterator[str]: ...

    return tell_story


# --------------------------------------------------------------------------
# 5. Composability: chain plain functions and endpoints with `|`
# --------------------------------------------------------------------------

@endpoint
async def summarize_order(order: Order) -> str:
    return f"Order {order.id}: ${order.total:.2f} ({order.status})"


order_summary_pipeline = get_order | summarize_order


# --------------------------------------------------------------------------
# Demo driver (network calls here will fail against example.com - replace
# with real endpoints/credentials to actually run this).
# --------------------------------------------------------------------------

async def main():
    # REST, with retry/timeout/fallback/logging already attached above.
    user = await get_user(user_id=42)
    print("User:", user)

    # GraphQL composed straight into a plain-function pipeline.
    summary = await order_summary_pipeline(order_id="A100")
    print("Order summary:", summary)

    # SSE streaming.
    async for tick in watch_price.stream(symbol="AAPL"):
        print("Price tick:", tick)

    # LLM single-shot + streaming, provider swappable via LLMClient.
    client = AnthropicAdapter(api_key="sk-...")
    classify_sentiment = make_sentiment_endpoint(client)
    sentiment = await classify_sentiment(text="Octeract makes APIs delightful to use.")
    print("Sentiment:", sentiment)

    tell_story = make_story_stream_endpoint(client)
    async for chunk in tell_story.stream(topic="a database that learns to dream"):
        print(chunk, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
