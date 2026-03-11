# Scheduled Commands (`gate schedule`)

> Status: **Planned** | Priority: Medium

Allow recurring shell commands or AI prompts to be triggered automatically on an interval schedule. Results are posted back to the originating chat or Slack channel when each job fires.

---

## Usage

**Telegram** (prefix is `/gate` by default):
```
/gate schedule shell: "git pull && pytest" every 6h
/gate schedule ai: "check if any services are down" every 30m
/gate schedule list
/gate schedule cancel <id>
```

**Slack** (prefix is `gate` by default):
```
gate schedule shell: git pull && pytest every 6h
gate schedule ai: check if any services are down every 30m
gate schedule list
gate schedule cancel abc123
```

**Interval formats supported:** `Ns` (seconds), `Nm` (minutes), `Nh` (hours), `Nd` (days), `Nw` (weeks)

**Routing:**
- `shell:` prefix → run via `executor.run_shell()` in `REPO_DIR`
- `ai:` prefix → forward to active AI backend, same as a normal message
- No prefix → default to `ai:` (safest — no accidental shell execution)

---

## Critical Architecture Notes

### APScheduler version already present

`python-telegram-bot[job-queue]` (already in `requirements.txt`) installs **APScheduler 3.x** as a transitive dependency. At the time of writing, version **3.11.2** is present. The 3.x API is used throughout this document:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
```

> ⚠️ **Do NOT use APScheduler 4.x** (`AsyncScheduler`, `async with Scheduler()` etc.) — the installed version is 3.x and the APIs are incompatible.

### `SQLAlchemyJobStore` is NOT available

APScheduler 3.x ships `SQLAlchemyJobStore` but `sqlalchemy` is **not installed** in this project and must not be added without review. Use **our own `aiosqlite`-backed persistence table** (already used for history) instead. APScheduler runs in-memory (`MemoryJobStore`) and the authoritative job list lives in our SQLite table.

### PTB `JobQueue` is available but scoped to Telegram only

`python-telegram-bot` exposes `app.job_queue` (wrapping APScheduler) for Telegram. It is usable but **does not apply to Slack**. For a unified implementation shared by both platforms, implement a standalone `AgentScheduler` class that wraps `AsyncIOScheduler` directly.

---

## Persistence Strategy

Jobs are stored in a `schedules` table in **`/data/schedules.db`** (separate from `/data/history.db` to keep concerns isolated). On every restart, `AgentScheduler.start()` reads all rows and re-registers each job with the in-memory `AsyncIOScheduler`. Deleting a job removes it from both APScheduler and the DB atomically.

### Schema

```sql
CREATE TABLE IF NOT EXISTS schedules (
    id          TEXT PRIMARY KEY,       -- short random ID, e.g. "a3f9"
    chat_id     TEXT NOT NULL,          -- TG chat_id or Slack channel_id
    command     TEXT NOT NULL,          -- raw command / prompt
    is_shell    INTEGER NOT NULL,       -- 1 = executor, 0 = AI prompt
    interval_secs INTEGER NOT NULL,    -- always stored as seconds
    created_at  TEXT NOT NULL           -- ISO-8601 UTC
);
```

---

## Config Variables

Add to `BotConfig` in `src/config.py`:

| Env var | Default | Description |
|---|---|---|
| `SCHEDULE_ENABLED` | `true` | Set `false` to disable all scheduling |
| `SCHEDULE_MAX_JOBS` | `10` | Max concurrent jobs per chat/channel |

Add `SCHEDULES_DB_PATH` as a module-level constant in `src/config.py` (alongside `REPO_DIR` and `DB_PATH`):

```python
SCHEDULES_DB_PATH = Path("/data/schedules.db")
```

---

## Implementation Steps

### Step 1 — `src/config.py`

1. Add to `BotConfig`:

```python
schedule_enabled: bool = True       # SCHEDULE_ENABLED
schedule_max_jobs: int = 10         # SCHEDULE_MAX_JOBS
```

2. Add module-level constant after `DB_PATH`:

```python
SCHEDULES_DB_PATH = Path("/data/schedules.db")
```

### Step 2 — `src/scheduler.py` (new file)

Create `src/scheduler.py` implementing `AgentScheduler`:

```python
"""
Scheduled-job engine for AgentGate.

Uses APScheduler 3.x AsyncIOScheduler (MemoryJobStore) for execution,
and an aiosqlite SQLite table for cross-restart persistence.
"""
from __future__ import annotations

import logging
import secrets
import aiosqlite
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import SCHEDULES_DB_PATH

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Module-level reference to the running scheduler instance.
# Set by AgentScheduler.start(); used by the job runner.
_scheduler_instance: "AgentScheduler | None" = None


