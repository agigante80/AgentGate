# Slack: Post Final AI Response as New Message (`SLACK_DELETE_THINKING`)

> Status: **Implemented** | Priority: **High** | Last reviewed: 2026-03-13

Docs update: README.md and .env.example were updated to document `SLACK_DELETE_THINKING` and `SLACK_THREAD_REPLIES`.

When streaming or waiting for an AI response, the bot posts a ⏳ "thinking" placeholder and then
**edits** that same message with the final content. Because other Slack bots ignore edited
messages, agent-to-agent responses are silently lost. This feature changes the delivery model so
the final response is always posted as a new message.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Slack-only. Telegram uses `message.reply_text()` which always posts a new message.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). The change is in the Slack delivery
   layer, not the AI backend.
3. **Stateful vs stateless** — Not relevant. Delivery behaviour is the same for both.
4. **Breaking change?** — No. The user-visible result (a message with the AI response) is
   unchanged. The mechanism (new message instead of edit) is transparent. **MINOR** bump.
5. **New dependency?** — No. `client.chat_delete()` is already part of `slack-bolt`.
6. **Persistence** — No new DB table. The ⏳ placeholder `ts` only needs to survive a single
   request lifecycle (a local variable).
7. **Auth** — No new secrets. `chat:write` (already required) covers both post and delete.
8. **Delete permission** — `chat:write` covers deleting bot-authored messages. If the bot cannot
   delete (e.g., restricted workspace), it should fall back to leaving the placeholder as-is
   rather than raising an error.

---

## Problem Statement

1. **Agent-to-agent responses are invisible.** `_stream_to_slack()` and the non-streaming path in
   `_run_ai_pipeline()` both deliver the final AI response by editing the ⏳ placeholder message.
   Slack delivers edits as `message_changed` events with `subtype` set. `_on_message()` returns
   immediately for any event with a `subtype` (line 258), so every agent response is silently
   discarded by all other agents.

2. **Multi-agent workflows are broken.** Any orchestration pattern where agent A asks agent B a
   question — and B's response is expected to trigger agent A or agent C — cannot work today,
   because B's response never appears as a triggerable new message.

3. **Users cannot rely on message order.** In channels with multiple bots, editing a message
   changes its content but not its position, while a new message appears at the bottom of the
   thread. New messages are more natural to follow in an active multi-agent conversation.

---

## Current Behaviour (as of v0.9.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Event filter | `src/platform/slack.py:258` (`_on_message`) | Returns immediately if `event.get("subtype")` is truthy — covers `message_changed`, `message_deleted`, bot edits |
| Streaming delivery | `src/platform/slack.py:117` (`_stream_to_slack`) | Posts ⏳ via `say()`, streams edits via `_edit()`, **edits** final response at line 177 |
| Non-streaming delivery | `src/platform/slack.py:201–235` (`_run_ai_pipeline`) | Posts ⏳ via `say()`, waits for AI, **edits** with response at line 233 |
| Edit helper | `src/platform/slack.py:110` (`_edit`) | Calls `client.chat_update()` — changes content of existing message |
| Config | `src/config.py` (`BotConfig`) | No field controlling delete-thinking behaviour |

> **Key gap**: The final AI response is delivered via `chat_update` (an edit), which Slack
> propagates as `message_changed`. All bots ignore `message_changed` at line 258, so no agent
> can ever react to another agent's AI response.

---

## Code Review Notes (2026-03-13)

Verified against `src/platform/slack.py` on `develop`:

- **Line numbers confirmed**: `_stream_to_slack()` final `_edit()` is at line 177; non-streaming final `_edit()` is at line 233; streaming timeout is at lines 162–165; non-streaming timeout is at lines 221–224. All match the Implementation Steps below.
- **`_handle_files()` edit calls** (lines 618, 629, 632): These use `_edit()` for transcription status updates (`"🎙️ Transcribing…"`, error text, `"🎙️ I heard: …"`). These are bot status messages, _not_ AI responses — they do **not** need to change for this feature. The AI response itself goes through `_run_ai_pipeline()` at line 633, which is covered by Steps 2–3.
- **Initial thinking placeholder**: Lines 120 (`_stream_to_slack`) and 201 (`_run_ai_pipeline`) post ⏳ via `say()` — this remains `say()` for 2.1. Only the **final** delivery (lines 177 and 233) switches to `chat_postMessage`. (When 2.3 is also enabled, the initial `say()` will also switch to `client.chat_postMessage` with `thread_ts` — handled by `slack-thread-replies.md` Steps 3–4.)
- **Command handlers** (`_cmd_run`, `_cmd_sync`, etc.) already use `say()` which posts new messages — no changes needed there.
- **`_on_message` subtype guard** (line 258): `if event.get("subtype"): return` — confirmed in current code. Leave as-is.

---

## Design Space

### Axis 1 — How to deliver the final AI response

#### Option A — Keep editing *(status quo)*

