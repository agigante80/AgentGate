"""Unit tests for request-cancellation feature — streaming path."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.adapter import AICLIBackend
from src.audit import NullAuditLog
from src.bot import _BotHandlers
from src.config import AIConfig, BotConfig, DirectAIConfig, GitHubConfig, Settings, TelegramConfig, VoiceConfig
from src.history import ConversationStorage


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(stream=True, ai_timeout_secs=0, cancel_timeout_secs=5):
    tg = MagicMock(spec=TelegramConfig)
    tg.chat_id = "99999"
    tg.allowed_users = []
    tg.bot_token = ""
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = "gate"
    bot.max_output_chars = 3000
    bot.stream_responses = stream
    bot.history_enabled = True
    bot.stream_throttle_secs = 1.0
    bot.confirm_destructive = True
    bot.skip_confirm_keywords = []
    bot.image_tag = ""
    bot.ai_timeout_secs = ai_timeout_secs
    bot.cancel_timeout_secs = cancel_timeout_secs
    bot.thinking_slow_threshold_secs = 15
    bot.thinking_update_secs = 30
    bot.ai_timeout_warn_secs = 60
    bot.thinking_show_elapsed = True
    bot.allow_secrets = False
    bot.system_prompt = ""
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    gh.github_repo_token = ""
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = "api"
    ai.ai_model = ""
    ai.ai_api_key = ""
    direct = MagicMock(spec=DirectAIConfig)
    direct.ai_provider = "openai"
    ai.direct = direct
    voice = MagicMock(spec=VoiceConfig)
    voice.whisper_provider = "none"
    voice.whisper_api_key = ""
    voice.whisper_model = "whisper-1"
    s = MagicMock(spec=Settings)
    s.telegram = tg
    s.bot = bot
    s.github = gh
    s.ai = ai
    s.voice = voice
    s.slack = MagicMock()
    s.slack.slack_bot_token = ""
    s.slack.slack_app_token = ""
    return s


def _make_update(chat_id="99999", user_id=42, text="hello"):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.effective_user.id = user_id
    update.effective_message.text = text
    update.effective_message.reply_text = AsyncMock(
        return_value=MagicMock(edit_text=AsyncMock())
    )
    return update


def _make_handlers(settings=None):
    s = settings or _make_settings()
    backend = MagicMock(spec=AICLIBackend)
    backend.is_stateful = False
    backend.send = AsyncMock(return_value="response")
    backend.close = MagicMock()
    backend.clear_history = MagicMock()
    storage = MagicMock(spec=ConversationStorage)
    storage.get_history = AsyncMock(return_value=[])
    storage.add_exchange = AsyncMock()
    h = _BotHandlers(s, backend, storage, 0.0, NullAuditLog())
    return h


# ── Streaming cancellation tests ──────────────────────────────────────────────

class TestStreamingCancellation:
    async def test_cancelled_error_during_streaming_sends_user_message(self):
        """CancelledError raised in the streaming task → pipeline sends '⚠️ Request cancelled.'."""
        settings = _make_settings(stream=True)
        h = _make_handlers(settings)
        update = _make_update()

        async def streaming_raises_cancelled():
            raise asyncio.CancelledError()

        with patch("src.bot._stream_to_telegram", side_effect=streaming_raises_cancelled):
            await h._run_ai_pipeline(update, "hello", "99999")

        update.effective_message.reply_text.assert_awaited()
        # Find the cancel notification
        calls = [str(c) for c in update.effective_message.reply_text.call_args_list]
        assert any("cancelled" in c.lower() for c in calls), (
            f"Expected 'cancelled' in reply, got: {calls}"
        )

    async def test_inflight_guard_rejects_while_streaming(self):
        """Second prompt while a streaming task is in-flight → returns 'in progress' message."""
        settings = _make_settings(stream=True)
        h = _make_handlers(settings)
        chat_id = "99999"

        # Plant a running "streaming" task
        running_task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks[chat_id] = running_task

        update = _make_update(chat_id=chat_id)

        with patch("src.bot._stream_to_telegram", new=AsyncMock(return_value="response")) as mock_stream:
            await h._run_ai_pipeline(update, "second prompt", chat_id)
            mock_stream.assert_not_called()

        reply_text = update.effective_message.reply_text
        reply_text.assert_awaited_once()
        call_text = reply_text.call_args[0][0]
        assert "in progress" in call_text.lower()

        running_task.cancel()
        try:
            await running_task
        except (asyncio.CancelledError, Exception):
            pass
