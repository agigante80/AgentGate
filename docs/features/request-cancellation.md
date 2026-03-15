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
| GateCode | 2 | 7/10 | 2026-03-15 | 2 blockers, 3 gaps — addressed by GateDocs |
| GateSec  | 1 | 7/10 | 2026-03-15 | 5 findings (1 blocker, 3 medium, 1 low) — see GateSec R1 below |
| GateDocs | 1 | 9/10 | 2026-03-15 | Applied 4 inline fixes (test files table, AC slash-command wording, redundant contract test, modularity-debt note); doc is implementation-ready from docs perspective |
| GateCode | 3 | 9/10 | 2026-03-15 | All 5 Round 1 Blocking Gaps resolved — see GateCode R3 below |
| GateSec  | 2 | -/10 | - | Pending |
| GateDocs | 2 | -/10 | - | Pending |

**Status**: ⏳ Round 2 in progress — GateCode R3 9/10 (all 5 Round 1 Blocking Gaps resolved); GateSec R2 and GateDocs R2 pending

### Round 1 Blocking Gaps (for Round 2 addressal)

> Listed here for GateCode to work through in round 2. Do not list exploit-ready details in delegation messages — reference this section by name only.

1. **`backend.close()` race with new requests** _(GateSec R1 Finding 1)_ — `_cancel_active_task()` Step 2b includes a guard (`if current is None or current is task`) but the Architecture Note still says `close()` fires "unconditionally" in the summary. Ensure the guard is explicit in both the code sample and the prose description, and verify the race remediation is complete (check if the guard covers the `clear_history()` call too).

2. **`clear_history()` is chat-agnostic** _(GateSec R1 Finding 2)_ — The Architecture Note documents the trade-off but does not recommend a concrete stance: "user must run `gate clear` manually" or "call `clear_history()` unconditionally." The implementation step (Step 2b) calls `clear_history()` inside the guard, which differs from the documented trade-off. Resolve to one clear recommendation and align Step 2b + Architecture Notes.

3. **Audit `user_id=None` follow-up tracking** _(GateSec R1 Finding 3)_ — The docstring in `_handle_cancel` notes the gap and mentions a follow-up to thread `user_id` through `_dispatch()`. No acceptance criterion or open-question/issue reference tracks this. Either add an acceptance criterion "follow-up ticket created" or explicitly close this as out-of-scope with a rationale.

4. **`AI_TIMEOUT_SECS=0` hard ceiling** _(GateSec R1 Finding 4)_ — Architecture Note recommends `AI_TIMEOUT_SECS > 0` but stops short of a hard ceiling. Consider whether the spec should mandate a fallback ceiling (e.g. 30 min) even when `AI_TIMEOUT_SECS=0`, or formally accept indefinite blocking as a known risk for single-operator deployments.

5. **`backend.close()` semantic / re-entrance contract** _(GateSec R1 Finding 5)_ — The Architecture Note asks future backend authors to ensure `close()` is re-entrant. This should also appear in the ABC docstring update (Files table). Add an explicit Files table row for `src/ai/adapter.py` — update `AICLIBackend.close()` docstring to state the re-entrance requirement.

### GateCode R2 Findings (2026-03-15)

**Score: 7/10** — All R1 blockers cleanly resolved. Two new blockers and three gaps uncovered by codebase cross-check against the actual `_dispatch` calling convention and `build_app` registration pattern.

#### 🔴 Blocker 1 — `_handle_cancel` has the wrong parameter signature

The spec defines `_handle_cancel(self, say, client, args, channel, thread_ts, user_id)` (Step 3h, line 584). But the actual `_dispatch()` mechanism in `slack.py:635–665` calls every handler as:

```python
await handler(args, say, client, channel, thread_ts=thread_ts)
```

The correct signature must match this convention exactly:

```python
async def _handle_cancel(
    self, args: list[str], say, client, channel: str, *, thread_ts: str | None = None
) -> None:
```

There is no `user_id` parameter in the dispatch call — it is not available here. The audit call `user_id=user_id` in the spec's code sample will raise a `NameError` at runtime. Remove `user_id` from the signature and omit it from the `audit.record()` call (pass `user_id=None` or omit the field), or extract it via a different mechanism if needed.

#### 🔴 Blocker 2 — `cmd_cancel` not registered in `build_app` (Telegram slash command broken)

