# Persistent Thinking Message (`THINKING_SHOW_ELAPSED`)

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-15

Fix the non-streaming message lifecycle so the "⏳ Still thinking…" placeholder persists with its final elapsed time instead of being silently overwritten by the AI response.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/thinking-persist.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both Telegram and Slack platforms.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). The bug is in the message delivery layer, not the backend layer.
3. **Stateful vs stateless** — No interaction; the thinking message lifecycle is independent of backend state management.
4. **Breaking change?** — No. `THINKING_SHOW_ELAPSED` already exists and defaults to `true`. The config comment already describes the intended (but unimplemented) behaviour: "final response posted as new message". This fix makes the code match the documented intent. Users with `THINKING_SHOW_ELAPSED=false` see no change. Users with the default (`true`) will now see the thinking message persist — a UX improvement, not a regression. → PATCH bump.
5. **New dependency?** — No.
6. **Persistence** — No.
7. **Auth** — No.
8. **Slack `SLACK_DELETE_THINKING` interaction** — When `SLACK_DELETE_THINKING=true`, that flag takes priority: the thinking message is deleted regardless of `THINKING_SHOW_ELAPSED`. No conflict.

---

## Problem Statement

1. **Thinking message is overwritten in non-streaming mode** — When a user sends a prompt and the backend returns a non-streamed response, the "⏳ Still thinking… (15s)" placeholder is edited to "🤖 Thought for Xs" by `finalize_thinking()`, but then immediately overwritten with the AI response by `_deliver_telegram()` / `_deliver_slack()`. The user never sees the final elapsed time.

2. **Inconsistent behaviour between streaming and non-streaming** — In streaming mode, the thinking message correctly persists as "🤖 Thought for Xs" because the streaming response is delivered via a *separate* message (`final_msg` / `final_ts`). In non-streaming mode, the same thinking message object is reused as the delivery target, destroying the finalized text. Users experience different UX depending on which backend/mode they happen to use.

3. **Config comment contradicts code** — `BotConfig.thinking_show_elapsed` (line 60 of `src/config.py`) has the comment: _"update '🤖 Thinking…' to '🤖 Thought for Xs' after AI responds; final response posted as new message"_. The "posted as new message" part is not implemented in the non-streaming path — the response replaces the thinking message in-place.

Affected users: all Telegram users and Slack users with `SLACK_DELETE_THINKING=false`, when the AI backend uses the non-streaming `send()` path.

---

## Current Behaviour (as of v0.18.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Ticker | `src/platform/common.py:26` (`thinking_ticker`) | Background task edits thinking message: `⏳ Still thinking… (15s)`, updates every `THINKING_UPDATE_SECS` seconds |
| Finalize | `src/platform/common.py:60` (`finalize_thinking`) | Edits thinking message to `🤖 Thought for Xs` (if `THINKING_SHOW_ELAPSED=true`) |
| TG non-stream | `src/bot.py:373-374` (`forward_to_ai`) | Calls `finalize_thinking(msg.edit_text, …)` then `_deliver_telegram(update, msg, response)` — passes the thinking message as `streaming_msg`, which overwrites it |
| TG streaming | `src/bot.py:136-137` (`_stream_to_telegram`) | Calls `finalize_thinking(thinking_msg.edit_text, …)` then `_deliver_telegram(update, final_msg, final)` — passes a *separate* `final_msg`, thinking message persists ✅ |
| TG delivery | `src/bot.py:141` (`_deliver_telegram`) | Edits `streaming_msg` with AI response text; if `streaming_msg` is the thinking message, it overwrites the finalized text |
| Slack non-stream | `src/platform/slack.py:569-577` (`_handle_message`) | `finalize_thinking` runs, then `_deliver_slack` is called with `existing_ts=ts` (the thinking message TS), which overwrites it |
| Slack streaming | `src/platform/slack.py:299-310` (`_stream_to_slack`) | `finalize_thinking` runs on thinking `ts`, `_deliver_slack` called with `final_ts` (separate message) — thinking persists ✅ |
| Slack delete | `src/platform/slack.py:563-567` | When `SLACK_DELETE_THINKING=true`, thinking message is deleted, `_deliver_slack` receives `None` — response sent as new message |
| Config | `src/config.py:60` (`BotConfig`) | `thinking_show_elapsed: bool = True` — comment says "final response posted as new message" but code doesn't implement this |

