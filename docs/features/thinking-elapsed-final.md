# Thinking Elapsed Time + Final Response as New Message

> Status: **Implemented** (v0.17.0, commits `32089f2` + `c13f17f`) | Last reviewed: 2026-03-14

When the AI finishes, the "🤖 Thinking…" placeholder is updated to show total elapsed time (e.g., "🤖 Thought for 12s"), and the final AI response is posted as a brand-new message — keeping conversation flow clean and making response time visible at a glance. Thread context is preserved throughout.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/thinking-elapsed-final.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 10/10 | 2026-03-14 | Implementation verified |
| GateSec  | 1 | 10/10 | 2026-03-14 | Security review passed |
| GateDocs | 1 | 10/10 | 2026-03-14 | Spec consistent with shipped implementation; updated post-ship |

**Status**: ✅ Approved and Implemented (v0.17.0)
**Approved**: Yes

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms: Telegram (`src/bot.py`) and Slack (`src/platform/slack.py`). Both use `thinking_ticker` and `_run_ai_pipeline`.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). The change is in the delivery layer, not the AI layer.
3. **Stateful vs stateless** — No difference: both paths go through the same thinking placeholder and response-delivery code. The change applies identically.
4. **Breaking change?** — No. Current behaviour (thinking message replaced by final response in-place) changes, but there are no env var removals or renames. New env vars all have safe opt-out defaults. **MINOR** version bump.
5. **New dependency?** — None. `time.monotonic()` is already used in the pipeline; no new packages needed.
6. **Persistence** — No new DB tables or files. Elapsed time is computed in-process from existing `t0` timestamps.
7. **Auth** — No new secrets or tokens.
8. **Telegram threading** — Telegram does not have native Slack-style threads, but it supports `reply_to_message_id`. The new final-response message must reply to the original user message (preserving the reply chain), not to the thinking placeholder.
9. **Slack `SLACK_DELETE_THINKING`** — This existing flag currently deletes the thinking placeholder after posting the final response. The new behaviour replaces deletion with an elapsed-time edit; `SLACK_DELETE_THINKING` must be deprecated or its semantics updated (see Design Space below).

---

## Problem Statement

1. **Response replaces thinking in-place** — On both platforms, the final AI response currently edits (overwrites) the "🤖 Thinking…" placeholder. Users lose the record of when AI started thinking; the message timestamp shown in chat belongs to the placeholder, not the final answer.
2. **No total elapsed time visible** — `thinking_ticker` shows live elapsed time during generation, but once the response arrives the elapsed time disappears entirely. Users cannot see how long a response took.
3. **Thread continuity** — In Slack threads and Telegram reply chains, the new final-response message must stay within the same thread/reply chain. The current in-place edit approach naturally preserves position, but the new approach requires explicit thread propagation.

Affected: all users on both Telegram and Slack, for every AI query.

---

## Current Behaviour (as of v0.16.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Telegram streaming | `src/bot.py:65` (`_stream_to_telegram`) | Posts "🤖 Thinking…", streams chunks into it via `msg.edit_text`, final edit replaces it with full response |
| Telegram non-streaming | `src/bot.py:198–230` (`_run_ai_pipeline`) | Posts "🤖 Thinking…", `thinking_ticker` edits with elapsed time, `msg.edit_text(response)` overwrites it |
| Slack streaming | `src/platform/slack.py:172` (`_stream_to_slack`) | Posts thinking placeholder, streams chunks via `_edit`, posts final as *new* message, then optionally deletes placeholder |
| Slack non-streaming | `src/platform/slack.py:321–365` (`_run_ai_pipeline`) | Posts thinking placeholder, `thinking_ticker` edits it, posts final as *new* message, then optionally deletes placeholder |
| Thinking ticker | `src/platform/common.py:23` (`thinking_ticker`) | Edits placeholder with "⏳ Still thinking… (Xs)" on a loop; cancelled when AI returns |
| Config | `src/config.py:22` (`SlackConfig`) | `slack_delete_thinking: bool = True` — deletes the placeholder after final is posted |
| Config | `src/config.py` (`BotConfig`) | `thinking_slow_threshold_secs`, `thinking_update_secs`, `ai_timeout_secs`, `ai_timeout_warn_secs` |

> **Key gap**: Telegram always overwrites the thinking message with the response — elapsed time is lost. Slack deletes the thinking placeholder by default. Neither platform surfaces total elapsed time after completion, and Telegram never sends the final response as a separate message.