Step 2e adds `"cancel": self.cmd_cancel` to the `cmd_ta` dispatch table — this covers the `gate cancel` prefix form. But the Acceptance Criteria says "`gate cancel` works on Telegram (`/cancel` command + `gate cancel` prefix)."

Looking at `build_app` (lines 672–684), every other utility command has a dedicated `CommandHandler` registration:

```python
app.add_handler(CommandHandler(f"{p}clear", h.cmd_clear))   # /gateclear
app.add_handler(CommandHandler(f"{p}sync",  h.cmd_sync))    # /gatesync
# etc.
```

Step 2e never adds `app.add_handler(CommandHandler(f"{p}cancel", h.cmd_cancel))`. Without this, `/gatecancel` (the Telegram slash command form) is silently forwarded to `forward_to_ai` as plain text instead of invoking `cmd_cancel`. The Files table lists `src/bot.py` but the `build_app` registration step is missing from the implementation instructions.

#### 🟡 Gap 3 — `asyncio.shield(task)` inside `_cancel_active_task` is semantically confusing

Step 2b's `_cancel_active_task()` does:

```python
task.cancel()
with suppress(asyncio.CancelledError, Exception):
    await asyncio.wait_for(asyncio.shield(task), timeout=...)
```

After `task.cancel()`, using `asyncio.shield(task)` in the wait is misleading — the intent is "wait for the task to finish (whether via CancelledError or normally)." Shield is used to protect a task from *cancellation propagation*, but here the task is already cancelled. A plain `await asyncio.wait_for(task, timeout=...)` achieves the same result with clearer intent. The only edge case where shield matters here is if `_cancel_active_task` itself gets cancelled while waiting — the shield prevents the inner task from being double-cancelled. If that protection is intentional, add a one-line comment explaining it; otherwise simplify to `await asyncio.wait_for(task, timeout=...)`.

#### 🟡 Gap 4 — Step 4b has no code sample (Slack streaming path)

Step 4b says "mirror the same pattern" for the Slack streaming branch without any code. Step 4a (Telegram) has a complete, reviewable code block. Slack's streaming path has meaningful differences — `self._stream_to_slack(...)` is a method (not a module-level function), the reply mechanism uses `client.chat_update`, and thread_ts must be threaded through. "Mirror" is insufficient for a path described as complex.

#### 🟡 Gap 5 — Double notification on user-initiated cancel (undocumented UX behaviour)

When `cmd_cancel` → `_cancel_active_task()` cancels a task, the pipeline's `except asyncio.CancelledError` block fires and edits the "Thinking…" placeholder to "⚠️ Request cancelled." Simultaneously, `cmd_cancel` sends its own `reply_text("⚠️ Request cancelled.")`. The user sees two notifications: the placeholder is edited and a new reply appears. This is not wrong, but it is intentional UX behaviour that should be documented. Add an Architecture Note or Edge Case entry clarifying: "the pipeline's `CancelledError` handler edits the thinking placeholder in-place; `cmd_cancel` sends a separate reply confirming receipt. Both are expected."

---

### GateCode R3 Findings (2026-03-15)

**Score: 9/10** — All 5 Round 1 Blocking Gaps (from GateSec R1) fully resolved. Spec is
implementation-ready from a code perspective. One minor residual note below (score cap).

#### ✅ Gap 1 — `backend.close()` race — resolved

`_cancel_active_task()` Step 2b already includes the guard (`if current is None or current is
task`). Updated: (a) Recommended Solution pseudocode now explicitly shows the guard condition;
(b) Architecture Note expanded to name the guard pattern and confirm both `close()` and
`clear_history()` sit inside it.

#### ✅ Gap 2 — `clear_history()` chat-agnostic trade-off — resolved

Architecture Note now states the chosen v1 stance explicitly: call `clear_history()` after
cancel (inside the race guard). Rationale documented: inconsistent half-written history is
worse than a clean slate for the primary single-tenant use case. Multi-channel `DirectAPIBackend`
trade-off acknowledged.

#### ✅ Gap 3 — Audit `user_id=None` follow-up — resolved

Added Edge Case 9 documenting the gap and formally closing it as out-of-scope for v1 with a
rationale. Added an Acceptance Criterion: "Follow-up issue created: 'Thread user_id through
_dispatch() for full audit attribution on Slack text commands.'"

