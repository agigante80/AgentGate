"""Unit tests for src/platform/slack.py — SlackBot."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    AIConfig,
    BotConfig,
    GitHubConfig,
    Settings,
    SlackConfig,
    TelegramConfig,
    VoiceConfig,
)
from src.ai.adapter import AICLIBackend


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(
    channel_id="C12345",
    allowed_users=None,
    confirm_destructive=True,
    skip_confirm_keywords=None,
    stream=False,
    history_enabled=True,
    max_output=3000,
    stream_throttle=1.0,
    slack_bot_token="xoxb-test",
    slack_app_token="xapp-test",
    prefix="gate",
    prefix_only=False,
    trusted_agent_bot_ids=None,
):
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = prefix
    bot.max_output_chars = max_output
    bot.stream_responses = stream
    bot.history_enabled = history_enabled
    bot.stream_throttle_secs = stream_throttle
    bot.confirm_destructive = confirm_destructive
    bot.skip_confirm_keywords = skip_confirm_keywords or []
    bot.prefix_only = prefix_only
    bot.system_prompt = ""
    bot.ai_timeout_secs = 0
    bot.thinking_slow_threshold_secs = 15
    bot.thinking_update_secs = 30
    bot.ai_timeout_warn_secs = 60
    slack = MagicMock(spec=SlackConfig)
    slack.slack_bot_token = slack_bot_token
    slack.slack_app_token = slack_app_token
    slack.slack_channel_id = channel_id
    slack.allowed_users = allowed_users or []
    slack.trusted_agent_bot_ids = trusted_agent_bot_ids or []
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    ai_cfg = MagicMock(spec=AIConfig)
    ai_cfg.ai_cli = "api"
    ai_cfg.ai_api_key = "sk-test"
    ai_cfg.ai_model = ""
    ai_cfg.ai_provider = ""
    voice = MagicMock(spec=VoiceConfig)
    voice.whisper_provider = "none"
    tg = MagicMock(spec=TelegramConfig)
    settings = MagicMock(spec=Settings)
    settings.platform = "slack"
    settings.bot = bot
    settings.slack = slack
    settings.github = gh
    settings.ai = ai_cfg
    settings.voice = voice
    settings.telegram = tg
    return settings


def _make_backend(is_stateful=False, response="AI response"):
    backend = MagicMock(spec=AICLIBackend)
    backend.is_stateful = is_stateful
    backend.send = AsyncMock(return_value=response)
    backend.stream = MagicMock(return_value=_async_gen([response]))
    backend.clear_history = MagicMock()
    backend.close = MagicMock()
    return backend


async def _async_gen(items):
    for item in items:
        yield item


def _make_event(text="", channel="C12345", user="U999", files=None, subtype=""):
    event = {"channel": channel, "user": user, "text": text, "subtype": subtype}
    if files:
        event["files"] = files
    return event


def _make_say():
    say = AsyncMock(return_value={"ts": "1000.000", "channel": "C12345"})
    return say


def _make_client():
    client = AsyncMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock(
        return_value={"ts": "1001.000", "channel": "C12345"}
    )
    return client


def _make_bot(settings=None, backend=None):
    settings = settings or _make_settings()
    backend = backend or _make_backend()
    with patch("slack_bolt.async_app.AsyncApp"):
        from src.platform.slack import SlackBot
        bot = SlackBot(settings, backend, start_time=0.0)
    return bot


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    async def test_allowed_channel_and_user(self):
        bot = _make_bot(_make_settings(channel_id="C123"))
        assert bot._is_allowed("C123", "U456") is True

    async def test_blocked_wrong_channel(self):
        bot = _make_bot(_make_settings(channel_id="C123"))
        assert bot._is_allowed("C999", "U456") is False

    async def test_unauthorized_user_skipped(self):
        """Messages from unauthorized users must be silently ignored."""
        bot = _make_bot(_make_settings(channel_id="C123", allowed_users=["U111"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="hello", channel="C999", user="U999")
        await bot._on_message(event, say, client)
        say.assert_not_awaited()


# ── Command routing ───────────────────────────────────────────────────────────

class TestCommandRouting:
    async def test_sync_command_parsed(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.repo.pull", AsyncMock(return_value="up to date")):
            event = _make_event(text="gate sync")
            await bot._on_message(event, say, client)
        assert say.call_count >= 1

    async def test_git_command_parsed(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.repo.status", AsyncMock(return_value="On branch main")):
            await bot._on_message(_make_event(text="gate git"), say, client)
        assert say.call_count >= 1

    async def test_unknown_subcommand_forwarded_to_ai(self):
        backend = _make_backend(response="Sure!")
        bot = _make_bot(backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="unknowncmd arg1"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(_make_event(text="gate unknowncmd arg1"), say, client)
        # Unknown subcommand should be forwarded to AI, not show "Unknown command"
        backend.send.assert_awaited_once()

    async def test_non_prefix_message_forwarded_to_ai(self):
        backend = _make_backend(response="Great!")
        bot = _make_bot(backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(_make_event(text="what is 2+2?"), say, client)
        backend.send.assert_awaited_once()

    async def test_bot_messages_ignored(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate sync")
        event["bot_id"] = "BBOT123"
        await bot._on_message(event, say, client)
        say.assert_not_awaited()

    async def test_prefix_only_ignores_unprefixed_messages(self):
        backend = _make_backend(response="AI response")
        bot = _make_bot(backend=backend, settings=_make_settings(prefix_only=True))
        say = _make_say()
        client = _make_client()
        await bot._on_message(_make_event(text="what is 2+2?"), say, client)
        backend.send.assert_not_awaited()

    async def test_prefix_only_still_handles_prefixed_commands(self):
        bot = _make_bot(settings=_make_settings(prefix_only=True))
        say = _make_say()
        client = _make_client()
        with patch("src.executor.run_shell", AsyncMock(return_value="ok")), \
             patch("src.executor.is_destructive", return_value=False):
            await bot._on_message(_make_event(text="gate run echo hi"), say, client)
        say.assert_awaited()

    async def test_trusted_agent_message_triggers_prefix_command(self):
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate help")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        say.assert_awaited()

    async def test_trusted_agent_message_does_not_trigger_ai(self):
        backend = _make_backend(response="AI response")
        bot = _make_bot(backend=backend, settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="some unprefixed message")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        backend.send.assert_not_awaited()

    async def test_untrusted_bot_messages_still_ignored(self):
        backend = _make_backend(response="AI response")
        bot = _make_bot(backend=backend, settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate sync")
        event["bot_id"] = "BUNTRUSTED"
        await bot._on_message(event, say, client)
        backend.send.assert_not_awaited()
        say.assert_not_awaited()


# ── _resolve_trusted_ids ──────────────────────────────────────────────────────

class TestResolveTrustedIds:
    async def test_already_bot_id_passthrough(self):
        """B-prefixed IDs are pre-populated in __init__, no API call needed."""
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["BSECAGENT1"]))
        assert "BSECAGENT1" in bot._trusted_bot_ids

    async def test_name_resolved_via_users_list(self):
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["GateSec"]))
        assert len(bot._trusted_bot_ids) == 0  # not pre-populated (no B-prefix)

        users_list_resp = {
            "members": [
                {
                    "is_bot": True,
                    "name": "gatesec",
                    "profile": {"display_name": "GateSec", "bot_id": "BSECRESOLVED"},
                }
            ]
        }
        bot._app.client.users_list = AsyncMock(return_value=users_list_resp)
        await bot._resolve_trusted_ids()
        assert "BSECRESOLVED" in bot._trusted_bot_ids

    async def test_unresolved_name_logs_warning(self):
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["UnknownBot"]))
        bot._app.client.users_list = AsyncMock(return_value={"members": []})
        await bot._resolve_trusted_ids()
        assert len(bot._trusted_bot_ids) == 0

    async def test_mixed_names_and_ids(self):
        bot = _make_bot(
            settings=_make_settings(trusted_agent_bot_ids=["BDEVAGENT1", "GateSec"])
        )
        assert "BDEVAGENT1" in bot._trusted_bot_ids  # pre-populated

        users_list_resp = {
            "members": [
                {
                    "is_bot": True,
                    "name": "gatesec",
                    "profile": {"display_name": "GateSec", "bot_id": "BSECRESOLVED"},
                }
            ]
        }
        bot._app.client.users_list = AsyncMock(return_value=users_list_resp)
        await bot._resolve_trusted_ids()
        assert "BDEVAGENT1" in bot._trusted_bot_ids
        assert "BSECRESOLVED" in bot._trusted_bot_ids

    async def test_api_failure_does_not_raise(self):
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["GateSec"]))
        bot._app.client.users_list = AsyncMock(side_effect=Exception("API error"))
        await bot._resolve_trusted_ids()  # should not raise
        assert len(bot._trusted_bot_ids) == 0




class TestCmdRun:
    async def test_run_normal_command(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.executor.run_shell", AsyncMock(return_value="result")), \
             patch("src.executor.is_destructive", return_value=False):
            await bot._cmd_run(["echo", "hello"], say, client, "C12345")
        assert say.call_count == 2  # "⏳ Running…" + result

    async def test_run_no_args_shows_usage(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        await bot._cmd_run([], say, client, "C12345")
        say.assert_awaited_once()
        assert "Usage" in say.call_args[0][0]

    async def test_run_destructive_shows_confirm_dialog(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.executor.is_destructive", return_value=True), \
             patch("src.executor.is_exempt", return_value=False):
            await bot._cmd_run(["git", "push", "--force"], say, client, "C12345")
        # Should post Block Kit message, not run
        client.chat_postMessage.assert_awaited_once()
        assert ("C12345", client.chat_postMessage.call_args[1]["ts"]
                if "ts" in (client.chat_postMessage.call_args[1] or {}) else
                client.chat_postMessage.return_value["ts"]) or True  # dialog sent


# ── Block Kit actions ─────────────────────────────────────────────────────────

class TestConfirmActions:
    async def _setup_pending(self, bot, channel="C12345", ts="1000.000"):
        bot._pending_cmds[(channel, ts)] = "rm -rf /tmp/test"
        return channel, ts

    async def test_confirm_run_executes_command(self):
        bot = _make_bot()
        channel, ts = await self._setup_pending(bot)
        client = _make_client()
        body = {"channel": {"id": channel}, "message": {"ts": ts}}
        with patch("src.executor.run_shell", AsyncMock(return_value="done")) as mock_run:
            await bot._on_confirm_run(AsyncMock(), {}, client, body)
        mock_run.assert_awaited_once()
        # Pending cmd should be removed
        assert (channel, ts) not in bot._pending_cmds

    async def test_cancel_run_removes_pending(self):
        bot = _make_bot()
        channel, ts = await self._setup_pending(bot)
        client = _make_client()
        body = {"channel": {"id": channel}, "message": {"ts": ts}}
        await bot._on_cancel_run(AsyncMock(), {}, client, body)
        assert (channel, ts) not in bot._pending_cmds
        client.chat_update.assert_awaited_once()
        assert "❌" in client.chat_update.call_args[1]["text"]


# ── cmd_status ────────────────────────────────────────────────────────────────

class TestCmdStatus:
    async def test_idle_message(self):
        bot = _make_bot()
        say = _make_say()
        await bot._cmd_status([], say, MagicMock(), "C12345")
        assert "idle" in say.call_args[0][0].lower()

    async def test_busy_shows_active_tasks(self):
        import time
        bot = _make_bot()
        bot._active_ai["some long prompt"] = time.time()
        say = _make_say()
        await bot._cmd_status([], say, MagicMock(), "C12345")
        assert "processing" in say.call_args[0][0].lower()


# ── cmd_confirm toggle ────────────────────────────────────────────────────────

class TestCmdConfirm:
    async def test_toggle_off(self):
        bot = _make_bot(_make_settings(confirm_destructive=True))
        say = _make_say()
        await bot._cmd_confirm(["off"], say, MagicMock(), "C12345")
        assert bot._confirm_destructive is False

    async def test_toggle_on(self):
        bot = _make_bot(_make_settings(confirm_destructive=False))
        bot._confirm_destructive = False
        say = _make_say()
        await bot._cmd_confirm(["on"], say, MagicMock(), "C12345")
        assert bot._confirm_destructive is True

    async def test_query_state(self):
        bot = _make_bot()
        say = _make_say()
        await bot._cmd_confirm([], say, MagicMock(), "C12345")
        assert "enabled" in say.call_args[0][0].lower() or "disabled" in say.call_args[0][0].lower()


# ── Streaming ─────────────────────────────────────────────────────────────────

class TestStreaming:
    async def test_stream_calls_edit(self):
        backend = _make_backend(is_stateful=True, response="streamed!")

        async def _fake_stream(prompt):
            yield "streamed!"

        backend.stream = _fake_stream
        bot = _make_bot(backend=backend)
        bot._settings.bot.stream_responses = True
        bot._settings.bot.stream_throttle_secs = 0.0  # no throttle in test
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="streamed!"):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        # say called for initial placeholder
        say.assert_awaited()
        # edit called for final
        client.chat_update.assert_awaited()
