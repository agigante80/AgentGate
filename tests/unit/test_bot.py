"""Unit tests for bot.py — pure functions (_prefix, _is_allowed)."""
import pytest
from unittest.mock import MagicMock

from src.bot import _is_allowed, _prefix
from src.config import Settings, TelegramConfig, GitHubConfig, BotConfig, AIConfig


def _make_settings(chat_id="99999", prefix="gate", allowed_users=None):
    tg = MagicMock(spec=TelegramConfig)
    tg.chat_id = chat_id
    tg.allowed_users = allowed_users or []
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = prefix
    s = MagicMock(spec=Settings)
    s.telegram = tg
    s.bot = bot
    return s


def _make_update(chat_id="99999", user_id=None):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    if user_id is not None:
        update.effective_user.id = user_id
    else:
        update.effective_user = None
    return update


class TestPrefix:
    def test_default_prefix(self):
        s = _make_settings(prefix="gate")
        assert _prefix(s) == "gate"

    def test_uppercase_normalized(self):
        s = _make_settings(prefix="GATE")
        assert _prefix(s) == "gate"

    def test_hyphens_stripped(self):
        s = _make_settings(prefix="my-bot")
        assert _prefix(s) == "mybot"

    def test_underscores_stripped(self):
        s = _make_settings(prefix="my_bot")
        assert _prefix(s) == "mybot"

    def test_mixed_stripped(self):
        s = _make_settings(prefix="My_Bot-2")
        assert _prefix(s) == "mybot2"


class TestIsAllowed:
    def test_correct_chat_allowed(self):
        s = _make_settings(chat_id="99999")
        u = _make_update(chat_id="99999")
        assert _is_allowed(u, s) is True

    def test_wrong_chat_rejected(self):
        s = _make_settings(chat_id="99999")
        u = _make_update(chat_id="11111")
        assert _is_allowed(u, s) is False

    def test_allowed_user_in_correct_chat(self):
        s = _make_settings(chat_id="99999", allowed_users=[42])
        u = _make_update(chat_id="99999", user_id=42)
        assert _is_allowed(u, s) is True

    def test_disallowed_user_in_correct_chat(self):
        s = _make_settings(chat_id="99999", allowed_users=[42])
        u = _make_update(chat_id="99999", user_id=99)
        assert _is_allowed(u, s) is False

    def test_no_user_with_allowlist_rejected(self):
        s = _make_settings(chat_id="99999", allowed_users=[42])
        u = _make_update(chat_id="99999", user_id=None)
        assert _is_allowed(u, s) is False

    def test_no_allowlist_any_user_ok(self):
        s = _make_settings(chat_id="99999", allowed_users=[])
        u = _make_update(chat_id="99999", user_id=9999)
        assert _is_allowed(u, s) is True


# ── Ticker integration tests ──────────────────────────────────────────────────

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

from src.bot import _stream_to_telegram
from src.ai.adapter import AICLIBackend


class TestStreamToTelegramTicker:
    """Tests for _stream_to_telegram ticker lifecycle."""

    def _make_backend(self, chunks: list[str]):
        backend = MagicMock(spec=AICLIBackend)

        async def _stream(prompt):
            for chunk in chunks:
                yield chunk

        backend.stream = _stream
        return backend

    async def test_fast_response_ticker_cancelled_before_firing(self):
        """First chunk arrives before slow_threshold — ticker never fires."""
        backend = self._make_backend(["hello"])
        update = MagicMock()
        msg = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=msg)

        edit_calls = []

        async def record_edit(text):
            edit_calls.append(text)

        msg.edit_text = record_edit

        with patch("src.platform.common.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            result = await _stream_to_telegram(
                update, backend, "prompt", max_chars=3000,
                throttle_secs=0.0, timeout_secs=0,
                slow_threshold=15, update_interval=30, warn_before_secs=60,
            )

        # No "Still thinking" edits should appear
        thinking_edits = [t for t in edit_calls if "Still thinking" in t]
        assert thinking_edits == []
        assert result == "hello"

    async def test_timeout_error_posts_error_message(self):
        """When asyncio.TimeoutError fires, user sees the timeout error message."""
        backend = MagicMock(spec=AICLIBackend)

        async def _never_stream(prompt):
            await asyncio.sleep(9999)
            yield "never"

        backend.stream = _never_stream

        update = MagicMock()
        msg = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=msg)

        edit_texts = []

        async def record_edit(text):
            edit_texts.append(text)

        msg.edit_text = record_edit

        with patch("src.platform.common.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            with patch("src.bot.asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)):
                result = await _stream_to_telegram(
                    update, backend, "prompt", max_chars=3000,
                    throttle_secs=0.0, timeout_secs=30,
                    slow_threshold=15, update_interval=30, warn_before_secs=60,
                )

        assert result == ""
        assert any("cancelled" in t.lower() or "cancelled" in t.lower() for t in edit_texts)


# ── sanitize_git_ref via cmd_diff ────────────────────────────────────────────

