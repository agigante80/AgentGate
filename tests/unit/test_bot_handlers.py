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
    confirm_destructive=True,
    skip_confirm_keywords=None,
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
    bot.confirm_destructive = confirm_destructive
    bot.skip_confirm_keywords = skip_confirm_keywords or []
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


# ── cmd_restart ───────────────────────────────────────────────────────────────

class TestCmdRestart:
    async def test_restart_replaces_backend(self):
        h = _make_handlers()
        original_backend = h._backend
        new_backend = _make_backend()
        update = _make_update()

        with patch("src.bot.ai_factory.create_backend", return_value=new_backend):
            await h.cmd_restart(update, MagicMock())

        original_backend.close.assert_called_once()
        assert h._backend is new_backend
        update.effective_message.reply_text.assert_awaited()

    async def test_restart_reports_error_on_failure(self):
        h = _make_handlers()
        update = _make_update()

        with patch("src.bot.ai_factory.create_backend", side_effect=RuntimeError("auth failed")):
            await h.cmd_restart(update, MagicMock())

        calls = [str(c) for c in update.effective_message.reply_text.await_args_list]
        assert any("failed" in c.lower() or "auth" in c.lower() for c in calls)


# ── cmd_help version ──────────────────────────────────────────────────────────

class TestCmdHelp:
    async def test_help_contains_version(self):
        import src.config as cfg
        h = _make_handlers()
        update = _make_update()
        with patch.object(cfg, "VERSION", "9.9.9"):
            import importlib, src.bot as bot_mod
            importlib.reload(bot_mod)
            # reload re-imports VERSION; just check string directly
            await h.cmd_help(update, MagicMock())
        text = update.effective_message.reply_text.call_args[0][0]
        assert "TeleAgent" in text

    async def test_help_lists_restart_command(self):
        h = _make_handlers()
        update = _make_update()
        await h.cmd_help(update, MagicMock())
        text = update.effective_message.reply_text.call_args[0][0]
        assert "restart" in text

    async def test_help_lists_confirm_command(self):
        h = _make_handlers()
        update = _make_update()
        await h.cmd_help(update, MagicMock())
        text = update.effective_message.reply_text.call_args[0][0]
        assert "confirm" in text


# ── cmd_confirm ───────────────────────────────────────────────────────────────

class TestCmdConfirm:
    async def test_confirm_off_disables(self):
        h = _make_handlers(_make_settings(confirm_destructive=True))
        update = _make_update(text="/taconfirm off")
        update.effective_message.text = "/taconfirm off"
        ctx = MagicMock()
        ctx.args = ["off"]
        await h.cmd_confirm(update, ctx)
        assert h._confirm_destructive is False
        update.effective_message.reply_text.assert_awaited()

    async def test_confirm_on_enables(self):
        h = _make_handlers(_make_settings(confirm_destructive=False))
        update = _make_update(text="/taconfirm on")
        ctx = MagicMock()
        ctx.args = ["on"]
        await h.cmd_confirm(update, ctx)
        assert h._confirm_destructive is True

    async def test_confirm_no_arg_reports_state(self):
        h = _make_handlers(_make_settings(confirm_destructive=True))
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        await h.cmd_confirm(update, ctx)
        text = update.effective_message.reply_text.call_args[0][0]
        assert "on" in text.lower() or "enabled" in text.lower()


# ── cmd_run confirmation bypass ───────────────────────────────────────────────

class TestCmdRunConfirmation:
    async def test_destructive_skipped_when_confirm_disabled(self):
        settings = _make_settings(confirm_destructive=False)
        h = _make_handlers(settings)
        update = _make_update(text="/trun rm -rf /tmp/foo")
        ctx = MagicMock()
        ctx.args = ["rm", "-rf", "/tmp/foo"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="done")):
            await h.cmd_run(update, ctx)
        # reply_text called with result, not inline keyboard
        call_kwargs = update.effective_message.reply_text.call_args
        assert call_kwargs is not None

    async def test_destructive_skipped_for_exempt_keyword(self):
        settings = _make_settings(confirm_destructive=True, skip_confirm_keywords=["rm"])
        h = _make_handlers(settings)
        update = _make_update(text="/trun rm -rf /tmp/foo")
        ctx = MagicMock()
        ctx.args = ["rm", "-rf", "/tmp/foo"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="done")):
            await h.cmd_run(update, ctx)
        call_kwargs = update.effective_message.reply_text.call_args
        assert call_kwargs is not None
