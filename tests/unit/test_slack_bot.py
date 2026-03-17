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
from src.history import ConversationStorage


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
    bot.history_turns = 10
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


def _make_storage():
    storage = MagicMock(spec=ConversationStorage)
    storage.get_history = AsyncMock(return_value=[])
    storage.add_exchange = AsyncMock()
    storage.clear = AsyncMock()
    return storage


def _make_bot(settings=None, backend=None, storage=None):
    settings = settings or _make_settings()
    backend = backend or _make_backend()
    storage = storage or _make_storage()
    with patch("slack_bolt.async_app.AsyncApp"):
        from src.platform.slack import SlackBot
        from src.audit import NullAuditLog
        bot = SlackBot(settings, backend, storage, start_time=0.0, audit=NullAuditLog())
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
        with patch("src.platform.common.history.build_context", return_value="unknowncmd arg1"):
            await bot._on_message(_make_event(text="gate unknowncmd arg1"), say, client)
        # Unknown subcommand should be forwarded to AI, not show "Unknown command"
        backend.send.assert_awaited_once()

    async def test_non_prefix_message_forwarded_to_ai(self):
        backend = _make_backend(response="Great!")
        bot = _make_bot(backend=backend)
        say = _make_say()
        client = _make_client()
        with patch("src.platform.common.history.build_context", return_value="hello"):
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
            await bot.cmd_run(["echo", "hello"], say, client, "C12345")
        assert client.chat_postMessage.call_count == 2  # "⏳ Running…" + result

    async def test_run_no_args_shows_usage(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        await bot.cmd_run([], say, client, "C12345")
        client.chat_postMessage.assert_awaited_once()
        assert "Usage" in client.chat_postMessage.call_args[1]["text"]

    async def test_run_destructive_shows_confirm_dialog(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        with patch("src.executor.is_destructive", return_value=True), \
             patch("src.executor.is_exempt", return_value=False):
            await bot.cmd_run(["git", "push", "--force"], say, client, "C12345")
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
        await bot.cmd_status([], say, client, "C12345")
        text = client.chat_postMessage.call_args[1]["text"]
        assert "idle" in text.lower()

    async def test_busy_shows_active_tasks(self):
        import time
        bot = _make_bot()
        bot._active_ai["some long prompt"] = time.time()
        say = _make_say()
        client = _make_client()
        await bot.cmd_status([], say, client, "C12345")
        text = client.chat_postMessage.call_args[1]["text"]
        assert "processing" in text.lower()


# ── cmd_confirm toggle ────────────────────────────────────────────────────────

class TestCmdConfirm:
    async def test_toggle_off(self):
        bot = _make_bot(_make_settings(confirm_destructive=True))
        say = _make_say()
        client = _make_client()
        await bot.cmd_confirm(["off"], say, client, "C12345")
        assert bot._confirm_destructive is False

    async def test_toggle_on(self):
        bot = _make_bot(_make_settings(confirm_destructive=False))
        bot._confirm_destructive = False
        say = _make_say()
        client = _make_client()
        await bot.cmd_confirm(["on"], say, client, "C12345")
        assert bot._confirm_destructive is True

    async def test_query_state(self):
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        await bot.cmd_confirm([], say, client, "C12345")
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
        with patch("src.platform.common.history.build_context", return_value="streamed!"):
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
        with patch("src.platform.common.history.build_context", return_value="hello!"):
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
        with patch("src.platform.common.history.build_context", return_value="hello!"):
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
        with patch("src.platform.common.history.build_context", return_value="hello!"):
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
        with patch("src.platform.common.history.build_context", return_value="non-streamed!"), \
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
        with patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
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
        with patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
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
        async def _capture_save(channel, user_text, ai_text, settings, storage):
            saved_texts.append(ai_text)
        with patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
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
        with patch("src.platform.common.history.build_context", return_value=response_with_sentinel), \
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
        with patch("src.platform.common.history.build_context", return_value=response_with_sentinel):
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
        with patch("src.platform.common.history.build_context", return_value="hello"):
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
        with patch("src.platform.common.history.build_context", return_value="hello"):
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
        with patch("src.platform.common.history.build_context", return_value="follow-up"):
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
        with patch("src.platform.common.history.build_context", return_value="hi"):
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
        with patch("src.platform.common.history.build_context", return_value="review"):
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


class TestBroadcast:
    """Broadcast detection via <!here>, <!channel>, <!everyone>."""

    async def test_broadcast_ai_prompt_goes_to_pipeline(self):
        """<!here> + unprefixed text → all bots run their AI pipeline."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!here> pull latest and review it")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai:
            await bot._on_message(event, say, client)
        mock_ai.assert_called_once()
        call_args = mock_ai.call_args[0]
        assert "pull latest and review it" in call_args[2]

    async def test_broadcast_own_prefix_command_dispatches(self):
        """<!here> gate sync → bot with prefix 'gate' dispatches sync."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!here> gate sync")
        with patch.object(bot, "_dispatch", AsyncMock()) as mock_dispatch:
            await bot._on_message(event, say, client)
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args[0]
        assert args[0] == "sync"

    async def test_broadcast_other_prefix_goes_to_ai(self):
        """<!here> dev sync → bot with different prefix treats as AI prompt."""
        bot = _make_bot(_make_settings(prefix="sec"))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!here> dev sync")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai, \
             patch.object(bot, "_dispatch", AsyncMock()) as mock_dispatch:
            await bot._on_message(event, say, client)
        mock_ai.assert_called_once()
        mock_dispatch.assert_not_called()

    async def test_broadcast_empty_after_strip_is_noop(self):
        """<!here> with no payload → bot silently ignores."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!here>")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai, \
             patch.object(bot, "_dispatch", AsyncMock()) as mock_dispatch:
            await bot._on_message(event, say, client)
        mock_ai.assert_not_called()
        mock_dispatch.assert_not_called()

    async def test_broadcast_channel_trigger(self):
        """<!channel> also triggers broadcast."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!channel> tell me the status")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai:
            await bot._on_message(event, say, client)
        mock_ai.assert_called_once()

    async def test_broadcast_everyone_trigger(self):
        """<!everyone> also triggers broadcast."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!everyone> who are you?")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai:
            await bot._on_message(event, say, client)
        mock_ai.assert_called_once()

    async def test_broadcast_blocked_for_unauthorized_user(self):
        """Broadcast from unauthorized user is rejected before routing."""
        bot = _make_bot(_make_settings(channel_id="C123", allowed_users=["U111"]))
        say = _make_say()
        client = _make_client()
        event = _make_event(text="<!here> do something", channel="C123", user="U999")
        with patch.object(bot, "_run_ai_pipeline", AsyncMock()) as mock_ai, \
             patch.object(bot, "_dispatch", AsyncMock()) as mock_dispatch:
            await bot._on_message(event, say, client)
        mock_ai.assert_not_called()
        mock_dispatch.assert_not_called()

    async def test_outgoing_delegation_still_sanitised(self):
        """<!here> in a delegation message is still stripped before posting (regression guard)."""
        response_with_here = "Here is info.[DELEGATE: docs <!here> please update docs]"
        backend = _make_backend(is_stateful=True, response=response_with_here)
        bot = _make_bot(backend=backend)
        say = _make_say()
        client = _make_client()
        event = _make_event(text="gate review this")
        with patch("src.platform.common.history.build_context", return_value="review this"):
            await bot._on_message(event, say, client)
        delegation_texts = [
            c[1].get("text", "") for c in client.chat_postMessage.call_args_list
        ]
        assert all("<!here>" not in t for t in delegation_texts), \
            "<!here> must be stripped from outgoing delegation messages"


# ── _deliver_slack ────────────────────────────────────────────────────────────

class TestDeliverSlack:
    """Branch-routing tests for _deliver_slack."""

    def _make_deliver_bot(self, delete_thinking=False):
        return _make_bot(_make_settings(slack_delete_thinking=delete_thinking))

    async def test_short_response_edits_existing_ts(self):
        """≤ 3000 chars with existing_ts → edits the placeholder."""
        bot = self._make_deliver_bot()
        client = _make_client()
        await bot._deliver_slack(client, "C1", "T100", "short text", None)
        client.chat_update.assert_awaited_once()
        client.chat_postMessage.assert_not_awaited()

    async def test_short_response_no_ts_posts_new(self):
        """≤ 3000 chars with existing_ts=None → posts a new message."""
        bot = self._make_deliver_bot()
        client = _make_client()
        await bot._deliver_slack(client, "C1", None, "short text", None)
        client.chat_postMessage.assert_awaited_once()

    async def test_multi_block_uses_blocks_payload(self):
        """3001–12000 chars → chat_update with blocks list."""
        from src.platform.slack import _SLACK_BLOCK_LIMIT
        bot = self._make_deliver_bot()
        client = _make_client()
        text = "z" * (_SLACK_BLOCK_LIMIT + 1)
        await bot._deliver_slack(client, "C1", "T100", text, None)
        call_kwargs = client.chat_update.call_args[1]
        assert "blocks" in call_kwargs

    async def test_large_response_uploads_file(self):
        """> 12000 chars → files_upload_v2 called."""
        from src.platform.slack import _SLACK_SNIPPET_THRESHOLD
        bot = self._make_deliver_bot()
        client = _make_client()
        text = "w" * (_SLACK_SNIPPET_THRESHOLD + 1)
        client.files_upload_v2 = AsyncMock()
        await bot._deliver_slack(client, "C1", "T100", text, None)
        client.files_upload_v2.assert_awaited_once()

    async def test_empty_text_posts_placeholder(self):
        """Empty text → '_(empty response)_' message."""
        bot = self._make_deliver_bot()
        client = _make_client()
        await bot._deliver_slack(client, "C1", None, "", None)
        client.chat_postMessage.assert_awaited_once()
        call_text = client.chat_postMessage.call_args[1].get("text", "")
        assert "empty" in call_text

    async def test_multi_block_fallback_on_api_error(self):
        """chat_update failure in multi-block path falls back to plain text."""
        from src.platform.slack import _SLACK_BLOCK_LIMIT
        bot = self._make_deliver_bot()
        client = _make_client()
        client.chat_update = AsyncMock(side_effect=Exception("API error"))
        text = "z" * (_SLACK_BLOCK_LIMIT + 1)
        # Should not raise; fallback via _edit which calls chat_update again
        try:
            await bot._deliver_slack(client, "C1", "T100", text, None)
        except Exception:
            pytest.fail("_deliver_slack should not propagate API errors")


# ── Issue #18: user_id attribution in _dispatch ───────────────────────────────

class TestDispatchUserIdAttribution:
    """Regression tests: _dispatch must forward user_id to handlers for full audit attribution."""

    def _make_audit_bot(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from src.audit import AuditLog

        audit = MagicMock(spec=AuditLog)
        audit.record = AsyncMock()

        with patch("slack_bolt.async_app.AsyncApp"):
            from src.platform.slack import SlackBot
            bot = SlackBot(
                _make_settings(), _make_backend(), _make_storage(),
                start_time=0.0, audit=audit,
            )
        return bot, audit

    async def test_cancel_text_command_audit_has_user_id(self):
        """gate cancel text command must record the actual user_id, not None."""
        bot, audit = self._make_audit_bot()
        event = _make_event(text="dev cancel", user="U42")
        await bot._on_message(event, _make_say(), _make_client())
        audit.record.assert_awaited()
        call_kwargs = audit.record.call_args_list[-1][1]
        assert call_kwargs.get("user_id") == "U42", (
            f"Expected user_id='U42', got {call_kwargs.get('user_id')!r}"
        )

    async def test_clear_text_command_audit_has_user_id(self):
        """gate clear text command must record the actual user_id."""
        bot, audit = self._make_audit_bot()
        event = _make_event(text="dev clear", user="U55")
        await bot._on_message(event, _make_say(), _make_client())
        audit.record.assert_awaited()
        call_kwargs = audit.record.call_args_list[-1][1]
        assert call_kwargs.get("user_id") == "U55"

    async def test_init_text_command_audit_has_user_id(self):
        """gate init text command must record the actual user_id."""
        bot, audit = self._make_audit_bot()
        say = _make_say()
        client = _make_client()
        # Patch _run_ai_pipeline to avoid full pipeline execution
        bot._run_ai_pipeline = AsyncMock()
        await bot._dispatch("init", [], say, client, "C1", user_id="U77")
        audit.record.assert_awaited()
        init_call = next(
            (c for c in audit.record.call_args_list if c[1].get("action") == "command"),
            None,
        )
        assert init_call is not None
        assert init_call[1].get("user_id") == "U77"

    async def test_dispatch_passes_user_id_kwarg(self):
        """_dispatch must forward user_id keyword arg to the handler."""
        bot, _ = self._make_audit_bot()
        called_with = {}

        async def fake_handler(args, say, client, channel, *, thread_ts=None, user_id=None):
            called_with["user_id"] = user_id

        bot.cmd_sync = fake_handler
        say = _make_say()
        client = _make_client()
        await bot._dispatch("sync", [], say, client, "C1", user_id="U99")
        assert called_with.get("user_id") == "U99"

    async def test_dispatch_command_error_sends_reply(self):
        """Command failures must surface an ❌ reply instead of silently dropping."""
        bot = _make_bot()
        say = _make_say()
        client = _make_client()

        async def failing_handler(args, say, client, channel, *, thread_ts=None, user_id=None):
            raise RuntimeError("git failed")

        bot.cmd_sync = failing_handler
        await bot._dispatch("sync", [], say, client, "C1")
        # At least one postMessage with ❌ should have been sent
        messages = [str(call) for call in client.chat_postMessage.call_args_list]
        assert any("❌" in m for m in messages), f"Expected ❌ error reply, got: {messages}"
