# Request Cancellation (`gate cancel`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-15

Allow users to cancel an in-progress AI request from Telegram or Slack without waiting for it
to finish or restarting the container. A `gate cancel` text command and an optional Slack
Block Kit "Cancel" button interrupt the running pipeline cleanly and notify the user.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/request-cancellation.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 6/10 | 2026-03-15 | 6 blockers/gaps — see R1 findings below |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ In review — GateCode R1 findings must be addressed before GateSec/GateDocs rounds

### GateCode R1 Findings (2026-03-15)

**Score: 6/10** — Solid structure and threat analysis, but six implementation gaps prevent direct handoff to code.

#### 🔴 Blocker 1 — `CodexBackend.is_stateful` is `False`, not `True`

Prerequisite Q3 and Architecture Notes both say "Stateful backends (CodexBackend, DirectAPIBackend)". This is factually wrong. `CodexBackend` never sets `is_stateful`; it inherits the default `False` from `AICLIBackend` (confirmed in `src/ai/codex.py` — no `is_stateful` override). Consequence: the history-inconsistency risk in Edge Case 2 does not apply to CodexBackend. The spec's argument for calling `backend.clear_history()` after cancel only applies to `DirectAPIBackend`. Fix: correct every occurrence of "CodexBackend is stateful" throughout the spec.

#### 🔴 Blocker 2 — `_handle_cancel` undefined for Slack text command

Step 3h adds `"cancel": self._handle_cancel` to the Slack `_dispatch` table, but `_handle_cancel` is never defined anywhere in the spec. Only `_on_cancel_ai` (the Block Kit button handler) is specced. The Slack text-command path needs its own `_cmd_cancel` (or `_handle_cancel`) method with code sample, analogous to the Telegram `cmd_cancel` in Step 2d.

#### 🔴 Blocker 3 — `_KNOWN_SUBS` not updated (critical routing bug)

`_KNOWN_SUBS` (slack.py line 69) is the gating set — only subcommands in it are routed to `_dispatch()`. If `"cancel"` is absent from `_KNOWN_SUBS`, `gate cancel` falls through to the AI pipeline instead of the cancel handler. The spec's Files table and Step 3 do not mention updating `_KNOWN_SUBS`. Add `"cancel"` to the set and document it explicitly.

#### 🔴 Blocker 4 — `asyncio.TimeoutError` handler not updated for `shield` (correctness bug)

Open Question 7 correctly identifies that with `asyncio.shield(ai_task)` in the pipeline, an `AI_TIMEOUT_SECS` expiry cancels only the shield future — the underlying `ai_task` keeps running. OQ7 says "the timeout path should call `_cancel_active_task()` too." But Step 2c's code sample does not update the `except asyncio.TimeoutError` block. The existing handler just returns:
```python
except asyncio.TimeoutError:
    await msg.edit_text(f"⚠️ Request cancelled after {cfg.ai_timeout_secs}s. ...")
    return  # ← ai_task is still running!
```
With shield in place, `return` here leaks the task. The implementation step must show the updated `TimeoutError` handler calling `await self._cancel_active_task(chat_id)` (or at minimum `ai_task.cancel()`). Mirror fix required in `slack.py`.

#### 🟡 Gap 5 — `asyncio.ensure_future` in Step 2c should be `asyncio.create_task`

Step 2c uses `asyncio.ensure_future(...)`. The entire codebase uses `asyncio.create_task(...)`. `ensure_future` is deprecated for coroutines in Python 3.10+. Change to `create_task` for consistency.

#### 🟡 Gap 6 — Streaming path (Step 4) has no code sample

