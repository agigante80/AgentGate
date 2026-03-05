"""Contract tests — every AICLIBackend subclass satisfies the adapter contract."""
import inspect
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend
from src.ai.codex import CodexBackend
from src.ai.direct import DirectAPIBackend
from src.ai.copilot import CopilotBackend


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_copilot():
    with patch("src.ai.session.CopilotSession"):
        return CopilotBackend()

def make_codex():
    return CodexBackend(api_key="sk-test", model="o3")

def make_direct():
    return DirectAPIBackend(provider="openai", api_key="sk-test", model="gpt-4o")

ALL_BACKENDS = [
    pytest.param(make_copilot, id="copilot"),
    pytest.param(make_codex, id="codex"),
    pytest.param(make_direct, id="direct"),
]


# ── Contract tests ────────────────────────────────────────────────────────────

class TestAdapterContract:
    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    def test_is_subclass_of_abc(self, factory):
        backend = factory()
        assert isinstance(backend, AICLIBackend)

    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    def test_has_send_method(self, factory):
        backend = factory()
        assert callable(getattr(backend, "send", None))
        assert inspect.iscoroutinefunction(backend.send)

    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    def test_has_stream_method(self, factory):
        backend = factory()
        assert callable(getattr(backend, "stream", None))
        assert inspect.isasyncgenfunction(backend.stream)

    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    def test_has_clear_history_method(self, factory):
        backend = factory()
        assert callable(getattr(backend, "clear_history", None))

    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    def test_has_is_stateful_attribute(self, factory):
        backend = factory()
        assert isinstance(backend.is_stateful, bool)

    def test_copilot_is_stateful(self):
        assert make_copilot().is_stateful is True

    def test_direct_is_stateful(self):
        assert make_direct().is_stateful is True

    def test_codex_is_not_stateful(self):
        assert make_codex().is_stateful is False

    def test_clear_history_does_not_raise_on_any_backend(self):
        for factory in [make_copilot, make_codex, make_direct]:
            backend = factory()
            backend.clear_history()  # must not raise

    @pytest.mark.parametrize("factory", ALL_BACKENDS)
    async def test_stream_yields_strings(self, factory):
        backend = factory()
        # Override stream() with the base class default (yield from send)
        # by patching send to avoid real network/process calls
        async def fake_send(prompt):
            return "response text"

        original_stream = AICLIBackend.stream
        backend.send = fake_send  # type: ignore

        # Use base class stream() which calls self.send()
        chunks = []
        async for chunk in original_stream(backend, "test prompt"):
            chunks.append(chunk)
            assert isinstance(chunk, str)
        assert "".join(chunks) == "response text"

    def test_direct_clear_history_resets_messages(self):
        backend = make_direct()
        backend._messages = [{"role": "user", "content": "hello"}]
        backend.clear_history()
        assert backend._messages == []
