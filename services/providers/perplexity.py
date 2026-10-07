from openai import AsyncOpenAI
from services.providers.base import LLMProvider

_PROMPT_SUFFIX = (
    "\n\nProvide a comprehensive answer with the top options ranked. "
    "Use numbered rankings (1., 2., 3. …) where appropriate."
)


class PerplexityProvider(LLMProvider):
    name = "perplexity"
    label = "Perplexity AI"
    color = "#0891b2"

    def __init__(self, api_key: str):
        self._api_key = api_key
        # Perplexity exposes an OpenAI-compatible REST API
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
        ) if api_key else None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def query(self, question: str) -> str:
        response = await self._client.chat.completions.create(
            model="sonar",
            max_tokens=800,
            messages=[{"role": "user", "content": question + _PROMPT_SUFFIX}],
        )
        return response.choices[0].message.content