Step 4 says "mirror the task tracking in the streaming helpers" and calls it "the most complex part." But it provides zero code. The key challenge: `_stream_to_telegram` is a module-level function — it cannot access `self._active_tasks`. The refactor belongs in the *caller* inside `_run_ai_pipeline`:
```python
# In _run_ai_pipeline streaming branch:
stream_task = asyncio.create_task(
    _stream_to_telegram(update, self._backend, prompt, ...)
)
self._active_tasks[chat_id] = stream_task
try:
    response = await asyncio.wait_for(asyncio.shield(stream_task), timeout=... or None)
except asyncio.CancelledError:
    await update.effective_message.reply_text("⚠️ Request cancelled.")
    return
except asyncio.TimeoutError:
    await self._cancel_active_task(chat_id)
    return
finally:
    self._active_tasks.pop(chat_id, None)
```
Add a code sample for both platforms and add streaming-specific tests to the Test Plan:
- `test_cancelled_error_during_streaming_sends_user_message`
- `test_inflight_guard_rejects_while_streaming`

#### ℹ️ Minor — `test_close_is_callable_on_all_backends` is already guaranteed by the ABC

`close()` is defined on `AICLIBackend` with a default no-op body — it is always callable. This contract test adds no signal. Replace with `test_cancel_calls_backend_close` (verify `backend.close()` is invoked after cancel regardless of backend type).

#### ℹ️ Minor — Edge Case 2 (`clear_history` after cancel) left open

The spec proposes calling `backend.clear_history()` after cancel but ends with "Needs confirmation." `_cancel_active_task()` in Step 2b does not call it. Make a decision and close the OQ: either add the call to the implementation step, or explicitly document "user must run `gate clear` to reset history" as the accepted trade-off.
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both Telegram and Slack. The Telegram `/cancel` command and `gate cancel` prefix
   form, plus Slack `gate cancel` text command and an optional Block Kit "Cancel" button injected
   into the "Thinking…" message.
2. **Backend** — All backends (`copilot`, `codex`, `api`). The cancellation mechanism targets the
   asyncio Task wrapping the backend call, not the backend API directly, so it is backend-agnostic.
3. **Stateful vs stateless** — Stateful backends (`CodexBackend`, `DirectAPIBackend`) may have
   inconsistent in-memory history after a mid-flight cancel (the prompt was sent but the reply was
   never stored). The spec addresses this in Edge Cases (item 2).
4. **Breaking change?** — No. New command and new config var with a safe default. MINOR bump.
5. **New dependency?** — No. Pure `asyncio` — no new packages required.
6. **Persistence** — No new DB table or file. Task registry is an in-memory dict keyed by
   `chat_id` / Slack `channel`, discarded on container restart (acceptable — in-flight tasks
   are also gone on restart).
7. **Auth** — No new secret. The cancel command goes through the existing `@_requires_auth`
   guard (Telegram) and `self._is_allowed()` check (Slack).
8. **Race condition** — Cancel command may arrive after the task has already completed. The
   per-chat task dict entry must be checked for completion state before acting (see Edge Cases).

---

## Problem Statement

1. **No escape hatch** — Once `gate <prompt>` is sent, the user has no way to stop the AI call
   short of restarting the container, which affects all users of that deployment.
2. **Hanging requests** — Long-running AI calls (slow LLM, stuck subprocess, large Copilot
   session) can block the channel for minutes. `AI_TIMEOUT_SECS` provides a hard ceiling but
   it is coarse and not user-controlled.
3. **Wasted compute** — A user who sent the wrong prompt must wait the full timeout before
   re-sending the correct one; the backend subprocess may already be generating an irrelevant
   multi-minute response.
4. **No per-chat isolation** — There is no per-`chat_id` task handle stored; even if a cancel
   command existed, there would be nothing to cancel.
5. **Slack UX gap** — Confirmations for shell commands already use a Block Kit "Cancel" button
   (`_on_cancel_run`). The "Thinking…" placeholder for AI calls has no equivalent button.

---

