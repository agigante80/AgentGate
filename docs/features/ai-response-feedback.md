# AI Response Feedback & Timeout Handling

> Status: **Planned** | Priority: High

Provide live progress updates while the AI is thinking (periodic "Still thinking…" edits) and enforce a configurable hard timeout across all backends uniformly at the platform layer.

---

## ⚠️ Prerequisite Questions

> Answer these before writing a single line of code. A wrong assumption costs 10× more to fix than a clarification takes.

1. **Scope** — Both platforms. The "Thinking…" message pattern and timeout logic appear in both `src/bot.py` (Telegram) and `src/platform/slack.py`. Both must be updated — see platform symmetry note in Architecture Notes.
2. **Backend** — All backends (`copilot`, `codex`, `api`). The timeout is applied at the platform layer wrapping the backend call, so all backends gain timeout coverage for free.
3. **Stateful vs stateless** — Both. The timeout wraps `backend.send()` / `backend.stream()` regardless of `is_stateful`. No backend-internal changes are needed (except removing `CopilotSession.TIMEOUT`).
4. **Breaking change?** — Soft yes. The existing `TIMEOUT = 180` constant in `src/ai/session.py` is removed; the default is raised to `AI_TIMEOUT_SECS=360`. Existing deployments that relied on the 180s limit will silently get 360s. This is intentionally more permissive. Consider whether to document this as a behaviour change in the release notes.
5. **New dependency?** — No. `asyncio.wait_for()` and `contextlib.suppress` are stdlib.
6. **Persistence** — No new DB table or file.
7. **Auth** — No new credential.
8. **Mid-stream stall** — Does the ticker restart if a stream stalls after the first chunk? **No** — this is documented as out of scope (see Open Questions item 4). The ticker covers the pre-first-chunk phase only.

---

## Problem Statement

When an AI backend takes longer than a few seconds to respond, users currently see a static
"🤖 Thinking…" message with no indication of progress, elapsed time, or expected wait. This
creates three related pain points:

1. **Silent waiting** — the user has no feedback after the initial message; they cannot
   distinguish a slow response from a crashed or stalled process.
2. **Abrupt timeout** — the Copilot backend has a hardcoded 180-second limit in
   `CopilotSession`. If exceeded, the user sees `⚠️ Copilot timed out after 180s.` with no
   prior warning. 360 seconds (or no limit at all) may be more appropriate for complex tasks.
   Critically, `DirectAPIBackend` and `CodexBackend` have **no timeout at all**.
3. **`gate status` is reactive, not proactive** — the command correctly shows elapsed time,
   but requires the user to remember to ask. Most users won't know to do this, especially on
   mobile.

---

## Current Behaviour (as of v0.7.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Telegram streaming | `src/bot.py:54` (`_stream_to_telegram`) | Posts "🤖 Thinking…", edits with arriving chunks |
| Telegram non-streaming | `src/bot.py:134` (`_run_ai_pipeline`) | Posts "🤖 Thinking…", single edit when response arrives |
| Slack streaming | `src/platform/slack.py:101` (`_stream_to_slack`) | `say(_THINKING)` then `chat_update()` with chunks |
| Slack non-streaming | `src/platform/slack.py:140` (`_run_ai_pipeline`) | `say(_THINKING)` then `chat_update()` when done |
| `_THINKING` constant | `src/platform/slack.py:36` | `_THINKING = "🤖 Thinking…"` |
| Timeout (Copilot only) | `src/ai/session.py:15,40` | `TIMEOUT = 180` module constant; `asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)` |
| Timeout (Direct API) | `src/ai/direct.py` | **No timeout** — relies entirely on provider HTTP client defaults |
| Timeout (Codex) | `src/ai/codex.py` | **No timeout** — `proc.communicate()` with no `wait_for` |
| Status cmd | `src/bot.py:222-229` | Shows elapsed time per active prompt on demand; queries `_active_ai` dict |
| Streaming config | `src/config.py` (`BotConfig`) | `stream_responses: bool = True`, `stream_throttle_secs: float = 1.0` |

**Key architectural gap**: the 180s timeout lives inside `CopilotSession.send()`, deep inside
the AI stack. It is only reachable via the Copilot backend. There is no platform-level timeout
that covers all backends uniformly. This needs to change — see Implementation Design below.

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints specific to this feature.