#### ✅ Gap 4 — `AI_TIMEOUT_SECS=0` hard ceiling — resolved

Architecture Note now formally accepts indefinite blocking as a v1 risk for single-operator
deployments, and defers the hard-ceiling enhancement with rationale.

#### ✅ Gap 5 — `src/ai/adapter.py` missing from Files table — resolved

Added `src/ai/adapter.py` to the Files table with description: update `AICLIBackend.close()`
docstring with the re-entrance contract.

#### 🟡 Residual — score cap at 9/10

One point held back: the `_handle_cancel` docstring mentions a follow-up ticket but no issue
number yet exists (it will be created on merge, per the new AC). No blocker; GateSec should
confirm the re-entrance contract wording in the Architecture Note is sufficient before
approving.

---

### GateSec R1 Findings (2026-03-15)

**Score: 7/10** — Auth guards are solid on both platforms. No injection, no plaintext secret exposure, no auth bypass. One blocker (race between `backend.close()` and new requests) and four design-level concerns that should be resolved before implementation.

#### 🔴 Finding 1 — `backend.close()` in `_cancel_active_task()` races with new requests

`_cancel_active_task()` (Step 2b) calls `task.cancel()`, then `await asyncio.wait_for(asyncio.shield(task), timeout=...)`, then unconditionally calls `self._backend.close()` followed by `self._backend.clear_history()`. The `await` yields control to the event loop. During this yield, another coroutine (e.g. a new prompt arriving in the same or different chat) can call `backend.send()`, spawning a new subprocess or HTTP request. When `_cancel_active_task` resumes, `backend.close()` fires against the backend instance — potentially disrupting the *new* request, not the cancelled one.

Today this is a latent bug because `close()` is a no-op for all current backends (`CopilotSession.close()` is `pass`, `CodexBackend` and `DirectAPIBackend` inherit the ABC default no-op). But the spec's intent is for `close()` to "kill subprocess if any" — once a backend implements a real `close()`, this race becomes a live bug.

*Remediation options:*
1. Guard the `close()` call: after the grace period, check whether a *new* task now exists in `_active_tasks[chat_id]`. If so, skip `close()` — the backend is already serving a new request.
2. Move to a per-request cleanup model instead of per-instance: the `CancelledError` handler inside `CopilotSession.send()` already calls `proc.kill()` on the *specific* subprocess. This is the correct level of granularity. Document that `backend.close()` is a defence-in-depth fallback, not the primary cleanup mechanism, and add the guard from option 1.

#### 🟡 Finding 2 — `clear_history()` is chat-agnostic (cross-chat data loss)

`_cancel_active_task()` calls `self._backend.clear_history()` after cancel. For `DirectAPIBackend` (`is_stateful = True`), this clears `self._messages` — the *entire* conversation history across all chats, not just the cancelled chat's history. In a Slack deployment where multiple channels use the same bot instance, cancelling one channel's request wipes all channels' conversation context.

This is not a data *leakage* issue (no information crosses tenant boundaries), but it is unexpected data *loss*. The spec's Edge Case 2 correctly identifies the inconsistency problem but the proposed fix (`clear_history()`) is overly broad.

*Remediation:* Add an Architecture Note documenting this trade-off explicitly: "`clear_history()` after cancel resets *all* conversation context for `DirectAPIBackend`, not just the cancelled chat. This is acceptable for single-tenant single-channel deployments. Multi-channel deployments using `DirectAPIBackend` should be aware that a cancel in one channel resets context everywhere." Alternatively, defer `clear_history()` and document "user must run `gate clear` manually to reset history after cancel" as the accepted trade-off — this gives the user control over when context is cleared.

#### 🟡 Finding 3 — Audit gap: `user_id=None` on Slack text-command cancel

Step 3h's `_handle_cancel` records `user_id=None` in the audit log because the `_dispatch` calling convention does not pass `user_id`. This means a security-relevant action (cancelling an AI request) has no attribution in the audit trail when invoked via text command.

The asymmetry is notable: Block Kit button cancel (`_on_cancel_ai`) *does* have `user_id` via `body["user"]["id"]`. So the audit trail varies by invocation method for the same action.

*Impact:* An administrator investigating a suspicious cancellation cannot determine who initiated it if the text-command path was used. This is a gap in forensic capability.

