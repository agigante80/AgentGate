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
        self._messages: list[dict] = []
        # Cached clients — created lazily, reused across calls
        self._openai_client = None
        self._anthropic_client = None

    # ── Public API ───────────────────────────────────────────────────────

    async def send(self, prompt: str) -> str:
        self._messages.append({"role": "user", "content": prompt})
        reply = await self._do_send()
        self._messages.append({"role": "assistant", "content": reply})
        return reply

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        self._messages.append({"role": "user", "content": prompt})
        full = ""
        async for chunk in self._do_stream():
            full += chunk
            yield chunk
        self._messages.append({"role": "assistant", "content": full})

    def clear_history(self) -> None:
        self._messages.clear()

    # ── Provider dispatch ─────────────────────────────────────────────────

    def _get_provider_callables(self):
        """Return (send_fn, stream_fn) for the configured provider. Single routing point."""
        if self._provider in ("openai", "openai-compat", "ollama"):
            return self._openai_send, self._openai_stream
        if self._provider == "anthropic":
            return self._anthropic_send, self._anthropic_stream
        raise ValueError(f"Unknown AI_PROVIDER: {self._provider!r}")

    async def _do_send(self) -> str:
        send_fn, _ = self._get_provider_callables()
        return await send_fn()

    async def _do_stream(self) -> AsyncGenerator[str, None]:
        _, stream_fn = self._get_provider_callables()
        async for chunk in stream_fn():
            yield chunk

    # ── Client factories (lazy, cached) ──────────────────────────────────

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import AsyncOpenAI
            kwargs: dict = {"api_key": self._api_key or "ollama"}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._openai_client = AsyncOpenAI(**kwargs)
        return self._openai_client

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            from anthropic import AsyncAnthropic
            self._anthropic_client = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic_client

    # ── OpenAI / Ollama ──────────────────────────────────────────────────

    async def _openai_send(self) -> str:
        client = self._get_openai_client()
        response = await client.chat.completions.create(
            model=self._model,
            messages=self._messages,
        )
        return response.choices[0].message.content or ""

    async def _openai_stream(self) -> AsyncGenerator[str, None]:
        client = self._get_openai_client()
        async with client.chat.completions.stream(
            model=self._model,
            messages=self._messages,
        ) as stream:
            async for event in stream:
                chunk = event.choices[0].delta.content if event.choices else None
                if chunk:
                    yield chunk

    # ── Anthropic ────────────────────────────────────────────────────────

    async def _anthropic_send(self) -> str:
        client = self._get_anthropic_client()
        message = await client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=self._messages,
        )
        return message.content[0].text if message.content else ""

    async def _anthropic_stream(self) -> AsyncGenerator[str, None]:
        client = self._get_anthropic_client()
        async with client.messages.stream(
            model=self._model,
            max_tokens=4096,
            messages=self._messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
