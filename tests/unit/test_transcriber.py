"""Unit tests for src/transcriber.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.transcriber import (
    NullTranscriber,
    OpenAITranscriber,
    create_transcriber,
)
from src.config import VoiceConfig


# ── NullTranscriber ────────────────────────────────────────────────────────────

class TestNullTranscriber:
    async def test_raises_runtime_error(self):
        t = NullTranscriber()
        with pytest.raises(RuntimeError, match="disabled"):
            await t.transcribe(b"audio", "voice.ogg")


# ── OpenAITranscriber ─────────────────────────────────────────────────────────

class TestOpenAITranscriber:
    async def test_transcribe_returns_text(self):
        mock_result = MagicMock()
        mock_result.text = "Hello world"
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_result)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            t = OpenAITranscriber(api_key="sk-test", model="whisper-1")
            t._client = mock_client  # inject mock directly

        result = await t.transcribe(b"fake audio", "voice.ogg")
        assert result == "Hello world"

    async def test_transcribe_strips_whitespace(self):
        mock_result = MagicMock()
        mock_result.text = "  trimmed text  "
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_result)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            t = OpenAITranscriber(api_key="sk-test")
            t._client = mock_client

        result = await t.transcribe(b"audio", "audio.mp3")
        assert result == "trimmed text"

    async def test_transcribe_propagates_exception(self):
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            t = OpenAITranscriber(api_key="sk-test")
            t._client = mock_client

        with pytest.raises(RuntimeError, match="API error"):
            await t.transcribe(b"audio", "voice.ogg")


# ── create_transcriber factory ────────────────────────────────────────────────

class TestCreateTranscriber:
    def test_none_provider_returns_null(self):
        cfg = VoiceConfig(whisper_provider="none")
        t = create_transcriber(cfg)
        assert isinstance(t, NullTranscriber)

    def test_openai_provider_with_key(self):
        cfg = VoiceConfig(whisper_provider="openai", whisper_api_key="sk-test", whisper_model="whisper-1")
        with patch("openai.AsyncOpenAI"):
            t = create_transcriber(cfg)
        assert isinstance(t, OpenAITranscriber)

    def test_openai_provider_no_key_raises(self):
        cfg = VoiceConfig(whisper_provider="openai", whisper_api_key="")
        with pytest.raises(ValueError, match="WHISPER_API_KEY"):
            create_transcriber(cfg)

    def test_local_provider_raises_not_implemented(self):
        cfg = VoiceConfig(whisper_provider="local")
        with pytest.raises(NotImplementedError):
            create_transcriber(cfg)

    def test_google_provider_raises_not_implemented(self):
        cfg = VoiceConfig(whisper_provider="google")
        with pytest.raises(NotImplementedError):
            create_transcriber(cfg)
