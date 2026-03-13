"""Security tests for agent-to-agent delegation (feature 2.2).

Verifies that the command blocklist and delegation cap in _post_delegations()
prevent RCE and flood attacks.
"""
from __future__ import annotations

import logging
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
from src.platform.slack import SlackBot, _BLOCKED_DELEGATION_SUBS, _MAX_DELEGATIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings():
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = "dev"
    bot.max_output_chars = 3000
    bot.stream_responses = False
    bot.history_enabled = False
    bot.stream_throttle_secs = 1.0
    bot.confirm_destructive = False
    bot.skip_confirm_keywords = []
    bot.prefix_only = False
    bot.system_prompt = ""
    bot.ai_timeout_secs = 0
    bot.thinking_slow_threshold_secs = 15
    bot.thinking_update_secs = 30
    bot.ai_timeout_warn_secs = 60
    slack = MagicMock(spec=SlackConfig)
    slack.slack_bot_token = "xoxb-test"
    slack.slack_app_token = "xapp-test"
    slack.slack_channel_id = "C12345"
    slack.allowed_users = []
    slack.trusted_agent_bot_ids = []
    slack.slack_delete_thinking = True
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


def _make_bot():
    settings = _make_settings()
    backend = MagicMock(spec=AICLIBackend)
    backend.is_stateful = True
    with patch("slack_bolt.async_app.AsyncApp"):
        bot = SlackBot(settings, backend, start_time=0.0)
    bot._bot_display_name = "GateCode"
    return bot


def _make_client():
    client = MagicMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
    return client


# ── Blocklist tests ───────────────────────────────────────────────────────────

class TestDelegationBlocklist:
    async def test_blocked_sub_run(self):
        """[DELEGATE: dev run rm -rf /] must NOT be posted."""
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("dev", "run rm -rf /")])
        client.chat_postMessage.assert_not_awaited()

    async def test_blocked_sub_sync(self):
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("dev", "sync")])
        client.chat_postMessage.assert_not_awaited()

    async def test_blocked_sub_git(self):
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("dev", "git push --force")])
        client.chat_postMessage.assert_not_awaited()

    async def test_blocked_sub_diff(self):
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("dev", "diff 10")])
        client.chat_postMessage.assert_not_awaited()

    async def test_blocked_sub_restart(self):
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("dev", "restart")])
        client.chat_postMessage.assert_not_awaited()

    async def test_allowed_sub_review(self):
        """[DELEGATE: sec review auth.py] is NOT in blocklist and must be posted."""
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("sec", "review auth.py for XSS")])
        client.chat_postMessage.assert_awaited_once()
        call_text = client.chat_postMessage.call_args[1]["text"]
        assert call_text == "sec review auth.py for XSS"

    async def test_allowed_sub_please(self):
        """Delegation starting with 'please' (not in blocklist) is posted."""
        bot = _make_bot()
        client = _make_client()
        await bot._post_delegations(client, "C12345", [("docs", "please update the README")])
        client.chat_postMessage.assert_awaited_once()

    async def test_blocklist_is_complete(self):
        """All expected sub-commands are in the blocklist."""
        expected = {"run", "sync", "git", "diff", "log", "restart", "clear", "confirm"}
        assert expected <= _BLOCKED_DELEGATION_SUBS


# ── Cap tests ─────────────────────────────────────────────────────────────────

class TestDelegationCap:
    async def test_cap_exceeded(self, caplog):
        """When more than _MAX_DELEGATIONS are found, only the first _MAX_DELEGATIONS are posted."""
        bot = _make_bot()
        client = _make_client()
        many = [("sec", f"please check item {i}") for i in range(5)]
        with caplog.at_level(logging.WARNING, logger="src.platform.slack"):
            await bot._post_delegations(client, "C12345", many)
        assert client.chat_postMessage.await_count == _MAX_DELEGATIONS
        assert "cap exceeded" in caplog.text.lower()

    async def test_cap_not_exceeded(self):
        """Two delegations — both posted, no warning."""
        bot = _make_bot()
        client = _make_client()
        two = [("sec", "review auth.py"), ("docs", "update README")]
        await bot._post_delegations(client, "C12345", two)
        assert client.chat_postMessage.await_count == 2

    async def test_cap_boundary(self):
        """Exactly _MAX_DELEGATIONS — all posted."""
        bot = _make_bot()
        client = _make_client()
        exact = [("sec", f"task {i}") for i in range(_MAX_DELEGATIONS)]
        await bot._post_delegations(client, "C12345", exact)
        assert client.chat_postMessage.await_count == _MAX_DELEGATIONS


# ── Failure-handling tests ────────────────────────────────────────────────────

class TestDelegationFailureSilence:
    async def test_postmessage_failure_is_silent(self):
        """If chat_postMessage raises for a delegation, no exception propagates."""
        bot = _make_bot()
        client = _make_client()
        client.chat_postMessage.side_effect = Exception("channel not found")
        # Must not raise
        await bot._post_delegations(client, "C12345", [("sec", "please check this")])