---

## Design Space

### Axis 1 — What happens to the thinking placeholder after AI responds

#### Option A — Keep current: overwrite with final response *(status quo)*

The thinking message is edited in-place to show the final response.

**Pros:** Simple. No extra API calls.
**Cons:** Elapsed time lost. Message timestamp belongs to the "Thinking" moment, not the answer.

---

#### Option B — Update placeholder to elapsed time summary; post final as new message *(recommended)*

When the AI finishes, two things happen atomically:
1. Edit the thinking placeholder to `🤖 Thought for Xs` (or `Xm Ys` for > 60s).
2. Post the final response as a new message (respecting thread context).

```python
elapsed = _format_elapsed(int(time.monotonic() - start))
await edit_thinking("🤖 Thought for " + elapsed)
await post_new_message(response, thread_ts=thread_ts)
```

**Pros:** Elapsed time is permanently visible. Final response has its own timestamp. Cleaner UX. Thread context preserved via explicit `thread_ts` / `reply_to_message_id`.
**Cons:** One extra API call per response. Slight layout change (two messages instead of one).

**Recommendation: Option B** — preserving elapsed time and separating concerns (thinking vs. response) improves UX at minimal cost.

---

#### Option C — Delete placeholder; post final as new message with elapsed time in footer

Delete the thinking placeholder and append `_⏱ 12s_` to the final response.

**Pros:** Single visible message.
**Cons:** Elapsed time buried in response text; breaks redaction invariants (must not modify AI text); less scannable.

---

### Axis 2 — Handling `SLACK_DELETE_THINKING` deprecation

#### Option A — Deprecate `SLACK_DELETE_THINKING`; new behaviour is always "edit to elapsed time"

Remove the delete path. Existing users who set `SLACK_DELETE_THINKING=true` see the new elapsed-time edit instead.

**Pros:** Clean; no ambiguity.
**Cons:** Silent behaviour change for users who explicitly set `SLACK_DELETE_THINKING=true`.

---

#### Option B — Keep `SLACK_DELETE_THINKING`; add new `THINKING_SHOW_ELAPSED` flag *(recommended)*

`THINKING_SHOW_ELAPSED` (default `true`) controls the new behaviour. If `SLACK_DELETE_THINKING=true`, deletion still wins (delete instead of editing to elapsed time). This preserves backward compat.

| `SLACK_DELETE_THINKING` | `THINKING_SHOW_ELAPSED` | Result |
|------------------------|------------------------|--------|
| `false` | `true` | Edit thinking to elapsed time ✅ (new default) |
| `false` | `false` | Leave thinking as "🤖 Thinking…" (old non-delete behaviour) |
| `true` | `true` or `false` | Delete thinking (old opt-in behaviour — unchanged) |

**Recommendation: Option B** — preserves backward compat for users who opted into deletion; new default delivers the elapsed-time edit.

---

### Axis 3 — Telegram "new message" reply target

#### Option A — New message replies to the thinking placeholder

The final response is sent as `reply_to_message_id=thinking_msg_id`.

**Pros:** Groups thinking + response visually.
**Cons:** Users get notified of a reply to the bot's own message, which feels odd.

---

#### Option B — New message replies to the original user message *(recommended)*

The final response is sent as `reply_to_message_id=original_user_message_id`.

```python
original_msg_id = update.effective_message.message_id
await context.bot.send_message(chat_id, response, reply_to_message_id=original_msg_id)
```

**Pros:** Mirrors the natural expectation — the bot is replying to the user, not to itself. Consistent with how `reply_text` works today.
**Cons:** None.

**Recommendation: Option B** — the response is a reply to the user's message, not the thinking placeholder.

---

## Recommended Solution

- **Axis 1**: Option B — edit thinking to elapsed time; post final as new message.
- **Axis 2**: Option B — `THINKING_SHOW_ELAPSED` flag; `SLACK_DELETE_THINKING` retains priority.
- **Axis 3**: Option B — Telegram final message replies to original user message.

**Runtime flow (both platforms, non-streaming):**