## Current Behaviour (as of v`0.18.x`)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Telegram pipeline | `src/bot.py:254–315` (`_run_ai_pipeline`) | Spawns `thinking_ticker` as `asyncio.create_task`, then awaits `asyncio.wait_for(backend.send(), timeout=ai_timeout_secs)`. No per-chat task handle stored. |
| Slack pipeline | `src/platform/slack.py:410–493` (`_run_ai_pipeline`) | Identical pattern to Telegram. No per-chat task handle stored. |
| Ticker start/cancel | `src/bot.py:283–308`, `src/platform/slack.py:438–469` | `ticker = asyncio.create_task(thinking_ticker(...))`. Cancelled in `finally` block via `ticker.cancel()` + `suppress(CancelledError)`. |
| Thinking ticker | `src/platform/common.py:26–57` (`thinking_ticker`) | Async background task; sleeps `slow_threshold` seconds then edits the "Thinking…" message on a loop. Cancelled externally. |
| Timeout path | `src/bot.py:299–308`, `src/platform/slack.py:454–469` | `asyncio.TimeoutError` caught, user notified, returns. No user-initiated cancel path. |
| Shell cancel | `src/platform/slack.py:966–979` (`_on_cancel_run`) | Handles Block Kit `cancel_run` action for *shell confirmations only* — not for AI pipeline cancellation. |
| Config | `src/config.py` (`BotConfig`) | `ai_timeout_secs: int = 0` (no timeout). No cancel-related field. |
| Backend cleanup | `src/ai/copilot.py:34–39`, `src/ai/direct.py:45–46` | `CopilotSession.close()` is a no-op (fresh subprocess per call). `DirectAPIBackend.clear_history()` clears `self._messages`. No mid-flight HTTP/process kill. |
| Shell execution | `src/executor.py:49–61` (`run_shell`) | Uses `asyncio.create_subprocess_shell` + `proc.communicate()`. Awaitable and cancellable; subprocess is orphaned (not killed) on cancellation unless caller does `proc.kill()`. |

> **Key gap**: There is no per-chat asyncio Task handle stored anywhere. A user-initiated
> `gate cancel` command has nothing to target; the only cancellation today is a coarse hard
> timeout (`AI_TIMEOUT_SECS`) that fires automatically.

---

## Design Space

### Axis 1 — Where to store the per-chat task handle

#### Option A — Dict on the handler/bot instance *(recommended)*

Store a `dict[str, asyncio.Task]` (keyed by `chat_id` / Slack `channel`) as an instance
attribute on `_BotHandlers` (Telegram) and `SlackBot` (Slack).

```python
# In _BotHandlers.__init__:
self._active_tasks: dict[str, asyncio.Task] = {}

# In _run_ai_pipeline, before awaiting the AI:
task = asyncio.create_task(backend.send(prompt))
self._active_tasks[chat_id] = task
try:
    response = await asyncio.wait_for(asyncio.shield(task), timeout=...)
finally:
    self._active_tasks.pop(chat_id, None)
    ticker.cancel()
```

**Pros:**
- Zero external state — no DB, no file, no new module.
- Naturally scoped per deployment (each container is one bot instance).
- Trivially thread-safe: asyncio event loop is single-threaded; dict mutations do not race.

**Cons:**
- Lost on container restart (acceptable — the task is also gone).
- Only one in-flight task per `chat_id` (see Axis 2).

---

#### Option B — Separate `TaskRegistry` class

Wrap the dict in a small `src/task_registry.py` module with methods `register()`, `cancel()`, `get()`.

**Pros:**
- Testable in isolation; auditable.

**Cons:**
- Overkill for a single dict — adds a new module with no extra behaviour vs Option A.

**Recommendation: Option A** — Simple dict on the existing instance; no new module needed at this stage.

---

### Axis 2 — What happens when a new prompt arrives while one is in-flight?

#### Option A — One active task per chat (cancel-on-new) *(not recommended)*

Auto-cancel the previous task when a new prompt arrives.

**Cons:** Silent cancellation surprises users; violates principle of least surprise.

---

#### Option B — Reject the new prompt *(recommended)*

Return a user-facing message: "⏳ A request is already in progress. Use `gate cancel` to stop it."

