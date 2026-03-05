"""Integration tests — history module with a real SQLite database."""
import pytest
from pathlib import Path

import src.history as history_module


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "DB_PATH", tmp_path / "history.db")


class TestHistoryRoundTrip:
    async def test_full_cycle(self):
        """init → add → get → build_context → clear → get empty."""
        await history_module.init_db()

        await history_module.add_exchange("u1", "What is Docker?", "A container runtime.")
        await history_module.add_exchange("u1", "How do I install it?", "Run apt install docker.")

        rows = await history_module.get_history("u1")
        assert len(rows) == 2

        context = history_module.build_context(rows, "What about Podman?")
        assert "What is Docker?" in context
        assert "A container runtime." in context
        assert "What about Podman?" in context

        await history_module.clear_history("u1")
        assert await history_module.get_history("u1") == []

    async def test_multiple_chats_isolated(self):
        await history_module.init_db()
        await history_module.add_exchange("alice", "q1", "a1")
        await history_module.add_exchange("bob", "q2", "a2")
        await history_module.add_exchange("alice", "q3", "a3")

        alice = await history_module.get_history("alice")
        bob = await history_module.get_history("bob")

        assert len(alice) == 2
        assert len(bob) == 1
        assert all(r[0].startswith("q") for r in alice)

    async def test_history_limit_boundary(self):
        await history_module.init_db()
        limit = history_module.HISTORY_LIMIT
        for i in range(limit + 5):
            await history_module.add_exchange("chat", f"q{i}", f"a{i}")

        rows = await history_module.get_history("chat")
        assert len(rows) == limit
        # Should be the most recent ones, oldest-first → last item is newest
        assert rows[-1][0] == f"q{limit + 4}"

    async def test_build_context_empty_history(self):
        result = history_module.build_context([], "standalone question")
        assert result == "standalone question"

    async def test_build_context_preserves_order(self):
        await history_module.init_db()
        for i in range(3):
            await history_module.add_exchange("chat", f"msg{i}", f"resp{i}")
        rows = await history_module.get_history("chat")
        context = history_module.build_context(rows, "final")
        positions = [context.index(f"msg{i}") for i in range(3)]
        assert positions == sorted(positions), "history must appear oldest-first in context"