```
User sends message
  → Bot posts "🤖 Thinking…" placeholder (thinking_msg)
  → thinking_ticker starts (edits placeholder with live elapsed time)
  → AI backend.send(prompt) called
  → AI returns response
  → thinking_ticker cancelled
  → elapsed = time since start
  → [if SLACK_DELETE_THINKING] → delete thinking_msg
  → [elif THINKING_SHOW_ELAPSED] → edit thinking_msg to "🤖 Thought for Xs"
  → post final response as NEW message (in thread if thread_ts set)
```

**Runtime flow (streaming):**

```
User sends message
  → Bot posts "🤖 Thinking…" placeholder (thinking_msg)
  → thinking_ticker starts
  → First chunk arrives → ticker cancelled
  → Stream chunks edit thinking_msg in-place (current streaming behaviour)
  → Stream complete
  → elapsed = time since start
  → [if SLACK_DELETE_THINKING] → delete thinking_msg
  → [elif THINKING_SHOW_ELAPSED] → edit thinking_msg to "🤖 Thought for Xs"
  → post final response as NEW message (in thread if thread_ts set)
```

---

## Architecture Notes

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = True`. History injection in `platform/common.py:build_prompt()` only runs for stateless backends. This feature does not touch the history/prompt path; it only affects the delivery side.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode paths.
- **Platform symmetry** — every change to `_run_ai_pipeline` and `_stream_to_telegram`/`_stream_to_slack` in `src/bot.py` must have a mirrored change in `src/platform/slack.py`.
- **Auth guard** — all Telegram handlers must be decorated with `@_requires_auth`. This feature adds no new handlers.
- **`t0` is already captured** — both `_run_ai_pipeline` implementations already record `t0 = time.time()`. Use `time.monotonic()` for elapsed measurement (consistent with `thinking_ticker`) — record `t_start = time.monotonic()` alongside `t0`.
- **Thread safety** — `thinking_ticker` is cancelled before elapsed-time edit. The edit must happen after cancellation is awaited to avoid a race between the ticker and the elapsed-time edit.
- **Streaming path** — in the streaming path, the thinking placeholder is progressively edited with response chunks. The elapsed-time edit (or deletion) must happen *after* streaming completes; the new final-response message is posted after the elapsed-time edit.
- **`asyncio_mode = auto`** — all `async def test_*` functions in `tests/` run without `@pytest.mark.asyncio`.
- **`THINKING_SHOW_ELAPSED` applies to both platforms** — add it to `BotConfig` (not `SlackConfig`) so Telegram also benefits.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `THINKING_SHOW_ELAPSED` | `bool` | `True` | When `True`, update the "Thinking…" placeholder to "🤖 Thought for Xs" after AI responds. When `False`, leave the placeholder as-is (unless `SLACK_DELETE_THINKING` takes priority). |

> **Naming convention**: `THINKING_*` prefix is already established by `THINKING_SLOW_THRESHOLD_SECS` and `THINKING_UPDATE_SECS`. The new var follows that pattern.
>
> **Interaction with `SLACK_DELETE_THINKING`**: if both are set, `SLACK_DELETE_THINKING=true` takes priority (delete wins over edit). `THINKING_SHOW_ELAPSED` is the new default for non-delete deployments.

---

## Implementation Steps

### Step 1 — `src/config.py`: add `THINKING_SHOW_ELAPSED` to `BotConfig`

```python
# In BotConfig:
thinking_show_elapsed: bool = Field(True, alias="THINKING_SHOW_ELAPSED")
```

---

### Step 2 — `src/platform/common.py`: update `thinking_ticker` return value (or add helper)

Add a module-level helper that performs the post-AI elapsed-time edit, so it can be called identically from both `bot.py` and `slack.py`:

```python
async def finalize_thinking(
    edit_fn: Callable[[str], Awaitable[None]],
    elapsed_secs: int,
    show_elapsed: bool,
) -> None:
    """Edit the thinking placeholder to show total elapsed time (if enabled).

    Errors from edit_fn (message deleted, rate-limited, permissions) are caught
    internally so a failed placeholder edit can never prevent the final AI
    response from being posted.
    """
    if show_elapsed:
        label = _format_elapsed(elapsed_secs)
        try:
            await edit_fn(f"🤖 Thought for {label}")
        except Exception:
            logger.debug("Could not update thinking placeholder with elapsed time")
```

This keeps the logic DRY and testable in isolation. Error handling is internal — callers do not need their own try/except around `finalize_thinking`.

---

### Step 3 — `src/bot.py`: update `_stream_to_telegram` and non-streaming path in `_run_ai_pipeline`

#### `_stream_to_telegram` changes

```python
# Record monotonic start for elapsed calculation
t_start = time.monotonic()
msg = await update.effective_message.reply_text("🤖 Thinking…")
# ... (existing streaming loop unchanged) ...