- **Platform symmetry is mandatory** — `src/bot.py` and `src/platform/slack.py` both contain `_stream_to_*` and `_run_ai_pipeline` methods. Every change to the ticker and timeout must be mirrored in both files. The shared helper `thinking_ticker()` should live in `src/platform/common.py` to avoid duplication.
- **Remove `TIMEOUT` from `CopilotSession`** — `src/ai/session.py` currently has `TIMEOUT = 180` and calls `asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)`. This must be removed entirely; do not leave it as a fallback. Otherwise, the Copilot backend will have a double-timeout (inner 180s + outer `AI_TIMEOUT_SECS`).
- **`asyncio.TimeoutError` vs `CancelledError`** — `asyncio.wait_for()` raises `asyncio.TimeoutError` (a subclass of `TimeoutError`). The inner coroutine receives `CancelledError`. Handle both at the right layer: catch `TimeoutError` at the platform layer (where you know what message to send the user); handle `CancelledError` inside `CopilotSession` to call `proc.kill()` before re-raising.
- **Zombie subprocess prevention** — Without an explicit `proc.kill()` in the `CancelledError` handler inside `CopilotSession`, the `copilot` subprocess continues running invisibly after a timeout. This is the highest-priority correctness issue in the entire implementation.
- **`is_stateful` flag** — not relevant here. The timeout wraps the outer `backend.send()` / `backend.stream()` call regardless of backend type. All three backends gain coverage.
- **`REPO_DIR` and `DB_PATH`** — not relevant to this feature.
- **`asyncio_mode = auto`** — all `async def test_*` functions run without `@pytest.mark.asyncio`.

---

## Design Space

### Axis 1 — Periodic Progress Updates

How often (and how) should the bot edit the "Thinking…" message to show elapsed time?

#### Option A — No change (status quo)
Static "🤖 Thinking…" until response arrives.

**Pros:** Simple. No extra messages. No API edit rate risk.  
**Cons:** User has zero feedback for long requests. Feels broken after ~10s.

---

#### Option B — Elapsed-time ticker (recommended baseline)
Edit the thinking message every N seconds with elapsed time.

```
🤖 Thinking… (30s)
🤖 Thinking… (60s)
🤖 Thinking… (90s)
```

**Env var:** `THINKING_UPDATE_SECS` (default: `30`)

**Pros:**
- Zero new messages — just edits the existing placeholder.
- Instant reassurance that the process is alive.
- A background `asyncio.Task` running alongside the AI call in `_run_ai_pipeline()`.
- Low API call rate (one edit per 30s by default).

**Cons:**
- Requires careful task cancellation when the response arrives to avoid a race condition on
  the final message edit.
- On Telegram, rapid edits can trigger rate-limiting (not a concern at 30s intervals).

---

#### Option C — Milestone messages (verbose)
Post a new message at each milestone rather than editing.

```
🤖 Thinking…
⏳ Still thinking (30s elapsed)…
⏳ Still thinking (60s elapsed)…
```

**Pros:** Cannot be "lost" if the original thinking message scrolls up in a busy channel.  
**Cons:** Pollutes chat history. Worse in Slack where threads fill up. Annoying for fast
responses that still cross the 30s threshold.

---

#### Option D — Single update at threshold
Edit the message **once** after a configurable threshold (e.g., 15s), then leave it.

```
🤖 Thinking…
→ after 15s:
⏳ Still working on it… (this may take a minute)
```

**Env var:** `THINKING_SLOW_THRESHOLD_SECS` (default: `15`)

**Pros:** Low noise. Covers the common case (user thinks bot is broken after 15s of silence).  
**Cons:** No ongoing reassurance for 2–3 minute requests. User still doesn't know if it's
alive at 90s.

---

#### Option E — Hybrid: threshold + ticker
Edit once at threshold, then tick every N seconds thereafter.

```
🤖 Thinking…
→ 15s: ⏳ Still thinking… (15s)
→ 45s: ⏳ Still thinking… (45s)
→ 75s: ⏳ Still thinking… (75s)
```

**Env var:** `THINKING_SLOW_THRESHOLD_SECS=15`, `THINKING_UPDATE_SECS=30`

**Pros:** Best UX — quiet for fast responses, informative for slow ones.  
**Cons:** Two new config values. Slightly more complex task management.

**Recommendation: Option E** — best balance of noise vs. reassurance.

---

### Axis 2 — Timeout Behaviour

What should happen when an AI backend takes too long?

#### Option 1 — Hardcoded 180s (status quo, Copilot backend only)
```python
TIMEOUT = 180  # src/ai/session.py:15
```

