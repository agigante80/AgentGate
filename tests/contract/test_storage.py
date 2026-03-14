"""Contract tests — verifies SQLiteStorage satisfies the ConversationStorage ABC.

Each test in this file checks one aspect of the storage contract. Any
alternative implementation (Redis, Postgres, etc.) must pass the same tests.
"""
import pytest
from pathlib import Path
from unittest.mock import patch

from src.history import ConversationStorage, SQLiteStorage, HISTORY_LIMIT


@pytest.fixture
def storage(tmp_path) -> SQLiteStorage:
    """Return an un-initialised SQLiteStorage backed by a temp file."""
    return SQLiteStorage(tmp_path / "contract_history.db")


@pytest.fixture
async def ready_storage(storage) -> SQLiteStorage:
    """Return an initialised SQLiteStorage ready for use."""
    await storage.init()
    return storage


# ── ABC conformance ───────────────────────────────────────────────────────────

def test_sqlite_satisfies_abc():
    """SQLiteStorage must be a concrete subclass of ConversationStorage."""
    assert issubclass(SQLiteStorage, ConversationStorage)


def test_sqlite_is_instantiable():
    """ConversationStorage ABC itself must not be directly instantiable."""
    import pytest
    with pytest.raises(TypeError):
        ConversationStorage()  # type: ignore[abstract]


# ── init ─────────────────────────────────────────────────────────────────────

async def test_sqlite_init_creates_table(storage):
    """After init(), the history table must exist and be usable."""
    await storage.init()
    # Verify the table exists by doing a round-trip
    await storage.add_exchange("probe", "q", "a")
    rows = await storage.get_history("probe")
    assert len(rows) == 1


async def test_sqlite_init_is_idempotent(storage):
    """Calling init() twice must not raise or corrupt data."""
    await storage.init()
    await storage.add_exchange("chat1", "q1", "a1")
    await storage.init()  # second call — must not wipe data
    rows = await storage.get_history("chat1")
    assert len(rows) == 1


# ── add_exchange / get_history ────────────────────────────────────────────────

async def test_sqlite_add_and_get(ready_storage):
    """add_exchange followed by get_history must return the same exchange."""
    await ready_storage.add_exchange("chat1", "user message", "ai response")
    rows = await ready_storage.get_history("chat1")
    assert rows == [("user message", "ai response")]


async def test_sqlite_get_empty(ready_storage):
    """get_history on an unknown chat_id must return an empty list."""
    rows = await ready_storage.get_history("nonexistent")
    assert rows == []


async def test_sqlite_get_limit(ready_storage):
    """get_history must return at most HISTORY_LIMIT exchanges by default."""
    for i in range(HISTORY_LIMIT + 5):
        await ready_storage.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await ready_storage.get_history("chat1")
    assert len(rows) == HISTORY_LIMIT


async def test_sqlite_get_custom_limit(ready_storage):
    """get_history respects an explicit limit parameter."""
    for i in range(8):
        await ready_storage.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await ready_storage.get_history("chat1", limit=5)
    assert len(rows) == 5


async def test_sqlite_get_zero_limit(ready_storage):
    """get_history with limit=0 must return []."""
    await ready_storage.add_exchange("chat1", "q", "a")
    rows = await ready_storage.get_history("chat1", limit=0)
    assert rows == []


async def test_sqlite_get_negative_limit_clamped(ready_storage):
    """Negative limit must not bypass the cap (SQLite LIMIT -1 = no limit)."""
    for i in range(150):
        await ready_storage.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await ready_storage.get_history("chat1", limit=-1)
    assert len(rows) <= 100


async def test_sqlite_get_history_oldest_first(ready_storage):
    """get_history must return exchanges oldest-first."""
    await ready_storage.add_exchange("chat1", "first", "r1")
    await ready_storage.add_exchange("chat1", "second", "r2")
    rows = await ready_storage.get_history("chat1")
    assert rows[0][0] == "first"
    assert rows[1][0] == "second"


async def test_sqlite_get_returns_most_recent_when_over_limit(ready_storage):
    """When stored exchanges exceed the limit, most recent are returned."""
    limit = HISTORY_LIMIT
    for i in range(limit + 3):
        await ready_storage.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await ready_storage.get_history("chat1")
    assert rows[-1][0] == f"q{limit + 2}"  # newest is last (oldest-first order)


# ── clear ─────────────────────────────────────────────────────────────────────

async def test_sqlite_clear(ready_storage):
    """clear() must remove all rows for the given chat_id."""
    await ready_storage.add_exchange("chat1", "msg", "resp")
    await ready_storage.clear("chat1")
    rows = await ready_storage.get_history("chat1")
    assert rows == []


async def test_sqlite_clear_only_affects_target_chat(ready_storage):
    """clear() must not remove exchanges from other chat_ids."""
    await ready_storage.add_exchange("chat1", "a", "b")
    await ready_storage.add_exchange("chat2", "c", "d")
    await ready_storage.clear("chat1")
    assert await ready_storage.get_history("chat1") == []
    assert len(await ready_storage.get_history("chat2")) == 1


# ── exception swallowing ──────────────────────────────────────────────────────

async def test_sqlite_add_exception_swallowed(caplog):
    """A DB error in add_exchange must be logged but not propagate."""
    bad_storage = SQLiteStorage(Path("/nonexistent/path/history.db"))
    await bad_storage.add_exchange("chat1", "msg", "resp")  # must not raise
    assert "Failed to save history" in caplog.text


async def test_sqlite_get_exception_returns_empty():
    """A DB error in get_history must return [] and not propagate."""
    bad_storage = SQLiteStorage(Path("/nonexistent/path/history.db"))
    result = await bad_storage.get_history("chat1")  # must not raise
    assert result == []


async def test_sqlite_clear_exception_swallowed(caplog):
    """A DB error in clear() must be logged but not propagate."""
    bad_storage = SQLiteStorage(Path("/nonexistent/path/history.db"))
    await bad_storage.clear("chat1")  # must not raise
    assert "Failed to clear history" in caplog.text


# ── redaction ordering regression ────────────────────────────────────────────

async def test_stored_history_contains_redacted_value(ready_storage):
    """Storage must receive the already-redacted value, not the raw secret.

    This is a regression test for the Slack pre-redaction bug described in the
    feature doc. Callers (bot.py / slack.py) must redact before calling
    add_exchange(). Here we simulate that contract by calling add_exchange()
    with a pre-redacted value and asserting it is what gets stored.
    """
    raw_response = "ghp_secret_token_12345678901234567890"
    redacted_response = "[REDACTED]"

    # Simulate: caller redacts BEFORE storing
    await ready_storage.add_exchange("chat1", "user question", redacted_response)
    rows = await ready_storage.get_history("chat1")
    assert len(rows) == 1
    stored_ai_msg = rows[0][1]
    assert stored_ai_msg == redacted_response
    assert raw_response not in stored_ai_msg