```python
if chat_id in self._active_tasks and not self._active_tasks[chat_id].done():
    await update.effective_message.reply_text(
        "⏳ A request is already in progress. Use `gate cancel` to stop it."
    )
    return
```

**Pros:** Explicit user control; no surprise side effects.

**Recommendation: Option B** — Reject, don't auto-cancel.

---

### Axis 3 — Slack "Cancel" button in the "Thinking…" message

#### Option A — Text command only (`gate cancel`)

No Block Kit changes; user types `gate cancel` to interrupt.

**Pros:** Minimal change.
**Cons:** Worse Slack UX — the "Thinking…" message sits there with no affordance.

---

#### Option B — Inject a "Cancel" button into the "Thinking…" Block Kit message *(recommended)*

When the non-streaming "Thinking…" placeholder is posted, attach a Block Kit button with
`action_id: "cancel_ai"`. Register a new `_on_cancel_ai` action handler alongside the
existing `_on_cancel_run`.

```python
# _THINKING_BLOCKS with cancel button:
_THINKING_BLOCKS = [
    {"type": "section", "text": {"type": "mrkdwn", "text": "🤖 Thinking…"}},
    {"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "❌ Cancel"},
         "style": "danger", "action_id": "cancel_ai"}
    ]},
]
```

When the AI response arrives, replace the blocks with the answer (existing `_edit()` flow);
the Cancel button disappears naturally.

**Pros:** Consistent Slack UX with shell confirm/cancel buttons. No new text command required,
though `gate cancel` text command still works.
**Cons:** Must remove/replace blocks when the task completes normally (otherwise a stale
"Cancel" button lingers). Need a new `action_id` to avoid collision with `cancel_run`.

**Recommendation: Option B** — Inject Cancel button; use `action_id: "cancel_ai"`.

---

### Axis 4 — Graceful cancellation and subprocess cleanup

#### Option A — asyncio cancel only (no subprocess kill)

`task.cancel()` sends `CancelledError` into the awaited coroutine. For `DirectAPIBackend`
(HTTP call), the aiohttp/httpx request is cancelled cleanly. For `CopilotBackend`, the
session spawns a fresh process per call, so the orphaned process will finish on its own
(short-lived). For `CodexBackend` (persistent PTY), the process is not killed.

**Cons:** CodexBackend subprocess may continue running, consuming CPU.

---

#### Option B — asyncio cancel + subprocess kill with `CANCEL_TIMEOUT_SECS` *(recommended)*

After `task.cancel()`, wait up to `CANCEL_TIMEOUT_SECS` (default `5`) for the task to
finish. If the backend has an active subprocess, call `backend.close()` explicitly.

```python
async def _cancel_active_task(self, chat_id: str) -> bool:
    task = self._active_tasks.get(chat_id)
    if task is None or task.done():
        return False
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(asyncio.shield(task), timeout=self._settings.bot.cancel_timeout_secs)
    self._backend.close()  # kill subprocess if any
    return True
```

**Pros:** Cleaner resource cleanup, especially for CodexBackend.
**Cons:** `backend.close()` is a blunt instrument — it kills the PTY for *all* users of
that backend instance, not just this chat. Acceptable for the single-tenant deployment model.

**Recommendation: Option B** — cancel + `backend.close()` + `CANCEL_TIMEOUT_SECS`.

---

## Recommended Solution

- **Axis 1**: Option A — in-memory dict `self._active_tasks` on the bot/handler instance.
- **Axis 2**: Option B — reject new prompts while one is in-flight.
- **Axis 3**: Option B — Slack Block Kit "Cancel" button (`action_id: "cancel_ai"`) + `gate cancel` text command.
- **Axis 4**: Option B — asyncio cancel + `backend.close()` + `CANCEL_TIMEOUT_SECS`.