**Pros:** Simple. Protects against zombie processes.  
**Cons:** Wrong default for complex tasks. Applies only to `CopilotBackend` — `DirectAPIBackend`
and `CodexBackend` have zero timeout. Users are silently punished for real work.

---

#### Option 2 — Configurable timeout, default 360s
```python
TIMEOUT = int(os.getenv("AI_TIMEOUT_SECS", "360"))
```

**Pros:**
- Doubles the current window, covering most real-world slow responses.
- Operator-adjustable for unusually large repos or slow machines.
- Still protects against truly stalled processes.

**Cons:** Still arbitrary. A 361-second request will silently fail. No user warning before
the cut-off. Still only covers Copilot if placed in `session.py`.

---

#### Option 3 — No timeout (unlimited)
```python
await proc.communicate()  # no asyncio.wait_for()
```

**Pros:**
- Never fails a legitimate long-running request.
- Correct for local/trusted deployments where you fully control the AI process.

**Cons:**
- A crashed or deadlocked backend will block the handler forever.
- The user cannot issue a new command while the old one is stuck.
- No way to recover without restarting the bot.
- **Not safe as a default** for production or shared deployments.

---

#### Option 4 — Configurable timeout + pre-timeout warning *(recommended)*
At `(TIMEOUT - WARN_SECS)` the ticker message includes a cancellation warning. Cancel on
timeout with a clear error message.

```
⏳ Still thinking… (290s) — approaching time limit, will cancel in 70s
→ 360s: ⚠️ Request cancelled after 360s. Use `gate status` to check for stuck processes.
```

**Env vars:** `AI_TIMEOUT_SECS=360`, `AI_TIMEOUT_WARN_SECS=60`

**Implemented at the platform layer** (`_run_ai_pipeline` in `bot.py` / `slack.py`) via
`asyncio.wait_for()` wrapping the entire AI call. This covers **all backends uniformly**,
not just Copilot.

**Pros:**
- User gets advance notice before cancellation.
- Graceful UX — not a surprise error.
- Backend-agnostic: DirectAPIBackend and CodexBackend gain timeout coverage for free.

**Cons:** More complexity. Two more config values. Warning message content needs care.

---

#### Option 5 — Tiered: soft timeout + hard timeout
`SOFT_TIMEOUT`: bot sends a warning and asks user if they want to keep waiting (inline button
on Telegram, reaction/message on Slack). `HARD_TIMEOUT`: unconditional kill.

```
→ 180s: ⚠️ AI is taking a long time. [Keep waiting] [Cancel]
→ 360s: ⚠️ Hard timeout reached. Request cancelled.
```

**Pros:** User has agency. Excellent UX for interactive use.  
**Cons:** Complex to implement correctly (must handle button press race with response arrival).
The "keep waiting" path essentially just resets the soft timeout. Works poorly when user is
away from their phone (original use case: remote machine control from mobile).

---

## Recommended Solution

Combine **Option E** (progress ticker) with **Option 4** (configurable timeout + pre-warning):

```
🤖 Thinking…
→ 15s:  ⏳ Still thinking… (15s)
→ 45s:  ⏳ Still thinking… (45s)
→ 290s: ⏳ Still thinking… (290s) — approaching 360s time limit, will cancel in 70s
→ 360s: ⚠️ Request cancelled after 360s. Use /gate status if the process appears stuck.
```

### New env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_TIMEOUT_SECS` | `360` | Hard timeout for any AI backend (0 = no timeout) |
| `THINKING_SLOW_THRESHOLD_SECS` | `15` | Seconds before first elapsed-time update |
| `THINKING_UPDATE_SECS` | `30` | Interval between subsequent ticker updates |
| `AI_TIMEOUT_WARN_SECS` | `60` | Seconds before hard timeout to show a cancellation warning |

Setting `AI_TIMEOUT_SECS=0` disables the timeout entirely (trust your backend, accept the
risk of a stalled handler).

---

## Implementation Design

### Step 1 — `src/config.py`

Add to `BotConfig`:

```python
ai_timeout_secs: int = 360                # 0 = no timeout; env: AI_TIMEOUT_SECS
thinking_slow_threshold_secs: int = 15   # env: THINKING_SLOW_THRESHOLD_SECS
thinking_update_secs: int = 30           # env: THINKING_UPDATE_SECS
ai_timeout_warn_secs: int = 60           # env: AI_TIMEOUT_WARN_SECS
```

All four fields must go into `BotConfig` (not `AIConfig`) because they affect message
presentation, not the AI backend itself.

---

### Step 2 — `src/platform/common.py` — add `thinking_ticker()`

