import anthropic
from services.providers.base import LLMProvider

_PROMPT_SUFFIX = (
    "\n\nProvide a comprehensive answer with the top options ranked. "
    "Use numbered rankings (1., 2., 3. …) where appropriate."
)


class ClaudeProvider(LLMProvider):
    name = "claude"
    label = "Claude (Anthropic)"
    color = "#7c3aed"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def query(self, question: str) -> str:
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": question + _PROMPT_SUFFIX}],
        )
        return response.content[0].text