```
User sends prompt
  └─ _run_ai_pipeline(chat_id)
       ├─ Guard: is chat_id in _active_tasks (not done)? → "request in progress" reply
       ├─ Post "Thinking…" (+ Cancel button on Slack)
       ├─ ticker = create_task(thinking_ticker(...))
       ├─ ai_task = create_task(backend.send(prompt) or backend.stream(prompt))
       ├─ _active_tasks[chat_id] = ai_task
       ├─ try: response = await asyncio.wait_for(asyncio.shield(ai_task), timeout=...)
       │    └─ CancelledError → edit message to "⚠️ Request cancelled." → return
       └─ finally: _active_tasks.pop(chat_id); ticker.cancel(); [remove Slack Cancel button]

User sends "gate cancel" (or clicks Slack Cancel button)
  └─ cmd_cancel(chat_id)
       ├─ Lookup task = _active_tasks.get(chat_id)
       ├─ If None or done → "No request in progress."
       └─ Else: task.cancel(); await shield(task) up to CANCEL_TIMEOUT_SECS;
                backend.close(); audit.record(..., status="cancelled")
                → "⚠️ Request cancelled."
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = True`.
  History injection in `platform/common.py:build_prompt()` only runs for stateless backends.
  This feature must respect that boundary.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode `/repo` or `/data/history.db`.
- **Platform symmetry** — every change to `_run_ai_pipeline` in `src/bot.py` must be mirrored
  in `src/platform/slack.py`. The `_active_tasks` dict and `_cancel_active_task()` helper should
  live on each class separately (they are already separate classes, not a shared base).
- **Auth guard** — `cmd_cancel` in Telegram must be decorated with `@_requires_auth`. The Slack
  `_on_cancel_ai` action handler must call `self._is_allowed(channel, user_id)` early.
- **`asyncio.shield(task)` vs raw `await task`** — use `asyncio.shield(task)` inside
  `asyncio.wait_for()` so that a timeout cancels only the wait, not the underlying task. The
  task is then explicitly cancelled in the cancel path. This prevents double-cancel.
- **Slack `action_id` collision** — `cancel_run` is already registered for shell confirmations.
  Use `cancel_ai` for the new AI-pipeline cancel button to avoid routing conflicts.
- **Single-tenant model** — `backend.close()` kills the subprocess for the entire bot instance.
  This is acceptable because each AgentGate container is one project / one bot. Document this
  explicitly in config as a known trade-off.
- **asyncio_mode = auto** — all `async def test_*` functions in `tests/` run without
  `@pytest.mark.asyncio`.
- **Streaming path** — `_stream_to_telegram` and `_stream_to_slack` also need task tracking and
  cancel handling. The streaming helper must store the task in `_active_tasks` the same way as
  the non-streaming path. This is not optional — a cancel command while streaming must work.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `CANCEL_TIMEOUT_SECS` | `int` | `5` | Grace period in seconds to wait for the AI task to acknowledge cancellation before calling `backend.close()`. Range: 1–60. |

---

## Implementation Steps

### Step 1 — `src/config.py`: add `cancel_timeout_secs` to `BotConfig`

```python
# In BotConfig:
cancel_timeout_secs: int = Field(5, env="CANCEL_TIMEOUT_SECS")
# Grace period after task.cancel() before backend.close() is called. Range: 1-60.
```

---

### Step 2 — `src/bot.py`: per-chat task tracking + `cmd_cancel` (Telegram)

**2a.** Add `_active_tasks` dict to `_BotHandlers.__init__`:

```python
self._active_tasks: dict[str, asyncio.Task] = {}
```

**2b.** Add `_cancel_active_task()` private helper:

```python
async def _cancel_active_task(self, chat_id: str) -> bool:
    """Cancel the active AI task for chat_id. Returns True if a task was cancelled."""
    task = self._active_tasks.get(chat_id)
    if task is None or task.done():
        return False
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(
            asyncio.shield(task),
            timeout=self._settings.bot.cancel_timeout_secs,
        )
    self._backend.close()
    return True
```

**2c.** In `_run_ai_pipeline` (non-streaming path), after building the prompt and before posting
"Thinking…":