This is a backend-agnostic `asyncio.Task` function. Add to `common.py` (already shared
between Telegram and Slack). New imports required: `asyncio`, `time`, `Callable`, `Awaitable`
from `collections.abc`.

```python
import asyncio
import time
from collections.abc import Awaitable, Callable


async def thinking_ticker(
    edit_fn: Callable[[str], Awaitable[None]],
    slow_threshold: int,
    update_interval: int,
    timeout_secs: int,
    warn_before_secs: int,
) -> None:
    """Background task: edits the 'Thinking…' placeholder with elapsed time.

    Sleeps for slow_threshold seconds first (Option E: quiet for fast responses).
    After that, edits every update_interval seconds.
    When timeout is set and remaining time <= warn_before_secs, adds a cancellation warning.
    Cancelled externally when the AI call completes or is timed out.
    """
    start = time.monotonic()
    await asyncio.sleep(slow_threshold)
    while True:
        elapsed = int(time.monotonic() - start)
        if timeout_secs > 0:
            remaining = timeout_secs - elapsed
            if remaining <= warn_before_secs:
                text = f"⏳ Still thinking… ({elapsed}s) — will cancel in {remaining}s"
            else:
                text = f"⏳ Still thinking… ({elapsed}s)"
        else:
            text = f"⏳ Still thinking… ({elapsed}s)"
        await edit_fn(text)
        await asyncio.sleep(update_interval)
```

---

### Step 3 — `src/bot.py` — non-streaming path

The non-streaming path in `_run_ai_pipeline` (around line 133) becomes:

```python
from contextlib import suppress  # add to top-level imports
from src.platform.common import thinking_ticker  # add to top-level imports

# inside _run_ai_pipeline, non-streaming branch:
msg = await update.effective_message.reply_text("🤖 Thinking…")
cfg = self._settings.bot
ticker = asyncio.create_task(
    thinking_ticker(
        edit_fn=msg.edit_text,
        slow_threshold=cfg.thinking_slow_threshold_secs,
        update_interval=cfg.thinking_update_secs,
        timeout_secs=cfg.ai_timeout_secs,
        warn_before_secs=cfg.ai_timeout_warn_secs,
    )
)
try:
    if cfg.ai_timeout_secs > 0:
        response = await asyncio.wait_for(
            self._backend.send(prompt), timeout=cfg.ai_timeout_secs
        )
    else:
        response = await self._backend.send(prompt)
except asyncio.TimeoutError:
    await msg.edit_text(
        f"⚠️ Request cancelled after {cfg.ai_timeout_secs}s. "
        "Use /gate status to check if the process is stuck."
    )
    return
finally:
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

**Important**: the timeout is applied here at the platform layer via `asyncio.wait_for()`,
not inside `backend.send()`. This makes it backend-agnostic. `AICLIBackend.send()` signature
**does not change** — no `timeout_secs` argument is added to the ABC or any backend.

---

### Step 4 — `src/bot.py` — streaming path (`_stream_to_telegram`)

For streaming, the ticker must stop when the first chunk arrives. If the ticker has not yet
fired when the first chunk lands, it is cancelled silently. This means the ticker only fires
for slow-to-first-token streams. The timeout wraps the entire streaming coroutine.

```python
async def _stream_to_telegram(
    update: Update,
    backend: AICLIBackend,
    prompt: str,
    max_chars: int,
    throttle_secs: float = 1.0,
    timeout_secs: int = 0,
    slow_threshold: int = 15,
    update_interval: int = 30,
    warn_before_secs: int = 60,
) -> str:
    msg = await update.effective_message.reply_text("🤖 Thinking…")
    accumulated = ""
    last_edit = time.monotonic()
    first_chunk = True

    ticker = asyncio.create_task(
        thinking_ticker(
            edit_fn=msg.edit_text,
            slow_threshold=slow_threshold,
            update_interval=update_interval,
            timeout_secs=timeout_secs,
            warn_before_secs=warn_before_secs,
        )
    )

    async def _stream_body() -> str:
        nonlocal accumulated, last_edit, first_chunk
        async for chunk in backend.stream(prompt):
            if first_chunk:
                ticker.cancel()  # first token arrived — stop ticker
                first_chunk = False
            accumulated += chunk
            now = time.monotonic()
            if now - last_edit >= throttle_secs:
                display = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
                try:
                    await msg.edit_text(display + " ▌")
                except Exception:
                    logger.debug("Telegram edit skipped")
                last_edit = now
        return accumulated

    try:
        if timeout_secs > 0:
            await asyncio.wait_for(_stream_body(), timeout=timeout_secs)
        else:
            await _stream_body()
    except asyncio.TimeoutError:
        await msg.edit_text(
            f"⚠️ Stream cancelled after {timeout_secs}s. "
            "Use /gate status to check for stuck processes."
        )
        return ""
    finally:
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker

    final = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
    try:
        await msg.edit_text(final or "_(empty response)_")
    except Exception:
        logger.debug("Telegram final edit skipped")
    return final
