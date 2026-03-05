import aiosqlite
from pathlib import Path

DB_PATH = Path("/data/history.db")
HISTORY_LIMIT = 10  # exchanges to inject as context


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   TEXT    NOT NULL,
                user_msg  TEXT    NOT NULL,
                ai_msg    TEXT    NOT NULL,
                ts        INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        await db.commit()


async def add_exchange(chat_id: str, user_msg: str, ai_msg: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (chat_id, user_msg, ai_msg) VALUES (?, ?, ?)",
            (chat_id, user_msg, ai_msg),
        )
        await db.commit()


async def get_history(chat_id: str) -> list[tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_msg, ai_msg FROM history WHERE chat_id=? ORDER BY ts DESC LIMIT ?",
            (chat_id, HISTORY_LIMIT),
        ) as cur:
            rows = await cur.fetchall()
    return list(reversed(rows))  # oldest first


async def clear_history(chat_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE chat_id=?", (chat_id,))
        await db.commit()


def build_context(history: list[tuple[str, str]], current: str) -> str:
    if not history:
        return current
    lines = ["Previous conversation:"]
    for user, ai in history:
        lines.append(f"User: {user}")
        lines.append(f"AI: {ai}")
    lines.append(f"\nUser: {current}")
    return "\n".join(lines)