async def _job_runner(job_id: str) -> None:
    """Entry point called by APScheduler when a job fires."""
    global _scheduler_instance
    if _scheduler_instance is None:
        return
    await _scheduler_instance._execute_job(job_id)


class AgentScheduler:
    """
    Platform-agnostic scheduler. Accepts a post_message callback so the
    caller (Telegram or Slack) controls how results are delivered.
    """

    def __init__(
        self,
        post_message: Callable[[str, str], Awaitable[None]],
        run_shell: Callable[[str, int], Awaitable[str]],
        ai_send: Callable[[str], Awaitable[str]],
        max_output_chars: int = 3000,
        max_jobs_per_chat: int = 10,
    ) -> None:
        self._post = post_message
        self._run_shell = run_shell
        self._ai_send = ai_send
        self._max_output_chars = max_output_chars
        self._max_jobs_per_chat = max_jobs_per_chat
        self._apscheduler = AsyncIOScheduler()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        global _scheduler_instance
        _scheduler_instance = self
        await self._init_db()
        await self._restore_jobs()
        self._apscheduler.start()
        logger.info("AgentScheduler started")

    def shutdown(self) -> None:
        self._apscheduler.shutdown(wait=False)
        logger.info("AgentScheduler stopped")

    # ── Public CRUD ───────────────────────────────────────────────────────

    async def add_job(
        self,
        chat_id: str,
        command: str,
        is_shell: bool,
        interval_secs: int,
    ) -> str:
        """Register a new recurring job; returns its short ID."""
        count = await self._count_jobs_for_chat(chat_id)
        if count >= self._max_jobs_per_chat:
            raise ValueError(
                f"Maximum of {self._max_jobs_per_chat} jobs per chat/channel reached."
            )
        job_id = secrets.token_hex(2)  # e.g. "a3f9"
        await self._persist_job(job_id, chat_id, command, is_shell, interval_secs)
        self._register_apscheduler_job(job_id, interval_secs)
        return job_id

    async def list_jobs(self, chat_id: str) -> list[dict]:
        """Return all jobs for a given chat/channel."""
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM schedules WHERE chat_id = ? ORDER BY created_at",
                (chat_id,),
            ) as cur:
                return [dict(row) async for row in cur]

    async def cancel_job(self, job_id: str, chat_id: str) -> bool:
        """Cancel a job. Returns True if found and removed, False if not found."""
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM schedules WHERE id = ? AND chat_id = ?",
                (job_id, chat_id),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return False
            await db.execute("DELETE FROM schedules WHERE id = ?", (job_id,))
            await db.commit()
        try:
            self._apscheduler.remove_job(job_id)
        except Exception:
            pass
        return True

    # ── Internal ──────────────────────────────────────────────────────────

    async def _init_db(self) -> None:
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS schedules (
                    id           TEXT PRIMARY KEY,
                    chat_id      TEXT NOT NULL,
                    command      TEXT NOT NULL,
                    is_shell     INTEGER NOT NULL,
                    interval_secs INTEGER NOT NULL,
                    created_at   TEXT NOT NULL
                )"""
            )
            await db.commit()

    async def _persist_job(
        self,
        job_id: str,
        chat_id: str,
        command: str,
        is_shell: bool,
        interval_secs: int,
    ) -> None:
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            await db.execute(
                "INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    chat_id,
                    command,
                    int(is_shell),
                    interval_secs,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def _restore_jobs(self) -> None:
        """Re-register all persisted jobs with APScheduler after a restart."""
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM schedules") as cur:
                rows = [dict(row) async for row in cur]
        for row in rows:
            self._register_apscheduler_job(row["id"], row["interval_secs"])
        logger.info("Restored %d scheduled job(s) from DB", len(rows))

    def _register_apscheduler_job(self, job_id: str, interval_secs: int) -> None:
        self._apscheduler.add_job(
            _job_runner,
            trigger=IntervalTrigger(seconds=interval_secs),
            id=job_id,
            kwargs={"job_id": job_id},
            replace_existing=True,
            misfire_grace_time=60,
        )

    async def _execute_job(self, job_id: str) -> None:
        """Fetch job details from DB and run it."""
        async with aiosqlite.connect(SCHEDULES_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM schedules WHERE id = ?", (job_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            logger.warning("Scheduled job %s not found in DB; skipping", job_id)
            return
        row = dict(row)
        logger.info("Running scheduled job %s: %s", job_id, row["command"][:60])
        try:
            if row["is_shell"]:
                result = await self._run_shell(row["command"], self._max_output_chars)
                text = f"🕐 Scheduled job `{job_id}`:\n```\n{result}\n```"
            else:
                result = await self._ai_send(row["command"])
                text = f"🕐 Scheduled job `{job_id}`:\n{result}"
        except Exception as exc:
            text = f"⚠️ Scheduled job `{job_id}` failed: {exc}"
            logger.exception("Scheduled job %s error", job_id)
        await self._post(row["chat_id"], text)
```

**Key design decisions:**
- `_job_runner` is a module-level function (importable path) so APScheduler can call it
- Only `job_id` (a plain string) is passed to `_job_runner` — no uncacheable closures
- `_scheduler_instance` global is set at `start()` — safe because only one scheduler runs per container
- `misfire_grace_time=60` handles short downtime gracefully (missed fires run once within 60s)

### Step 3 — Interval parser (add to `src/scheduler.py`)

```python
import re

_INTERVAL_RE = re.compile(r"^(\d+)(s|m|h|d|w)$", re.IGNORECASE)
_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def parse_interval(raw: str) -> int:
    """Parse '30m', '6h', '2d', etc. → seconds. Raises ValueError on invalid input."""
    m = _INTERVAL_RE.match(raw.strip())
    if not m:
        raise ValueError(
            f"Invalid interval '{raw}'. Use format: 30m, 6h, 1d, 2w (s/m/h/d/w)"
        )
    n, unit = int(m.group(1)), m.group(2).lower()
    secs = n * _MULTIPLIERS[unit]
    if secs < 60:
        raise ValueError("Minimum interval is 60 seconds.")
    return secs
```

### Step 4 — Command parser (add to `src/scheduler.py`)

```python
_SCHEDULE_RE = re.compile(
    r'^(?:(shell|ai):\s*)?(.+?)\s+every\s+(\S+)$',
    re.IGNORECASE | re.DOTALL,
)

def parse_schedule_command(args_text: str) -> tuple[str, bool, int]:
    """
    Parse: '[shell:|ai:] <command> every <interval>'
    Returns: (command, is_shell, interval_secs)
    Default routing when no prefix: ai (False).
    """
    m = _SCHEDULE_RE.match(args_text.strip())
    if not m:
        raise ValueError(
            "Usage: `schedule [shell:|ai:] <command> every <interval>`\n"
            "Example: `schedule shell: git pull every 6h`\n"
            "Example: `schedule ai: check for errors every 30m`"
        )
    prefix, command, interval_raw = m.group(1), m.group(2).strip(), m.group(3)
    is_shell = (prefix or "ai").lower() == "shell"
    interval_secs = parse_interval(interval_raw)
    return command, is_shell, interval_secs
```

### Step 5 — `src/bot.py` — `cmd_schedule` handler

Add to `_BotHandlers`:

```python
@_requires_auth
async def cmd_schedule(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from src import scheduler as sched_mod

    if not self._settings.bot.schedule_enabled:
        await _reply(update, "⏰ Scheduling is disabled (SCHEDULE_ENABLED=false).")
        return

    args_text = " ".join(ctx.args) if ctx.args else ""
    sub = args_text.split()[0].lower() if args_text else ""
    chat_id = str(update.effective_chat.id)

    if sub == "list":
        await self._schedule_list(update, chat_id)
    elif sub == "cancel":
        rest = " ".join(args_text.split()[1:])
        await self._schedule_cancel(update, chat_id, rest)
    else:
        await self._schedule_add(update, chat_id, args_text)

async def _schedule_add(self, update, chat_id, args_text):
    from src.scheduler import parse_schedule_command
    try:
        command, is_shell, interval_secs = parse_schedule_command(args_text)
    except ValueError as exc:
        await _reply(update, f"⚠️ {exc}")
        return
    try:
        job_id = await self._scheduler.add_job(chat_id, command, is_shell, interval_secs)
    except ValueError as exc:
        await _reply(update, f"⚠️ {exc}")
        return
    kind = "shell" if is_shell else "AI"
    await _reply(update, (
        f"✅ Scheduled job `{job_id}` created.\n"
        f"Type: {kind} | Interval: every {interval_secs}s\n"
        f"Command: `{command}`\n"
        f"Use `/{self._p} schedule cancel {job_id}` to stop."
    ))

async def _schedule_list(self, update, chat_id):
    jobs = await self._scheduler.list_jobs(chat_id)
    if not jobs:
        await _reply(update, "📭 No scheduled jobs for this chat.")
        return
    lines = ["📋 *Scheduled Jobs:*"]
    for j in jobs:
        kind = "shell" if j["is_shell"] else "AI"
        lines.append(
            f"• `{j['id']}` — {kind} — every {j['interval_secs']}s\n"
            f"  `{j['command'][:60]}`"
        )
    await _reply(update, "\n".join(lines))

async def _schedule_cancel(self, update, chat_id, job_id):
    if not job_id:
        await _reply(update, f"Usage: `/{self._p} schedule cancel <id>`")
        return
    removed = await self._scheduler.cancel_job(job_id, chat_id)
    if removed:
        await _reply(update, f"🗑 Job `{job_id}` cancelled.")
    else:
        await _reply(update, f"❌ Job `{job_id}` not found (or belongs to another chat).")
```

**Also:**
- Add `self._scheduler: AgentScheduler | None = None` to `__init__`
- Add `"schedule": self.cmd_schedule` to the `dispatch` dict in `cmd_ta`
- Register `CommandHandler(f"{p}schedule", h.cmd_schedule)` in `build_app`
- Expose a `set_scheduler(scheduler)` method so `main.py` can inject after startup

### Step 6 — `src/platform/slack.py` — `cmd_schedule` handler

Mirror the Telegram logic. Add `_schedule_add`, `_schedule_list`, `_schedule_cancel` methods to `SlackBot`. Register in `_register_handlers()` so that messages matching `schedule ...` call `cmd_schedule`. Accept `self._scheduler` injected via a `set_scheduler()` method.

The `_post_message` callback passed to `AgentScheduler` for Slack:

```python
async def _post_to_channel(self, channel: str, text: str) -> None:
    await self._app.client.chat_postMessage(channel=channel, text=text)
```

### Step 7 — `src/main.py` — Scheduler lifecycle

**For Telegram** (`_startup_telegram`):

```python
from src.scheduler import AgentScheduler
from src import executor

async def _startup_telegram(settings, backend, start_time):
    app = build_app(settings, backend, start_time)
    ...
    # Build and start scheduler
    async def _post(chat_id: str, text: str) -> None:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    scheduler = AgentScheduler(
        post_message=_post,
        run_shell=executor.run_shell,
        ai_send=backend.send,
        max_output_chars=settings.bot.max_output_chars,
        max_jobs_per_chat=settings.bot.schedule_max_jobs,
    )
    app.handlers_instance.set_scheduler(scheduler)  # inject into bot handlers
    ...
    async with app:
        await scheduler.start()
        ...
        stop_event.wait()
        scheduler.shutdown()
```

**For Slack** (`_startup_slack`), same pattern with `_post` using `self._app.client.chat_postMessage`.

> ⚠️ **Order matters:** build the app/bot first, then build the scheduler (which needs the `bot.send_message` reference), then inject into handlers, then start both.

### Step 8 — `src/bot.py` — expose handlers instance

`build_app` currently doesn't expose `h` externally. Add a reference:

```python
def build_app(settings, backend, start_time) -> Application:
    ...
    h = _BotHandlers(settings, backend, start_time)
    app = Application.builder().token(...).build()
    app.handlers_instance = h  # expose for scheduler injection
    ...
    return app
```

### Step 9 — Update `cmd_help` (both platforms)

Add schedule commands to the help text:

```
`/gate schedule` `shell:|ai: <cmd> every <interval>` — schedule a recurring command
`/gate schedule list` — list all scheduled jobs
`/gate schedule cancel <id>` — cancel a scheduled job
```

### Step 10 — `README.md`

1. Add `gate schedule` to the Bot Commands table:

```markdown
| `/gate schedule` | Schedule recurring commands or AI prompts |
| `/gate schedule list` | List all scheduled jobs |
| `/gate schedule cancel <id>` | Cancel a scheduled job |
```

2. Add to the Features bullet list:

```markdown
- ⏰ **Scheduled commands** — run shell commands or AI prompts on a recurring interval, results posted back to your chat
```

3. Add a `SCHEDULE_ENABLED` / `SCHEDULE_MAX_JOBS` row to the Environment Variables table.

---

## Files to Create/Change

| File | Action | Change |
|---|---|---|
| `src/scheduler.py` | **Create** | `AgentScheduler`, `parse_interval`, `parse_schedule_command`, `_job_runner` |
| `src/config.py` | **Edit** | Add `schedule_enabled`, `schedule_max_jobs` to `BotConfig`; add `SCHEDULES_DB_PATH` constant |
| `src/bot.py` | **Edit** | Add `cmd_schedule`, `_schedule_add/list/cancel`; expose `handlers_instance`; register handler |
| `src/platform/slack.py` | **Edit** | Mirror schedule handlers; add `set_scheduler()`; add `_post_to_channel()` |
| `src/main.py` | **Edit** | Construct `AgentScheduler` after app build; inject; `await scheduler.start()` / `scheduler.shutdown()` |
| `README.md` | **Edit** | Add feature bullet, command table rows, env var rows |
| `requirements.txt` | **No change** | `apscheduler` already present via `python-telegram-bot[job-queue]` |

---

## Dependencies

| Package | Status | Notes |
|---|---|---|
| `apscheduler` | ✅ Already installed (3.11.2) | Installed as dep of `python-telegram-bot[job-queue]` |
| `aiosqlite` | ✅ Already installed | Used for persistence (history.db pattern) |
| `sqlalchemy` | ❌ Not needed | `SQLAlchemyJobStore` skipped; we manage persistence ourselves |

> **Do not add `sqlalchemy` or `apscheduler` to `requirements.txt`** — they are transitive dependencies. Adding explicit version pins for transitive deps causes version-conflict headaches. If `apscheduler` is ever needed as a direct dependency, pin it then.

---

## Test Plan

### `tests/unit/test_scheduler.py` (new)

| Test | What it checks |
|---|---|
| `test_parse_interval_valid` | `"30m"` → 1800, `"6h"` → 21600, `"2d"` → 172800 |
| `test_parse_interval_minimum` | `"30s"` → `ValueError` (below 60s minimum) |
| `test_parse_interval_invalid_format` | `"6hours"`, `"abc"` → `ValueError` |
| `test_parse_schedule_command_shell` | `"shell: git pull every 6h"` → `(…, True, 21600)` |
| `test_parse_schedule_command_ai` | `"ai: check errors every 30m"` → `(…, False, 1800)` |
| `test_parse_schedule_command_default_ai` | `"check errors every 30m"` → `is_shell=False` |
| `test_parse_schedule_command_missing_every` | `"git pull 6h"` → `ValueError` |
| `test_add_job_persists_to_db` | After `add_job`, row appears in `schedules` table |
| `test_list_jobs_scoped_to_chat` | Jobs from other chats are not returned |
| `test_cancel_job_removes_from_db` | `cancel_job` deletes the row |
| `test_cancel_nonexistent_job_returns_false` | Returns `False`, no error |
| `test_max_jobs_limit` | Adding job beyond `max_jobs_per_chat` raises `ValueError` |
| `test_restore_jobs_on_start` | Pre-populated DB rows are re-registered on `start()` |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|---|---|
| `test_cmd_schedule_add` | `cmd_schedule` with valid args calls `scheduler.add_job` |
| `test_cmd_schedule_disabled` | `SCHEDULE_ENABLED=false` returns disabled message |
| `test_cmd_schedule_list_empty` | Empty list returns "no jobs" message |
| `test_cmd_schedule_cancel` | Valid cancel calls `scheduler.cancel_job` |

---

## Edge Cases and Open Questions

1. **Destructive shell commands**: Should `gate schedule shell: rm -rf build/ every 1d` require the confirmation flow? Recommendation: require it — call `is_destructive()` during `add_job` validation and reject unless `CONFIRM_DESTRUCTIVE=false`.

2. **AI backend restarts**: If `gate restart` is called, `backend.send` reference in `AgentScheduler` is stale. Scheduler needs to reference a wrapper that always calls `self._backend.send` via the handlers instance. Consider passing a lambda: `lambda prompt: h._backend.send(prompt)`.

3. **Slack channel scope**: When a job was created in `#channel-A` but the bot is now in a different channel, the `chat_postMessage` still works (Slack allows posting to any channel the bot is in). Document this as expected behaviour.

4. **Concurrent AI requests**: Scheduled AI jobs compete with interactive user messages. Add a brief note to the result message so users understand why a response appears unexpectedly.

5. **`gate clear` interaction**: Clearing history does not affect scheduled jobs — the scheduler's DB is independent.

6. **Maximum interval**: No enforced upper bound. A `1w` job is valid. Document this.

7. **Cron trigger (future)**: The schema and `AgentScheduler` do not preclude adding a `cron` column later for `@daily`, `@weekly`, or `0 9 * * 1-5` syntax. Leave `cron TEXT` nullable in the schema for forward compatibility.

---

## Summary

The feature requires **one new file** (`src/scheduler.py`) and targeted edits to four existing files. No new pip packages are needed — APScheduler 3.11.2 and aiosqlite are already available. The trickiest parts are:
- injecting the `post_message` callback into `AgentScheduler` after the bot client is initialized
- keeping the `backend.send` reference live across `gate restart` calls
- ensuring test coverage of the persistence-and-restore cycle
