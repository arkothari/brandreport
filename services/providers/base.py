from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str    # internal key, e.g. "chatgpt"
    label: str   # display name, e.g. "ChatGPT (OpenAI)"
    color: str   # hex for UI badge

    @abstractmethod
    async def query(self, question: str) -> str:
        """Send question; return response text."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True when the required API key is present."""
