"""Audio transcription backends for voice message support."""
from __future__ import annotations

import abc
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import VoiceConfig


class Transcriber(abc.ABC):
    """Abstract base for transcription providers."""

    @abc.abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        """Transcribe audio bytes to text. Raises RuntimeError on failure."""


class NullTranscriber(Transcriber):
    """No-op transcriber — voice support disabled."""

    async def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:  # noqa: ARG002
        raise RuntimeError("Voice transcription is disabled (WHISPER_PROVIDER=none).")


class OpenAITranscriber(Transcriber):
    """Transcribe via OpenAI Whisper API."""

    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        import openai  # lazy import — only needed when provider=openai
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        transcript = await self._client.audio.transcriptions.create(
            model=self._model,
            file=buf,
        )
        return transcript.text.strip()


def create_transcriber(config: "VoiceConfig") -> Transcriber:
    """Factory: return the appropriate Transcriber based on config."""
    provider = config.whisper_provider

    if provider == "none":
        return NullTranscriber()

    if provider == "openai":
        api_key = config.whisper_api_key
        if not api_key:
            raise ValueError(
                "WHISPER_API_KEY must be set when WHISPER_PROVIDER=openai"
            )
        return OpenAITranscriber(api_key=api_key, model=config.whisper_model)

    # local and google — not yet implemented; fall back to error at runtime
    raise NotImplementedError(
        f"WHISPER_PROVIDER={provider!r} is not yet implemented. "
        "See docs/roadmap.md for planned providers."
    )