*Remediation:* The `_dispatch` caller in `slack.py` (approx. line 635-665) has access to the Slack event payload, which includes `user_id`. Thread `user_id` through to `_dispatch` as a keyword argument. This is a broader fix that benefits all dispatch-routed commands, not just cancel. If that refactor is out of scope for this feature, add a comment in `_handle_cancel` documenting the gap and create a follow-up ticket for the `_dispatch` signature change.

#### 🟡 Finding 4 — In-flight guard + no default timeout = channel-blocking DoS

The in-flight guard (Step 2c/3c) rejects any new prompt while a request is in-flight for the same `chat_id`/`channel`. Combined with `AI_TIMEOUT_SECS=0` (the default — no timeout), a stuck backend request blocks the *entire* channel indefinitely. The only recourse is `gate cancel`, but if the authorized user is unavailable or unaware, the channel remains blocked.

On Slack, this is per-channel: one stuck request in `#team-dev` blocks all team members in that channel. On Telegram group chats, same effect.

*Remediation:* Add an Architecture Note recommending `AI_TIMEOUT_SECS > 0` when the in-flight guard is active. Consider adding a hard ceiling (e.g. 30 minutes) even when `AI_TIMEOUT_SECS=0` — this is a safety net against indefinite blocking. Alternatively, document this as an accepted risk for v1 and require operators to set a timeout.

#### 🟢 Finding 5 — `backend.close()` semantic mismatch (low risk, design note)

The spec uses `backend.close()` as a per-cancel cleanup mechanism, but the ABC documents it as "Release resources (e.g. PTY process). Override in backends that hold external state." This is a lifecycle method intended for shutdown, not for per-request cancellation. Calling `close()` on every cancel means a backend author who implements `close()` to tear down a connection pool or release a license would inadvertently destroy shared state on every cancel.

Today this is a no-op for all backends. But the semantic mismatch creates a maintenance trap.

*Remediation:* Add a one-line comment in `_cancel_active_task()` clarifying that `close()` is used here as a defence-in-depth subprocess cleanup, not a full lifecycle shutdown. If a dedicated `cancel()` method is added to the ABC in the future, this should be replaced. Alternatively, note in the ABC docstring for `close()` that it may be called after cancel and must be re-entrant (safe to call multiple times, backend must remain usable after).

---

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
3. **Stateful vs stateless** — Only `DirectAPIBackend` is stateful (`is_stateful = True`); it
   maintains `self._messages` in memory and may have inconsistent history after a mid-flight cancel
   (the prompt was sent but the reply was never stored). `CodexBackend` inherits `is_stateful =
   False` from `AICLIBackend` — it does not maintain in-memory history, so history consistency is
   not a concern for it. The spec addresses the `DirectAPIBackend` case in Edge Cases (item 2).
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
(short-lived). For `CodexBackend` (persistent PTY subprocess), the PTY process is not killed.

**Cons:** CodexBackend PTY subprocess may continue running, consuming CPU.

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