The final response replaces the ⏳ placeholder via `chat_update`. No changes.

**Pros:**
- Simple; single message per exchange.

**Cons:**
- Breaks agent-to-agent communication entirely.
- Final response is invisible to other agents.

---

#### Option B — Post final as new message; delete ⏳ placeholder *(recommended)*

After streaming finishes (or non-streaming response arrives), call `client.chat_postMessage()`
with the final content. Then call `client.chat_delete()` to remove the ⏳ placeholder.
If deletion fails (permissions), leave the placeholder and continue — the new message is
still visible and triggerable.

```python
# _stream_to_slack() – after streaming loop:
final = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
await client.chat_postMessage(channel=channel, text=final or "_(empty response)_")
if self._settings.bot.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder")
return final

# _run_ai_pipeline() – non-streaming path (replace _edit call):
await client.chat_postMessage(channel=channel, text=response or "_(empty response)_")
if self._settings.bot.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder")
```

**Pros:**
- Final response is a new message → other agents can react to it.
- Clean channel history (no ⏳ ghost messages with `SLACK_DELETE_THINKING=true`).
- Non-breaking: same content, different delivery mechanism.

**Cons:**
- Two API calls for delivery (post + delete) instead of one (edit).
- Delete can fail in restricted workspaces — handled gracefully by ignoring the error.

---

#### Option C — Post final as new message; leave ⏳ placeholder

Same as Option B but never delete the placeholder, leaving it as a visible "request receipt".

**Pros:**
- Simpler (no delete call, no permission concern).

**Cons:**
- ⏳ ghost messages accumulate in noisy channels.
- Clutters the channel history in multi-agent workflows.

---

### Axis 2 — Scope of "edit" during streaming

During streaming, intermediate edits (every `stream_throttle_secs`) show the user that the AI
is producing output. These are legitimate UI updates and do **not** need to trigger other agents.

#### Option A — Keep intermediate streaming edits as-is *(recommended)*

Only the **final** delivery changes (new message). Intermediate edits continue using `_edit()`.

**Pros:**
- Streaming UX is preserved (user sees progress).
- Minimal code change.

**Cons:**
- None significant.

---

#### Option B — Stream to a new message for each chunk

Post a new message for every streaming update instead of editing.

**Pros:**
- Fully eliminates edits from the system.

**Cons:**
- Extremely noisy (dozens of messages per response).
- Slack API rate limits would be hit immediately.
- Not needed: intermediate chunks do not need to be triggerable by other agents.

**Recommendation: Option A** — intermediate edits are a UX feature; only the final delivery needs to change.

---

## Recommended Solution

- **Axis 1**: Option B — post final as new message; delete ⏳ placeholder (configurable via `SLACK_DELETE_THINKING`)
- **Axis 2**: Option A — keep intermediate streaming edits unchanged

**End-to-end flow:**

```
User sends: "dev what's in main.py?"
  → bot posts: ⏳ Thinking...          (ts = T1)
  → streaming edits T1: "Looking at..."  "Looking at the fi..."  (intermediate, UI only)
  → streaming finishes
  → bot posts NEW message: "Here's what's in main.py: ..."  (ts = T2, visible to all agents)
  → bot deletes T1 (the ⏳ placeholder)   ← optional, controlled by SLACK_DELETE_THINKING

Other agents see T2 as a normal new message and can react to it.
```

---

## Architecture Notes

- **`_on_message()` subtype guard** — line 258 MUST stay as-is. Edits (including intermediate
  streaming updates) fire `message_changed`. The guard correctly ignores them. The fix is at
  the delivery end, not the filter end.
- **`client.chat_postMessage` vs `say()`** — `say()` is a shorthand that uses the channel from
  the current event context. For final delivery, use `client.chat_postMessage(channel=channel, ...)`
  explicitly, because the context may have moved on by the time streaming finishes.
- **`chat_delete` permission** — the bot's `chat:write` scope allows it to delete its own
  messages. Wrap in `try/except` and log at DEBUG level; never let a delete failure propagate.
- **Platform symmetry** — Telegram already posts new messages via `reply_text()`; this change
  only affects `src/platform/slack.py`.
- **`REPO_DIR` and `DB_PATH`** — not involved in this feature.
- **`asyncio_mode = auto`** — tests remain `async def test_*` without decorator.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `SLACK_DELETE_THINKING` | `bool` | `True` | Delete the ⏳ placeholder after posting the final response. Set `false` to keep it as a "request receipt". |

> **Naming convention**: `SLACK_` prefix groups all Slack-specific vars together.
> Default `True` gives the cleanest UX. Set `False` for workspaces where delete is restricted.

---

## Implementation Steps

### Step 1 — `src/config.py`: add config field

```python
# In SlackConfig (or BotConfig if cross-platform — Slack-specific, so SlackConfig preferred):
slack_delete_thinking: bool = Field(True, env="SLACK_DELETE_THINKING")
```

---

