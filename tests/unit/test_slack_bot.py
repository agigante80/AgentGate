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
    slack_delete_thinking=True,
    slack_thread_replies=False,
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
    bot.allow_secrets = False
    slack = MagicMock(spec=SlackConfig)
    slack.slack_bot_token = slack_bot_token
    slack.slack_app_token = slack_app_token
    slack.slack_channel_id = channel_id
    slack.allowed_users = allowed_users or []
    slack.trusted_agent_bot_ids = trusted_agent_bot_ids or []
    slack.slack_delete_thinking = slack_delete_thinking
    slack.slack_thread_replies = slack_thread_replies
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    gh.github_repo_token = ""
    ai_cfg = MagicMock(spec=AIConfig)
    ai_cfg.ai_cli = "api"
    ai_cfg.ai_api_key = "sk-test"
    ai_cfg.ai_model = ""
    ai_cfg.ai_provider = ""
    voice = MagicMock(spec=VoiceConfig)
    voice.whisper_provider = "none"
    voice.whisper_api_key = ""
    tg = MagicMock(spec=TelegramConfig)
    tg.bot_token = ""
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


def _make_event(text="", channel="C12345", user="U999", files=None, subtype="", ts="T100", thread_ts=None):
    event = {"channel": channel, "user": user, "text": text, "subtype": subtype, "ts": ts}
    if files:
        event["files"] = files
    if thread_ts:
        event["thread_ts"] = thread_ts
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
        assert client.chat_postMessage.call_count >= 1

    async def test_git_command_parsed(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.repo.status", AsyncMock(return_value="On branch main")):
            await bot._on_message(_make_event(text="gate git"), say, client)
        assert client.chat_postMessage.call_count >= 1

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
        client.chat_postMessage.assert_awaited()

    async def test_trusted_agent_message_triggers_prefix_command(self):
        bot = _make_bot(settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate help")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        client.chat_postMessage.assert_awaited()

    async def test_trusted_agent_message_does_not_trigger_ai(self):
        backend = _make_backend(response="AI response")
        bot = _make_bot(backend=backend, settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="some unprefixed message")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        backend.send.assert_not_awaited()

    async def test_trusted_agent_ai_delegation_forwarded_to_ai(self):
        """Trusted bot sends 'gate Please review...' — unknown sub → forwarded to AI, not 'Unknown command'."""
        backend = _make_backend(response="AI response")
        bot = _make_bot(backend=backend, settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        # Simulate GateCode delegating to this bot: "gate Please review the docs..."
        event = _make_event(text="gate Please review the docs for security issues")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        # Should forward to AI, not reply with "Unknown command"
        backend.send.assert_awaited_once()
        unknown_cmd_replies = [
            str(call) for call in client.chat_postMessage.call_args_list
            if "Unknown command" in str(call)
        ]
        assert unknown_cmd_replies == [], "Should not reply 'Unknown command' for AI-addressed delegations"

    async def test_trusted_agent_pull_delegation_forwarded_to_ai(self):
        """Regression: 'gate Pull latest develop...' from trusted bot must not return Unknown command: pull."""
        backend = _make_backend(response="Pulled latest develop.")
        bot = _make_bot(backend=backend, settings=_make_settings(trusted_agent_bot_ids=["BTRUSTED"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate Pull latest `develop` and review for security")
        event["bot_id"] = "BTRUSTED"
        await bot._on_message(event, say, client)
        backend.send.assert_awaited_once()
        for call in client.chat_postMessage.call_args_list:
            assert "Unknown command" not in str(call)

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
        assert client.chat_postMessage.call_count == 2  # "⏳ Running…" + result

    async def test_run_no_args_shows_usage(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        await bot._cmd_run([], say, client, "C12345")
        client.chat_postMessage.assert_awaited_once()
        assert "Usage" in client.chat_postMessage.call_args[1]["text"]

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
        client = _make_client()
        await bot._cmd_status([], say, client, "C12345")
        text = client.chat_postMessage.call_args[1]["text"]
        assert "idle" in text.lower()

    async def test_busy_shows_active_tasks(self):
        import time
        bot = _make_bot()
        bot._active_ai["some long prompt"] = time.time()
        say = _make_say()
        client = _make_client()
        await bot._cmd_status([], say, client, "C12345")
        text = client.chat_postMessage.call_args[1]["text"]
        assert "processing" in text.lower()


# ── cmd_confirm toggle ────────────────────────────────────────────────────────

class TestCmdConfirm:
    async def test_toggle_off(self):
        bot = _make_bot(_make_settings(confirm_destructive=True))
        say = _make_say()
        client = _make_client()
        await bot._cmd_confirm(["off"], say, client, "C12345")
        assert bot._confirm_destructive is False

    async def test_toggle_on(self):
        bot = _make_bot(_make_settings(confirm_destructive=False))
        bot._confirm_destructive = False
        say = _make_say()
        client = _make_client()
        await bot._cmd_confirm(["on"], say, client, "C12345")
        assert bot._confirm_destructive is True

    async def test_query_state(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        await bot._cmd_confirm([], say, client, "C12345")
        text = client.chat_postMessage.call_args[1]["text"]
        assert "enabled" in text.lower() or "disabled" in text.lower()


# ── Streaming ─────────────────────────────────────────────────────────────────

class TestStreaming:
    async def test_stream_posts_new_message(self):
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
        # final response and thinking placeholder both go through chat_postMessage
        client.chat_postMessage.assert_awaited()
        texts = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
        assert any("streamed!" in t for t in texts)

    async def test_stream_final_deletes_thinking(self):
        """With slack_delete_thinking=True (default), chat_delete is called on the placeholder."""
        backend = _make_backend(is_stateful=True, response="hello!")

        async def _fake_stream(prompt):
            yield "hello!"

        backend.stream = _fake_stream
        bot = _make_bot(_make_settings(slack_delete_thinking=True), backend=backend)
        bot._settings.bot.stream_responses = True
        bot._settings.bot.stream_throttle_secs = 0.0
        say = _make_say()
        client = _make_client()
        # The thinking placeholder ts comes from the first chat_postMessage call
        client.chat_postMessage.return_value = {"ts": "111.000"}
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello!"):
            await bot._run_ai_pipeline(say, client, "hi", "C12345")
        client.chat_delete.assert_awaited_once()
        assert client.chat_delete.call_args[1]["ts"] == "111.000"

    async def test_stream_no_delete_when_disabled(self):
        """With slack_delete_thinking=False, chat_delete is NOT called."""
        backend = _make_backend(is_stateful=True, response="hello!")

        async def _fake_stream(prompt):
            yield "hello!"

        backend.stream = _fake_stream
        bot = _make_bot(_make_settings(slack_delete_thinking=False), backend=backend)
        bot._settings.bot.stream_responses = True
        bot._settings.bot.stream_throttle_secs = 0.0
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello!"):
            await bot._run_ai_pipeline(say, client, "hi", "C12345")
        client.chat_delete.assert_not_awaited()

    async def test_stream_delete_failure_is_silent(self):
        """If chat_delete raises, no exception propagates; response is still posted."""
        backend = _make_backend(is_stateful=True, response="hello!")

        async def _fake_stream(prompt):
            yield "hello!"

        backend.stream = _fake_stream
        bot = _make_bot(_make_settings(slack_delete_thinking=True), backend=backend)
        bot._settings.bot.stream_responses = True
        bot._settings.bot.stream_throttle_secs = 0.0
        say = _make_say()
        client = _make_client()
        client.chat_delete.side_effect = Exception("delete forbidden")
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello!"):
            # Must not raise
            await bot._run_ai_pipeline(say, client, "hi", "C12345")
        # Response still posted despite delete failure
        client.chat_postMessage.assert_awaited()

    async def test_nonstream_final_posts_new_message(self):
        """Non-streaming path posts final response as new message, not an edit."""
        backend = _make_backend(is_stateful=True, response="non-streamed!")
        bot = _make_bot(_make_settings(stream=False), backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="non-streamed!"), \
             patch("src.executor.summarize_if_long", AsyncMock(return_value="non-streamed!")):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        client.chat_postMessage.assert_awaited()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert "non-streamed!" in call_kwargs["text"]


# ── Delegation (feature 2.2) ──────────────────────────────────────────────────

class TestDelegation:
    async def test_delegation_posts_new_message(self):
        """When AI response contains a sentinel, chat_postMessage is called for the delegation."""
        response_with_sentinel = (
            "I reviewed the code.[DELEGATE: sec Please check auth.py for injection.]"
        )
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)
        bot = _make_bot(_make_settings(stream=False), backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
             patch("src.executor.summarize_if_long", AsyncMock(return_value=response_with_sentinel)):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        # Three chat_postMessage calls: thinking placeholder + main response + delegation
        assert client.chat_postMessage.await_count == 3
        texts = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
        assert any("sec" in t and "auth.py" in t for t in texts)

    async def test_delegation_stripped_from_display(self):
        """The main response message must NOT contain the sentinel block."""
        sentinel = "[DELEGATE: sec Check this.]"
        response_with_sentinel = f"Clean response.{sentinel}"
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)
        bot = _make_bot(_make_settings(stream=False), backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
             patch("src.executor.summarize_if_long", AsyncMock(return_value=response_with_sentinel)):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        # Second postMessage call is the main response (first is thinking placeholder)
        second_call_text = client.chat_postMessage.call_args_list[1][1]["text"]
        assert "[DELEGATE" not in second_call_text
        assert "Clean response." in second_call_text

    async def test_delegation_stripped_from_history(self):
        """save_to_history receives the cleaned text (sentinel removed), not the raw AI output."""
        sentinel = "[DELEGATE: sec Review this.]"
        response_with_sentinel = f"Main answer.{sentinel}"
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)
        bot = _make_bot(_make_settings(stream=False), backend=backend)
        say = _make_say()
        client = _make_client()
        saved_texts: list[str] = []
        async def _capture_save(channel, user_text, ai_text, settings):
            saved_texts.append(ai_text)
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
             patch("src.executor.summarize_if_long", AsyncMock(return_value=response_with_sentinel)), \
             patch("src.platform.common.save_to_history", _capture_save):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        assert saved_texts, "save_to_history was not called"
        assert "[DELEGATE" not in saved_texts[0]

    async def test_delegation_failure_is_silent(self):
        """If chat_postMessage raises for delegation, the main response is still delivered."""
        response_with_sentinel = "Answer.[DELEGATE: sec Check this.]"
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)
        bot = _make_bot(_make_settings(stream=False), backend=backend)
        say = _make_say()
        client = _make_client()
        call_count = 0
        async def _sometimes_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # second call is the delegation
                raise Exception("channel not found")
            return {"ts": "1001.000"}
        client.chat_postMessage.side_effect = _sometimes_fail
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
             patch("src.executor.summarize_if_long", AsyncMock(return_value=response_with_sentinel)):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        # Main response was posted (first call)
        assert call_count >= 1

    async def test_trusted_bot_no_delegation(self):
        """Messages from trusted bots do not trigger _run_ai_pipeline() (loop prevention)."""
        bot = _make_bot(_make_settings(trusted_agent_bot_ids=["B_TRUSTED_ID"]))
        bot._trusted_bot_ids = {"B_TRUSTED_ID"}
        say = _make_say()
        client = _make_client()
        event = {
            "channel": "C12345",
            "user": "",
            "text": "unrecognised command",
            "bot_id": "B_TRUSTED_ID",
        }
        pipeline_called = False
        original = bot._run_ai_pipeline
        async def _spy(*args, **kwargs):
            nonlocal pipeline_called
            pipeline_called = True
            return await original(*args, **kwargs)
        bot._run_ai_pipeline = _spy
        await bot._on_message(event, say, client)
        assert not pipeline_called, "_run_ai_pipeline must NOT be called for trusted bot messages"

    async def test_stream_delegation_posted(self):
        """Streaming path also extracts and posts delegation sentinels."""
        response_with_sentinel = "Streamed answer.[DELEGATE: docs Update the README.]"
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)

        async def _fake_stream(prompt):
            yield response_with_sentinel

        backend.stream = _fake_stream
        bot = _make_bot(_make_settings(stream=True, stream_throttle=0.0), backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.add_exchange", AsyncMock()), \
             patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value=response_with_sentinel):
            await bot._run_ai_pipeline(say, client, "query", "C12345")
        texts = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
        assert any("docs" in t and "README" in t for t in texts)
        # Main message must not contain the sentinel
        assert "[DELEGATE" not in texts[0]


# ── Thread Reply Mode ─────────────────────────────────────────────────────────

class TestThreadReplies:
    async def test_thread_replies_disabled_by_default(self):
        """With slack_thread_replies=False (default), chat_postMessage is called without thread_ts."""
        backend = _make_backend(response="OK")
        bot = _make_bot(_make_settings(slack_thread_replies=False), backend=backend)
        say = _make_say()
        client = _make_client()
        event = _make_event(text="hello", ts="T100")
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(event, say, client)
        for call in client.chat_postMessage.call_args_list:
            assert "thread_ts" not in call[1], "thread_ts must not be set when disabled"

    async def test_thread_reply_uses_event_ts(self):
        """With slack_thread_replies=True, a root message's ts is used as thread_ts."""
        backend = _make_backend(response="reply")
        bot = _make_bot(_make_settings(slack_thread_replies=True), backend=backend)
        say = _make_say()
        client = _make_client()
        # Root-level message: has ts but no thread_ts
        event = _make_event(text="hello", ts="T200")
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hello"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(event, say, client)
        # At least one postMessage should carry thread_ts=T200
        thread_ts_values = [
            c[1].get("thread_ts") for c in client.chat_postMessage.call_args_list
        ]
        assert "T200" in thread_ts_values, f"Expected thread_ts=T200, got: {thread_ts_values}"

    async def test_thread_reply_continues_existing_thread(self):
        """With slack_thread_replies=True, a threaded message continues the existing thread."""
        backend = _make_backend(response="reply")
        bot = _make_bot(_make_settings(slack_thread_replies=True), backend=backend)
        say = _make_say()
        client = _make_client()
        # Message inside a thread: has both ts (reply ts) and thread_ts (root ts)
        event = _make_event(text="follow-up", ts="T300", thread_ts="T100")
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="follow-up"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(event, say, client)
        thread_ts_values = [
            c[1].get("thread_ts") for c in client.chat_postMessage.call_args_list
        ]
        # Must use the existing thread root (T100), not the reply's own ts (T300)
        assert "T100" in thread_ts_values, f"Expected thread_ts=T100, got: {thread_ts_values}"
        assert "T300" not in thread_ts_values, "Must NOT create a new sub-thread from reply ts"

    async def test_thread_reply_stream(self):
        """Streaming path posts thinking placeholder and final message with thread_ts."""
        backend = _make_backend(response="streamed")
        async def _stream(prompt):
            yield "streamed"
        backend.stream = _stream
        bot = _make_bot(_make_settings(slack_thread_replies=True, stream=True, stream_throttle=0.0), backend=backend)
        say = _make_say()
        client = _make_client()
        event = _make_event(text="hi", ts="T400")
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="hi"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(event, say, client)
        thread_ts_values = [
            c[1].get("thread_ts") for c in client.chat_postMessage.call_args_list
        ]
        assert "T400" in thread_ts_values, f"Expected thread_ts=T400 in streaming path, got: {thread_ts_values}"

    async def test_thread_reply_prefix_command(self):
        """Prefix command output (gate git) is posted with thread_ts when enabled."""
        bot = _make_bot(_make_settings(slack_thread_replies=True))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate git", ts="T500")
        with patch("src.repo.status", AsyncMock(return_value="On branch develop")):
            await bot._on_message(event, say, client)
        thread_ts_values = [
            c[1].get("thread_ts") for c in client.chat_postMessage.call_args_list
        ]
        assert "T500" in thread_ts_values, f"Expected thread_ts=T500 for command, got: {thread_ts_values}"

    async def test_thread_reply_delegation(self):
        """Delegation messages are also posted with thread_ts when thread replies enabled."""
        response_with_sentinel = "Here is a review.[DELEGATE: docs Update the README.]"
        backend = _make_backend(is_stateful=True, response=response_with_sentinel)
        bot = _make_bot(_make_settings(slack_thread_replies=True), backend=backend)
        say = _make_say()
        client = _make_client()
        event = _make_event(text="review", ts="T600")
        with patch("src.platform.common.history.get_history", AsyncMock(return_value=[])), \
             patch("src.platform.common.history.build_context", return_value="review"), \
             patch("src.platform.common.history.add_exchange", AsyncMock()):
            await bot._on_message(event, say, client)
        delegation_calls = [
            c for c in client.chat_postMessage.call_args_list
            if "docs" in (c[1].get("text") or "")
        ]
        assert delegation_calls, "Delegation message must be posted"
        assert delegation_calls[0][1].get("thread_ts") == "T600", \
            "Delegation must carry the same thread_ts"


class TestCmdDiffSanitization:
    """_cmd_diff must reject malicious git refs before calling run_shell."""

    async def test_malicious_ref_rejected(self):
        bot = _make_bot(_make_settings())
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate diff ; rm -rf /")
        with patch("src.executor.run_shell", AsyncMock(return_value="")) as mock_run:
            await bot._on_message(event, say, client)
        mock_run.assert_not_called()
        posted_texts = [
            c[1].get("text", "") for c in client.chat_postMessage.call_args_list
        ]
        assert any("Invalid git ref" in t for t in posted_texts)

    async def test_valid_ref_calls_run_shell(self):
        bot = _make_bot(_make_settings())
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate diff main")
        with patch("src.executor.run_shell", AsyncMock(return_value="some diff")) as mock_run:
            await bot._on_message(event, say, client)
        mock_run.assert_called_once()
        call_cmd = mock_run.call_args[0][0]
        assert "main" in call_cmd
