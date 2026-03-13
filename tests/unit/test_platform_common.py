"""Unit tests for src/platform/common.py — platform-agnostic helpers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.platform.common import build_prompt, is_allowed_slack, save_to_history
from src.config import BotConfig, SlackConfig, Settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(
    history_enabled=True,
    history_turns=10,
    slack_channel_id="",
    allowed_users=None,
):
    bot = MagicMock(spec=BotConfig)
    bot.history_enabled = history_enabled
    bot.history_turns = history_turns
    slack = MagicMock(spec=SlackConfig)
    slack.slack_channel_id = slack_channel_id
    slack.allowed_users = allowed_users or []
    settings = MagicMock(spec=Settings)
    settings.bot = bot
    settings.slack = slack
    return settings


def _make_backend(is_stateful: bool):
    backend = MagicMock()
    backend.is_stateful = is_stateful
    return backend


# ── build_prompt ──────────────────────────────────────────────────────────────

class TestBuildPrompt:
    async def test_stateful_returns_text_directly(self):
        backend = _make_backend(is_stateful=True)
        result = await build_prompt("hello", "chan1", _make_settings(), backend)
        assert result == "hello"

    async def test_stateless_no_history(self):
        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=False)
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "src.platform.common.history.get_history", AsyncMock(return_value=[])
        ), __import__("unittest.mock", fromlist=["patch"]).patch(
            "src.platform.common.history.build_context",
            return_value="context+hello",
        ):
            result = await build_prompt("hello", "chan1", settings, backend)
        # history_enabled=False → hist=[], build_context([], text) still called
        assert result == "context+hello"

    async def test_stateless_injects_history(self):
        from unittest.mock import patch, AsyncMock

        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=True)
        hist = [("q", "a")]
        with patch(
            "src.platform.common.history.get_history", AsyncMock(return_value=hist)
        ), patch(
            "src.platform.common.history.build_context",
            return_value="context+hello",
        ):
            result = await build_prompt("hello", "chan1", settings, backend)
        assert result == "context+hello"

    async def test_history_turns_zero_no_injection(self):
        """HISTORY_TURNS=0: build_prompt returns raw text even when history_enabled=True."""
        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=True, history_turns=0)
        result = await build_prompt("hello", "chan1", settings, backend)
        assert result == "hello"
        assert "<HISTORY>" not in result


# ── save_to_history ───────────────────────────────────────────────────────────

class TestSaveToHistory:
    async def test_saves_when_enabled(self):
        from unittest.mock import patch, AsyncMock

        settings = _make_settings(history_enabled=True)
        mock_add = AsyncMock()
        with patch("src.platform.common.history.add_exchange", mock_add):
            await save_to_history("chan1", "question", "answer", settings)
        mock_add.assert_awaited_once_with("chan1", "question", "answer")

    async def test_skips_when_disabled(self):
        from unittest.mock import patch, AsyncMock

        settings = _make_settings(history_enabled=False)
        mock_add = AsyncMock()
        with patch("src.platform.common.history.add_exchange", mock_add):
            await save_to_history("chan1", "question", "answer", settings)
        mock_add.assert_not_awaited()


# ── is_allowed_slack ──────────────────────────────────────────────────────────

class TestIsAllowedSlack:
    def test_no_restrictions_allows_all(self):
        settings = _make_settings(slack_channel_id="", allowed_users=[])
        assert is_allowed_slack("C123", "U456", settings) is True

    def test_channel_restriction_allows_matching(self):
        settings = _make_settings(slack_channel_id="C123")
        assert is_allowed_slack("C123", "U456", settings) is True

    def test_channel_restriction_blocks_other(self):
        settings = _make_settings(slack_channel_id="C123")
        assert is_allowed_slack("C999", "U456", settings) is False

    def test_user_restriction_allows_listed(self):
        settings = _make_settings(allowed_users=["U111", "U222"])
        assert is_allowed_slack("C123", "U111", settings) is True

    def test_user_restriction_blocks_unlisted(self):
        settings = _make_settings(allowed_users=["U111", "U222"])
        assert is_allowed_slack("C123", "U999", settings) is False

    def test_both_restrictions_applied(self):
        settings = _make_settings(
            slack_channel_id="C123", allowed_users=["U111"]
        )
        assert is_allowed_slack("C123", "U111", settings) is True
        assert is_allowed_slack("C999", "U111", settings) is False
        assert is_allowed_slack("C123", "U999", settings) is False
