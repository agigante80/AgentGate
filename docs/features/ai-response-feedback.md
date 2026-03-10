# AI Response Feedback & Timeout Handling

> Status: **Planned** | Priority: High

## Problem Statement

When an AI backend takes longer than a few seconds to respond, users currently see a static
"🤖 Thinking…" message with no indication of progress, elapsed time, or expected wait. This
creates two related pain points:

1. **Silent waiting** — the user has no feedback after the initial message; they cannot
   distinguish a slow response from a crashed or stalled process.
2. **Abrupt timeout** — the Copilot backend has a hardcoded 180-second limit. If exceeded,
   the user sees `⚠️ Copilot timed out after 180s.` with no prior warning. 360 seconds (or no
   limit at all) may be more appropriate for complex tasks.
3. **`gate status` is reactive, not proactive** — the command correctly shows elapsed time,
   but requires the user to think to ask. Most users won't know to do this.

---

## Current Behaviour (as of v0.7.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Telegram | `src/bot.py:54,134` | Posts "🤖 Thinking…", edits with chunks during streaming |
| Slack | `src/platform/slack.py:36,101,140` | Same pattern, `_THINKING = "🤖 Thinking…"` |
| Timeout | `src/ai/session.py:15,40` | `TIMEOUT = 180` hardcoded; `asyncio.wait_for()` |
| Status cmd | `src/bot.py:223-231` | Shows elapsed time per active prompt on demand |
| Streaming | `src/config.py:44-45` | `stream_responses`, `stream_throttle_secs=1.0` |

The `gate status` command does surface elapsed time, but only when the user explicitly asks.
Non-streaming (e.g., `CopilotBackend`) gives the user zero visibility until the response lands.

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
- Trivially implemented: a background `asyncio.Task` alongside `_run_ai_pipeline()`.
- Works for both streaming and non-streaming backends.
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
TIMEOUT = 180  # src/ai/session.py
```

**Pros:** Simple. Protects against zombie processes.  
**Cons:** Wrong default. Complex prompts (e.g., "refactor this 2000-line file") routinely
take 3–5 minutes. Users are silently punished for doing real work.

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
the cut-off.

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

#### Option 4 — Configurable timeout + pre-timeout warning
At `(TIMEOUT - WARNING_SECS)`, edit the thinking message with a warning. Cancel on timeout.

```
⏳ Still thinking… (290s) — approaching time limit, will cancel in 70s
→ 360s: ⚠️ Request cancelled after 360s. Use `gate status` to check for stuck processes.
```

**Env vars:** `AI_TIMEOUT_SECS=360`, `AI_TIMEOUT_WARN_SECS=70`

**Pros:**
- User gets advance notice before cancellation.
- Graceful UX — not a surprise error.
- Gives the user a chance to decide (they could cancel manually).

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
→ 290s: ⏳ Still thinking… (290s) — approaching 360s time limit
→ 360s: ⚠️ Request cancelled after 360s. Use /gate status if the process is stuck.
```

### New env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_TIMEOUT_SECS` | `360` | Hard timeout for AI subprocess (0 = no timeout) |
| `THINKING_SLOW_THRESHOLD_SECS` | `15` | Seconds before first elapsed-time update |
| `THINKING_UPDATE_SECS` | `30` | Interval between subsequent updates |
| `AI_TIMEOUT_WARN_SECS` | `60` | Warn this many seconds before hard timeout |

Setting `AI_TIMEOUT_SECS=0` disables the timeout entirely (trust your backend, accept the
risk of a stalled handler).

---

## Implementation Design

### `src/config.py`

Add to `BotConfig`:

```python
ai_timeout_secs: int = 360          # 0 = no timeout; env: AI_TIMEOUT_SECS
thinking_slow_threshold_secs: int = 15   # env: THINKING_SLOW_THRESHOLD_SECS
thinking_update_secs: int = 30           # env: THINKING_UPDATE_SECS
ai_timeout_warn_secs: int = 60           # env: AI_TIMEOUT_WARN_SECS
```

### `src/ai/session.py`

Replace hardcoded `TIMEOUT = 180` with a parameter:

```python
async def send(self, prompt: str, timeout_secs: int = 360) -> str:
    ...
    if timeout_secs > 0:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_secs
        )
    else:
        stdout, stderr = await proc.communicate()
```

### `src/platform/common.py` (new helper)

