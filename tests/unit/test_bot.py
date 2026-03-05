"""Unit tests for bot.py — pure functions (_prefix, _is_allowed)."""
import pytest
from unittest.mock import MagicMock

from src.bot import _is_allowed, _prefix
from src.config import Settings, TelegramConfig, GitHubConfig, BotConfig, AIConfig


def _make_settings(chat_id="99999", prefix="ta", allowed_users=None):
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
        s = _make_settings(prefix="ta")
        assert _prefix(s) == "ta"

    def test_uppercase_normalized(self):
        s = _make_settings(prefix="TA")
        assert _prefix(s) == "ta"

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
