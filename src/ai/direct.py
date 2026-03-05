import logging
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend

logger = logging.getLogger(__name__)


class DirectAPIBackend(AICLIBackend):
    is_stateful = True  # self._messages maintains native chat history

    def __init__(self, provider: str, api_key: str, model: str, base_url: str = "") -> None:
        self._provider = provider
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        # Native multi-turn history for chat APIs
        self._messages: list[dict] = []

    async def send(self, prompt: str) -> str:
        self._messages.append({"role": "user", "content": prompt})
        if self._provider in ("openai", "openai-compat", "ollama"):
            reply = await self._openai_send()
        elif self._provider == "anthropic":
            reply = await self._anthropic_send()
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {self._provider!r}")
        self._messages.append({"role": "assistant", "content": reply})
        return reply

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        self._messages.append({"role": "user", "content": prompt})
        if self._provider in ("openai", "openai-compat", "ollama"):
            full = ""
            async for chunk in self._openai_stream():
                full += chunk
                yield chunk
            self._messages.append({"role": "assistant", "content": full})
        elif self._provider == "anthropic":
            full = ""
            async for chunk in self._anthropic_stream():
                full += chunk
                yield chunk
            self._messages.append({"role": "assistant", "content": full})
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {self._provider!r}")

    def clear_history(self) -> None:
        self._messages.clear()

    async def _openai_send(self) -> str:
        from openai import AsyncOpenAI
        kwargs: dict = {"api_key": self._api_key or "ollama"}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = AsyncOpenAI(**kwargs)
        response = await client.chat.completions.create(
            model=self._model,
            messages=self._messages,
        )
        return response.choices[0].message.content or ""

    async def _openai_stream(self) -> AsyncGenerator[str, None]:
        from openai import AsyncOpenAI
        kwargs: dict = {"api_key": self._api_key or "ollama"}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = AsyncOpenAI(**kwargs)
        async with client.chat.completions.stream(
            model=self._model,
            messages=self._messages,
        ) as stream:
            async for event in stream:
                chunk = event.choices[0].delta.content if event.choices else None
                if chunk:
                    yield chunk

    async def _anthropic_send(self) -> str:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        message = await client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=self._messages,
        )
        return message.content[0].text if message.content else ""

    async def _anthropic_stream(self) -> AsyncGenerator[str, None]:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        async with client.messages.stream(
            model=self._model,
            max_tokens=4096,
            messages=self._messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