```python
# Reject if already in-flight
if chat_id in self._active_tasks and not self._active_tasks[chat_id].done():
    await update.effective_message.reply_text(
        "⏳ A request is already in progress. Use `gate cancel` to stop it."
    )
    return

# ... post "Thinking…" message, create ticker ...

ai_task = asyncio.ensure_future(
    self._backend.send(prompt) if not self._settings.bot.stream_responses else ...
)
self._active_tasks[chat_id] = ai_task
try:
    response = await asyncio.wait_for(
        asyncio.shield(ai_task),
        timeout=cfg.ai_timeout_secs if cfg.ai_timeout_secs > 0 else None,
    )
except asyncio.CancelledError:
    await msg.edit_text("⚠️ Request cancelled.")
    return
finally:
    self._active_tasks.pop(chat_id, None)
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

**2d.** Add `cmd_cancel` handler:

```python
@_requires_auth
async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle `gate cancel` — cancel the in-progress AI request for this chat."""
    chat_id = str(update.effective_chat.id)
    cancelled = await self._cancel_active_task(chat_id)
    msg = "⚠️ Request cancelled." if cancelled else "ℹ️ No request in progress."
    await update.effective_message.reply_text(msg)
    await self._audit.record(
        platform="telegram", chat_id=chat_id,
        user_id=str(update.effective_user.id),
        action="cancel", status="cancelled" if cancelled else "no_op",
    )
```

**2e.** Register `cmd_cancel` in the prefix dispatch table:

```python
"cancel": self.cmd_cancel,
```

---

### Step 3 — `src/platform/slack.py`: mirror for Slack

**3a.** Add `_active_tasks: dict[str, asyncio.Task] = {}` to `SlackBot.__init__`.

**3b.** Add `_cancel_active_task()` (same logic as Step 2b, adapted for Slack).

**3c.** In `_run_ai_pipeline`, add in-flight guard and task registration (mirror of Step 2c).

**3d.** Add `_THINKING_BLOCKS` with embedded Cancel button:

```python
_THINKING_BLOCKS = [
    {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "🤖 Thinking…"},
    },
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "❌ Cancel"},
                "style": "danger",
                "action_id": "cancel_ai",
                "value": "cancel",
            }
        ],
    },
]
```

**3e.** Post thinking placeholder with blocks; in `finally`, replace with plain text (removes button):

```python
# On normal completion or timeout — strip blocks:
await client.chat_update(channel=channel, ts=ts, text=response, blocks=[])
```

**3f.** Add `_on_cancel_ai` action handler:

```python
async def _on_cancel_ai(self, ack, body, client) -> None:
    await ack()
    channel = body["channel"]["id"]
    user_id = body.get("user", {}).get("id")
    if not self._is_allowed(channel, user_id):
        return
    cancelled = await self._cancel_active_task(channel)
    msg = "⚠️ Request cancelled." if cancelled else "ℹ️ No request in progress."
    await self._reply(client, channel, msg)
    await self._audit.record(
        platform="slack", chat_id=channel, user_id=user_id,
        action="cancel", status="cancelled" if cancelled else "no_op",
    )
```

**3g.** Register the new action handler in `_register_handlers()`:

```python
self._app.action("cancel_ai")(self._on_cancel_ai)
```

**3h.** Add `"cancel"` to the Slack prefix dispatch table (text command path):

```python
"cancel": self._handle_cancel,
```

---

### Step 4 — Streaming path (`_stream_to_telegram` / `_stream_to_slack`)

Mirror the task tracking and cancel guard in the streaming helpers. The streaming coroutine
must also be wrapped in a Task stored in `_active_tasks[chat_id]`, and `CancelledError` must
be caught to produce the user-facing "⚠️ Request cancelled." message.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `cancel_timeout_secs: int = Field(5, env="CANCEL_TIMEOUT_SECS")` to `BotConfig` |
| `src/bot.py` | **Edit** | Add `_active_tasks` dict, `_cancel_active_task()`, `cmd_cancel`, in-flight guard in `_run_ai_pipeline`, `CancelledError` handling, dispatch registration |
| `src/platform/slack.py` | **Edit** | Mirror all of the above; add `_THINKING_BLOCKS` with Cancel button; add `_on_cancel_ai` handler; register `cancel_ai` action |
| `README.md` | **Edit** | Feature bullet, `CANCEL_TIMEOUT_SECS` env var row, `gate cancel` command row |
| `docs/features/request-cancellation.md` | **Edit** | Mark `Implemented` on merge |
| `docs/roadmap.md` | **Edit** | Mark done on merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `asyncio` | ✅ stdlib | No new packages. `asyncio.create_task`, `asyncio.shield`, `asyncio.wait_for` all available. |

---

## Test Plan

### `tests/unit/test_cancel.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_cancel_active_task_cancels_and_returns_true` | `_cancel_active_task` returns `True` when a pending task exists |
| `test_cancel_no_active_task_returns_false` | Returns `False` when `_active_tasks` is empty |
| `test_cancel_completed_task_returns_false` | Returns `False` when task is already done |
| `test_cancel_calls_backend_close` | `backend.close()` is called after task cancellation |
| `test_inflight_guard_rejects_second_prompt` | Second `forward_to_ai` call while task in-flight returns "in progress" message |
| `test_cancelled_error_sends_user_message` | `CancelledError` in pipeline → "⚠️ Request cancelled." edit |
| `test_cancel_timeout_secs_respected` | `CANCEL_TIMEOUT_SECS=1` → `asyncio.wait_for` timeout ≤ 1s |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_cmd_cancel_no_task` | `gate cancel` with no in-flight task → "No request in progress." |
| `test_cmd_cancel_with_task` | `gate cancel` with in-flight task → task cancelled, "⚠️ Request cancelled." |
| `test_cmd_cancel_auth` | Unauthenticated user → rejected by `@_requires_auth` |

### `tests/unit/test_slack.py` additions

| Test | What it checks |
|------|----------------|
| `test_on_cancel_ai_no_task` | Block Kit `cancel_ai` action with no in-flight task → "No request in progress." |
| `test_on_cancel_ai_with_task` | Block Kit `cancel_ai` → task cancelled, message updated |
| `test_on_cancel_ai_unallowed_user` | `_is_allowed()` returns False → silently returns |
| `test_thinking_blocks_contain_cancel_button` | `_THINKING_BLOCKS` has `action_id: cancel_ai` |

### `tests/contract/test_backends.py` additions

| Test | What it checks |
|------|----------------|
| `test_close_is_callable_on_all_backends` | All backends expose a `close()` method (existing contract, already true) |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing`. Target: all branches of
`_cancel_active_task()`, `cmd_cancel`, and `_on_cancel_ai` covered. The
`backend.close()` call after timeout has a near-impossible race; mark with
`# pragma: no cover` if needed with a one-line explanation.

---

## Documentation Updates

### `README.md`

1. **Features bullet** — `🛑 Request cancellation — stop an in-progress AI call with \`gate cancel\``
2. **Env var row** — `| \`CANCEL_TIMEOUT_SECS\` | \`5\` | Seconds to wait for graceful cancel before forcing backend close. |`
3. **Commands table** — `| \`gate cancel\` | Cancel the current in-progress AI request for this chat/channel. |`

### `.env.example` and `docker-compose.yml.example`

> Per the `docs-align-sync` contract: only the most important/non-obvious vars go in example
> files. `CANCEL_TIMEOUT_SECS` has a sensible default (`5`) and is rarely changed — *omit
> from example files*. It is fully documented in `README.md`.

### `docs/roadmap.md`

- Mark entry ✅ once merged to `main`.

### `docs/features/request-cancellation.md`

- Change `Status: **Planned**` → `Status: **Implemented**` on merge.
- Add `Implemented in: v0.19.0` below the status line.

---

## Version Bump

| This feature… | Bump |
|---------------|------|
| Adds `gate cancel` command, `CANCEL_TIMEOUT_SECS` env var with safe default, no removals | **MINOR** |

**Expected bump**: `0.18.0` → `0.19.0`

---

## Edge Cases and Open Questions

1. **Race: cancel arrives after task completes** — `task.done()` returns `True`; the guard in
   `_cancel_active_task()` returns `False` without calling `task.cancel()`. User receives
   "ℹ️ No request in progress." This is correct. No explicit handling needed beyond the `done()`
   check.

2. **Stateful backend history consistency** — If `CodexBackend` or `DirectAPIBackend` receives a
   prompt but the reply is cancelled mid-flight, the in-memory history may be in an inconsistent
   state (prompt logged, reply missing). Proposed answer: after cancellation, call
   `backend.clear_history()` in addition to `backend.close()`. This ensures the next prompt
   starts from a known state. Needs confirmation: is this the desired UX, or should the user
   decide via `gate clear`?

3. **Slack Cancel button stale after container restart** — If the container restarts while a
   "Thinking…" message with a Cancel button is visible in Slack, clicking the button will trigger
   `_on_cancel_ai` with an empty `_active_tasks` dict, returning "No request in progress." This
   is correct graceful behaviour. No action needed.

4. **`gate restart` interaction** — `gate restart` replaces the container process. Any in-flight
   `asyncio.Task` in `_active_tasks` is killed by the OS. No explicit cleanup needed — the dict
   is in-memory and discarded. The "Thinking…" Slack message will linger with a stale Cancel
   button (see item 3 above).

5. **Slack thread scope** — The "⚠️ Request cancelled." reply from a Block Kit button click
   should be posted to the same channel (not a thread), matching the current behaviour of
   `_on_cancel_run`. If the original request was in a thread, the `thread_ts` is not available
   in the action payload — post to channel root with a note if needed.

6. **Streaming path complexity** — The streaming helpers (`_stream_to_telegram`,
   `_stream_to_slack`) are currently called with `await` directly, not wrapped in a Task.
   To support cancel during streaming, the streaming coroutine must be wrapped in
   `asyncio.create_task()` and stored in `_active_tasks`. This requires refactoring the call
   site in `_run_ai_pipeline`. This is the most complex part of the implementation — GateCode
   should flag this for careful review.

7. **`asyncio.shield` usage** — `asyncio.shield(task)` prevents the timeout's cancellation from
   propagating into the underlying task. This means on `AI_TIMEOUT_SECS` expiry, the task
   continues running until `_cancel_active_task()` is called or the container restarts. This
   is intentional: the timeout path should call `_cancel_active_task()` too, replacing the
   current direct `task.cancel()` in the `TimeoutError` handler.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `gate cancel` works on Telegram (`/cancel` command + `gate cancel` prefix).
- [ ] `gate cancel` works on Slack (text command + Block Kit "Cancel" button in "Thinking…" message).
- [ ] In-flight guard: second prompt while one is in-progress returns "request in progress" message.
- [ ] `CancelledError` in `_run_ai_pipeline` (streaming and non-streaming) produces "⚠️ Request cancelled." to the user — not a stack trace or silent failure.
- [ ] `backend.close()` is called after cancel to release subprocess/PTY resources.
- [ ] `CANCEL_TIMEOUT_SECS` controls the grace period; default `5` preserves existing behaviour.
- [ ] Audit log records `action="cancel"` with `status="cancelled"` or `status="no_op"`.
- [ ] `README.md` updated: feature bullet, env var row, commands table.
- [ ] `docs/roadmap.md` entry marked done (✅) on merge.
- [ ] `docs/features/request-cancellation.md` status changed to `Implemented` on merge.
- [ ] `VERSION` bumped to `0.19.0` before merge PR to `main`.
- [ ] Feature works on both **Telegram** and **Slack**.
- [ ] Feature works with all backends (`copilot`, `codex`, `api`).
- [ ] Edge cases 1–7 above are resolved and either handled in code or documented as accepted trade-offs.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
