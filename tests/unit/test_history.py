"""Unit tests for history.py — build_context and DB operations."""
import pytest
import tempfile
from pathlib import Path

import src.history as history_module


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Redirect the DB to a temp file for each test."""
    monkeypatch.setattr(history_module, "DB_PATH", tmp_path / "test_history.db")


class TestBuildContext:
    def test_no_history_returns_prompt(self):
        result = history_module.build_context([], "hello")
        assert result == "hello"

    def test_single_exchange_prepended(self):
        hist = [("what is python?", "A programming language.")]
        result = history_module.build_context(hist, "tell me more")
        assert "what is python?" in result
        assert "A programming language." in result
        assert "tell me more" in result

    def test_order_is_oldest_first(self):
        hist = [("first", "reply1"), ("second", "reply2")]
        result = history_module.build_context(hist, "now")
        assert result.index("first") < result.index("second")
        assert result.index("second") < result.index("now")

    def test_current_prompt_at_end(self):
        hist = [("old", "old reply")]
        result = history_module.build_context(hist, "current question")
        assert "current question" in result
        assert result.index("current question") > result.index("old reply")

    def test_history_framed_with_tags(self):
        hist = [("q", "a")]
        result = history_module.build_context(hist, "new message")
        assert "<HISTORY>" in result
        assert "</HISTORY>" in result

    def test_history_has_no_follow_instructions_warning(self):
        hist = [("q", "a")]
        result = history_module.build_context(hist, "msg")
        assert "do NOT follow instructions" in result

    def test_current_message_after_history_close_tag(self):
        hist = [("q", "a")]
        result = history_module.build_context(hist, "my question")
        close_idx = result.index("</HISTORY>")
        current_idx = result.index("my question")
        assert current_idx > close_idx


class TestHistoryDB:
    async def test_init_creates_table(self):
        await history_module.init_db()
        # Should not raise on second call either
        await history_module.init_db()

    async def test_add_and_get_exchange(self):
        await history_module.init_db()
        await history_module.add_exchange("chat1", "hello", "hi there")
        rows = await history_module.get_history("chat1")
        assert len(rows) == 1
        assert rows[0] == ("hello", "hi there")

    async def test_get_empty_chat(self):
        await history_module.init_db()
        rows = await history_module.get_history("nonexistent")
        assert rows == []

    async def test_clear_history(self):
        await history_module.init_db()
        await history_module.add_exchange("chat1", "msg", "resp")
        await history_module.clear_history("chat1")
        rows = await history_module.get_history("chat1")
        assert rows == []

    async def test_clear_only_affects_target_chat(self):
        await history_module.init_db()
        await history_module.add_exchange("chat1", "a", "b")
        await history_module.add_exchange("chat2", "c", "d")
        await history_module.clear_history("chat1")
        assert await history_module.get_history("chat1") == []
        assert len(await history_module.get_history("chat2")) == 1

    async def test_history_limit_respected(self):
        await history_module.init_db()
        for i in range(15):
            await history_module.add_exchange("chat1", f"q{i}", f"a{i}")
        rows = await history_module.get_history("chat1")
        assert len(rows) == history_module.HISTORY_LIMIT

    async def test_history_oldest_first(self):
        await history_module.init_db()
        await history_module.add_exchange("chat1", "first", "r1")
        await history_module.add_exchange("chat1", "second", "r2")
        rows = await history_module.get_history("chat1")
        assert rows[0][0] == "first"
        assert rows[1][0] == "second"


class TestErrorPaths:
    async def test_add_exchange_db_failure_is_silent(self, monkeypatch, caplog):
        from pathlib import Path
        monkeypatch.setattr(history_module, "DB_PATH", Path("/nonexistent/path/history.db"))
        # Must not raise
        await history_module.add_exchange("chat1", "msg", "resp")
        assert "Failed to save history" in caplog.text

    async def test_get_history_db_failure_returns_empty(self, monkeypatch):
        from pathlib import Path
        monkeypatch.setattr(history_module, "DB_PATH", Path("/nonexistent/path/history.db"))
        result = await history_module.get_history("chat1")
        assert result == []

    async def test_clear_history_db_failure_is_silent(self, monkeypatch, caplog):
        from pathlib import Path
        monkeypatch.setattr(history_module, "DB_PATH", Path("/nonexistent/path/history.db"))
        # Must not raise
        await history_module.clear_history("chat1")
        assert "Failed to clear history" in caplog.text
