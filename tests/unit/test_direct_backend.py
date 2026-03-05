"""Unit tests for ai/direct.py — DirectAPIBackend."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ai.direct import DirectAPIBackend


def _make_backend(provider="openai", api_key="sk-test", model="gpt-4o"):
    return DirectAPIBackend(provider=provider, api_key=api_key, model=model)


class TestSend:
    async def test_openai_send_returns_content(self):
        backend = _make_backend("openai")
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Hello!"
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        backend._openai_client = mock_client

        result = await backend.send("Hi")

        assert result == "Hello!"
        assert backend._messages[-1] == {"role": "assistant", "content": "Hello!"}

    async def test_anthropic_send_returns_content(self):
        backend = _make_backend("anthropic", model="claude-3-5-sonnet-20241022")
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Anthropic reply")]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        backend._anthropic_client = mock_client

        result = await backend.send("Hello")

        assert result == "Anthropic reply"

    async def test_unknown_provider_raises(self):
        backend = _make_backend("unknown")
        with pytest.raises(ValueError, match="Unknown AI_PROVIDER"):
            await backend.send("hi")

    async def test_ollama_uses_openai_client(self):
        backend = _make_backend("ollama", model="llama3")
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Ollama response"
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        backend._openai_client = mock_client

        result = await backend.send("test")
        assert result == "Ollama response"

    async def test_messages_accumulate_across_calls(self):
        backend = _make_backend("openai")
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "reply"
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        backend._openai_client = mock_client

        await backend.send("first")
        await backend.send("second")

        roles = [m["role"] for m in backend._messages]
        assert roles == ["user", "assistant", "user", "assistant"]


class TestClearHistory:
    def test_clear_history_resets_messages(self):
        backend = _make_backend()
        backend._messages = [{"role": "user", "content": "test"}]
        backend.clear_history()
        assert backend._messages == []

    def test_is_stateful_flag(self):
        assert DirectAPIBackend.is_stateful is True


class TestStream:
    async def test_openai_stream_yields_chunks(self):
        backend = _make_backend("openai")

        async def fake_stream():
            for chunk in ["Hello", " world"]:
                event = MagicMock()
                event.choices = [MagicMock()]
                event.choices[0].delta.content = chunk
                yield event

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=fake_stream())
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client = MagicMock()
        mock_client.chat.completions.stream = MagicMock(return_value=mock_ctx)
        backend._openai_client = mock_client

        chunks = []
        async for chunk in backend.stream("test"):
            chunks.append(chunk)

        assert chunks == ["Hello", " world"]
        assert backend._messages[-1]["content"] == "Hello world"