> **Key gap**: In the non-streaming path, `finalize_thinking()` is effectively a no-op because the delivery function immediately overwrites the thinking message. Streaming mode works correctly because it uses a separate message for the response. The fix is to align non-streaming with the streaming pattern: pass `None` as the delivery target so the response always goes to a new message when the thinking message is persisted.

---

## Design Space

### Axis 1 — How to persist the thinking message in non-streaming mode

#### Option A — Pass `None` to delivery when `thinking_show_elapsed=true` *(recommended)*

After `finalize_thinking()`, pass `None` (instead of the thinking message) to `_deliver_telegram()` / `_deliver_slack()`. This forces the delivery function to create a new message for the response, exactly as the streaming path does.

**Telegram** (`src/bot.py`):
```python
# Before (line 374):
await _deliver_telegram(update, msg, response)

# After:
await _deliver_telegram(
    update,
    None if cfg.thinking_show_elapsed else msg,
    response,
)
```

**Slack** (`src/platform/slack.py`):
```python
# Before (line 574-580):
await self._deliver_slack(
    client, channel,
    None if self._settings.slack.slack_delete_thinking else ts,
    response, thread_ts,
)

# After:
persist = (
    not self._settings.slack.slack_delete_thinking
    and self._settings.bot.thinking_show_elapsed
)
await self._deliver_slack(
    client, channel,
    None if self._settings.slack.slack_delete_thinking or persist else ts,
    response, thread_ts,
)
```

**Pros:**
- Minimal code change (two call sites, ≤5 lines each)
- Aligns non-streaming with streaming (same delivery pattern)
- No new env vars — uses existing `THINKING_SHOW_ELAPSED`
- Backwards compatible — `THINKING_SHOW_ELAPSED=false` preserves current overwrite behaviour

**Cons:**
- Doubles message count when enabled (one thinking + one response)

---

#### Option B — New `THINKING_PERSIST` env var

Introduce a separate `THINKING_PERSIST` boolean to decouple "show elapsed time" from "persist as separate message".

**Pros:**
- Finer-grained control

**Cons:**
- Config complexity for minimal benefit — if you want to see elapsed time, you inherently want the message to persist
- The existing config comment already documents the persist behaviour as intended
- Slack already has `SLACK_DELETE_THINKING` for the delete case; adding a third thinking-related flag is confusing

**Recommendation: Option A** — the simplest fix with zero config surface increase. `THINKING_SHOW_ELAPSED` already documents this as intended behaviour; we're just making the code match.

---

### Axis 2 — `SLACK_DELETE_THINKING` precedence

#### Option A — `SLACK_DELETE_THINKING` overrides `THINKING_SHOW_ELAPSED` *(recommended)*

When `SLACK_DELETE_THINKING=true`, the thinking message is always deleted regardless of `THINKING_SHOW_ELAPSED`. This preserves backwards compatibility for Slack users who prefer a clean channel.

**Precedence matrix:**

| `SLACK_DELETE_THINKING` | `THINKING_SHOW_ELAPSED` | Behaviour |
|---|---|---|
| `true` | `true` | Thinking deleted, response as new message |
| `true` | `false` | Thinking deleted, response as new message |
| `false` | `true` | Thinking persists as `🤖 Thought for Xs`, response as new message *(new behaviour)* |
| `false` | `false` | Thinking overwritten with response *(current behaviour)* |

**Recommendation: Option A** — clear, predictable, no surprises.

---

### Axis 3 — Telegram thinking message disposition when `THINKING_SHOW_ELAPSED=false`

#### Option A — Overwrite thinking with response *(current behaviour, recommended)*

