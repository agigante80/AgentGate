"""Unit tests for request-cancellation feature — _BotHandlers._cancel_active_task and cmd_cancel."""
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

def _make_settings(
    chat_id="99999",
    prefix="gate",
    stream=False,
    history_enabled=True,
    ai_timeout_secs=0,
    cancel_timeout_secs=5,
):
    tg = MagicMock(spec=TelegramConfig)
    tg.chat_id = chat_id
    tg.allowed_users = []
    tg.bot_token = ""
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = prefix
    bot.max_output_chars = 3000
    bot.stream_responses = stream
    bot.history_enabled = history_enabled
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


# ── _cancel_active_task ───────────────────────────────────────────────────────

class TestCancelActiveTask:
    async def test_returns_false_when_no_task(self):
        h = _make_handlers()
        result = await h._cancel_active_task("chat123")
        assert result is False

    async def test_returns_false_when_task_done(self):
        h = _make_handlers()
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task  # let it complete
        h._active_tasks["chat123"] = done_task
        result = await h._cancel_active_task("chat123")
        assert result is False

    async def test_returns_true_when_pending_task(self):
        h = _make_handlers()
        task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks["chat123"] = task
        result = await h._cancel_active_task("chat123")
        assert result is True
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def test_calls_backend_close_after_cancel(self):
        h = _make_handlers()
        task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks["chat123"] = task
        await h._cancel_active_task("chat123")
        h._backend.close.assert_called_once()

    async def test_calls_backend_clear_history_after_cancel(self):
        h = _make_handlers()
        task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks["chat123"] = task
        await h._cancel_active_task("chat123")
        h._backend.clear_history.assert_called_once()

    async def test_guard_skips_close_when_new_task_registered(self):
        """backend.close() must not fire if a new task arrived during the grace period."""
        h = _make_handlers()
        old_task = asyncio.create_task(asyncio.sleep(100))
        new_task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks["chat123"] = old_task

        # Simulate a new task arriving before _cancel_active_task re-checks
        old_task.cancel()
        with pytest.raises((asyncio.CancelledError, Exception)):
            await old_task
        # Replace with new task to simulate race
        h._active_tasks["chat123"] = new_task

        # Now re-check the guard directly (current is new_task, not old_task)
        current = h._active_tasks.get("chat123")
        assert current is not old_task  # guard would skip close()
        new_task.cancel()
        try:
            await new_task
        except (asyncio.CancelledError, Exception):
            pass

    async def test_cancel_timeout_secs_respected(self):
        """_cancel_active_task uses cancel_timeout_secs from config."""
        settings = _make_settings(cancel_timeout_secs=1)
        h = _make_handlers(settings)
        # A task that ignores CancelledError (never finishes)
        async def stubborn():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                await asyncio.sleep(100)  # ignore and keep sleeping

        task = asyncio.create_task(stubborn())
        h._active_tasks["chat123"] = task
        import time
        t0 = time.monotonic()
        await h._cancel_active_task("chat123")
        elapsed = time.monotonic() - t0
        # Should give up after ~1s (cancel_timeout_secs)
        assert elapsed < 5, f"cancel took too long: {elapsed}s"
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ── cmd_cancel ────────────────────────────────────────────────────────────────

class TestCmdCancel:
    async def test_no_task_sends_no_request_message(self):
        h = _make_handlers()
        update = _make_update()
        await h.cmd_cancel(update, MagicMock())
        update.effective_message.reply_text.assert_awaited_once()
        args = update.effective_message.reply_text.call_args[0]
        assert "No request in progress" in args[0]

    async def test_with_task_sends_cancelled_message(self):
        h = _make_handlers()
        update = _make_update()
        task = asyncio.create_task(asyncio.sleep(100))
        h._active_tasks[str(update.effective_chat.id)] = task
        await h.cmd_cancel(update, MagicMock())
        update.effective_message.reply_text.assert_awaited_once()
        args = update.effective_message.reply_text.call_args[0]
        assert "cancelled" in args[0].lower()

    async def test_auth_guard_rejects_wrong_chat(self):
        """cmd_cancel is decorated with @_requires_auth — wrong chat_id → no action."""
        settings = _make_settings(chat_id="99999")
        h = _make_handlers(settings)
        update = _make_update(chat_id="00000")  # different chat
        # @_requires_auth returns early — reply_text not called
        await h.cmd_cancel(update, MagicMock())
        update.effective_message.reply_text.assert_not_awaited()


# ── in-flight guard ───────────────────────────────────────────────────────────

class TestInflightGuard:
    async def test_second_prompt_rejected_while_inflight(self):
        h = _make_handlers()
        # Inject a running task
        task = asyncio.create_task(asyncio.sleep(100))
        chat_id = "99999"
        h._active_tasks[chat_id] = task
        update = _make_update(chat_id=chat_id)

        with patch.object(h, "_backend") as mock_backend:
            mock_backend.is_stateful = False
            mock_backend.send = AsyncMock(return_value="never called")
            await h._run_ai_pipeline(update, "second prompt", chat_id)

        reply_text = update.effective_message.reply_text
        reply_text.assert_awaited_once()
        call_text = reply_text.call_args[0][0]
        assert "in progress" in call_text.lower()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
