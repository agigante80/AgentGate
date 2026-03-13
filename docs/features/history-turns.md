# Context Window Control (`HISTORY_TURNS`)

> Status: **Implemented in v0.11.0** | Priority: **High** | Last reviewed: 2026-03-13

Control how many recent SQLite conversation exchanges are injected into every AI prompt.
Setting this to `0` disables local memory injection entirely — useful when the AI backend
already has persistent session state (e.g. `AI_CLI_OPTS=--allow-all --resume=<id>`).

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both Telegram and Slack. The injection happens in `platform/common.py:build_prompt()`
   which is shared.
2. **Backend** — Stateless backends only (`copilot`, `api`). Stateful backends (`codex`,
   `is_stateful=True`) already bypass history injection; `HISTORY_TURNS` has no effect on them.
3. **Stateful vs stateless** — `build_prompt()` in `common.py` already guards with
   `if backend.is_stateful: return text`. `HISTORY_TURNS` only changes behaviour for stateless
   backends.
4. **Breaking change?** — No. Default `10` preserves existing behaviour. **MINOR** bump.
5. **New dependency?** — No.
6. **Persistence** — `HISTORY_TURNS` is a config field. The SQLite DB schema is unchanged.
   History is still stored (unless `HISTORY_ENABLED=false`); only the injection window changes.
7. **Auth** — No new secrets.
8. **Interaction with `--resume`** — When `AI_CLI_OPTS=--allow-all --resume=<id>`, the Copilot
   CLI already maintains full session history internally. Setting `HISTORY_TURNS=0` avoids
   re-injecting that same history as text, eliminating the "double context" effect.

---

## Problem Statement

1. **Fixed 10-exchange injection window** — Every AI call for a stateless backend prefixes
   the last 10 exchanges, regardless of whether the backend already has session state (via
   `--resume`) or whether the user wants a shorter/longer window.

2. **No way to disable injection without disabling storage** — `HISTORY_ENABLED=false` turns
   off both storage and injection. There is no way to keep storing history for later reference
   while not injecting it into every prompt.

3. **Double context when using `--resume`** — With `AI_CLI_OPTS=--allow-all --resume=<id>`,
   Copilot's session already holds the full conversation. The SQLite prefix causes the last
   10 exchanges to appear twice in every prompt — once from the session, once from the
   text prefix. Setting `HISTORY_TURNS=0` eliminates this redundancy cleanly.

---

## Current Behaviour (as of v0.10.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| History limit | `src/history.py:6` (`HISTORY_LIMIT`) | `HISTORY_LIMIT = 10` — module-level constant, not configurable |
| History fetch | `src/history.py:38` (`get_history`) | `async def get_history(chat_id: str) -> list[tuple[str, str]]` — no `limit` param |
| SQL query | `src/history.py:43` | `LIMIT ?` with `HISTORY_LIMIT` always — correct SQL, wrong value source |
| Prompt build | `src/platform/common.py:51–53` (`build_prompt`) | `await history.get_history(chat_id) if settings.bot.history_enabled else []` — no limit param |
| Config | `src/config.py:46` (`BotConfig`) | Only `history_enabled: bool = True` — no `history_turns` field |
| Test helper | `tests/unit/test_platform_common.py:14` (`_make_settings`) | Sets `bot.history_enabled` only — must add `bot.history_turns = 10` |
| Test helper | `tests/unit/test_bot.py:9` (`_make_settings`) | Similar — check if `history_turns` is accessed; add if needed |
| Test helper | `tests/unit/test_slack_bot.py:22` (`_make_settings`) | Same — add `bot.history_turns = 10` |

> **Key gap**: `get_history` has no `limit` parameter; `build_prompt` cannot vary the window. The SQL `LIMIT ?` already works with a variable — just needs to be wired through.

---

## Design Space

### Axis 1 — How to expose the limit

#### Option A — Module-level constant only *(status quo)*

`HISTORY_LIMIT = 10` in `history.py`. Not configurable.

**Pros:** Simple.
**Cons:** Cannot be tuned per-deployment or set to `0`.

