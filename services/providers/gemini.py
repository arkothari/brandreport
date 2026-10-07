from google import genai
from services.providers.base import LLMProvider

_PROMPT_SUFFIX = (
    "\n\nProvide a comprehensive answer with the top options ranked. "
    "Use numbered rankings (1., 2., 3. …) where appropriate."
)


class GeminiProvider(LLMProvider):
    name = "gemini"
    label = "Gemini (Google)"
    color = "#2563eb"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = genai.Client(api_key=api_key) if api_key else None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def query(self, question: str) -> str:
        response = await self._client.aio.models.generate_content(
            model="gemini-3.6-flash",
            contents=question + _PROMPT_SUFFIX,
        )
        return response.text