**Pros:** Cleaner resource cleanup, especially for CodexBackend's persistent PTY subprocess.
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
                if no new task registered for chat_id during grace period:
                    backend.close(); backend.clear_history()  ← guarded, not unconditional
                audit.record(..., status="cancelled")
                → "⚠️ Request cancelled."
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = False`
  (inherited default — no override in `codex.py`); `DirectAPIBackend.is_stateful = True`.
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
- **`clear_history()` is chat-agnostic — chosen v1 stance** _(GateSec R1 Finding 2)_ —
  `backend.clear_history()` after cancel clears `DirectAPIBackend._messages` for *all*
  conversations, not just the cancelled chat. Multi-channel Slack deployments should be aware
  that a cancel in one channel resets context everywhere.
  *Chosen approach*: call `clear_history()` automatically after cancel (inside the same race
  guard as `close()` in Step 2b). Rationale: an inconsistent half-written history is worse than
  a blank slate; the user can re-establish context by simply continuing the conversation. This
  is acceptable for the single-tenant single-channel primary use case. Operators running
  multi-channel `DirectAPIBackend` deployments should note this trade-off — they can always
  set `AI_CLI=copilot` or `codex` (stateless) to avoid it.
- **`backend.close()` is defence-in-depth, guarded** _(GateSec R1 Finding 1)_ — The primary
  cancellation mechanism is `task.cancel()` which propagates `CancelledError` into the backend
  (e.g. `CopilotSession.send()` catches it and calls `proc.kill()`). `backend.close()` in
  `_cancel_active_task()` is a fallback for backends that don't handle `CancelledError` internally.
  It is *not* a full lifecycle shutdown — the backend must remain usable after `close()`. Future
  backend authors must ensure `close()` is re-entrant and does not destroy shared connection pools.
  Critically, `backend.close()` (and `backend.clear_history()`) are called *only inside a guard*:
  `if current is None or current is task` — where `current = self._active_tasks.get(chat_id)`.
  If a new request arrived during the grace-period `await`, `current` will be a different task
  and the guard skips `close()`, preventing disruption of the new request. Both `close()` and
  `clear_history()` are inside this guard (see Step 2b code sample).
- **Recommend `AI_TIMEOUT_SECS > 0`** _(GateSec R1 Finding 4)_ — The in-flight guard rejects
  new prompts while a request is active. With `AI_TIMEOUT_SECS=0` (default), a stuck backend
  request blocks the entire chat/channel indefinitely.
  *Accepted v1 risk*: indefinite blocking is explicitly accepted for single-operator deployments
  where the operator knows they can `gate cancel` at any time. Operators should set
  `AI_TIMEOUT_SECS` to a reasonable value (e.g. `300`) for unattended or shared deployments.
  A hard ceiling (e.g. 30-minute fallback even when `AI_TIMEOUT_SECS=0`) is deferred to a
  future enhancement — it requires UI/UX decisions (user notification, partial response, etc.)
  that are out of scope for v1.
- **asyncio_mode = auto** — all `async def test_*` functions in `tests/` run without
  `@pytest.mark.asyncio`.
- **Streaming path** — `_stream_to_telegram` is a module-level function and cannot access
  `self._active_tasks`. Task tracking for the streaming path belongs in the *caller*
  (`_run_ai_pipeline`): wrap the streaming coroutine in `asyncio.create_task()`, store in
  `_active_tasks[chat_id]`, and handle `CancelledError` / `TimeoutError` at the pipeline level.
  The streaming helper functions themselves do not change.
- **Future modularity debt** _(pre-Milestone 2.16)_ — This feature adds `"cancel"` to the
  `_dispatch` table in `slack.py` and the prefix dispatch dict in `bot.py` by direct dict
  mutation. After Milestone 2.16 (modular plugin architecture), new commands should use
  `@register_command(...)` instead of editing dispatch tables by hand. Flagged as
  future-modularity-debt; does not block this feature.

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
        # asyncio.shield(task) protects the underlying task from a second cancellation
        # if _cancel_active_task() itself is cancelled while waiting (e.g. a race with
        # gate restart). Without shield, a cancellation of this coroutine would deliver
        # a second CancelledError into an already-cancelling task.
        # If double-cancel protection is not needed, this can be simplified to:
        #   await asyncio.wait_for(task, timeout=...)
        await asyncio.wait_for(
            asyncio.shield(task),
            timeout=self._settings.bot.cancel_timeout_secs,
        )
    # Guard: skip close() if a new task was registered during the grace period —
    # close() is instance-wide and would disrupt the new request. (GateSec R1 Finding 1)
    current = self._active_tasks.get(chat_id)
    if current is None or current is task:
        self._backend.close()
        self._backend.clear_history()  # Reset DirectAPIBackend in-memory history after cancel
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

ai_task = asyncio.create_task(
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
except asyncio.TimeoutError:
    # Shield kept ai_task running — must explicitly cancel it.
    await self._cancel_active_task(chat_id)
    await msg.edit_text(
        f"⚠️ Request cancelled after {cfg.ai_timeout_secs}s. "
        "Use `gate status` to check if the process is stuck."
    )
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

**2f.** Register `cmd_cancel` with a `CommandHandler` in `build_app()` so that the `/gatecancel`
Telegram slash command form also works. Without this, `/gatecancel` is silently forwarded to the
AI pipeline as plain text instead of invoking `cmd_cancel`:

```python
# In build_app(), alongside the other CommandHandler registrations:
app.add_handler(CommandHandler(f"{p}cancel", h.cmd_cancel))
```

Update the Files table entry for `src/bot.py` to include "add `CommandHandler` in `build_app()`".

---

### Step 3 — `src/platform/slack.py`: mirror for Slack

**3a.** Add `_active_tasks: dict[str, asyncio.Task] = {}` to `SlackBot.__init__`.

**3b.** Add `_cancel_active_task()` (same logic as Step 2b, adapted for Slack).

**3c.** In `_run_ai_pipeline`, add in-flight guard and task registration (mirror of Step 2c).
The `asyncio.TimeoutError` handler must also call `_cancel_active_task(channel)` — the shield
keeps the underlying task running after timeout, so it must be explicitly cancelled:

```python
# Reject if already in-flight
if channel in self._active_tasks and not self._active_tasks[channel].done():
    await self._reply(client, channel, "⏳ A request is already in progress. Use `gate cancel` to stop it.", thread_ts)
    return