When `THINKING_SHOW_ELAPSED=false`, keep current behaviour: response overwrites the thinking placeholder. No stale `🤖 Thinking…` message left in chat.

#### Option B — Always persist, show `🤖 Done` instead of elapsed time

Always persist the thinking message, even when elapsed time is disabled. Show a generic `🤖 Done` label.

**Recommendation: Option A** — no one wants a bare `🤖 Thinking…` or `🤖 Done` message cluttering chat. Persistence is only useful when it carries the elapsed time.

---

## Recommended Solution

- **Axis 1**: Option A — pass `None` to delivery when `thinking_show_elapsed=true`
- **Axis 2**: Option A — `SLACK_DELETE_THINKING` overrides `THINKING_SHOW_ELAPSED`
- **Axis 3**: Option A — overwrite thinking with response when elapsed display is disabled

End-to-end flow (non-streaming, `THINKING_SHOW_ELAPSED=true`):

```
User sends prompt
  → Bot replies: "🤖 Thinking…"
  → Ticker edits:  "⏳ Still thinking… (15s)"
  → Ticker edits:  "⏳ Still thinking… (45s)"
  → AI returns response
  → Ticker cancelled
  → finalize_thinking() edits: "🤖 Thought for 48s"     ← PERSISTS
  → _deliver_*(update, None, response)                    ← NEW MESSAGE
  → Bot replies (new message): "<AI response text>"
```

This matches the streaming path exactly:

```
User sends prompt
  → Bot replies: "🤖 Thinking…"
  → Ticker edits:  "⏳ Still thinking… (15s)"
  → Stream starts → Bot replies (new message): "<chunk> ▌"
  → Ticker edits:  "⏳ Still thinking… (30s)"
  → Stream edits:  "<accumulated> ▌"
  → Stream complete
  → Ticker cancelled
  → finalize_thinking() edits: "🤖 Thought for 35s"     ← PERSISTS
  → _deliver_*(update, final_msg, response)              ← SEPARATE MSG
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = True`.
  History injection in `platform/common.py:build_prompt()` only runs for stateless backends.
  This feature does not interact with the stateful/stateless boundary; it operates at the message delivery layer.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode `/repo` or
  `/data/history.db`.
- **Platform symmetry** — every feature that changes `_run_ai_pipeline` or `_stream_to_*` in
  `src/bot.py` must have a mirrored change in `src/platform/slack.py`.
- **Auth guard** — all Telegram handlers must be decorated with `@_requires_auth`.
- **No new auth required** — this change affects only the message delivery call; no command handlers are added or modified.
- **`asyncio_mode = auto`** — all `async def test_*` functions in `tests/` run without
  `@pytest.mark.asyncio`.
- **Rate limits** — persisting the thinking message means one extra message per prompt in non-streaming mode. Telegram allows 30 messages/second per bot (well within limits). Slack's rate limit (chat.postMessage: ~1/sec) is also fine since the response message only fires once.
- **`_deliver_telegram` with `streaming_msg=None`** — already handles `None` correctly: creates a new `reply_text()` instead of editing. No changes needed to the delivery function itself.
- **`_deliver_slack` with `existing_ts=None`** — already handles `None` correctly: creates a new `_reply()` instead of editing. No changes needed to the delivery function itself.

---

## Config Variables

No new env vars introduced. Existing vars and their interaction:

| Env var | Type | Default | Role in this fix |
|---------|------|---------|------------------|
| `THINKING_SHOW_ELAPSED` | `bool` | `True` | When `true`, thinking message persists with elapsed time; response sent as new message. When `false`, response overwrites thinking (current behaviour). |
| `SLACK_DELETE_THINKING` | `bool` | `True` | When `true`, overrides `THINKING_SHOW_ELAPSED` — thinking message is deleted, response sent as new message. |
| `THINKING_SLOW_THRESHOLD_SECS` | `int` | `15` | Unchanged. Seconds before first ticker update. |
| `THINKING_UPDATE_SECS` | `int` | `30` | Unchanged. Interval between ticker updates. |

---

## Implementation Steps

