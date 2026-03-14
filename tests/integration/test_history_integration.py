"""Integration tests — SQLiteStorage with a real SQLite database."""
import pytest
from pathlib import Path

from src.history import SQLiteStorage, build_context, HISTORY_LIMIT


@pytest.fixture
def storage(tmp_path):
    """Return an un-initialised SQLiteStorage backed by a temp file."""
    return SQLiteStorage(tmp_path / "history.db")


class TestHistoryRoundTrip:
    async def test_full_cycle(self, storage):
        """init → add → get → build_context → clear → get empty."""
        await storage.init()

        await storage.add_exchange("u1", "What is Docker?", "A container runtime.")
        await storage.add_exchange("u1", "How do I install it?", "Run apt install docker.")

        rows = await storage.get_history("u1")
        assert len(rows) == 2

        context = build_context(rows, "What about Podman?")
        assert "What is Docker?" in context
        assert "A container runtime." in context
        assert "What about Podman?" in context

        await storage.clear("u1")
        assert await storage.get_history("u1") == []

    async def test_multiple_chats_isolated(self, storage):
        await storage.init()
        await storage.add_exchange("alice", "q1", "a1")
        await storage.add_exchange("bob", "q2", "a2")
        await storage.add_exchange("alice", "q3", "a3")

        alice = await storage.get_history("alice")
        bob = await storage.get_history("bob")

        assert len(alice) == 2
        assert len(bob) == 1
        assert all(r[0].startswith("q") for r in alice)

    async def test_history_limit_boundary(self, storage):
        await storage.init()
        limit = HISTORY_LIMIT
        for i in range(limit + 5):
            await storage.add_exchange("chat", f"q{i}", f"a{i}")

        rows = await storage.get_history("chat")
        assert len(rows) == limit
        # Should be the most recent ones, oldest-first → last item is newest
        assert rows[-1][0] == f"q{limit + 4}"

    async def test_build_context_empty_history(self):
        result = build_context([], "standalone question")
        assert result == "standalone question"

    async def test_build_context_preserves_order(self, storage):
        await storage.init()
        for i in range(3):
            await storage.add_exchange("chat", f"msg{i}", f"resp{i}")
        rows = await storage.get_history("chat")
        context = build_context(rows, "final")
        positions = [context.index(f"msg{i}") for i in range(3)]
        assert positions == sorted(positions), "history must appear oldest-first in context"