```

Call site in `_run_ai_pipeline` passes the new config values:
```python
response = await _stream_to_telegram(
    update, self._backend, prompt,
    self._settings.bot.max_output_chars,
    self._settings.bot.stream_throttle_secs,
    timeout_secs=self._settings.bot.ai_timeout_secs,
    slow_threshold=self._settings.bot.thinking_slow_threshold_secs,
    update_interval=self._settings.bot.thinking_update_secs,
    warn_before_secs=self._settings.bot.ai_timeout_warn_secs,
)
```

---

### Step 5 — `src/platform/slack.py` — both paths

Slack uses `self._edit(client, channel, ts, text)` instead of `msg.edit_text(text)`. The
pattern is identical to Telegram; the `edit_fn` lambda captures the right references:

**Non-streaming** (around line 140):
```python
resp = await say(_THINKING)
ts = resp["ts"]
cfg = self._settings.bot
ticker = asyncio.create_task(
    thinking_ticker(
        edit_fn=lambda text: self._edit(client, channel, ts, text),
        slow_threshold=cfg.thinking_slow_threshold_secs,
        update_interval=cfg.thinking_update_secs,
        timeout_secs=cfg.ai_timeout_secs,
        warn_before_secs=cfg.ai_timeout_warn_secs,
    )
)
try:
    if cfg.ai_timeout_secs > 0:
        response = await asyncio.wait_for(
            self._backend.send(prompt), timeout=cfg.ai_timeout_secs
        )
    else:
        response = await self._backend.send(prompt)
except asyncio.TimeoutError:
    await self._edit(client, channel, ts,
        f"⚠️ Request cancelled after {cfg.ai_timeout_secs}s.")
    return
finally:
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

**Streaming** (`_stream_to_slack`): same first-chunk cancellation pattern as Telegram,
with `self._edit(client, channel, ts, text)` as the edit function. Also wrap the stream
body in `asyncio.wait_for()` when `ai_timeout_secs > 0`.

Add `from contextlib import suppress` to the top of `slack.py`.

---

### Step 6 — `src/ai/session.py` — remove or raise the internal timeout

With a platform-level `asyncio.wait_for()` wrapping all backends, the `TIMEOUT = 180`
module constant in `session.py` is now a secondary failsafe. The recommended approach is:

**Option A (preferred):** Remove the `TIMEOUT` constant and the internal `asyncio.wait_for`
entirely. Rely solely on the platform-level timeout. Simplifies `CopilotSession.send()`.

**Option B (conservative):** Keep it, but raise it to a value that will never fire before
the platform timeout (e.g., `TIMEOUT = 600`). Acts as a last-resort zombie killer if the
platform-level timeout somehow fails to propagate.

The implementation should choose **Option A** — one timeout, one place.

Changed `CopilotSession.send()`:
```python
async def send(self, prompt: str) -> str:
    try:
        proc = await self._spawn(self._build_cmd(prompt), self._env)
        stdout, stderr = await proc.communicate()  # no wait_for — platform layer handles it
    except Exception as exc:
        logger.exception("Copilot subprocess error")
        return f"⚠️ Session error: {exc}"
    if proc.returncode != 0:
        err = stderr.decode().strip() or stdout.decode().strip()
        logger.error("copilot CLI error (rc=%d): %s", proc.returncode, err)
        return f"⚠️ Copilot error (rc={proc.returncode}):\n{err}"
    return _strip_stats(stdout.decode())
```

Note: when `asyncio.wait_for()` times out at the platform level, it cancels the
`CopilotSession.send()` coroutine, which propagates a `CancelledError` into `proc.communicate()`.
`proc` is then an orphaned subprocess. Add a `try/finally` to kill the process on cancellation:

```python
async def send(self, prompt: str) -> str:
    proc = None
    try:
        proc = await self._spawn(self._build_cmd(prompt), self._env)
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        raise  # re-raise so the platform timeout handler sees it as TimeoutError
    except Exception as exc:
        logger.exception("Copilot subprocess error")
        return f"⚠️ Session error: {exc}"
    ...
```