### Step 2 — `src/platform/slack.py`: update `_stream_to_slack()`

Replace the final `_edit()` call with a `chat_postMessage` + optional `chat_delete`:

```python
# Replace line 177:
# await self._edit(client, channel, ts, final or "_(empty response)_")

await client.chat_postMessage(channel=channel, text=final or "_(empty response)_")
if self._settings.slack.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder (ts=%s)", ts)
return final
```

---

### Step 3 — `src/platform/slack.py`: update non-streaming path in `_run_ai_pipeline()`

Replace the `_edit()` call at line 233:

```python
# Replace:
# await self._edit(client, channel, ts, response or "_(empty response)_")

await client.chat_postMessage(channel=channel, text=response or "_(empty response)_")
if self._settings.slack.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder (ts=%s)", ts)
```

---

### Step 4 — `src/platform/slack.py`: update timeout/error paths

The timeout edit paths in both `_stream_to_slack()` (line 162) and `_run_ai_pipeline()` (line 221)
should also post as new messages — error messages should be visible to other agents too:

```python
# In _stream_to_slack() timeout handler:
await client.chat_postMessage(
    channel=channel,
    text=f"⚠️ Stream cancelled after {cfg.ai_timeout_secs}s."
)
if self._settings.slack.slack_delete_thinking:
    try:
        await client.chat_delete(channel=channel, ts=ts)
    except Exception:
        logger.debug("Could not delete thinking placeholder")
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `slack_delete_thinking: bool = True` to `SlackConfig` |
| `src/platform/slack.py` | **Edit** | Replace final `_edit()` calls with `chat_postMessage` + optional `chat_delete` in `_stream_to_slack()`, `_run_ai_pipeline()`, and timeout/error paths |
| `tests/unit/test_slack_bot.py` | **Edit** | Update mocks; add `slack_delete_thinking` to `_make_settings()`; add tests for new/delete behaviour |
| `docs/roadmap.md` | **Edit** | Mark feature done on completion |
| `docs/features/slack-final-response-new-message.md` | **Edit** | Change status to `Implemented` after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `slack-bolt[async]` | ✅ Already installed | `client.chat_delete()` is part of the standard SDK |

---

## Test Plan

### `tests/unit/test_slack_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_stream_final_posts_new_message` | After `_stream_to_slack()`, `chat_postMessage` is called with final content |
| `test_stream_final_deletes_thinking` | With `SLACK_DELETE_THINKING=true`, `chat_delete` is called on the thinking `ts` |
| `test_stream_no_delete_when_disabled` | With `SLACK_DELETE_THINKING=false`, `chat_delete` is NOT called |
| `test_nonstream_final_posts_new_message` | Non-streaming path also uses `chat_postMessage` for final response |
| `test_stream_delete_failure_is_silent` | If `chat_delete` raises, no exception propagates; response is still posted |
| `test_timeout_posts_new_message` | Timeout error is also posted as new message, not an edit |

---

## Documentation Updates

### `README.md`

Add to environment variables table:
```markdown
| `SLACK_DELETE_THINKING` | `true` | Delete the ⏳ placeholder after AI responds. Set `false` to keep it. |
```

### `docs/roadmap.md`

Mark this feature as done (✅) when merged to `main`.

---

## Version Bump

This feature adds a new optional env var with a safe default. Existing behaviour is preserved
for users who set `SLACK_DELETE_THINKING=false`. The delivery mechanism change is transparent
to human users.

**Expected bump**: `MINOR` → `0.10.0`

---

## Edge Cases and Open Questions

1. **Delete permission in restricted workspaces** — Some Slack workspaces restrict message
   deletion to admins. The bot must handle `chat_delete` failures gracefully (log at DEBUG,
   do not re-raise). The final response is still visible as a new message.

2. **Race condition between streaming and delete** — Streaming edits and the final post happen
   sequentially (`await`). The delete only runs after `chat_postMessage` succeeds, so there's
   no race.

3. **`gate restart` interaction** — This feature holds no persistent state. `gate restart` is
   unaffected.

4. **Slack thread scope** — If `SLACK_THREAD_REPLIES=true` is also enabled (see
   `slack-thread-replies.md`), the new message must be posted with the same `thread_ts`.
   The two features must coordinate `thread_ts` plumbing.

5. **`say()` vs `chat_postMessage`** — `say()` is a context-bound shorthand; for the final
   delivery inside an async streaming task, prefer `client.chat_postMessage(channel=channel)`
   to avoid context binding issues.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` is updated (env var table).
- [ ] `docs/roadmap.md` entry is marked done (✅).
- [ ] `docs/features/slack-final-response-new-message.md` status changed to `Implemented`.
- [ ] `VERSION` file bumped.
- [ ] `SLACK_DELETE_THINKING=false` preserves current editing behaviour (regression test).
- [ ] With `SLACK_DELETE_THINKING=true` (default), agents can react to the final response.
- [ ] Deletion failure does not break the response delivery.