### Step 1 — `src/bot.py`: fix non-streaming delivery target

Change the `_deliver_telegram` call in `forward_to_ai` to pass `None` when `thinking_show_elapsed` is enabled:

```python
# In forward_to_ai (non-streaming branch), replace:
await _deliver_telegram(update, msg, response)

# With:
await _deliver_telegram(
    update,
    None if cfg.thinking_show_elapsed else msg,
    response,
)
```

This is the only change in `bot.py`. The streaming path (`_stream_to_telegram`) already works correctly.

---

### Step 2 — `src/platform/slack.py`: fix non-streaming delivery target

In `_handle_message`, change the `_deliver_slack` call when `SLACK_DELETE_THINKING=false` to pass `None` when `thinking_show_elapsed` is enabled:

```python
# Replace:
await self._deliver_slack(
    client,
    channel,
    None if self._settings.slack.slack_delete_thinking else ts,
    response,
    thread_ts,
)

# With:
thinking_persists = (
    not self._settings.slack.slack_delete_thinking
    and self._settings.bot.thinking_show_elapsed
)
await self._deliver_slack(
    client,
    channel,
    None if self._settings.slack.slack_delete_thinking or thinking_persists else ts,
    response,
    thread_ts,
)
```

This is the only change in `slack.py`. The streaming path (`_stream_to_slack`) already works correctly.

---

### Step 3 — `src/config.py`: fix config comment

Update the `thinking_show_elapsed` comment to reflect the now-correct behaviour:

```python
# Replace:
thinking_show_elapsed: bool = True      # THINKING_SHOW_ELAPSED: update "🤖 Thinking…" to "🤖 Thought for Xs" after AI responds; final response posted as new message

# With:
thinking_show_elapsed: bool = True      # THINKING_SHOW_ELAPSED: persist "🤖 Thought for Xs" after AI responds; response posted as a separate new message
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/bot.py` | **Edit** | Pass `None` to `_deliver_telegram` when `thinking_show_elapsed=true` (1 line) |
| `src/platform/slack.py` | **Edit** | Pass `None` to `_deliver_slack` when thinking persists (3 lines) |
| `src/config.py` | **Edit** | Fix config comment on `thinking_show_elapsed` (1 line) |
| `tests/unit/test_bot.py` | **Edit** | Add test for thinking message persistence in non-streaming mode |
| `tests/unit/test_thinking_persist.py` | **Create** | Tests for both platforms, both `THINKING_SHOW_ELAPSED` values |
| `docs/features/thinking-persist.md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Add entry for this fix |

---

## Dependencies

No new dependencies.

---

## Test Plan

### `tests/unit/test_thinking_persist.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_telegram_nonstream_persist_enabled` | When `THINKING_SHOW_ELAPSED=true`, `_deliver_telegram` is called with `streaming_msg=None` (new message) |
| `test_telegram_nonstream_persist_disabled` | When `THINKING_SHOW_ELAPSED=false`, `_deliver_telegram` is called with `streaming_msg=msg` (overwrites thinking) |
| `test_telegram_stream_persist_unchanged` | Streaming path still passes `final_msg` (not `thinking_msg`) regardless of setting |
| `test_slack_nonstream_persist_enabled` | When `SLACK_DELETE_THINKING=false` and `THINKING_SHOW_ELAPSED=true`, `_deliver_slack` receives `existing_ts=None` |
| `test_slack_nonstream_persist_disabled` | When `SLACK_DELETE_THINKING=false` and `THINKING_SHOW_ELAPSED=false`, `_deliver_slack` receives `existing_ts=ts` |
| `test_slack_delete_overrides_persist` | When `SLACK_DELETE_THINKING=true`, thinking message is deleted regardless of `THINKING_SHOW_ELAPSED` |
| `test_slack_stream_persist_unchanged` | Streaming path still passes `final_ts` regardless of setting |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_forward_to_ai_thinking_persists` | Integration test: full `forward_to_ai` call → thinking message retains `🤖 Thought for Xs` and response is a separate `reply_text` |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target:
no uncovered branches in the changed lines.