---

### Step 7 — Tests

**`tests/unit/test_session.py`**
- Remove test for internal 180s timeout (no longer applicable).
- Add test: `send()` re-raises `CancelledError` and calls `proc.kill()`.

**New `tests/unit/test_thinking_ticker.py`** (or extend `test_common.py`):
- `test_ticker_fires_after_threshold` — verify edit_fn not called before threshold.
- `test_ticker_fires_at_interval` — verify edit_fn called every `update_interval` seconds.
- `test_ticker_warn_message` — verify warning text appears when remaining ≤ warn_before_secs.
- `test_ticker_no_timeout` — verify no warning when `timeout_secs=0`.
- `test_ticker_cancelled_immediately` — verify cancellation before threshold yields zero edits.

**`tests/unit/test_bot.py`**
- Add test: ticker is cancelled when non-streaming `send()` completes normally.
- Add test: ticker is cancelled when non-streaming `send()` raises `TimeoutError`.
- Add test: ticker is cancelled on first streaming chunk.
- Add test: `_run_ai_pipeline` posts correct timeout error message.

**`tests/unit/test_slack.py`** (if it exists) or new file:
- Mirror the bot.py ticker tests for Slack's `_run_ai_pipeline`.

---

## Scenarios

### Scenario 1 — Fast response (< 15s)
User sends a prompt. AI replies in 8 seconds.
- Ticker is created, sleeps for 15s, but backend returns in 8s.
- Ticker is cancelled during the `finally` block before it ever edits the message.
- UX identical to today. ✅

### Scenario 2 — Medium response (15–60s)
Prompt takes 40 seconds. Ticker fires at 15s and 45s.
- User sees "⏳ Still thinking… (15s)" then "⏳ Still thinking… (45s)".
- Response arrives at 40s — ticker cancelled in `finally`, response replaces the message. ✅

### Scenario 3 — Long response (60–300s)
Copilot is rewriting a large file. Takes 4 minutes.
- Ticker fires at 15, 45, 75, 105, 135, 165, 195, 225 seconds.
- At 300s (360−60=300s elapsed), remaining ≤ warn_before_secs → message shifts to warning.
- Response arrives at 240s — ticker cancelled, response shown normally. ✅

### Scenario 4 — Hard timeout (360s)
Backend stalls completely. Ticker runs and shows warning at 300s.
- At 360s: `asyncio.wait_for()` raises `TimeoutError` in `_run_ai_pipeline`.
- Ticker is cancelled in `finally`. Error message is edited into the message. ✅
- For CopilotBackend: the `CancelledError` propagates into `CopilotSession.send()`, which
  calls `proc.kill()` on the stalled subprocess. No zombie process. ✅

### Scenario 5 — No timeout (`AI_TIMEOUT_SECS=0`)
Power user running a very long analysis. `ai_timeout_secs = 0`.
- `asyncio.wait_for()` is not called (the `if timeout_secs > 0` guard skips it).
- Ticker runs indefinitely (every 30s), with no warning message variant.
- User knows the bot is alive. Accepts the risk of no hard kill. ✅

### Scenario 6 — Streaming backend with fast first token
`DirectAPIBackend` (streaming), first chunk arrives in 2s.
- Ticker is created but sleeps for 15s (threshold).
- First chunk arrives at 2s → ticker is cancelled immediately, before it ever edits.
- Stream proceeds with normal chunk-edit cycle. Ticker never touches the message. ✅

### Scenario 7 — Streaming backend with slow first token
API backend is under load. First token takes 30s.
- Ticker fires at 15s → "⏳ Still thinking… (15s)" edit.
- At 30s first chunk arrives → ticker is cancelled mid-sleep.
- Stream then takes over editing the message with content. ✅

### Scenario 8 — Streaming stall mid-response
A streaming response delivers 3 chunks then stalls for 60s (e.g., network issue).
- After the 3rd chunk, first_chunk is already `False`, so ticker was already cancelled.
- **The ticker does NOT help here** — it was cancelled on the first chunk.
- The overall `asyncio.wait_for()` wrapping the entire stream body will fire at the
  configured `AI_TIMEOUT_SECS`. The timeout error is shown, and the partial response is lost.
- This is an acceptable trade-off. A mid-stream stall detector would need a different
  mechanism (heartbeat coroutine monitoring the last-chunk timestamp) — out of scope here.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add 4 new `BotConfig` fields |