---

#### Option B — Env var `HISTORY_TURNS` in `BotConfig` *(recommended)*

```python
# In BotConfig:
history_turns: int = Field(10, env="HISTORY_TURNS")
```

Thread through `build_prompt()` → `get_history(limit=...)`. Allow `0` to mean "do not inject".

```python
# In common.py:build_prompt():
hist = await history.get_history(chat_id, limit=settings.bot.history_turns) \
       if settings.bot.history_enabled and settings.bot.history_turns > 0 else []
```

**Pros:**
- Per-deployment control (each `.env` can set its own value).
- `0` cleanly disables injection without affecting storage.
- Non-breaking default (`10`).

**Cons:**
- Must thread `limit` through `get_history()` (minor change).

**Recommendation: Option B.**

---

#### Option C — Live `/gate context <n>` command

Allow the user to change `HISTORY_TURNS` at runtime without restart, stored in-memory.

**Pros:** No restart required to tune.
**Cons:** Adds a command handler on both platforms; value resets on restart; more complex.

> Note: Option C is a **stretch goal** for the same feature; document as future enhancement,
> implement only the env var for now.

---

### Axis 2 — Behaviour at `HISTORY_TURNS=0`

#### Option A — Treat `0` as "use default (10)"

`0` is an invalid value, silently replaced by `10`.

**Cons:** No way to disable injection.

---

#### Option B — Treat `0` as "inject nothing" *(recommended)*

`0` means the prompt is the raw user message with no history prefix.
This is the primary use case when `AI_CLI_OPTS --resume=<id>` is set.

**Pros:**
- Clean: disables the SQLite prefix without affecting storage.
- Eliminates double context when using `--resume`.

**Cons:**
- Slightly non-intuitive (`0 turns` → no history). Documented clearly.

---

### Axis 3 — Validation range

Accept `0–100`. Values above `100` are capped to `100` with a warning. Negative values
raise a `ValueError` at startup (caught by `_validate_config()`).

---

## Recommended Solution

- **Axis 1**: Option B — `HISTORY_TURNS` env var in `BotConfig`, default `10`
- **Axis 2**: Option B — `0` means inject nothing (raw prompt only)
- **Axis 3**: Accept `0–100`; reject negative values at startup

---

## Using `AI_CLI_OPTS` with `--resume` (Real-World Scenario)

The primary motivation for `HISTORY_TURNS=0` is pairing it with Copilot's `--resume` flag:

```env
# Resume a previous Copilot session — session holds full conversation context
AI_CLI_OPTS=--allow-all --resume=a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Disable SQLite injection — Copilot session is the only context source
HISTORY_TURNS=0
```

### How it works

Without `--resume`:
```
copilot -p "[last 10 exchanges]\nUser: what does auth.py do?"
→ Copilot starts a fresh session each time; SQLite window is the only context.
```

With `--resume` + `HISTORY_TURNS=10` (default):
```
copilot -p "[last 10 exchanges]\nUser: what does auth.py do?" --resume=<id>
→ Copilot session ALSO has full history internally.
→ Last 10 exchanges appear twice — mild redundancy.
```

With `--resume` + `HISTORY_TURNS=0` (recommended pairing):
```
copilot -p "what does auth.py do?" --resume=<id>
→ Copilot session is the sole context source — clean, no duplication.
```

### Pros and cons of the `--resume` + `HISTORY_TURNS=0` pairing

| Aspect | Details |
|--------|---------|
| ✅ Full continuity | AI remembers entire prior session, not just the last 10 exchanges |
| ✅ No double context | SQLite injection is off; session is the single source of truth |
| ✅ Richer context | Long-running projects keep all prior decisions, reviewed files, etc. |
| ⚠️ `gate clear` gap | `gate clear` only wipes SQLite; Copilot session persists — not a full reset |
| ⚠️ Session grows | Session file grows indefinitely; very long sessions may approach context limits |
| ⚠️ No `gate` command | Switching sessions requires editing `.env` and restarting |
| ⚠️ Local only | Sessions are stored in the `/data` volume (persisted). Synology uses prebuilt images — sessions are lost on container recreation unless the volume is preserved |

