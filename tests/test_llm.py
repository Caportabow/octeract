import asyncio
import json
from dataclasses import dataclass

from octeract import llm, llm_stream, Pipeline


@dataclass
class Sentiment:
    label: str
    score: float


class FakeLLMClient:
    """Stand-in for a real SDK (Anthropic/OpenAI/etc). Satisfies LLMClient protocol."""

    async def complete(self, *, prompt: str, model: str, **kwargs) -> str:
        # pretend the model always says the text is positive
        return json.dumps({"label": "positive", "score": 0.93})

    async def stream(self, *, prompt: str, model: str, **kwargs):
        for word in ["Once ", "upon ", "a ", "time..."]:
            await asyncio.sleep(0)
            yield word


client = FakeLLMClient()


@llm(client, "claude-sonnet-4-6", "Classify sentiment of: {text}", parse=json.loads, response_model=Sentiment)
async def classify(text: str) -> Sentiment: ...


@llm_stream(client, "gpt-5.6-sol", "Write a short story about {topic}")
async def tell_story(topic: str): ...


async def main():
    result = await classify.with_retry(max_attempts=2)(text="I love this library!")
    print("Classified:", result)
    assert isinstance(result, Sentiment) and result.label == "positive"
    print("LLM single-shot + typed coercion OK")

    chunks = [c async for c in tell_story.stream(topic="a robot")]
    story = "".join(chunks)
    print("Story:", story)
    assert story == "Once upon a time..."
    print("LLM streaming OK")

    # Pipeline mixing a plain function with an LLM endpoint.
    def make_prompt_text(raw: str) -> str:
        return raw.strip().lower()

    pipeline: Pipeline = make_prompt_text | classify
    out = await pipeline("  I LOVE THIS LIBRARY!  ")
    assert isinstance(out, Sentiment)
    print("Mixed pipeline (plain fn | LLM endpoint) OK:", out)


if __name__ == "__main__":
    asyncio.run(main())