| `src/platform/common.py` | **Edit** | Add `thinking_ticker()` async helper; add `asyncio`, `time`, `Callable`, `Awaitable` imports |
| `src/bot.py` | **Edit** | Add `from contextlib import suppress`; refactor `_stream_to_telegram()` signature; add ticker + `asyncio.wait_for()` to both streaming and non-streaming paths in `_run_ai_pipeline()` |
| `src/platform/slack.py` | **Edit** | Add `from contextlib import suppress`; add ticker + `asyncio.wait_for()` to both paths in `_stream_to_slack()` and `_run_ai_pipeline()` |
| `src/ai/session.py` | **Edit** | Remove `TIMEOUT = 180`; remove internal `asyncio.wait_for()`; add `CancelledError` handler that calls `proc.kill()` before re-raising |
| `README.md` | **Edit** | Add 4 new env vars to the **Bot Behaviour** table (both Telegram and Slack sections) |
| `tests/unit/test_session.py` | **Edit** | Remove old timeout tests; add `CancelledError` + `proc.kill()` test |
| `tests/unit/test_thinking_ticker.py` | **Create** | 5+ unit tests for `thinking_ticker()` |
| `tests/unit/test_bot.py` | **Edit** | Add ticker lifecycle tests (normal, timeout, streaming first-chunk cancel) |
| `docs/features/ai-response-feedback.md` | **Edit** | Mark status as `Implemented` after merge to `main` |
| `docs/roadmap.md` | **Edit** | Add entry and mark done (✅) after merge |

**No changes to:**
- `src/ai/adapter.py` — `AICLIBackend.send()` signature is **unchanged**
- `src/ai/copilot.py` — delegates to `CopilotSession`; no changes needed at this layer
- `src/ai/direct.py` — timeout now applied at platform layer; no internal changes needed
- `src/ai/codex.py` — same; gains timeout coverage for free

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `asyncio` | ✅ stdlib | `asyncio.wait_for()`, `asyncio.CancelledError`, `asyncio.Task` |
| `contextlib` | ✅ stdlib | `contextlib.suppress(CancelledError)` for clean ticker cancellation |
| `time` | ✅ stdlib | `time.monotonic()` for elapsed-time tracking in ticker |

> No new pip packages required. All dependencies are Python stdlib.

---

## Test Plan

### `tests/unit/test_thinking_ticker.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_ticker_fires_after_threshold` | Ticker callback is called after `slow_threshold_secs` |
| `test_ticker_updates_at_interval` | Callback called again after each `update_secs` interval |
| `test_ticker_cancelled_cleanly` | Cancelling the ticker task does not raise or leave state |
| `test_ticker_sends_warning_near_timeout` | Warning message includes timeout countdown when within `warn_secs` |
| `test_ticker_zero_threshold_fires_immediately` | If `slow_threshold_secs=0`, first update fires immediately |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_run_ai_pipeline_timeout` | `asyncio.TimeoutError` sends the timeout error message and cancels ticker |
| `test_run_ai_pipeline_ticker_cancelled_on_complete` | Ticker task is cancelled when AI responds normally |
| `test_stream_to_telegram_first_chunk_cancels_ticker` | First streaming chunk cancels the ticker |

### `tests/unit/test_session.py` modifications

| Test | What it changes |
|------|----------------|
| Remove `test_timeout_*` tests | Old internal timeout tests no longer valid after `TIMEOUT` removal |
| `test_cancelled_error_kills_proc` | `CancelledError` inside `send()` calls `proc.kill()` before re-raising |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target: 100% branch coverage on `thinking_ticker()` in `platform/common.py`. Ticker cancellation paths and warning branch must both be exercised.

---

## Documentation Updates

### `README.md`

Add to the **Bot Behaviour** environment variable table (in both Telegram and Slack sections):

```markdown
| `AI_TIMEOUT_SECS` | `360` | Hard timeout for any AI backend in seconds (0 = no timeout) |
| `THINKING_SLOW_THRESHOLD_SECS` | `15` | Seconds of silence before first "Still thinking…" update |
| `THINKING_UPDATE_SECS` | `30` | Seconds between subsequent elapsed-time updates |
| `AI_TIMEOUT_WARN_SECS` | `60` | Seconds before hard timeout to include a cancellation warning |
```

### `.github/copilot-instructions.md`

Add a note to the `src/platform/common.py` description:

> `thinking_ticker()` — async background task that edits the "Thinking…" message with elapsed time; started by both bots during `_run_ai_pipeline()`.

### `docs/roadmap.md`

This feature is not currently listed in `docs/roadmap.md`. Add it to the Features table:

```markdown
| 2.10 | AI response feedback — proactive "Still thinking…" ticker and configurable per-backend timeout | [→ features/ai-response-feedback.md](features/ai-response-feedback.md) |
```

After merge to `main`, mark it done (✅).

### `docs/features/ai-response-feedback.md`

Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`. Add `Implemented in: v0.8.0` below the status line.