class TestCmdDiffSanitization:
    """cmd_diff must reject malicious git refs before calling run_shell."""

    async def test_malicious_ref_rejected(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from src.bot import build_app
        from src.config import Settings, TelegramConfig, BotConfig, AIConfig, GitHubConfig, VoiceConfig, SlackConfig

        settings = MagicMock(spec=Settings)
        tg = MagicMock(spec=TelegramConfig)
        tg.chat_id = "99999"
        tg.allowed_users = []
        bot_cfg = MagicMock(spec=BotConfig)
        bot_cfg.bot_cmd_prefix = "gate"
        bot_cfg.max_output_chars = 3000
        bot_cfg.stream_responses = False
        bot_cfg.history_enabled = False
        bot_cfg.stream_throttle_secs = 1.0
        bot_cfg.confirm_destructive = False
        bot_cfg.skip_confirm_keywords = []
        bot_cfg.prefix_only = False
        bot_cfg.system_prompt = ""
        bot_cfg.ai_timeout_secs = 0
        bot_cfg.thinking_slow_threshold_secs = 15
        bot_cfg.thinking_update_secs = 30
        bot_cfg.ai_timeout_warn_secs = 60
        bot_cfg.allow_secrets = False
        settings.telegram = tg
        settings.bot = bot_cfg
        settings.platform = "telegram"
        settings.slack = MagicMock(spec=SlackConfig)
        settings.slack.slack_bot_token = ""
        settings.slack.slack_app_token = ""
        settings.ai = MagicMock(spec=AIConfig)
        settings.ai.ai_cli = "api"
        settings.ai.ai_api_key = "sk-test"
        settings.github = MagicMock(spec=GitHubConfig)
        settings.github.github_repo_token = ""
        settings.voice = MagicMock(spec=VoiceConfig)
        settings.voice.whisper_provider = "none"
        settings.voice.whisper_api_key = ""

        from src.bot import _BotHandlers
        backend = MagicMock()
        backend.is_stateful = False
        handlers = _BotHandlers(settings, backend, start_time=0.0)

        update = MagicMock()
        update.effective_chat.id = 99999
        update.effective_user = None
        reply_texts = []
        update.effective_message.reply_text = AsyncMock(side_effect=lambda t, **kw: reply_texts.append(t))
        ctx = MagicMock()
        ctx.args = ["; rm -rf /"]

        with patch("src.executor.run_shell", AsyncMock(return_value="")) as mock_run:
            await handlers.cmd_diff(update, ctx)

        mock_run.assert_not_called()
        assert any("Invalid git ref" in t for t in reply_texts)

    async def test_valid_ref_calls_run_shell(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from src.config import Settings, TelegramConfig, BotConfig, AIConfig, GitHubConfig, VoiceConfig, SlackConfig
        from src.bot import _BotHandlers

        settings = MagicMock(spec=Settings)
        tg = MagicMock(spec=TelegramConfig)
        tg.chat_id = "99999"
        tg.allowed_users = []
        bot_cfg = MagicMock(spec=BotConfig)
        bot_cfg.bot_cmd_prefix = "gate"
        bot_cfg.max_output_chars = 3000
        bot_cfg.stream_responses = False
        bot_cfg.history_enabled = False
        bot_cfg.stream_throttle_secs = 1.0
        bot_cfg.confirm_destructive = False
        bot_cfg.skip_confirm_keywords = []
        bot_cfg.prefix_only = False
        bot_cfg.system_prompt = ""
        bot_cfg.ai_timeout_secs = 0
        bot_cfg.thinking_slow_threshold_secs = 15
        bot_cfg.thinking_update_secs = 30
        bot_cfg.ai_timeout_warn_secs = 60
        bot_cfg.allow_secrets = False
        settings.telegram = tg
        settings.bot = bot_cfg
        settings.platform = "telegram"
        settings.slack = MagicMock(spec=SlackConfig)
        settings.slack.slack_bot_token = ""
        settings.slack.slack_app_token = ""
        settings.ai = MagicMock(spec=AIConfig)
        settings.ai.ai_cli = "api"
        settings.ai.ai_api_key = "sk-test"
        settings.github = MagicMock(spec=GitHubConfig)
        settings.github.github_repo_token = ""
        settings.voice = MagicMock(spec=VoiceConfig)
        settings.voice.whisper_provider = "none"
        settings.voice.whisper_api_key = ""

        backend = MagicMock()
        backend.is_stateful = False
        handlers = _BotHandlers(settings, backend, start_time=0.0)

        update = MagicMock()
        update.effective_chat.id = 99999
        update.effective_user = None
        update.effective_message.reply_text = AsyncMock(return_value=None)
        ctx = MagicMock()
        ctx.args = ["main"]

        with patch("src.executor.run_shell", AsyncMock(return_value="some diff")) as mock_run:
            await handlers.cmd_diff(update, ctx)

        mock_run.assert_called_once()
        call_cmd = mock_run.call_args[0][0]
        assert "'main'" in call_cmd or "main" in call_cmd
