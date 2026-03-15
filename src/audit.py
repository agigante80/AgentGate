"""Append-only audit log for compliance and incident forensics.

Records every command, AI query, shell execution, auth decision, and
delegation with timestamp, user ID, and action type.

Design mirrors ``src/history.py`` — ABC + SQLite implementation, async-first,
exception-swallowing (storage failures never crash the bot).
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import aiosqlite

from src.registry import audit_registry

logger = logging.getLogger(__name__)


class AuditLog(ABC):
    """Abstract base class for audit log backends.

    Implementations MUST be append-only — no update or delete methods.
    All write methods MUST swallow exceptions (log only) so a transient
    storage failure never crashes the bot pipeline.

    Callers MUST redact sensitive data before calling ``record()``.
    """

    @abstractmethod
    async def init(self) -> None:
        """Initialise the audit backend (create tables, connect, etc.).

        Unlike ``record()``, this method MUST raise on failure so the
        operator sees startup errors immediately.
        """
        ...

    @abstractmethod
    async def record(
        self,
        *,
        platform: str,
        chat_id: str,
        user_id: str | None = None,
        action: str,
        detail: dict[str, Any] | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
    ) -> None:
        """Append one audit entry.

        Implementations MUST swallow all exceptions (log only).

        Parameters
        ----------
        platform : str
            ``"telegram"`` or ``"slack"``.
        chat_id : str
            Chat / channel identifier.
        user_id : str | None
            Platform user ID (Telegram numeric or Slack ``U…``).
        action : str
            Action category — e.g. ``"ai_query"``, ``"shell_exec"``,
            ``"command"``, ``"auth_denied"``.
        detail : dict | None
            Arbitrary JSON-serialisable context (already redacted).
        status : str
            ``"ok"`` | ``"error"`` | ``"cancelled"``.
        duration_ms : int | None
            Wall-clock duration of the operation, if applicable.
        """
        ...

    async def verify(self) -> bool:
        """Smoke-test the audit pipeline at startup.

        Writes a sentinel record and reads it back to confirm the full
        write → read path is functional.  Returns ``True`` on success.

        This would have caught the ``961daf2`` SlackBot param-order bug
        where ``self._audit`` was silently assigned a ``float`` instead
        of an ``AuditLog`` instance, breaking all Slack audit logging.

        The default implementation returns ``True`` (suitable for
        ``NullAuditLog``).  ``SQLiteAuditLog`` overrides with a real
        round-trip check.
        """
        return True

    @abstractmethod
    async def get_entries(
        self,
        *,
        chat_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent audit entries (newest first), optionally filtered.

        Implementations MUST swallow all exceptions and return ``[]`` on
        failure.
        """
        ...


@audit_registry.register("sqlite", force=True)
class SQLiteAuditLog(AuditLog):
    """Default SQLite-backed audit log.

    Uses per-call ``aiosqlite`` connections (same pattern as
    ``SQLiteStorage``) — safe for concurrent coroutines.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL    NOT NULL DEFAULT (strftime('%s','now')),
                    platform    TEXT    NOT NULL,
                    chat_id     TEXT    NOT NULL,
                    user_id     TEXT,
                    action      TEXT    NOT NULL,
                    detail      TEXT,
                    status      TEXT    NOT NULL DEFAULT 'ok',
                    duration_ms INTEGER
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_chat ON audit_log (chat_id)"
            )
            await db.commit()

    async def record(
        self,
        *,
        platform: str,
        chat_id: str,
        user_id: str | None = None,
        action: str,
        detail: dict[str, Any] | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
    ) -> None:
        try:
            detail_json = json.dumps(detail) if detail else None
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO audit_log
                       (platform, chat_id, user_id, action, detail, status, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (platform, chat_id, user_id, action, detail_json, status, duration_ms),
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to write audit entry: action=%s chat=%s", action, chat_id)

    async def verify(self) -> bool:
        """Write a sentinel record and read it back to confirm the pipeline works."""
        try:
            await self.record(
                platform="system",
                chat_id="startup",
                action="audit_verify",
                detail={"msg": "startup smoke test"},
                status="ok",
            )
            entries = await self.get_entries(action="audit_verify", limit=1)
            if not entries:
                logger.error("Audit verify: write succeeded but read returned nothing")
                return False
            return True
        except Exception:
            logger.exception("Audit verification failed")
            return False

    async def get_entries(
        self,
        *,
        chat_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        try:
            capped = min(max(limit, 1), 500)
            clauses: list[str] = []
            params: list[str | int] = []
            if chat_id is not None:
                clauses.append("chat_id = ?")
                params.append(chat_id)
            if action is not None:
                clauses.append("action = ?")
                params.append(action)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(capped)
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ?",
                    params,
                ) as cur:
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to read audit entries")
            return []


@audit_registry.register("null", force=True)
class NullAuditLog(AuditLog):
    """No-op audit log used when ``AUDIT_ENABLED=false``."""

    async def init(self) -> None:
        pass

    async def record(self, **kwargs: Any) -> None:
        pass

    async def get_entries(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


# ── Convenience helper ───────────────────────────────────────────────────────

def _ms_since(start: float) -> int:
    """Return milliseconds elapsed since *start* (``time.time()``)."""
    return int((time.time() - start) * 1000)