### Pros and cons of `HISTORY_TURNS=N` (non-zero values)

| Value | Behaviour | Best for |
|-------|-----------|----------|
| `0` | No injection; rely on backend session (e.g. `--resume`) | Stateful Copilot sessions |
| `1–5` | Short recent context; low token cost | Cost-sensitive API deployments |
| `10` *(default)* | Standard 10-exchange window | General use without `--resume` |
| `20–50` | Longer context for complex sessions | Deep code review or long-running tasks |
| `100` | Maximum; highest token usage | Rarely needed; prefer `--resume` for this |

---

## Architecture Notes

- **`HISTORY_LIMIT` constant** — `src/history.py:6` is a module-level constant today.
  After this feature, it becomes a fallback default only. The runtime limit comes from
  `settings.bot.history_turns`.
- **`get_history(limit=...)` is already parameterised** — the SQL query uses `LIMIT ?`;
  just wire the setting through.
- **Storage vs injection are independent** — `HISTORY_ENABLED=false` disables both.
  `HISTORY_TURNS=0` disables injection only; storage continues. This is intentional.
- **Stateful backends** — `build_prompt()` returns early for `is_stateful=True`. No change.
- **Platform symmetry** — `build_prompt()` is in `common.py` and used by both Telegram and
  Slack. A single change covers both platforms.
- **`asyncio_mode = auto`** — tests remain `async def test_*` without decorator.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `HISTORY_TURNS` | `int` | `10` | Number of recent exchanges to inject into each AI prompt. `0` = inject nothing (use when pairing with `AI_CLI_OPTS --resume`). Range: `0–100`. |

> Pair with `AI_CLI_OPTS=--allow-all --resume=<session-id>` and set `HISTORY_TURNS=0` to let
> the Copilot session be the sole context source.

---

## Implementation Steps

### Step 1 — `src/config.py`: add `history_turns` field

```python
# In BotConfig:
history_turns: int = Field(10, env="HISTORY_TURNS")
```

Add validation to `_validate_config()` in `main.py`:

```python
if settings.bot.history_turns < 0:
    raise ValueError("HISTORY_TURNS must be >= 0")
if settings.bot.history_turns > 100:
    logger.warning("HISTORY_TURNS=%d exceeds 100; capping to 100", settings.bot.history_turns)
    # cap is applied at usage time, not here, to keep Settings immutable
```

---

### Step 2 — `src/history.py`: thread `limit` through `get_history()`

```python
async def get_history(chat_id: str, limit: int = HISTORY_LIMIT) -> list[tuple[str, str]]:
    if limit == 0:
        return []
    try:
        capped = min(limit, 100)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_msg, ai_msg FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, capped),
            ) as cur:
                rows = await cur.fetchall()
        return list(reversed(rows))
    except Exception:
        logger.exception("Failed to load history for chat %s", chat_id)
        return []
```

---

### Step 3 — `src/platform/common.py`: pass `limit` from settings

Current `build_prompt` (line 51):
```python
hist = (
    await history.get_history(chat_id) if settings.bot.history_enabled else []
)
```

Replace with:
```python
turns = settings.bot.history_turns
hist = (
    await history.get_history(chat_id, limit=turns)
    if settings.bot.history_enabled and turns > 0
    else []
)
```

### Step 4 — Update test helpers for the new `history_turns` field

In `tests/unit/test_platform_common.py`, `_make_settings()` builds a `MagicMock(spec=BotConfig)` and sets `bot.history_enabled`. Add:
```python
bot.history_turns = 10  # default; set to 0 in tests that need it
```

