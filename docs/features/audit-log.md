# Feature: Audit Log

**Status**: Implemented
**Version**: TBD

## Overview

Append-only audit log that records every command, AI query, shell execution,
auth decision, and agent delegation with timestamp, user ID, and action type.
Designed for compliance, incident forensics, and operational visibility.

## Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_ENABLED` | `true` | Set to `false` to disable audit logging entirely (uses `NullAuditLog` no-op backend). |

The audit database is stored at `/data/audit.db` (separate from conversation
history at `/data/history.db`) to allow independent retention policies.

## Schema

```sql
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL DEFAULT (strftime('%s','now')),
    platform    TEXT    NOT NULL,   -- "telegram" | "slack"
    chat_id     TEXT    NOT NULL,   -- Chat/channel ID
    user_id     TEXT,               -- Platform user ID (nullable for bot actions)
    action      TEXT    NOT NULL,   -- Action category (see below)
    detail      TEXT,               -- JSON context (redacted)
    status      TEXT    NOT NULL DEFAULT 'ok',  -- "ok" | "error" | "cancelled"
    duration_ms INTEGER             -- Wall-clock duration (nullable)
);
```

### Action Types

| Action | Logged When |
|--------|-------------|
| `ai_query` | AI pipeline invoked (prompt → response) |
| `shell_exec` | Shell command dispatched (includes destructive flag) |
| `shell_confirm` | Destructive command confirmed or cancelled |
| `command` | Utility command: `clear`, `restart`, etc. |
| `auth_denied` | Unauthorized access attempt |
| `delegation` | Agent-to-agent delegation posted |

## Design

### Architecture

- **ABC**: `AuditLog` in `src/audit.py` — mirrors `ConversationStorage` pattern
- **Concrete**: `SQLiteAuditLog` — per-call `aiosqlite` connections, indexed on `action` and `chat_id`
- **No-op**: `NullAuditLog` — used when `AUDIT_ENABLED=false`
- **Helper**: `_ms_since(start)` — convenience for computing `duration_ms`

### Key Contracts

1. **Append-only** — no update, delete, or clear methods on the ABC
2. **Exception swallowing** — `record()` and `get_entries()` log errors but never raise; `init()` fails fast at startup
3. **Redaction before storage** — callers must redact via `SecretRedactor` before calling `record()` (same contract as conversation history)
4. **Separate DB** — `/data/audit.db` is independent of `/data/history.db`

### Hook Points

| File | Method | What's Logged |
|------|--------|---------------|
| `bot.py` | `_requires_auth` decorator | Auth denied events |
| `bot.py` | `_run_ai_pipeline()` | AI query start/end with prompt/response lengths |
| `bot.py` | `cmd_run()` | Shell commands (redacted), destructive flag |
| `bot.py` | `callback_handler()` | Confirm/cancel decisions |
| `bot.py` | `cmd_clear()` | History clear events |
| `bot.py` | `cmd_restart()` | Backend restart events |
| `slack.py` | `_on_message()` | Auth denied events |
| `slack.py` | `_run_ai_pipeline()` | AI query start/end |
| `slack.py` | `_cmd_run()` | Shell commands |
| `slack.py` | `_on_confirm_run()` / `_on_cancel_run()` | Confirm/cancel |
| `slack.py` | `_cmd_clear()` / `_cmd_restart()` | Utility commands |
| `slack.py` | `_post_delegations()` | Delegation routing |

## Files Changed

- `src/audit.py` — NEW: `AuditLog` ABC, `SQLiteAuditLog`, `NullAuditLog`, `_ms_since()`
- `src/config.py` — ADD: `AuditConfig` sub-config, `AUDIT_DB_PATH` constant
- `src/main.py` — MODIFY: init audit log at startup, pass to bot constructors
- `src/bot.py` — MODIFY: audit hooks in handlers and AI pipeline
- `src/platform/slack.py` — MODIFY: audit hooks in handlers and AI pipeline
- `tests/contract/test_audit.py` — NEW: 19 contract tests for AuditLog ABC
- `tests/unit/test_bot_handlers.py` — MODIFY: pass `NullAuditLog` to constructors
- `tests/unit/test_bot.py` — MODIFY: pass `NullAuditLog` to constructors
- `tests/unit/test_slack_bot.py` — MODIFY: pass `NullAuditLog` to constructors
- `tests/unit/test_slack_delegation_security.py` — MODIFY: pass `NullAuditLog` to constructors
- `tests/unit/test_main.py` — MODIFY: mock `AuditConfig` and `SQLiteAuditLog`
- `tests/integration/test_startup.py` — MODIFY: mock `SQLiteAuditLog`
- `docs/features/audit-log.md` — NEW: this document

## Security Considerations

- **Redaction**: All `detail` values passed to `record()` are pre-redacted by the caller (shell commands via `self._redactor.redact(cmd)`, errors as plain strings). The audit log does not perform its own redaction.
- **Volume access**: Like `history.db`, the audit DB is plain SQLite. Operators should apply the same volume-level protections (encryption at rest, restricted Docker mounts).
- **No PII in queries**: User messages and AI responses are NOT stored in the audit log — only lengths, action types, and redacted command strings.