ai_task = asyncio.create_task(self._backend.send(prompt))
self._active_tasks[channel] = ai_task
try:
    response = await asyncio.wait_for(
        asyncio.shield(ai_task),
        timeout=cfg.ai_timeout_secs if cfg.ai_timeout_secs > 0 else None,
    )
except asyncio.CancelledError:
    await self._reply(client, channel, "⚠️ Request cancelled.", thread_ts)
    return
except asyncio.TimeoutError:
    # Shield kept ai_task running — must explicitly cancel it.
    await self._cancel_active_task(channel)
    await self._reply(
        client, channel,
        f"⚠️ Request cancelled after {cfg.ai_timeout_secs}s.",
        thread_ts,
    )
    return
finally:
    self._active_tasks.pop(channel, None)
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

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

**3h.** Add `"cancel"` to the Slack prefix dispatch table (text command path), and define the
`_handle_cancel` method:

```python
# In _KNOWN_SUBS (Step 3i — see below, add "cancel" to the set)
# In _dispatch table:
"cancel": self._handle_cancel,
```

```python
async def _handle_cancel(
    self, args: list[str], say, client, channel: str,
    *, thread_ts: str | None = None,
) -> None:
    """Handle `gate cancel` text command — cancel the in-progress AI request for this channel.

    Note: user_id is not available in the _dispatch calling convention
    (slack.py:665: await handler(args, say, client, channel, thread_ts=thread_ts)).
    Audit is recorded with user_id=None for text-command cancels; Block Kit button
    cancels (_on_cancel_ai) have user_id available via body["user"]["id"].
    GateSec R1 Finding 3: this creates a non-attributable audit record for a
    security-relevant action. Follow-up: thread user_id through _dispatch().
    """
    cancelled = await self._cancel_active_task(channel)
    msg = "⚠️ Request cancelled." if cancelled else "ℹ️ No request in progress."
    await self._reply(client, channel, msg, thread_ts)
    await self._audit.record(
        platform="slack", chat_id=channel, user_id=None,
        action="cancel", status="cancelled" if cancelled else "no_op",
    )
```

**3i.** Add `"cancel"` to `_KNOWN_SUBS` (line 69 in `slack.py`). This is the gating set — only
subcommands in it are routed to `_dispatch()`. Without this, `gate cancel` falls through to the
AI pipeline instead of `_handle_cancel`:

```python
_KNOWN_SUBS = {
    ...,
    "cancel",  # ADD — routes "gate cancel" to _dispatch()
}
```

---

### Step 4 — Streaming path (`_run_ai_pipeline` streaming branch)

`_stream_to_telegram` is a module-level function — it has no access to `self._active_tasks`. The
task must be created and tracked in the *caller* (`_run_ai_pipeline`), wrapping the streaming
coroutine. The `_stream_to_telegram` / `_stream_to_slack` functions themselves do not change.

**4a. `src/bot.py` — streaming branch in `_run_ai_pipeline`:**

