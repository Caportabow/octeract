import asyncio
import sys

from octeract import Endpoint, Pipeline, RetryPolicy, endpoint, RetryExhaustedError


async def main():
    # --- 1. basic endpoint decorator ---
    @endpoint
    async def add_one(x: int) -> int:
        return x + 1

    assert await add_one(1) == 2
    print("basic endpoint OK")

    # --- 2. retry: fails twice then succeeds ---
    attempts = {"n": 0}

    @endpoint
    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    resilient = flaky.with_retry(RetryPolicy(max_attempts=5, base_delay=0.01))
    result = await resilient()
    assert result == "ok" and attempts["n"] == 3
    print("retry OK (succeeded on attempt 3)")

    # --- 3. retry exhaustion raises RetryExhaustedError ---
    @endpoint
    async def always_fails() -> str:
        raise RuntimeError("boom")

    doomed = always_fails.with_retry(RetryPolicy(max_attempts=3, base_delay=0.01))
    try:
        await doomed()
        raise AssertionError("expected RetryExhaustedError")
    except RetryExhaustedError as exc:
        assert exc.attempts == 3
        print("retry exhaustion OK:", exc)

    # --- 4. timeout ---
    @endpoint
    async def slow() -> str:
        await asyncio.sleep(0.2)
        return "done"

    fast_fail = slow.with_timeout(0.05)
    try:
        await fast_fail()
        raise AssertionError("expected TimeoutError")
    except asyncio.TimeoutError:
        print("timeout OK")

    # --- 5. fallback ---
    @endpoint
    async def unreliable() -> str:
        raise ConnectionError("down")

    safe = unreliable.with_fallback("default-value")
    assert await safe() == "default-value"
    print("fallback (value) OK")

    safe_dynamic = unreliable.with_fallback(lambda exc: f"recovered from {type(exc).__name__}")
    assert await safe_dynamic() == "recovered from ConnectionError"
    print("fallback (callable) OK")

    # --- 6. composition with | ---
    @endpoint
    async def double(x: int) -> int:
        return x * 2

    @endpoint
    async def stringify(x: int) -> str:
        return f"value={x}"

    pipeline: Pipeline = add_one | double | stringify
    out = await pipeline(10)
    assert out == "value=22", out
    print("pipeline composition OK:", out)

    # --- 7. streaming endpoint ---
    @endpoint
    async def count_up(n: int):
        for i in range(n):
            yield i

    collected = [i async for i in count_up.stream(3)]
    assert collected == [0, 1, 2]
    print("streaming OK:", collected)

    # --- 8. chained resilience + logging combos are independent (immutability check) ---
    base = add_one
    a = base.with_retry(RetryPolicy(max_attempts=2))
    b = base.with_timeout(1.0)
    assert len(a._middlewares) == 1 and len(b._middlewares) == 1
    assert len(base._middlewares) == 0
    print("immutable middleware chaining OK")

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
