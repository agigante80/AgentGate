from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class AICLIBackend(ABC):
    is_stateful: bool = False  # True = backend manages its own conversation state

    @abstractmethod
    async def send(self, prompt: str) -> str:
        """Send a prompt and return the full response text."""

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Yield response chunks. Default: yield the full send() result at once."""
        yield await self.send(prompt)

    def clear_history(self) -> None:
        """Clear conversation history (override in stateful backends)."""