```python
# Streaming branch (replaces the bare `await _stream_to_telegram(...)` call)

# In-flight guard (same as non-streaming path):
if chat_id in self._active_tasks and not self._active_tasks[chat_id].done():
    await update.effective_message.reply_text(
        "⏳ A request is already in progress. Use `gate cancel` to stop it."
    )
    return

stream_task = asyncio.create_task(
    _stream_to_telegram(
        update, self._backend, prompt,
        self._settings.bot.max_output_chars,
        self._settings.bot.stream_throttle_secs,
        timeout_secs=0,  # timeout handled externally via wait_for below
        slow_threshold=cfg.thinking_slow_threshold_secs,
        update_interval=cfg.thinking_update_secs,
        warn_before_secs=cfg.ai_timeout_warn_secs,
        redactor=self._redactor,
        show_elapsed=cfg.thinking_show_elapsed,
    )
)
self._active_tasks[chat_id] = stream_task
try:
    timeout = cfg.ai_timeout_secs if cfg.ai_timeout_secs > 0 else None
    response = await asyncio.wait_for(asyncio.shield(stream_task), timeout=timeout)
except asyncio.CancelledError:
    await update.effective_message.reply_text("⚠️ Request cancelled.")
    return
except asyncio.TimeoutError:
    await self._cancel_active_task(chat_id)
    await update.effective_message.reply_text(
        f"⚠️ Stream cancelled after {cfg.ai_timeout_secs}s."
    )
    return
finally:
    self._active_tasks.pop(chat_id, None)
```

**4b. `src/platform/slack.py` — streaming branch in `_run_ai_pipeline`:**

