"""Unit tests for bot.py handler methods in _BotHandlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot import _BotHandlers, build_app, _stream_to_telegram
from src.config import Settings, TelegramConfig, BotConfig, AIConfig, GitHubConfig
from src.ai.adapter import AICLIBackend


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_settings(
    chat_id="99999",
    prefix="ta",
    allowed_users=None,
    stream=False,
    history_enabled=True,
    max_output=3000,
    stream_throttle=1.0,
):
    tg = MagicMock(spec=TelegramConfig)
    tg.chat_id = chat_id
    tg.allowed_users = allowed_users or []
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = prefix
    bot.max_output_chars = max_output
    bot.stream_responses = stream
    bot.history_enabled = history_enabled
    bot.stream_throttle_secs = stream_throttle
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = "api"
    ai.copilot_model = ""
    ai.codex_model = "o3"
    ai.ai_provider = "openai"
    ai.ai_model = "gpt-4o"
    s = MagicMock(spec=Settings)
    s.telegram = tg
    s.bot = bot
    s.github = gh
    s.ai = ai
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


def _make_backend(stateful=False, response="AI response"):
    backend = MagicMock(spec=AICLIBackend)
    backend.is_stateful = stateful
    backend.send = AsyncMock(return_value=response)
    backend.clear_history = MagicMock()

    async def _stream(prompt):
        yield response

    backend.stream = _stream
    return backend


def _make_handlers(settings=None, backend=None):
    settings = settings or _make_settings()
    backend = backend or _make_backend()
    return _BotHandlers(settings, backend, start_time=0.0)


# ── cmd_run ───────────────────────────────────────────────────────────────────

class TestCmdRun:
    async def test_safe_command_runs(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["ls", "-la"]

        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="output")) as mock_run, \
             patch("src.bot.executor.is_destructive", return_value=False):
            await h.cmd_run(update, ctx)
            mock_run.assert_awaited_once()

    async def test_empty_args_sends_usage(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        await h.cmd_run(update, ctx)
        update.effective_message.reply_text.assert_awaited()
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert "Usage" in call_text

    async def test_destructive_command_shows_keyboard(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["git", "push"]

        with patch("src.bot.executor.is_destructive", return_value=True):
            await h.cmd_run(update, ctx)
        msg = update.effective_message.reply_text.call_args
        assert msg is not None  # confirmation message sent


# ── cmd_sync ──────────────────────────────────────────────────────────────────

class TestCmdSync:
    async def test_cmd_sync_calls_pull(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        with patch("src.bot.repo.pull", new=AsyncMock(return_value="Already up to date.")):
            await h.cmd_sync(update, ctx)
        assert update.effective_message.reply_text.call_count >= 1


# ── cmd_git ───────────────────────────────────────────────────────────────────

class TestCmdGit:
    async def test_cmd_git_calls_status(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        with patch("src.bot.repo.status", new=AsyncMock(return_value="M file.py\nabc1234 msg")):
            await h.cmd_git(update, ctx)
        assert update.effective_message.reply_text.call_count >= 1


# ── cmd_status ────────────────────────────────────────────────────────────────

class TestCmdStatus:
    async def test_idle_response(self):
        h = _make_handlers()
        update = _make_update()
        await h.cmd_status(update, MagicMock())
        reply_text = update.effective_message.reply_text.call_args[0][0]
        assert "idle" in reply_text.lower()

    async def test_active_ai_shown(self):
        import time
        h = _make_handlers()
        h._active_ai["some long prompt here..."] = time.time()
        update = _make_update()
        await h.cmd_status(update, MagicMock())
        reply_text = update.effective_message.reply_text.call_args[0][0]
        assert "some long prompt" in reply_text


# ── cmd_clear ─────────────────────────────────────────────────────────────────

class TestCmdClear:
    async def test_clears_sqlite_and_backend(self):
        backend = _make_backend()
        h = _make_handlers(backend=backend)
        update = _make_update()

        with patch("src.bot.history.clear_history", new=AsyncMock()) as mock_hist:
            await h.cmd_clear(update, MagicMock())
            mock_hist.assert_awaited_once()
        backend.clear_history.assert_called_once()

    async def test_clear_skips_sqlite_when_disabled(self):
        settings = _make_settings(history_enabled=False)
        backend = _make_backend()
        h = _make_handlers(settings=settings, backend=backend)
        update = _make_update()

        with patch("src.bot.history.clear_history", new=AsyncMock()) as mock_hist:
            await h.cmd_clear(update, MagicMock())
            mock_hist.assert_not_awaited()


# ── _requires_auth ────────────────────────────────────────────────────────────

class TestRequiresAuth:
    async def test_wrong_chat_id_blocked(self):
        h = _make_handlers(_make_settings(chat_id="99999"))
        update = _make_update(chat_id="11111")  # different chat
        await h.cmd_status(update, MagicMock())
        update.effective_message.reply_text.assert_not_awaited()

    async def test_wrong_user_blocked(self):
        settings = _make_settings(chat_id="99999", allowed_users=[100])
        h = _make_handlers(settings)
        update = _make_update(chat_id="99999", user_id=999)
        await h.cmd_status(update, MagicMock())
        update.effective_message.reply_text.assert_not_awaited()

    async def test_allowed_user_passes(self):
        settings = _make_settings(chat_id="99999", allowed_users=[42])
        h = _make_handlers(settings)
        update = _make_update(chat_id="99999", user_id=42)
        await h.cmd_status(update, MagicMock())
        update.effective_message.reply_text.assert_awaited()


# ── forward_to_ai ─────────────────────────────────────────────────────────────

class TestForwardToAI:
    async def test_stateful_sends_raw_prompt(self):
        backend = _make_backend(stateful=True)
        h = _make_handlers(backend=backend)
        update = _make_update(text="hello AI")

        with patch("src.bot.history.add_exchange", new=AsyncMock()), \
             patch("src.bot.history.get_history", new=AsyncMock(return_value=[])):
            await h.forward_to_ai(update, MagicMock())

        backend.send.assert_awaited_once_with("hello AI")

    async def test_stateless_injects_history(self):
        backend = _make_backend(stateful=False)
        h = _make_handlers(backend=backend)
        update = _make_update(text="hello AI")
        hist = [("prev q", "prev a")]

        with patch("src.bot.history.get_history", new=AsyncMock(return_value=hist)), \
             patch("src.bot.history.add_exchange", new=AsyncMock()):
            await h.forward_to_ai(update, MagicMock())

        call_prompt = backend.send.call_args[0][0]
        assert "prev q" in call_prompt
        assert "hello AI" in call_prompt

    async def test_error_sends_warning(self):
        backend = _make_backend()
        backend.send = AsyncMock(side_effect=RuntimeError("boom"))
        h = _make_handlers(backend=backend)
        update = _make_update(text="test")

        with patch("src.bot.history.get_history", new=AsyncMock(return_value=[])), \
             patch("src.bot.history.add_exchange", new=AsyncMock()):
            await h.forward_to_ai(update, MagicMock())

        reply_text = update.effective_message.reply_text.call_args[0][0]
        assert "⚠️" in reply_text

    async def test_empty_text_ignored(self):
        backend = _make_backend()
        h = _make_handlers(backend=backend)
        update = _make_update(text="")
        update.effective_message.text = ""
        await h.forward_to_ai(update, MagicMock())
        backend.send.assert_not_awaited()


# ── callback_handler ──────────────────────────────────────────────────────────

class TestCallbackHandler:
    async def test_confirm_runs_command(self):
        h = _make_handlers()
        update = _make_update()
        query = AsyncMock()
        query.data = "confirm_run"
        query.message.message_id = 1
        query.message.reply_text = AsyncMock()
        update.callback_query = query
        h._pending_cmds[(int("99999"), 1)] = "ls -la"

        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="output")):
            await h.callback_handler(update, MagicMock())
        query.edit_message_text.assert_awaited()

    async def test_cancel_aborts(self):
        h = _make_handlers()
        update = _make_update()
        query = AsyncMock()
        query.data = "cancel_run"
        query.message.message_id = 2
        update.callback_query = query
        h._pending_cmds[(int("99999"), 2)] = "rm -rf /"

        await h.callback_handler(update, MagicMock())
        query.edit_message_text.assert_awaited_with("❌ Cancelled.")
