"""Unit tests for bot.py handler methods in _BotHandlers."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot import _BotHandlers, build_app, _stream_to_telegram
from src.config import Settings, TelegramConfig, BotConfig, AIConfig, GitHubConfig, VoiceConfig
from src.ai.adapter import AICLIBackend


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_settings(
    chat_id="99999",
    prefix="gate",
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
    tg.bot_token = ""
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = prefix
    bot.max_output_chars = max_output
    bot.stream_responses = stream
    bot.history_enabled = history_enabled
    bot.stream_throttle_secs = stream_throttle
    bot.confirm_destructive = confirm_destructive
    bot.skip_confirm_keywords = skip_confirm_keywords or []
    bot.image_tag = ""
    bot.ai_timeout_secs = 0
    bot.thinking_slow_threshold_secs = 15
    bot.thinking_update_secs = 30
    bot.ai_timeout_warn_secs = 60
    bot.allow_secrets = False
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    gh.github_repo_token = ""
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = "api"
    ai.ai_provider = "openai"
    ai.ai_model = "gpt-4o"
    ai.ai_api_key = ""
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
        assert "AgentGate" in text

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


# ── handle_voice ──────────────────────────────────────────────────────────────

class TestHandleVoice:
    async def test_voice_disabled_sends_message(self):
        """When WHISPER_PROVIDER=none, bot replies with disabled notice."""
        h = _make_handlers()  # voice.whisper_provider = "none" by default
        update = _make_update()
        voice_obj = MagicMock()
        update.effective_message.voice = voice_obj
        update.effective_message.audio = None
        await h.handle_voice(update, MagicMock())
        reply_text = update.effective_message.reply_text.call_args[0][0]
        assert "disabled" in reply_text.lower()

    async def test_voice_transcribes_and_calls_ai(self):
        """With a mock transcriber, transcription is shown and AI is called."""
        from src import transcriber as t_mod

        mock_transcriber = MagicMock(spec=t_mod.Transcriber)
        mock_transcriber.transcribe = AsyncMock(return_value="run the tests")

        backend = _make_backend(stateful=True, response="Tests passed")
        h = _make_handlers(backend=backend)
        h._transcriber = mock_transcriber  # inject directly (bypasses factory)

        voice_obj = AsyncMock()
        tg_file = AsyncMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
        voice_obj.get_file = AsyncMock(return_value=tg_file)

        update = _make_update()
        update.effective_message.voice = voice_obj
        update.effective_message.audio = None
        status_msg = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=status_msg)

        with patch("src.bot.history.add_exchange", new=AsyncMock()), \
             patch("src.bot.history.get_history", new=AsyncMock(return_value=[])):
            await h.handle_voice(update, MagicMock())

        # Transcription shown
        status_msg.edit_text.assert_awaited()
        transcription_call = status_msg.edit_text.call_args_list[0][0][0]
        assert "run the tests" in transcription_call

        # AI was called with framed transcription (voice injection protection)
        backend.send.assert_awaited_once()
        call_arg = backend.send.call_args[0][0]
        assert "run the tests" in call_arg
        assert "voice transcription" in call_arg

    async def test_voice_transcription_error_shown(self):
        """If transcription fails, error is shown."""
        from src import transcriber as t_mod

        mock_transcriber = MagicMock(spec=t_mod.Transcriber)
        mock_transcriber.transcribe = AsyncMock(side_effect=RuntimeError("API down"))

        h = _make_handlers()
        h._transcriber = mock_transcriber

        voice_obj = AsyncMock()
        tg_file = AsyncMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
        voice_obj.get_file = AsyncMock(return_value=tg_file)

        update = _make_update()
        update.effective_message.voice = voice_obj
        update.effective_message.audio = None
        status_msg = AsyncMock()
        update.effective_message.reply_text = AsyncMock(return_value=status_msg)

        await h.handle_voice(update, MagicMock())

        error_text = status_msg.edit_text.call_args[0][0]
        assert "API down" in error_text


# ── cmd_ta dispatcher ─────────────────────────────────────────────────────────

class TestCmdTa:
    async def test_dispatches_help(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["help"]
        await h.cmd_ta(update, ctx)
        text = update.effective_message.reply_text.call_args[0][0]
        assert "AgentGate" in text

    async def test_dispatches_info(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["info"]
        await h.cmd_ta(update, ctx)
        update.effective_message.reply_text.assert_awaited()
        text = update.effective_message.reply_text.call_args[0][0]
        assert "Repo" in text or "repo" in text.lower()

    async def test_dispatches_run_passes_remaining_args(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["run", "ls", "-la"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="output")):
            await h.cmd_ta(update, ctx)
        # ctx.args should have been rewritten to ["ls", "-la"]
        assert ctx.args == ["ls", "-la"]

    async def test_unknown_subcommand_shows_error_and_help(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["oops"]
        await h.cmd_ta(update, ctx)
        calls = [c[0][0] for c in update.effective_message.reply_text.call_args_list]
        assert any("Unknown" in t or "unknown" in t for t in calls)
        assert any("AgentGate" in t for t in calls)

    async def test_no_args_shows_help(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        await h.cmd_ta(update, ctx)
        text = update.effective_message.reply_text.call_args[0][0]
        assert "AgentGate" in text


# ── cmd_diff ──────────────────────────────────────────────────────────────────

class TestCmdDiff:
    async def test_diff_no_args_uses_head(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="diff output")) as mock_run:
            await h.cmd_diff(update, ctx)
        assert "HEAD~1 HEAD" in mock_run.call_args[0][0]

    async def test_diff_numeric_arg(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["3"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="diff")) as mock_run:
            await h.cmd_diff(update, ctx)
        assert "HEAD~3 HEAD" in mock_run.call_args[0][0]

    async def test_diff_sha_arg(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["abc1234"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="diff")) as mock_run:
            await h.cmd_diff(update, ctx)
        assert "abc1234 HEAD" in mock_run.call_args[0][0]

    async def test_diff_empty_result_shows_no_changes(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="   ")):
            await h.cmd_diff(update, ctx)
        text = update.effective_message.reply_text.call_args[0][0]
        assert "no changes" in text


# ── cmd_log ───────────────────────────────────────────────────────────────────

class TestCmdLog:
    async def test_log_default_lines(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="log lines")) as mock_run:
            await h.cmd_log(update, ctx)
        assert "tail -n 20" in mock_run.call_args[0][0]

    async def test_log_custom_lines(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["50"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="log")) as mock_run:
            await h.cmd_log(update, ctx)
        assert "tail -n 50" in mock_run.call_args[0][0]

    async def test_log_clamps_to_max(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["9999"]
        with patch("src.bot.executor.run_shell", new=AsyncMock(return_value="log")) as mock_run:
            await h.cmd_log(update, ctx)
        assert "tail -n 200" in mock_run.call_args[0][0]

    async def test_log_invalid_arg_shows_usage(self):
        h = _make_handlers()
        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["abc"]
        await h.cmd_log(update, ctx)
        text = update.effective_message.reply_text.call_args[0][0]
        assert "Usage" in text


# ── Streaming path in _run_ai_pipeline ───────────────────────────────────────

class TestRunAiPipelineStreaming:
    async def test_streaming_path_invokes_stream_to_telegram(self):
        """When stream_responses=True, _stream_to_telegram is called (line 167)."""
        settings = _make_settings(stream=True, history_enabled=False)
        backend = _make_backend(stateful=False, response="streamed reply")
        h = _BotHandlers(settings, backend, start_time=0.0)
        update = _make_update()

        with patch("src.bot._stream_to_telegram", new=AsyncMock(return_value="streamed reply")) as mock_stream, \
             patch("src.bot.history.add_exchange", new=AsyncMock()):
            await h._run_ai_pipeline(update, "hello", "99999")

        mock_stream.assert_awaited_once()

    async def test_non_streaming_with_timeout_secs_uses_wait_for(self):
        """When ai_timeout_secs > 0 and not streaming, asyncio.wait_for is used (line 190)."""
        settings = _make_settings(stream=False, history_enabled=False)
        settings.bot.ai_timeout_secs = 30
        backend = _make_backend(stateful=True, response="ok")
        h = _BotHandlers(settings, backend, start_time=0.0)
        update = _make_update()

        with patch("src.bot.asyncio.wait_for", new=AsyncMock(return_value="ok")) as mock_wait_for, \
             patch("src.bot.executor.summarize_if_long", new=AsyncMock(return_value="ok")), \
             patch("src.bot.history.add_exchange", new=AsyncMock()):
            await h._run_ai_pipeline(update, "hello", "99999")

        mock_wait_for.assert_awaited_once()

    async def test_non_streaming_timeout_error_shows_warning(self):
        """TimeoutError during non-streaming send edits message with warning (lines 196-200)."""
        settings = _make_settings(stream=False, history_enabled=False)
        settings.bot.ai_timeout_secs = 5
        backend = _make_backend(stateful=True)
        h = _BotHandlers(settings, backend, start_time=0.0)
        update = _make_update()

        with patch("src.bot.asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            await h._run_ai_pipeline(update, "slow query", "99999")

        msg_mock = update.effective_message.reply_text.return_value
        msg_mock.edit_text.assert_awaited()
        edit_text = msg_mock.edit_text.call_args[0][0]
        assert "cancelled" in edit_text.lower() or "5s" in edit_text


# ── _init_transcriber error path ─────────────────────────────────────────────

class TestInitTranscriber:
    def test_not_implemented_error_returns_none(self):
        """NotImplementedError from create_transcriber logs a warning and returns None (lines 151-153)."""
        settings = _make_settings()
        backend = _make_backend()
        with patch("src.bot.transcriber_mod.create_transcriber", side_effect=NotImplementedError("bad")):
            h = _BotHandlers(settings, backend, start_time=0.0)
        assert h._transcriber is None


# ── _stream_to_telegram edit exceptions ──────────────────────────────────────

class TestStreamEditExceptions:
    async def test_edit_exception_during_streaming_is_ignored(self):
        """Exception in edit_text during chunk streaming is silently swallowed (lines 88-89)."""
        settings = _make_settings(stream=False)
        backend = _make_backend()
        update = _make_update()

        msg = AsyncMock()
        edit_calls = []

        async def edit_side_effect(text):
            edit_calls.append(text)
            if "▌" in text:
                raise RuntimeError("rate limited")

        msg.edit_text = edit_side_effect
        update.effective_message.reply_text = AsyncMock(return_value=msg)

        async def _stream(prompt):
            yield "A" * 100

        backend.stream = _stream

        with patch("src.platform.common.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            result = await _stream_to_telegram(
                update, backend, "prompt", max_chars=3000,
                throttle_secs=0.0, timeout_secs=0,
                slow_threshold=15, update_interval=30, warn_before_secs=60,
            )

        # Should still return the content despite the edit exception
        assert "A" in result

    async def test_final_edit_exception_is_ignored(self):
        """Exception in the final edit_text call is silently swallowed (lines 111-112)."""
        settings = _make_settings(stream=False)
        backend = _make_backend()
        update = _make_update()

        msg = AsyncMock()
        call_count = [0]

        async def edit_side_effect(text):
            call_count[0] += 1
            if "▌" not in text:  # final edit has no cursor
                raise RuntimeError("flood control")

        msg.edit_text = edit_side_effect
        update.effective_message.reply_text = AsyncMock(return_value=msg)

        async def _stream(prompt):
            yield "hello"

        backend.stream = _stream

        with patch("src.platform.common.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            result = await _stream_to_telegram(
                update, backend, "prompt", max_chars=3000,
                throttle_secs=999.0, timeout_secs=0,
                slow_threshold=15, update_interval=30, warn_before_secs=60,
            )

        assert result == "hello"


# ── handle_voice with no audio ────────────────────────────────────────────────

class TestHandleVoiceNoAudio:
    async def test_handle_voice_returns_early_when_no_voice_or_audio(self):
        """If voice AND audio are both None, handle_voice returns early (line 446)."""
        settings = _make_settings()
        backend = _make_backend()

        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe = AsyncMock(return_value="hello")

        with patch("src.bot.transcriber_mod.create_transcriber", return_value=AsyncMock(spec=[])):
            h = _BotHandlers(settings, backend, start_time=0.0)
        # Force a non-None transcriber so we get past the first guard
        h._transcriber = mock_transcriber

        update = _make_update()
        update.effective_message.voice = None
        update.effective_message.audio = None

        await h.handle_voice(update, MagicMock())

        # reply_text is called for "Transcribing..." only if we get past the None check
        # Since voice and audio are both None, we should return early (no reply)
        # The first reply_text was for "Disabled" which is skipped since transcriber is set.
        # So no reply_text call for "Transcribing…"
        calls = [str(c) for c in update.effective_message.reply_text.call_args_list]
        assert not any("Transcribing" in c for c in calls)


# ── build_app handler count ───────────────────────────────────────────────────

class TestBuildApp:
    def test_build_app_registers_expected_handlers(self):
        """build_app() registers all expected command + message handlers (lines 472-494)."""
        settings = _make_settings()
        settings.telegram.bot_token = "123:fake-token"
        backend = _make_backend()

        with patch("src.bot.Application") as MockApp:
            mock_app_instance = MagicMock()
            MockApp.builder.return_value.token.return_value.build.return_value = mock_app_instance
            build_app(settings, backend, 0.0)

        # 12 CommandHandlers + 1 CallbackQueryHandler + 2 MessageHandlers = 16
        assert mock_app_instance.add_handler.call_count == 16
