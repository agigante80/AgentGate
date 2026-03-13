# Pluggable History Storage

> Status: **Planned** | Priority: Low | Last reviewed: 2026-03-12

Introduce a `ConversationStorage` ABC so that the history backend (currently hard-coded to SQLite) can be swapped for Redis, Postgres, or any other store without touching bot logic.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram `bot.py` and Slack `platform/slack.py`). Both call the same `history.*` module-level functions.
2. **Backend** — Only affects stateless AI backends (`copilot`, `api`). Stateful backends (`codex`) do not use `history.py` at all — `is_stateful = True` skips context injection.
3. **Stateful vs stateless** — Only stateless backends (`is_stateful = False`) call `history.get_history()` and `history.add_exchange()`. This refactor only affects that path.
4. **Breaking change?** — No. The default implementation remains SQLite; existing deployments see zero behaviour change. MINOR version bump.
5. **New dependency?** — No new deps for the default SQLite implementation. Future Redis/Postgres adapters would add deps in their own PRs.
6. **Persistence** — No DB schema changes; `SQLiteStorage` keeps the existing `history` table at `DB_PATH`.
7. **Auth** — No new secrets for the SQLite default. Future adapters will add their own connection-string env vars.
8. **Caller interface** — Today callers use module-level functions (`history.add_exchange(...)`, `history.get_history(...)`). After the refactor, callers will call the same-named methods on an injected `ConversationStorage` instance. This is the key interface decision.

---

## Problem Statement

1. **No abstraction over storage** — `src/history.py` is a module of standalone `async def` functions tied to `aiosqlite`. Adding any alternative store (Redis for multi-replica, Postgres for shared state) requires rewriting the module from scratch rather than implementing a known interface.
2. **All callers couple to a module** — `bot.py` calls `history.add_exchange()`, `history.get_history()`, `history.clear_history()`, and `history.build_context()` as bare module-level functions. Swapping the implementation requires a grep-and-replace, not a constructor change.
3. **No contract test** — There is no test that verifies a storage implementation satisfies the full interface. A partial implementation would silently fail at runtime.

Affected: self-hosters who want to run multiple AgentGate replicas sharing conversation history (requires network-accessible storage, not file-local SQLite).

---

## Current Behaviour (as of v0.8.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Storage init | `src/history.py:11` (`init_db`) | Creates `history` table in `/data/history.db` via `aiosqlite` |
| Write | `src/history.py:26` (`add_exchange`) | Inserts a row; swallows exceptions with `logger.exception` |
| Read | `src/history.py:38` (`get_history`) | Fetches last 10 rows ordered oldest-first; swallows exceptions |
| Delete | `src/history.py:52` (`clear_history`) | Deletes all rows for `chat_id`; swallows exceptions |
| Context | `src/history.py:61` (`build_context`) | Pure function — formats history list into a prompt prefix |
| Telegram caller | `src/bot.py:163-164,211,408` | Calls module-level functions directly |
| Slack caller | `src/platform/slack.py` | Calls same module-level functions directly |
| Config | `src/config.py` (`BotConfig`) | `history_enabled: bool` — disables history injection when `False` |

> **Key gap**: No interface separates the *contract* (what storage must do) from the *implementation* (SQLite). Adding a second backend today requires forking the entire module.

---

## Design Space

### Axis 1 — Interface style

#### Option A — Module-level functions remain, backed by a singleton *(minimal change)*

Keep `history.add_exchange(...)` etc. as module-level functions. Internally they delegate to a module-level `_storage: ConversationStorage` singleton set at startup.

**Pros:** Zero caller changes. Easy to implement.
**Cons:** Global mutable state; harder to test in isolation; hides the dependency.

---

#### Option B — `ConversationStorage` ABC injected into callers *(recommended)*

Define the ABC in `src/history.py`. Instantiate `SQLiteStorage` in `main.py`. Pass the instance to `_BotHandlers` (Telegram) and `SlackBot` (Slack) via constructor. Callers call `self._history.add_exchange(...)` instead of `history.add_exchange(...)`.

```python
class ConversationStorage(ABC):
    @abstractmethod
    async def init(self) -> None: ...
    @abstractmethod
    async def add_exchange(self, chat_id: str, user: str, assistant: str) -> None: ...
    @abstractmethod
    async def get_history(self, chat_id: str) -> list[tuple[str, str]]: ...
    @abstractmethod
    async def clear(self, chat_id: str) -> None: ...
```

`build_context()` remains a pure module-level helper (takes a list, returns a string — no I/O).