# After stream completes:
elapsed = int(time.monotonic() - t_start)
if cfg.thinking_show_elapsed:
    await finalize_thinking(msg.edit_text, elapsed, show_elapsed=True)

# Post final response as NEW reply to original user message
original_id = update.effective_message.message_id
await update.get_bot().send_message(
    chat_id=update.effective_chat.id,
    text=final or "_(empty response)_",
    reply_to_message_id=original_id,
)
return final
```

> Remove the existing `await msg.edit_text(final or "_(empty response)_")` call.

#### Non-streaming path in `_run_ai_pipeline`

```python
t_start = time.monotonic()
msg = await update.effective_message.reply_text("🤖 Thinking…")
# ... (ticker, backend.send, timeout handling unchanged) ...

# After response received and ticker cancelled:
elapsed = int(time.monotonic() - t_start)
await common.finalize_thinking(msg.edit_text, elapsed, cfg.thinking_show_elapsed)

# Post final response as new reply
original_id = update.effective_message.message_id
await update.get_bot().send_message(
    chat_id=update.effective_chat.id,
    text=response or "_(empty response)_",
    reply_to_message_id=original_id,
)
```

> Remove the existing `await msg.edit_text(response or "_(empty response)_")` call.

---

### Step 4 — `src/platform/slack.py`: update `_stream_to_slack` and non-streaming path in `_run_ai_pipeline`

#### `_stream_to_slack` changes

```python
t_start = time.monotonic()
resp = await self._reply(client, channel, _THINKING, thread_ts)
ts = resp["ts"]
# ... (existing streaming loop unchanged) ...

# After stream completes:
elapsed = int(time.monotonic() - t_start)
if self._settings.slack.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder (ts=%s)", ts)
else:
    await common.finalize_thinking(
        lambda text: self._edit(client, channel, ts, text),
        elapsed,
        self._settings.bot.thinking_show_elapsed,
    )