---

## Open Questions

1. **Should the ticker message also show the active prompt text?**
   e.g., `⏳ Still thinking about "refactor auth module"… (45s)`
   Avoids confusion when multiple requests are queued (rare but possible). Risks leaking
   sensitive prompt content into what is visible in a shared Slack channel.

2. **Should `gate status` be retired or enhanced?**
   With proactive tickers, `gate status` becomes less immediately useful. Options:
   - Keep as-is (still useful if the user dismissed the thinking message, or when using CLI).
   - Enhance to also show the current ticker message / estimated time to timeout.
   - Retire it and redirect to `gate info` (which shows active AI task count).

3. **Rate limits on Telegram edits:**
   Telegram allows ~20 edits/minute per chat. At `THINKING_UPDATE_SECS=30`, peak rate is
   2/minute — well within limits. At `THINKING_UPDATE_SECS=5` it would be 12/minute — still
   safe. Warn in docs that values below 5 are inadvisable.

4. **Mid-stream stall detection (future scope):**
   Scenario 8 shows that a stall after the first chunk arrives is not covered by the ticker.
   A future enhancement could run a "last-chunk heartbeat" coroutine that re-arms the ticker
   if no chunk arrives within N seconds of the previous one. Out of scope for this feature.

5. **Interaction with copilot pre-warm feature:**
   If `COPILOT_PREWARM_PROMPT` is set (see `docs/features/copilot-prewarm.md`), the cold-
   start delay is reduced. This may lower the effective `THINKING_SLOW_THRESHOLD_SECS` needed
   in practice, but doesn't change the implementation here.

6. **Zombie subprocess risk when `CancelledError` propagates through `proc.communicate()`:**
   Python's `asyncio` does not automatically kill child processes when a coroutine is
   cancelled. Without the explicit `proc.kill()` in the `CancelledError` handler (Step 6),
   the `copilot` subprocess would continue running invisibly in the background. This is the
   most critical correctness issue in the entire implementation.

---

## Version Bump

Consult `docs/versioning.md` for the full decision guide. Quick reference:

| This feature… | Bump |
|---------------|------|
| Adds 4 new env vars with safe defaults | **MINOR** |
| Removes `TIMEOUT = 180` from `session.py` (raises Copilot timeout from 180s → 360s default) | **MINOR** (behaviour change, no API removal) |
| No env vars renamed or removed | Not MAJOR |

**Expected bump for this feature**: `MINOR` → `0.8.0` (from current `0.7.3`)

> Bump `VERSION` on `develop` _before_ the merge PR to `main`. Never edit `VERSION` directly on `main`.

---

## Roadmap Update

When this feature is complete, update `docs/roadmap.md` (add and mark done):

```markdown
| 2.10 | ✅ AI response feedback — proactive "Still thinking…" ticker and configurable per-backend timeout | [→ features/ai-response-feedback.md](features/ai-response-feedback.md) |
```

Stretch goal (if identified during implementation): mid-stream stall detection heartbeat (see Open Questions item 4). Add as a new row if warranted.

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` is updated with the 4 new env vars in both Telegram and Slack sections.
- [ ] `docs/roadmap.md` entry is added and marked done (✅).
- [ ] `docs/features/ai-response-feedback.md` status changed to `Implemented` on merge to `main`.
- [ ] `.github/copilot-instructions.md` updated with `thinking_ticker()` description.
- [ ] `VERSION` file bumped to `0.8.0` on `develop` before merge to `main`.
- [ ] `TIMEOUT = 180` constant is completely removed from `src/ai/session.py` (no remnants).
- [ ] No zombie subprocesses: `proc.kill()` is called in the `CancelledError` handler in `CopilotSession`.
- [ ] Ticker fires on both Telegram and Slack paths (test both platforms).
- [ ] Ticker is cancelled cleanly when the AI responds before the threshold — no spurious "Still thinking…" messages.
- [ ] `AI_TIMEOUT_SECS=0` disables the timeout entirely (test with a mock that never resolves).
- [ ] Feature works with all three AI backends (`copilot`, `codex`, `api`).
- [ ] Edge cases in the Open Questions section above are resolved and either handled or documented.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.