In `tests/unit/test_bot.py` and `tests/unit/test_slack_bot.py`, the same pattern applies — add `bot.history_turns = 10` to the `_make_settings()` helpers there too. Run tests first without this change to see which tests fail (if `spec=BotConfig` is used, accessing `.history_turns` before it's set will raise `AttributeError`).

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `history_turns: int = Field(10, env="HISTORY_TURNS")` to `BotConfig` |
| `src/history.py` | **Edit** | Add `limit` param to `get_history()`; short-circuit on `limit == 0`; cap at 100 |
| `src/platform/common.py` | **Edit** | Pass `settings.bot.history_turns` as `limit` to `get_history()` in `build_prompt()` |
| `src/main.py` | **Edit** | Add validation for `history_turns` in `_validate_config()` |
| `README.md` | **Edit** | Add `HISTORY_TURNS` env var row; add `AI_CLI_OPTS` scenario with pros/cons |
| `tests/unit/test_history.py` | **Edit** | Add tests for `limit=0`, `limit=5`, `limit=100` |
| `tests/unit/test_platform_common.py` | **Edit** | Add `bot.history_turns = 10` to `_make_settings()`; add `HISTORY_TURNS=0` test |
| `tests/unit/test_bot.py` | **Edit** | Add `bot.history_turns = 10` (or param) to `_make_settings()` mock if `spec=BotConfig` is used |
| `tests/unit/test_slack_bot.py` | **Edit** | Same as `test_bot.py` |
| `docs/roadmap.md` | **Edit** | Mark `2.10` priority High; update description |
| `docs/features/history-turns.md` | **Edit** | Change status to `Implemented` after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `aiosqlite` | ✅ Already installed | No change to DB schema |

---

## Test Plan

### `tests/unit/test_history.py` additions to `TestHistoryDB`

The `test_history_limit_respected` test already exists and calls `get_history("chat1")` without a limit. After this feature, it verifies the default `HISTORY_LIMIT` still applies. Add these new tests:

```python
async def test_get_history_custom_limit(self):
    """limit=5 returns at most 5 rows even if more exist."""
    await history_module.init_db()
    for i in range(8):
        await history_module.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await history_module.get_history("chat1", limit=5)
    assert len(rows) == 5

async def test_get_history_zero_returns_empty(self):
    """limit=0 returns [] without querying the DB."""
    await history_module.init_db()
    await history_module.add_exchange("chat1", "q", "a")
    rows = await history_module.get_history("chat1", limit=0)
    assert rows == []

async def test_get_history_cap_at_100(self):
    """limit=200 is treated as 100 (cap enforced)."""
    await history_module.init_db()
    for i in range(15):
        await history_module.add_exchange("chat1", f"q{i}", f"a{i}")
    rows = await history_module.get_history("chat1", limit=200)
    # Only 15 exchanges stored; cap doesn't reduce this, just limits the SQL LIMIT
    assert len(rows) == 15  # fewer than cap, so all are returned
```

### `tests/unit/test_platform_common.py` additions

The `_make_settings()` helper uses `MagicMock(spec=BotConfig)` and sets `bot.history_enabled`. After this feature, `build_prompt()` also accesses `bot.history_turns`. Add to `_make_settings()`:

```python
def _make_settings(history_enabled=True, history_turns=10, ...):
    bot = MagicMock(spec=BotConfig)
    bot.history_enabled = history_enabled
    bot.history_turns = history_turns
    ...
```

Add test:
```python
async def test_build_prompt_turns_zero_no_history_prefix(self):
    """HISTORY_TURNS=0: build_prompt returns raw text without any history prefix."""
    settings = _make_settings(history_enabled=True, history_turns=0)
    backend = _make_backend(is_stateful=False)
    result = await build_prompt("hello", "chat1", settings, backend)
    assert result == "hello"
    assert "<HISTORY>" not in result
```

---

## Documentation Updates

### `README.md`

Add to environment variables table:

```markdown
| `HISTORY_TURNS` | `10` | Number of past exchanges injected into each AI prompt. Set `0` to disable injection (recommended when using `AI_CLI_OPTS --resume`). Range: 0–100. |
| `AI_CLI_OPTS` | _(empty)_ | Extra flags passed to the AI CLI subprocess. Replaces the default `--allow-all`. Example: `--allow-all --resume=a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
```

Add a dedicated section (e.g. under "Tips"):

```markdown
### Resuming a previous Copilot session

You can pick up a previous Copilot conversation across bot restarts by setting:

```env
AI_CLI_OPTS=--allow-all --resume=a1b2c3d4-e5f6-7890-abcd-ef1234567890
HISTORY_TURNS=0
```

The session ID (`--resume=...`) refers to a Copilot session stored in the `/data/.copilot/session-state/` directory (persisted across restarts via the `/data` volume).

Setting `HISTORY_TURNS=0` prevents AgentGate from prepending its own SQLite history — the Copilot session already holds the full conversation, so injecting it again would be redundant.

**Pros:** Full session continuity; AI remembers the complete prior conversation.
**Cons:** `gate clear` only wipes the SQLite history, not the Copilot session. To start completely fresh, remove `AI_CLI_OPTS` from your `.env` and restart.
```

### `docs/roadmap.md`

Update entry `2.10`: mark priority **High** and update description to mention `0` and `--resume`.

---

## Version Bump

New env var with a safe default of `10` (preserves existing behaviour). **MINOR** bump.

**Expected bump**: `0.10.0` (coordinate with other Slack delivery features)

---

## Security Considerations

1. **Interaction with prompt injection hardening (1.6)** — When `HISTORY_TURNS > 0`, `build_context()` wraps the history block in `<HISTORY>…</HISTORY>` framing tags (added in feature 1.6). This framing is preserved because `build_prompt()` calls `history.build_context(hist, text)` regardless of `turns` value. When `HISTORY_TURNS=0`, no history is injected and no framing tags are emitted — which is correct (no history = no injection surface to frame).

2. **SQL LIMIT safety** — The `LIMIT ?` in `get_history()` is parameterised (no SQL injection). Negative values are rejected at startup by `_validate_config()`. Even if bypassed programmatically, `min(limit, 100)` caps the query and SQLite treats negative `LIMIT` as returning zero rows — no data leakage.

3. **No new secrets exposure** — `HISTORY_TURNS` is a plain integer config field. History content (which may contain sensitive data) is already stored in SQLite and redacted on output by the `SecretRedactor` (feature 1.7). This feature does not change what is stored, only how much is *injected*.

---

## Edge Cases and Open Questions

1. **`HISTORY_TURNS=0` + `HISTORY_ENABLED=true`** — History is still stored to SQLite;
   only injection is disabled. This is intentional and the main value of `0`.

2. **`HISTORY_TURNS=0` without `--resume`** — The AI gets no context from prior exchanges.
   Each message is effectively stateless. Acceptable; the user chose this.

3. **`HISTORY_TURNS` > number of stored exchanges** — `get_history()` returns however many
   exist (could be 0–N). No error; the SQL `LIMIT` is an upper bound.

4. **`gate clear` interaction** — Clears SQLite. If `HISTORY_TURNS=0` and `--resume` is set,
   `gate clear` has no effect on the Copilot session. Document this limitation clearly.

5. **Stateful backend + `HISTORY_TURNS`** — `build_prompt()` returns early for stateful
   backends. `HISTORY_TURNS` is silently ignored. No error.

6. **`gate restart` interaction** — `gate restart` recreates the AI backend. The env-var-based
   `history_turns` setting is re-read from `settings` (which is stable). No issue.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` updated: `HISTORY_TURNS` env var row + `AI_CLI_OPTS --resume` scenario section.
- [ ] `docs/roadmap.md` entry `2.10` updated (priority High, description updated).
- [ ] `docs/features/history-turns.md` status changed to `Implemented` after merge.
- [ ] `VERSION` file bumped.
- [ ] Default `HISTORY_TURNS=10` preserves current behaviour exactly (regression test).
- [ ] `HISTORY_TURNS=0` with `HISTORY_ENABLED=true` stores exchanges but injects none.
- [ ] `HISTORY_TURNS=0` + `AI_CLI_OPTS --resume` pairs cleanly (no double context).
- [ ] Negative value raises `ValueError` at startup.