```python
# Streaming branch (replaces the bare await self._stream_to_slack(...) call)

# In-flight guard (same as non-streaming path):
if channel in self._active_tasks and not self._active_tasks[channel].done():
    await self._reply(
        client, channel,
        "⏳ A request is already in progress. Use `gate cancel` to stop it.",
        thread_ts,
    )
    return

stream_task = asyncio.create_task(
    self._stream_to_slack(
        client=client,
        channel=channel,
        thread_ts=thread_ts,
        backend=self._backend,
        prompt=prompt,
        max_chars=self._settings.bot.max_output_chars,
        throttle_secs=self._settings.bot.stream_throttle_secs,
    )
)
self._active_tasks[channel] = stream_task
try:
    timeout = cfg.ai_timeout_secs if cfg.ai_timeout_secs > 0 else None
    await asyncio.wait_for(asyncio.shield(stream_task), timeout=timeout)
except asyncio.CancelledError:
    await self._reply(client, channel, "⚠️ Request cancelled.", thread_ts)
    return
except asyncio.TimeoutError:
    await self._cancel_active_task(channel)
    await self._reply(
        client, channel,
        f"⚠️ Stream cancelled after {cfg.ai_timeout_secs}s.",
        thread_ts,
    )
    return
finally:
    self._active_tasks.pop(channel, None)
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

Key differences from the Telegram path (Step 4a): `_stream_to_slack` is an instance method (not a
module-level function), so it accesses `self` and the `client.chat_update` Slack API. The `thread_ts`
argument must be threaded through so replies land in the correct thread. The in-flight key is
`channel` (not `chat_id`).

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `cancel_timeout_secs: int = Field(5, env="CANCEL_TIMEOUT_SECS")` to `BotConfig` |
| `src/ai/adapter.py` | **Edit** | Update `AICLIBackend.close()` docstring: re-entrance requirement — must be safe to call after cancel and leave the backend usable for subsequent requests. |
| `src/bot.py` | **Edit** | Add `_active_tasks` dict, `_cancel_active_task()`, `cmd_cancel`, in-flight guard in `_run_ai_pipeline`, `CancelledError` handling, dispatch registration, `CommandHandler` in `build_app()` |
| `src/platform/slack.py` | **Edit** | Mirror all of the above; add `"cancel"` to `_KNOWN_SUBS` (routing gate); add `_THINKING_BLOCKS` with Cancel button; add `_on_cancel_ai` handler; add `_handle_cancel` text-command handler; register `cancel_ai` action |
| `README.md` | **Edit** | Feature bullet, `CANCEL_TIMEOUT_SECS` env var row, `gate cancel` command row |
| `tests/unit/test_cancel.py` | **Create** | New unit tests for `_cancel_active_task`, `cmd_cancel`, in-flight guard (see Test Plan) |
| `tests/unit/test_cancel_streaming.py` | **Create** | New unit tests for streaming path cancel and in-flight guard (see Test Plan) |
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
| `test_handle_cancel_text_command_no_task` | `gate cancel` text command with no in-flight task → "No request in progress." |
| `test_handle_cancel_text_command_with_task` | `gate cancel` text command → task cancelled, reply sent |

### `tests/unit/test_cancel_streaming.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_cancelled_error_during_streaming_sends_user_message` | `CancelledError` raised in streaming `asyncio.create_task` → pipeline catches it and sends "⚠️ Request cancelled." (not a stack trace) |
| `test_inflight_guard_rejects_while_streaming` | Second `forward_to_ai` call while a streaming task is in-flight → returns "⏳ A request is already in progress." and does not start a second task |

### `tests/contract/test_backends.py` additions

| Test | What it checks |
|------|----------------|
| `test_cancel_calls_backend_close` | `backend.close()` is invoked after cancellation for every backend, confirming the contract that `close()` must be re-entrant and leave the backend usable. Replaces the redundant `test_close_is_callable_on_all_backends` (which the ABC's default no-op already guarantees). |

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

2. **Stateful backend history consistency** — `DirectAPIBackend` (`is_stateful = True`) maintains
   `self._messages` in memory. If it receives a prompt but the reply is cancelled mid-flight, the
   in-memory history may be in an inconsistent state (prompt logged, reply missing). `CodexBackend`
   and `CopilotBackend` are stateless (`is_stateful = False`) and are not affected.
   *Resolved*: after cancellation, call `backend.clear_history()` in addition to `backend.close()`
   inside `_cancel_active_task()`. This ensures the next prompt starts from a known state for
   `DirectAPIBackend`; for stateless backends `clear_history()` is a no-op.

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

6. **Double-notification on user-initiated cancel** — When `cmd_cancel` (Telegram) or
   `_handle_cancel` / `_on_cancel_ai` (Slack) calls `_cancel_active_task()`, the task receives
   `CancelledError`. The pipeline's `except asyncio.CancelledError` block fires and edits the
   "Thinking…" placeholder to "⚠️ Request cancelled." (or removes the Slack Cancel button).
   Simultaneously, the cancel command itself sends a second "⚠️ Request cancelled." reply
   confirming receipt. *Both notifications are intentional and expected*:
   - The in-place edit on the thinking placeholder gives immediate visual feedback in-context.
   - The separate reply from `cmd_cancel` / `_handle_cancel` confirms that the command was
     received and acted upon (matches the `_on_cancel_run` shell cancel UX pattern).
   No action required — document this as accepted dual-feedback UX.

7. **Streaming path complexity** — *Resolved in Step 4.* `_stream_to_telegram` and
   `_stream_to_slack` are module-level / method functions and cannot access `self._active_tasks`.
   The fix wraps the streaming coroutine in `asyncio.create_task()` at the call site in
   `_run_ai_pipeline` and stores the task in `_active_tasks[chat_id]`. The streaming helper
   functions themselves are unchanged.

8. **`asyncio.shield` usage** — *Resolved in Steps 2b, 2c, and 3c.* See the `asyncio.shield`
   Architecture Note for the rationale. `asyncio.shield(task)` in `_cancel_active_task()`
   protects against double-cancel if the helper is itself interrupted. `asyncio.shield(task)` in
   `_run_ai_pipeline` prevents the `AI_TIMEOUT_SECS` wait from cancelling the underlying task —
   the task is then explicitly cancelled via `_cancel_active_task()` in the `TimeoutError` handler.

9. **Audit attribution gap for Slack text-command cancel** — `_handle_cancel` (Step 3h) records
   `user_id=None` because the `_dispatch()` calling convention does not pass `user_id`. This
   creates a non-attributable audit record for a security-relevant action when cancellation is
   triggered via text command (Block Kit button cancel via `_on_cancel_ai` does have `user_id`).
   *Out of scope for v1*: threading `user_id` through `_dispatch()` is a cross-cutting change that
   benefits all dispatch-routed commands (not just cancel) and should be done as a dedicated
   refactor. The gap is documented in the `_handle_cancel` docstring (Step 3h). A follow-up issue
   should be created when this feature is merged: "Thread user_id through _dispatch() for full
   audit attribution on Slack text commands."

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `gate cancel` works on Telegram (`/gatecancel` slash command + `gate cancel` prefix — registered via `CommandHandler(f"{p}cancel", h.cmd_cancel)` where `p` defaults to `gate`).
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
- [ ] Edge cases 1–9 above are resolved and either handled in code or documented as accepted trade-offs.
- [ ] Follow-up issue created: "Thread user_id through _dispatch() for full audit attribution on Slack text commands."
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