# Post final as NEW message (already the case; no change needed here)
await self._reply(client, channel, final or "_(empty response)_", thread_ts)
```

#### Non-streaming path in `_run_ai_pipeline` (Slack)

Same pattern: record `t_start`, call `common.finalize_thinking` after ticker is cancelled, then post response as new message (already done). Replace the `if self._settings.slack.slack_delete_thinking` delete block with the combined delete-or-elapsed-edit logic.

---

### Step 5 — `tests/unit/test_common.py` (new file or extension): test `finalize_thinking`

If `tests/unit/test_common.py` does not exist, create it. Add tests for `finalize_thinking`.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `thinking_show_elapsed: bool = True` to `BotConfig` |
| `src/platform/common.py` | **Edit** | Add `finalize_thinking()` helper |
| `src/bot.py` | **Edit** | `_stream_to_telegram`: elapsed-time edit + post final as new reply. `_run_ai_pipeline`: same for non-streaming path |
| `src/platform/slack.py` | **Edit** | `_stream_to_slack` + non-streaming `_run_ai_pipeline`: elapsed-time edit or delete, then post final (already new) |
| `tests/unit/test_common.py` | **Create / Edit** | Tests for `finalize_thinking` (elapsed formatting, show_elapsed=False no-op) |
| `tests/unit/test_bot.py` | **Edit** | Update assertions: response no longer edits thinking msg; new send_message call expected |
| `tests/unit/test_config.py` | **Edit** | Add `test_thinking_show_elapsed_default` asserting default is `True` |
| `docs/features/thinking-elapsed-final.md` | **Edit** | Mark `Implemented` on merge to `main` |
| `docs/roadmap.md` | **Edit** | Add entry; mark done on completion |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `asyncio` | ✅ stdlib | Already used throughout |
| `time` | ✅ stdlib | `time.monotonic()` already used in pipelines |

---

## Test Plan

### `tests/unit/test_common.py`

| Test | What it checks |
|------|----------------|
| `test_finalize_thinking_edits_with_elapsed` | `finalize_thinking` calls `edit_fn` with `"🤖 Thought for Xs"` |
| `test_finalize_thinking_formats_minutes` | Elapsed ≥ 60s formats as `"🤖 Thought for Xm Ys"` |
| `test_finalize_thinking_noop_when_disabled` | `show_elapsed=False` → `edit_fn` never called |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_stream_posts_final_as_new_message` | After streaming, `bot.send_message` called with response; thinking msg edited to elapsed |
| `test_nonstream_posts_final_as_new_message` | After `backend.send`, `bot.send_message` called; thinking msg edited |
| `test_thinking_show_elapsed_false_leaves_placeholder` | With `THINKING_SHOW_ELAPSED=false`, thinking msg not edited after response |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_thinking_show_elapsed_default` | `BotConfig().thinking_show_elapsed is True` |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target: `finalize_thinking` in `common.py` at 100% branch coverage. Both `show_elapsed=True` and `show_elapsed=False` branches must be exercised.

---

## Documentation Updates

### `README.md`

1. **Features bullet list**: add `🧠 Thinking duration — "🤖 Thought for Xs" shown after every AI response; final answer posted as a new message.`
2. **Environment variables table**: add row for `THINKING_SHOW_ELAPSED`.

### `docs/roadmap.md`

Add entry under Features:

```markdown
| 2.14 | Thinking elapsed time — final response as new message; placeholder updated with total time | [→ features/thinking-elapsed-final.md](features/thinking-elapsed-final.md) |
```

### `docs/features/thinking-elapsed-final.md`

Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.

---

## Version Bump

New `THINKING_SHOW_ELAPSED` env var with a safe default; no renames or removals. **MINOR** bump.

Expected bump: `0.16.x` → `0.17.0`

---

## Edge Cases and Open Questions

1. **Streaming + elapsed time race** — `thinking_ticker` is cancelled at the first chunk; the elapsed clock must start before the ticker task, not after the first chunk. Use `t_start = time.monotonic()` captured immediately after the thinking placeholder is posted.

2. **Telegram rate limits on two rapid messages** — Posting a new message immediately after editing the thinking placeholder could trigger Telegram's flood limits in high-volume chats. Mitigation: the elapsed-time edit and the new message are sequential (not concurrent); existing throttle logic already handles this.

3. **`gate restart` interaction** — No persistent state; no cleanup needed.

4. **Slack thread scope** — `thread_ts` is already propagated through the entire pipeline and passed to `_reply`. The new final-response post uses the same `thread_ts`. No change needed.

5. **Empty response edge case** — If `response` is empty, post `"_(empty response)_"` as the new message (same as current behaviour). The elapsed-time edit still happens.

6. **Timeout path** — If the AI times out, the thinking placeholder is already updated with a cancellation message (`⚠️ Request cancelled after Xs`). `finalize_thinking` must NOT be called in the timeout path (return early before reaching elapsed-time edit).

7. **`SLACK_DELETE_THINKING` interaction** — If `SLACK_DELETE_THINKING=true` AND `THINKING_SHOW_ELAPSED=true`, deletion takes priority (the elapsed-time edit is skipped). Document this clearly in the env var table.

8. **Telegram: reply chain depth** — If the original user message was itself a reply, `reply_to_message_id` will create a nested reply chain. This is standard Telegram behaviour and consistent with how `reply_text` works today.

---

## Acceptance Criteria

- [x] All implementation steps above are complete.
- [x] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [x] `ruff check src/` reports no new linting issues.
- [x] `THINKING_SHOW_ELAPSED=true` (default): thinking placeholder updated to `"🤖 Thought for Xs"` after AI responds.
- [x] `THINKING_SHOW_ELAPSED=false`: thinking placeholder left unchanged after AI responds.
- [x] `SLACK_DELETE_THINKING=true`: placeholder deleted (existing behaviour preserved); elapsed-time edit skipped.
- [x] Final AI response posted as a new message on both Telegram and Slack.
- [x] Slack: final response posted in same thread as original message.
- [x] Telegram: final response posted as reply to original user message.
- [x] Timeout path: elapsed-time edit NOT triggered; cancellation message shown as before.
- [x] `README.md` updated (feature bullet, env var row).
- [ ] `docs/roadmap.md` entry added.
- [ ] `docs/features/thinking-elapsed-final.md` status changed to `Implemented` on merge.
- [ ] `VERSION` bumped to `0.17.0` on `develop` before merge PR to `main`.
- [ ] Feature works identically on both **Telegram** and **Slack**.
- [ ] Feature works with all AI backends (`copilot`, `codex`, `api`).