**Pros:** Explicit dependency; easy to mock in tests; enables contract tests.
**Cons:** Touches constructors of `_BotHandlers`, `SlackBot`, and `main.py`.

**Recommendation: Option B** — explicit injection is the correct architectural pattern and enables proper contract testing.

---

### Axis 2 — Where `build_context()` lives

#### Option A — Keep as module-level function in `history.py` *(recommended)*

`build_context(history: list[tuple[str,str]], current: str) -> str` is pure (no I/O, no state). It belongs in `history.py` as a standalone helper used by callers after fetching history from the ABC.

**Recommendation: Option A** — no reason to move a pure function into the ABC.

---

## Recommended Solution

- **Axis 1**: Option B — `ConversationStorage` ABC, `SQLiteStorage` default, injected via constructor.
- **Axis 2**: Option A — `build_context()` stays as a module-level pure function.

**Runtime flow (after refactor):**
```
main.py
  → storage = SQLiteStorage(DB_PATH)
  → await storage.init()
  → pass storage to _BotHandlers(..., history=storage)
  → pass storage to SlackBot(..., history=storage)

_BotHandlers._run_ai_pipeline()
  → hist = await self._history.get_history(chat_id)
  → prompt = history.build_context(hist, text)
  → ...
  → await self._history.add_exchange(chat_id, text, response)
```

---

## Architecture Notes

- **`is_stateful` flag** — only stateless backends call `get_history`/`add_exchange`. The `if self._backend.is_stateful` guard in `bot.py:_run_ai_pipeline` must be preserved; do not call storage methods for stateful backends.
- **`DB_PATH`** — always import from `src/config.py`; `SQLiteStorage` should accept a `Path` in its constructor rather than hardcoding.
- **Platform symmetry** — both `bot.py` (`_BotHandlers`) and `platform/slack.py` (`SlackBot`) call history; both constructors must receive the storage instance.
- **`history_enabled` flag** — the `BotConfig.history_enabled` guard (`if self._settings.bot.history_enabled`) must still be respected; skip storage calls entirely when `False`.
- **`asyncio_mode = auto`** — all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **Backward compatibility** — `SQLiteStorage` must produce identical query results to the existing module-level functions. The table schema and `HISTORY_LIMIT` constant do not change.

---

## Config Variables

No new env vars for the SQLite default. Future adapters (Redis, Postgres) will introduce their own connection-string vars in separate feature docs.

---

## Implementation Steps

### Step 1 — `src/history.py`: introduce ABC and `SQLiteStorage`

Replace the module-level functions with an ABC and a concrete implementation. Keep `build_context()` as a module-level function.

```python
from abc import ABC, abstractmethod

HISTORY_LIMIT = 10

class ConversationStorage(ABC):
    @abstractmethod
    async def init(self) -> None: ...
    @abstractmethod
    async def add_exchange(self, chat_id: str, user: str, assistant: str) -> None: ...
    @abstractmethod
    async def get_history(self, chat_id: str) -> list[tuple[str, str]]: ...
    @abstractmethod
    async def clear(self, chat_id: str) -> None: ...

class SQLiteStorage(ConversationStorage):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        # existing init_db() logic, using self._db_path

    async def add_exchange(self, chat_id, user, assistant) -> None:
        # existing add_exchange() logic

    async def get_history(self, chat_id) -> list[tuple[str, str]]:
        # existing get_history() logic

    async def clear(self, chat_id) -> None:
        # existing clear_history() logic

def build_context(history: list[tuple[str, str]], current: str) -> str:
    # unchanged
```

Keep the old module-level functions as thin shim wrappers (deprecated) pointing to a default `SQLiteStorage` instance to avoid breaking any imports not yet updated.

---

### Step 2 — `src/main.py`: construct and inject storage

```python
from src.history import SQLiteStorage
from src.config import DB_PATH

async def startup(settings: Settings) -> None:
    ...
    storage = SQLiteStorage(DB_PATH)
    await storage.init()
    ...
    # Pass to platform startup functions
    await _startup_telegram(settings, backend, start_time, storage)
    # or
    await _startup_slack(settings, backend, start_time, storage)
```

---

### Step 3 — `src/bot.py`: accept `storage` in `_BotHandlers` and `build_app`

```python
class _BotHandlers:
    def __init__(self, settings, backend, start_time, history: ConversationStorage):
        self._history = history
        ...

    async def _run_ai_pipeline(self, update, text, chat_id):
        ...
        hist = await self._history.get_history(chat_id) if self._settings.bot.history_enabled else []
        ...
        await self._history.add_exchange(chat_id, text, response)

    async def cmd_clear(self, update, context):
        ...
        await self._history.clear(str(update.effective_chat.id))
```