```python
async def thinking_ticker(
    edit_fn: Callable[[str], Awaitable[None]],
    slow_threshold: int,
    update_interval: int,
    timeout_secs: int,
    warn_before_secs: int,
) -> None:
    """Background task: edits the 'Thinking…' placeholder with elapsed time."""
    start = time.monotonic()
    await asyncio.sleep(slow_threshold)
    while True:
        elapsed = int(time.monotonic() - start)
        remaining = timeout_secs - elapsed if timeout_secs > 0 else None
        if remaining is not None and remaining <= warn_before_secs:
            msg = f"⏳ Still thinking… ({elapsed}s) — will cancel in {remaining}s"
        else:
            msg = f"⏳ Still thinking… ({elapsed}s)"
        await edit_fn(msg)
        await asyncio.sleep(update_interval)
```

### `src/bot.py` and `src/platform/slack.py`

In `_run_ai_pipeline()`, launch the ticker as a background task and cancel it when done:

```python
ticker = asyncio.create_task(
    thinking_ticker(
        edit_fn=lambda text: msg.edit_text(text),
        slow_threshold=settings.bot.thinking_slow_threshold_secs,
        update_interval=settings.bot.thinking_update_secs,
        timeout_secs=settings.bot.ai_timeout_secs,
        warn_before_secs=settings.bot.ai_timeout_warn_secs,
    )
)
try:
    result = await backend.send(prompt, timeout_secs=settings.bot.ai_timeout_secs)
finally:
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker
```

---

## Scenarios

### Scenario 1 — Fast response (< 15s)
User sends a prompt. AI replies in 8 seconds.
- Ticker never fires (threshold is 15s).
- UX identical to today. ✅

### Scenario 2 — Medium response (15–60s)
Prompt takes 40 seconds. Ticker fires at 15s and 45s.
- User sees "⏳ Still thinking… (15s)" then "⏳ Still thinking… (45s)".
- Response arrives, final edit replaces the ticker message. ✅

### Scenario 3 — Long response (60–300s)
Copilot is rewriting a large file. Takes 4 minutes.
- Ticker fires at 15, 45, 75, 105, 135, 165, 195, 225 seconds.
- At 300s (360-60=300), message shifts to "…will cancel in 60s".
- Response arrives at 240s — ticker cancelled, response shown. ✅

### Scenario 4 — Timeout (360s)
Backend stalls. Ticker runs until 300s warn message, then hard timeout at 360s.
- User sees clear warning 60s ahead of kill.
- `asyncio.TimeoutError` → `⚠️ Request cancelled after 360s.` ✅

### Scenario 5 — No timeout (`AI_TIMEOUT_SECS=0`)
Power user running a long analysis. No cancellation.
- Ticker runs indefinitely (every 30s).
- User knows the bot is alive. Accepts the risk of no hard kill. ✅

### Scenario 6 — Streaming backend
For streaming backends, chunks arrive continuously so the ticker is largely cosmetic.
- But: if the stream stalls mid-response, the ticker continues updating, alerting the user.
- The timeout still applies to the total stream duration (via `asyncio.wait_for` on the
  stream iterator). ✅

---

## Files to Change

| File | Change |
|------|--------|
| `src/config.py` | Add 4 new `BotConfig` fields |
| `src/ai/session.py` | Parameterise timeout; accept `timeout_secs` arg |
| `src/ai/adapter.py` | Update `AICLIBackend.send()` signature to accept `timeout_secs` |
| `src/ai/copilot.py` | Pass `timeout_secs` through to `CopilotSession` |
| `src/platform/common.py` | Add `thinking_ticker()` async helper |
| `src/bot.py` | Launch ticker in `_run_ai_pipeline()`; pass timeout to backend |
| `src/platform/slack.py` | Same as `bot.py` |
| `tests/unit/test_bot.py` | Tests for ticker task lifecycle |
| `tests/unit/test_session.py` | Tests for timeout=0 path and parameterised timeout |

---

## Open Questions

1. **Should the ticker message also show the active prompt text?**  
   e.g., `⏳ Still thinking about "refactor auth module"… (45s)`  
   Avoids confusion when multiple requests are queued (rare but possible).

2. **Should `gate status` be retired or enhanced?**  
   With proactive tickers, `gate status` becomes less useful. It could be kept for the
   case where the user dismissed the thinking message, or repurposed to show bot-wide health
   (memory, uptime, backend type).

3. **Rate limits on Telegram edits:**  
   Telegram allows ~20 edits/minute per chat. At 30s intervals, peak rate is 2/minute — well
   within limits. At `THINKING_UPDATE_SECS=5` it would be 12/minute — still fine.

4. **Direct API / Codex backends:**  
   `DirectAPIBackend` and `CodexBackend` have their own internal timeout/retry behaviour.
   The wrapper timeout in `session.py` only applies to `CopilotBackend`. A unified timeout
   wrapper should be considered at the `AICLIBackend` level.