---

## Documentation Updates

### `README.md`

No new features or env vars to add. Optionally clarify the `THINKING_SHOW_ELAPSED` description:

```markdown
| `THINKING_SHOW_ELAPSED` | `true` | When enabled, the thinking placeholder is updated to "🤖 Thought for Xs" and persists; the AI response is sent as a separate message. |
```

### `.env.example` and `docker-compose.yml.example`

No changes needed — `THINKING_SHOW_ELAPSED` is already documented if present. If not present, add:

```bash
# Persist thinking message with elapsed time after AI responds. (default: true)
# THINKING_SHOW_ELAPSED=true
```

### `docs/roadmap.md`

Add entry under Technical Debt (this is a bug fix, not a new feature).

### `docs/features/thinking-persist.md`

Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.

---

## Version Bump

**Expected bump for this feature**: `PATCH` → `0.18.1`

This is a bug fix: the code now matches the documented intent of `THINKING_SHOW_ELAPSED`. No new env vars, no breaking changes, no new commands.

---

## Roadmap Update

When complete, add to Technical Debt in `docs/roadmap.md`:

```markdown
| 1.1 | ✅ Persistent thinking message — fix non-streaming path to preserve "🤖 Thought for Xs" | [→ features/thinking-persist.md](features/thinking-persist.md) |
```

---

## Edge Cases and Open Questions

1. **Fast responses (< `THINKING_SLOW_THRESHOLD_SECS`)** — If the AI responds before the ticker fires, the message stays as `🤖 Thinking…`. With persist enabled, `finalize_thinking()` edits it to `🤖 Thought for 2s`, which is a useful signal. No issue.

2. **Empty response** — `_deliver_telegram` handles empty text by posting `_(empty response)_`. With persist enabled, the user sees `🤖 Thought for Xs` followed by `_(empty response)_`. Acceptable — the thinking time is still useful context.

3. **Very long responses (file upload fallback)** — When the response exceeds `_TG_MAX_CHUNKS` (Telegram) or `_SLACK_SNIPPET_THRESHOLD` (Slack), the delivery function uploads a file. With `streaming_msg=None`, the file upload note is posted as a new message alongside the persisted thinking message. No conflict.

4. **`gate restart` interaction** — No impact. `gate restart` clears the backend; the thinking message lifecycle is already complete by the time the response is delivered.

5. **Slack thread scope** — The new response message inherits `thread_ts` from the delivery call, same as today. No change.

6. **Telegram group rate limits** — Adding one extra message per prompt in non-streaming mode (20 messages/minute per group). For typical usage (a few prompts per minute), this is well within limits. For automated/bot-driven usage with rapid-fire prompts, the extra message could contribute to rate limiting, but `THINKING_SHOW_ELAPSED=false` can opt out.

7. **Message ordering** — `finalize_thinking()` is `await`ed before `_deliver_*` is called, so the thinking message is always updated before the response message is created. No race condition.

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] Thinking message persists as `🤖 Thought for Xs` in non-streaming mode on Telegram (when `THINKING_SHOW_ELAPSED=true`).
- [ ] Thinking message persists as `🤖 Thought for Xs` in non-streaming mode on Slack (when `SLACK_DELETE_THINKING=false` and `THINKING_SHOW_ELAPSED=true`).
- [ ] Thinking message is overwritten by AI response when `THINKING_SHOW_ELAPSED=false` (both platforms).
- [ ] `SLACK_DELETE_THINKING=true` still deletes the thinking message regardless of `THINKING_SHOW_ELAPSED`.
- [ ] Streaming mode behaviour is unchanged on both platforms.
- [ ] `docs/roadmap.md` entry added.
- [ ] `docs/features/thinking-persist.md` status changed to `Implemented` after merge.
- [ ] `VERSION` file bumped to `0.18.1`.
- [ ] Feature works with **all AI backends** (`copilot`, `codex`, `api`).
- [ ] Edge cases in the section above are resolved and either handled or documented.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