Update `build_app()` signature to accept and pass through the storage instance.

---

### Step 4 — `src/platform/slack.py`: same changes for `SlackBot`

Mirror Step 3 for `SlackBot.__init__`, `_run_ai_pipeline`, and the clear-history handler.

---

### Step 5 — Remove shim wrappers from `src/history.py`

Once all callers are updated, delete the deprecated module-level shim functions.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/history.py` | **Edit** | Add `ConversationStorage` ABC, refactor functions into `SQLiteStorage` |
| `src/main.py` | **Edit** | Construct `SQLiteStorage`, pass to platform startup |
| `src/bot.py` | **Edit** | `_BotHandlers` accepts `ConversationStorage`; update `build_app` |
| `src/platform/slack.py` | **Edit** | `SlackBot` accepts `ConversationStorage`; update history calls |
| `tests/contract/test_storage.py` | **Create** | Contract test verifying `SQLiteStorage` satisfies the ABC |
| `tests/unit/test_history.py` | **Edit** | Update tests to use `SQLiteStorage` instance directly |
| `tests/unit/test_bot.py` | **Edit** | Pass mock `ConversationStorage` to `_BotHandlers` in test helpers |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `aiosqlite` | ✅ Already installed | Used by `SQLiteStorage`. Do NOT re-pin. |
| `abc` | ✅ stdlib | `ABC`, `abstractmethod` |

---

## Test Plan

### `tests/contract/test_storage.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_sqlite_satisfies_abc` | `SQLiteStorage` is a subclass of `ConversationStorage` |
| `test_sqlite_init_creates_table` | After `init()`, the `history` table exists |
| `test_sqlite_add_and_get` | `add_exchange` followed by `get_history` returns the same exchange |
| `test_sqlite_get_limit` | `get_history` returns at most `HISTORY_LIMIT` exchanges |
| `test_sqlite_clear` | `clear()` removes all rows for a given `chat_id` |
| `test_sqlite_get_empty` | `get_history` on an unknown `chat_id` returns `[]` |
| `test_sqlite_add_exception_swallowed` | DB error in `add_exchange` does not propagate (logs only) |

### `tests/unit/test_bot.py` changes

| Test | What it checks |
|------|----------------|
| `_make_settings` / `_make_handlers` | Updated to inject a `MagicMock(spec=ConversationStorage)` |
| `test_clear_calls_storage_clear` | `cmd_clear` calls `storage.clear(chat_id)` |
| `test_history_disabled_skips_storage` | `history_enabled=False` means `storage.get_history` is never called |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target: `src/history.py` remains at 100%; no new uncovered branches.

---

## Documentation Updates

### `README.md`

No user-visible change — SQLite remains the default. No new env vars to document.

### `.github/copilot-instructions.md`

Add a bullet to the **History** section:
> `ConversationStorage` ABC in `src/history.py` — `SQLiteStorage` is the default. Inject via constructor into `_BotHandlers` and `SlackBot`. Only used by stateless backends (`is_stateful = False`).

### `docs/roadmap.md`

Mark item 1.3 as ✅ once merged to `main`.

---

## Version Bump

**MINOR** — new ABC introduced; no env vars removed or renamed; fully backward-compatible for deployments.

Expected bump: `0.8.x` → `0.9.0`

---

## Security Considerations

### 🔴 Pre-existing bug: Slack stores unredacted responses

In `src/bot.py` (Telegram), line 216 redacts `response` in-place before line 220 stores it:
```python
response = self._redactor.redact(response)  # line 216
await history.add_exchange(chat_id, text, response)  # line 220 — redacted ✅
```

In `src/platform/slack.py`, `_reply()` (line 163) redacts for *display* only — it does not mutate the `response` variable. Line 357 then stores the **unredacted** response:
```python
await self._reply(client, channel, response, thread_ts)  # redacts for display only
await common.save_to_history(channel, text, response, self._settings)  # line 357 — UNREDACTED ❌
```

**This must be fixed in the implementing PR**: either redact `response` in-place before storage (matching the Telegram pattern), or have `save_to_history()` accept and apply a `SecretRedactor`.

### Redaction ordering contract

The ABC's `add_exchange()` docstring must state: *"Callers MUST redact text before calling this method. The storage layer does not perform redaction."*

Rationale: pushing redaction into the ABC would couple storage to `SecretRedactor`, violating separation of concerns. But the contract must be explicit so future callers don't repeat the Slack bug.

### Threat model — volume access

| Threat | Current | After ABC |
|--------|---------|-----------|
| Docker volume access (host compromise, shared volume, backup leak) | `history.db` is plaintext SQLite — full conversation history readable by anyone with file access | Unchanged with `SQLiteStorage` default. Mitigated by `EncryptedSQLiteStorage` adapter (see below). |
| Pre-redaction data at rest | Slack path stores raw AI responses including secrets the redactor would have scrubbed from output | Fixed by redaction ordering fix above |
| Retention compliance (GDPR Art. 17, right to erasure) | `clear_history()` deletes rows but SQLite doesn't zero freed pages — data recoverable with forensic tools | Mitigated by `VACUUM` after delete, or `ZeroRetentionStorage` adapter |
| Backup exfiltration | Volume backups contain full plaintext history | Mitigated by encryption-at-rest adapters |

### Recommended future adapters (security-motivated)

These should be documented as future extension points in the ABC design:

1. *`EncryptedSQLiteStorage`* — Uses SQLCipher (`pysqlcipher3`) for AES-256-CBC encryption at rest. Same file-local model as `SQLiteStorage` but unreadable without the key. Simplest upgrade for single-replica deployments.

2. *`ZeroRetentionStorage`* — In-memory only (`collections.deque` capped at `HISTORY_LIMIT`). History exists for context injection during the session but is never persisted to disk. For compliance-sensitive deployments. Set `history_turns > 0` for runtime context, but nothing survives a container restart.

3. *`KMSWrappedStorage`* — Wraps any persistent adapter with envelope encryption. Data encryption key (DEK) encrypted by a KMS master key (AWS KMS, GCP Cloud KMS, Azure Key Vault). DEK rotated per chat_id or per session.

### KMS key management recommendations

If a KMS adapter is implemented:

- **Never store the master key in env vars or config** — use IAM-based KMS access (instance profiles, workload identity).
- **Envelope encryption** — generate a per-session DEK, encrypt it with the KMS master key, store the encrypted DEK alongside the ciphertext. Decrypt at read time.
- **Key rotation** — support re-encrypting existing data when the master key is rotated. The ABC should expose an optional `async def rotate_key(self) -> None` method (default no-op).
- **Audit logging** — KMS calls should be logged (most cloud KMS providers do this automatically via CloudTrail / Cloud Audit Logs).
- **Minimum key size** — AES-256 for symmetric, RSA-2048+ for asymmetric wrapping.

---

## Edge Cases and Open Questions

1. **Exception swallowing** — Current module-level functions swallow all exceptions. `SQLiteStorage` must preserve this behaviour to avoid breaking the non-streaming pipeline when the DB is temporarily unavailable.
2. **Thread safety** — `aiosqlite` opens a new connection per call (current pattern). `SQLiteStorage` should do the same; do not introduce a shared connection pool without a proper lifecycle.
3. **`gate restart` interaction** — If `SQLiteStorage` holds no persistent connection (per-call pattern), `gate restart` requires no extra cleanup.
4. **`history_enabled=False`** — Callers must still skip `storage.get_history()` and `storage.add_exchange()` when this flag is `False`. The ABC does not enforce this — the caller guard must remain.
5. **Shim deprecation timeline** — The module-level shim functions (Step 1) can be removed as soon as all callers are updated in the same PR. Do not leave shims beyond the implementing PR.
6. **SQLite VACUUM after clear** — `clear()` should run `VACUUM` to zero freed pages, preventing forensic recovery of deleted history. This is a performance trade-off; document it as optional but recommended.

---

## Acceptance Criteria

- [ ] `ConversationStorage` ABC defined in `src/history.py`.
- [ ] `SQLiteStorage` implements all four abstract methods; produces identical behaviour to the old module-level functions.
- [ ] `build_context()` remains a module-level pure function.
- [ ] Old module-level shim functions removed by end of implementing PR.
- [ ] `main.py` constructs and injects `SQLiteStorage` into both platform startup paths.
- [ ] `bot.py` (`_BotHandlers`) and `slack.py` (`SlackBot`) accept `ConversationStorage` in their constructors.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `tests/contract/test_storage.py` passes and covers all ABC methods.
- [ ] `src/history.py` coverage remains at 100%.
- [ ] `.github/copilot-instructions.md` updated with `ConversationStorage` note.
- [ ] `docs/roadmap.md` item 1.3 marked done (✅).
- [ ] `docs/features/history-storage.md` status changed to `Implemented` on completion.
- [ ] `VERSION` bumped to `0.9.0` on `develop` before merge PR to `main`.
