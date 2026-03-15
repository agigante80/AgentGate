import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from src.config import REPO_DIR


class SubprocessMixin:
    """Mixin for backends that execute commands as child processes in the repo directory."""

    async def _spawn(
        self, cmd: list[str], env: dict | None = None
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )


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

    def close(self) -> None:
        """Release resources (e.g. PTY process). Override in backends that hold external state.

        Re-entrance contract: this method may be called after a cancel (not only at shutdown).
        Implementations must be safe to call multiple times and must leave the backend in a
        usable state for subsequent requests — do not tear down connection pools or shared state
        that would prevent future ``send()`` calls from succeeding.
        """
