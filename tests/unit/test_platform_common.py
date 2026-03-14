"""Unit tests for src/platform/common.py — platform-agnostic helpers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.platform.common import (
    build_prompt,
    finalize_thinking,
    is_allowed_slack,
    save_to_history,
    split_text,
)
from src.config import BotConfig, SlackConfig, Settings
from src.history import ConversationStorage


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


def _make_storage(history=None):
    storage = MagicMock(spec=ConversationStorage)
    storage.get_history = AsyncMock(return_value=history or [])
    storage.add_exchange = AsyncMock()
    storage.clear = AsyncMock()
    return storage


# ── build_prompt ──────────────────────────────────────────────────────────────

class TestBuildPrompt:
    async def test_stateful_returns_text_directly(self):
        backend = _make_backend(is_stateful=True)
        storage = _make_storage()
        result = await build_prompt("hello", "chan1", _make_settings(), backend, storage)
        assert result == "hello"
        storage.get_history.assert_not_awaited()

    async def test_stateless_no_history(self):
        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=False)
        storage = _make_storage(history=[])
        result = await build_prompt("hello", "chan1", settings, backend, storage)
        # history_enabled=False → hist=[], build_context([], text) returns text unchanged
        assert result == "hello"

    async def test_stateless_injects_history(self):
        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=True)
        hist = [("q", "a")]
        storage = _make_storage(history=hist)
        with patch("src.platform.common.history.build_context", return_value="context+hello"):
            result = await build_prompt("hello", "chan1", settings, backend, storage)
        assert result == "context+hello"

    async def test_history_turns_zero_no_injection(self):
        """HISTORY_TURNS=0: build_prompt returns raw text even when history_enabled=True."""
        backend = _make_backend(is_stateful=False)
        settings = _make_settings(history_enabled=True, history_turns=0)
        storage = _make_storage()
        result = await build_prompt("hello", "chan1", settings, backend, storage)
        assert result == "hello"
        assert "<HISTORY>" not in result
        storage.get_history.assert_not_awaited()


# ── save_to_history ───────────────────────────────────────────────────────────

class TestSaveToHistory:
    async def test_saves_when_enabled(self):
        settings = _make_settings(history_enabled=True)
        storage = _make_storage()
        await save_to_history("chan1", "question", "answer", settings, storage)
        storage.add_exchange.assert_awaited_once_with("chan1", "question", "answer")

    async def test_skips_when_disabled(self):
        settings = _make_settings(history_enabled=False)
        storage = _make_storage()
        await save_to_history("chan1", "question", "answer", settings, storage)
        storage.add_exchange.assert_not_awaited()


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


# ── finalize_thinking ─────────────────────────────────────────────────────────

class TestFinalizeThinking:
    async def test_edits_with_elapsed_seconds(self):
        """finalize_thinking calls edit_fn with '🤖 Thought for Xs' when enabled."""
        calls = []

        async def edit_fn(text):
            calls.append(text)

        await finalize_thinking(edit_fn, elapsed_secs=12, show_elapsed=True)
        assert calls == ["🤖 Thought for 12s"]

    async def test_formats_minutes_and_seconds(self):
        """Elapsed >= 60s formats as 'Xm Ys'."""
        calls = []

        async def edit_fn(text):
            calls.append(text)

        await finalize_thinking(edit_fn, elapsed_secs=75, show_elapsed=True)
        assert calls == ["🤖 Thought for 1m 15s"]

    async def test_noop_when_disabled(self):
        """show_elapsed=False → edit_fn never called."""
        calls = []

        async def edit_fn(text):
            calls.append(text)

        await finalize_thinking(edit_fn, elapsed_secs=5, show_elapsed=False)
        assert calls == []

    async def test_edit_fn_exception_is_swallowed(self):
        """If edit_fn raises, finalize_thinking logs and does not propagate."""

        async def edit_fn(text):
            raise RuntimeError("API error")

        # Must not raise
        await finalize_thinking(edit_fn, elapsed_secs=10, show_elapsed=True)


# ── split_text ────────────────────────────────────────────────────────────────

class TestSplitText:
    def test_short_text_returned_as_single_chunk(self):
        text = "Hello world"
        assert split_text(text, 100) == [text]

    def test_exact_chunk_size_not_split(self):
        text = "a" * 100
        assert split_text(text, 100) == [text]

    def test_splits_at_paragraph_boundary(self):
        text = "First paragraph.\n\nSecond paragraph."
        chunks = split_text(text, 20)
        assert len(chunks) == 2
        assert chunks[0] == "First paragraph.\n\n"
        assert chunks[1] == "Second paragraph."

    def test_splits_at_sentence_boundary(self):
        text = "First sentence. Second sentence is longer."
        chunks = split_text(text, 20)
        # Should split after "First sentence. "
        assert all(len(c) <= 20 for c in chunks)
        assert "".join(chunks) == text

    def test_splits_at_newline(self):
        text = "line one\nline two that is longer"
        chunks = split_text(text, 12)
        assert all(len(c) <= 12 for c in chunks)
        assert "".join(chunks) == text

    def test_hard_cuts_when_no_boundary(self):
        text = "a" * 50
        chunks = split_text(text, 10)
        assert all(len(c) == 10 for c in chunks)
        assert "".join(chunks) == text

    def test_no_data_loss(self):
        text = "Para one.\n\nPara two. Sentence A. Sentence B.\n\nPara three."
        for chunk_size in [15, 20, 30, 50]:
            chunks = split_text(text, chunk_size)
            assert "".join(chunks) == text, f"Data lost with chunk_size={chunk_size}"
            assert all(len(c) <= chunk_size for c in chunks), (
                f"Chunk exceeded limit with chunk_size={chunk_size}: {[len(c) for c in chunks]}"
            )

    def test_empty_string(self):
        assert split_text("", 100) == [""]
