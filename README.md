# Octeract

Turn any API into a Python function that's **async**, **typed**,
**composable**, **resilient**, **observable**, and **streamable** —
whether it's a REST endpoint, a GraphQL query, an SSE stream, or an LLM call.

```python
from octeract import rest, RetryPolicy
from dataclasses import dataclass

@dataclass
class User:
    id: int
    name: str

@rest("GET", "https://api.example.com/users/{user_id}", response_model=User)
async def get_user(user_id: int) -> User: ...

get_user = get_user.with_retry(RetryPolicy(max_attempts=3)).with_timeout(5.0)

user = await get_user(user_id=42)   # -> User(id=42, name=...)
```

## Install

```bash
pip install -e .          # from this directory
pip install -e ".[typed]" # + pydantic support for response_model
```

Core dependency: `httpx`. `pydantic` is optional — dataclasses work out of
the box, and pydantic models are auto-detected if installed.

## The core idea: `Endpoint`

Every transport decorator (`@rest`, `@graphql`, `@sse`, `@llm`) turns a
type-annotated stub function into an `Endpoint`. Endpoints are:

- **async** — always `await`-able (or async-iterable, for streams)
- **typed** — the declared `response_model` (a dataclass or pydantic model)
  is what you get back, not raw JSON
- **immutable & chainable** — `.with_retry()`, `.with_timeout()`,
  `.with_fallback()`, `.with_logging()` each return a *new* `Endpoint`,
  so you can branch configurations from a shared base
- **composable** — `endpoint_a | endpoint_b | plain_function` builds a
  `Pipeline` where each step's output feeds the next step's input
- **streamable** — endpoints built from async generators (SSE, LLM token
  streams) expose `.stream(...)` returning an `AsyncIterator`

## Resilience

```python
from octeract import RetryPolicy

resilient = my_endpoint \
    .with_retry(RetryPolicy(max_attempts=3, base_delay=0.2, multiplier=2.0)) \
    .with_timeout(5.0) \
    .with_fallback(lambda exc: some_default)
```

- `with_retry` — exponential backoff with jitter, configurable exception
  filter (`retry_on=(ConnectionError, TimeoutError)`)
- `with_timeout` — wraps the call in `asyncio.wait_for`
- `with_fallback` — catches matching exceptions and returns a value, or
  calls `fallback(exc)` / `fallback()` for dynamic recovery

Middleware order matters and is applied outside-in in the order you attach
it, e.g. `.with_retry(...).with_timeout(...)` retries a call that is itself
timeout-bounded on each attempt.

## Observability

```python
my_endpoint = my_endpoint.with_logging()          # uses logging.getLogger("octeract")
my_endpoint = my_endpoint.with_logging(my_logger)  # bring your own logger
```

Logs call id, args/kwargs, latency, and success/failure — opt-in and
zero-cost when not enabled.

## Composability

```python
pipeline = fetch_user | enrich_with_orders | render_summary
result = await pipeline(user_id=42)
```

- Works with `Endpoint`s and plain `async`/sync functions interchangeably
  (`plain_fn | endpoint` and `endpoint | plain_fn` both work)
- The first step receives your original call arguments; every later step
  receives exactly one positional argument: the previous result

## Transports

### REST

```python
@rest("POST", "https://api.example.com/orders", response_model=Order)
async def create_order(customer_id: int, items: list) -> Order: ...
```

`{placeholders}` in the URL are filled from matching arguments; the rest go
to query params (GET/DELETE) or a JSON body (POST/PUT/PATCH) by default.

### GraphQL

```python
@graphql(URL, QUERY, response_model=Order, unwrap="order")
async def get_order(order_id: str) -> Order: ...
```

Stub arguments become GraphQL `variables`; `unwrap="a.b.c"` digs into the
`data` payload before typed coercion.

### SSE

```python
@sse("https://api.example.com/events?topic={topic}", response_model=Event)
async def watch(topic: str): ...

async for event in watch.stream(topic="orders"):
    ...
```

Streaming endpoints are called via `.stream(...)`, never directly.

### LLM

Provider-agnostic: implement the small `LLMClient` protocol
(`complete()` / `stream()`) around any SDK (Anthropic, OpenAI, etc.).

```python
@llm(my_client, "claude-sonnet-4-6", "Summarize: {text}",
     parse=json.loads, response_model=Summary)
async def summarize(text: str) -> Summary: ...

@llm_stream(my_client, "gpt-5.6-sol", "Write about {topic}")
async def write(topic: str): ...

async for chunk in write.stream(topic="the sea"):
    print(chunk, end="")
```

## Layout

```
octeract/
  core.py              Endpoint, Pipeline, @endpoint
  resilience.py         RetryPolicy, retry/timeout/fallback middleware
  observability.py      LoggingMiddleware
  types.py               response_model coercion (dataclass / pydantic)
  exceptions.py         OctaractError hierarchy
  transports/
    rest.py            @rest
    graphql.py          @graphql
    sse.py               @sse
    llm.py                @llm, @llm_stream, LLMClient protocol
examples/
  example_usage.py      full tour of all four transports + composition
```

## Design notes

- **Typed by convention, not magic**: `response_model` coercion is
  best-effort — it handles dataclasses and pydantic models (v1 and v2) and
  falls back to returning raw data if it can't confidently coerce.
- **Middleware, not inheritance**: retry/timeout/fallback/logging are all
  the same `Middleware.wrap(call) -> call` shape, so custom middleware
  (rate limiting, caching, auth refresh, circuit breaking, ...) plugs in via
  `.with_middleware(MyMiddleware())`.
- **Streaming is a different shape on purpose**: retry/timeout/fallback are
  designed around single-shot calls; wrapping an entire stream in a retry
  would silently replay already-consumed items. Streaming endpoints
  currently pass through logging-free by default — add per-item handling
  in your own consumer loop, or open an issue/PR for stream-aware resilience.
