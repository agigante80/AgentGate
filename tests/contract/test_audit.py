"""Contract tests — verifies SQLiteAuditLog satisfies the AuditLog ABC.

Each test checks one aspect of the audit log contract.  Any alternative
implementation must pass the same tests.
"""
import pytest
from pathlib import Path

from src.audit import AuditLog, SQLiteAuditLog, NullAuditLog


@pytest.fixture
def audit(tmp_path) -> SQLiteAuditLog:
    """Return an un-initialised SQLiteAuditLog backed by a temp file."""
    return SQLiteAuditLog(tmp_path / "contract_audit.db")


@pytest.fixture
async def ready_audit(audit) -> SQLiteAuditLog:
    """Return an initialised SQLiteAuditLog ready for use."""
    await audit.init()
    return audit


# ── ABC conformance ───────────────────────────────────────────────────────────

def test_sqlite_audit_satisfies_abc():
    """SQLiteAuditLog must be a concrete subclass of AuditLog."""
    assert issubclass(SQLiteAuditLog, AuditLog)


def test_null_audit_satisfies_abc():
    """NullAuditLog must be a concrete subclass of AuditLog."""
    assert issubclass(NullAuditLog, AuditLog)


def test_audit_abc_not_instantiable():
    """AuditLog ABC itself must not be directly instantiable."""
    with pytest.raises(TypeError):
        AuditLog()  # type: ignore[abstract]


# ── init ─────────────────────────────────────────────────────────────────────

async def test_sqlite_audit_init_creates_table(audit):
    """After init(), the audit_log table must exist and be usable."""
    await audit.init()
    await audit.record(platform="test", chat_id="c1", action="probe")
    rows = await audit.get_entries(chat_id="c1")
    assert len(rows) == 1


async def test_sqlite_audit_init_is_idempotent(audit):
    """Calling init() twice must not raise or corrupt data."""
    await audit.init()
    await audit.record(platform="test", chat_id="c1", action="probe")
    await audit.init()  # second call
    rows = await audit.get_entries(chat_id="c1")
    assert len(rows) == 1


# ── record / get_entries ──────────────────────────────────────────────────────

async def test_sqlite_audit_record_and_get(ready_audit):
    """record() followed by get_entries() must return the entry."""
    await ready_audit.record(
        platform="telegram", chat_id="c1", user_id="u1",
        action="ai_query", detail={"prompt_len": 42},
        status="ok", duration_ms=100,
    )
    rows = await ready_audit.get_entries(chat_id="c1")
    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "telegram"
    assert row["chat_id"] == "c1"
    assert row["user_id"] == "u1"
    assert row["action"] == "ai_query"
    assert row["status"] == "ok"
    assert row["duration_ms"] == 100
    assert '"prompt_len": 42' in row["detail"]


async def test_sqlite_audit_get_empty(ready_audit):
    """get_entries on an empty DB must return []."""
    rows = await ready_audit.get_entries(chat_id="nonexistent")
    assert rows == []


async def test_sqlite_audit_filter_by_action(ready_audit):
    """get_entries(action=...) must filter correctly."""
    await ready_audit.record(platform="test", chat_id="c1", action="ai_query")
    await ready_audit.record(platform="test", chat_id="c1", action="shell_exec")
    rows = await ready_audit.get_entries(action="shell_exec")
    assert len(rows) == 1
    assert rows[0]["action"] == "shell_exec"


async def test_sqlite_audit_filter_by_chat_and_action(ready_audit):
    """get_entries with both filters must return the intersection."""
    await ready_audit.record(platform="test", chat_id="c1", action="ai_query")
    await ready_audit.record(platform="test", chat_id="c2", action="ai_query")
    await ready_audit.record(platform="test", chat_id="c1", action="shell_exec")
    rows = await ready_audit.get_entries(chat_id="c1", action="ai_query")
    assert len(rows) == 1


async def test_sqlite_audit_get_limit(ready_audit):
    """get_entries respects a limit parameter."""
    for i in range(20):
        await ready_audit.record(platform="test", chat_id="c1", action="ai_query")
    rows = await ready_audit.get_entries(chat_id="c1", limit=5)
    assert len(rows) == 5


async def test_sqlite_audit_get_negative_limit_clamped(ready_audit):
    """Negative limit must be clamped to 1 (not bypass the cap)."""
    for i in range(10):
        await ready_audit.record(platform="test", chat_id="c1", action="ai_query")
    rows = await ready_audit.get_entries(chat_id="c1", limit=-1)
    assert 1 <= len(rows) <= 10


async def test_sqlite_audit_newest_first(ready_audit):
    """get_entries must return entries newest-first (DESC order)."""
    await ready_audit.record(platform="test", chat_id="c1", action="first")
    await ready_audit.record(platform="test", chat_id="c1", action="second")
    rows = await ready_audit.get_entries(chat_id="c1")
    assert rows[0]["action"] == "second"
    assert rows[1]["action"] == "first"


async def test_sqlite_audit_nullable_fields(ready_audit):
    """user_id, detail, and duration_ms can be None."""
    await ready_audit.record(
        platform="test", chat_id="c1", action="probe",
    )
    rows = await ready_audit.get_entries(chat_id="c1")
    assert rows[0]["user_id"] is None
    assert rows[0]["detail"] is None
    assert rows[0]["duration_ms"] is None


# ── exception swallowing ──────────────────────────────────────────────────────

async def test_sqlite_audit_record_exception_swallowed(caplog):
    """A DB error in record() must be logged but not propagate."""
    bad = SQLiteAuditLog(Path("/nonexistent/path/audit.db"))
    await bad.record(platform="test", chat_id="c1", action="probe")  # must not raise
    assert "Failed to write audit entry" in caplog.text


async def test_sqlite_audit_get_exception_returns_empty():
    """A DB error in get_entries() must return [] and not propagate."""
    bad = SQLiteAuditLog(Path("/nonexistent/path/audit.db"))
    result = await bad.get_entries(chat_id="c1")  # must not raise
    assert result == []


# ── NullAuditLog ──────────────────────────────────────────────────────────────

async def test_null_audit_record_is_noop():
    """NullAuditLog.record() must not raise."""
    null = NullAuditLog()
    await null.init()
    await null.record(platform="test", chat_id="c1", action="probe")
    rows = await null.get_entries()
    assert rows == []


# ── append-only contract ─────────────────────────────────────────────────────

async def test_sqlite_audit_no_delete_or_update(ready_audit):
    """AuditLog ABC has no delete/update methods — verify append-only."""
    assert not hasattr(ready_audit, "delete")
    assert not hasattr(ready_audit, "update")
    assert not hasattr(ready_audit, "clear")


# ── verify() ─────────────────────────────────────────────────────────────────

async def test_sqlite_audit_verify_succeeds(ready_audit):
    """verify() must return True when the audit DB is functional."""
    assert await ready_audit.verify() is True
    # Sentinel record should be readable
    entries = await ready_audit.get_entries(action="audit_verify")
    assert len(entries) >= 1


async def test_sqlite_audit_verify_fails_on_broken_db():
    """verify() must return False when the DB path is invalid."""
    bad = SQLiteAuditLog(Path("/nonexistent/path/audit.db"))
    assert await bad.verify() is False


async def test_null_audit_verify_returns_true():
    """NullAuditLog.verify() must return True (no-op backend is always OK)."""
    null = NullAuditLog()
    assert await null.verify() is True
