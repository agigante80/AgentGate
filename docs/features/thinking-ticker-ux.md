# Thinking ticker UX — human-readable elapsed time + no-timeout default (`AI_TIMEOUT_SECS`, `THINKING_*`)

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-13

Two small UX improvements to the "Still thinking…" ticker: elapsed time is shown in human-readable format after 60 seconds (e.g. `2m 5s` instead of `125s`), and the default hard timeout changes from 720s to 0 (no timeout) so long-running AI calls are never silently cancelled by default.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram and Slack). The ticker lives in `src/platform/common.py` and is shared.
2. **Backend** — All backends. The ticker is backend-agnostic.
3. **Stateful vs stateless** — No difference; the ticker wraps the AI call regardless of backend type.
4. **Breaking change?** — Yes, in a UX sense: changing `AI_TIMEOUT_SECS` default from `720` to `0` means existing deployments that relied on the 12-minute auto-cancel will no longer time out. Existing users who set `AI_TIMEOUT_SECS` explicitly are unaffected. **MINOR** bump only — no env var renamed or removed.
5. **New dependency?** — None.
6. **Persistence** — None.
7. **Auth** — None.
8. **Display threshold** — Human-readable format kicks in at 60s elapsed. Below 60s, seconds-only display is cleaner and more precise.

---

## Problem Statement

1. **Raw seconds are hard to read at scale** — `(725s)` requires mental arithmetic. `(12m 5s)` is immediately understood. After ~60s the seconds format loses utility.
2. **Default timeout of 720s silently cancels legitimate long-running tasks** — Model inference, large diffs, and slow Copilot sessions routinely exceed 12 minutes. The current default punishes users who didn't know to set `AI_TIMEOUT_SECS=0`.

---

## Current Behaviour (as of v0.10.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Config | `src/config.py:54` (`BotConfig`) | `ai_timeout_secs: int = 720` |
| Ticker | `src/platform/common.py:32–38` (`thinking_ticker`) | Always formats elapsed as `{elapsed}s` |
| Ticker | `src/platform/common.py:34–36` | Appends `— will cancel in {remaining}s` when `remaining <= warn_before_secs` |

> **Key gap**: elapsed time is always shown in raw seconds; the default timeout of 720s kills long-running requests without user action.

---

## Design Space

### Axis 1 — Human-readable format threshold

#### Option A — Always human-readable *(e.g. `0m 45s` from the start)*

**Pros:** Consistent format throughout.

**Cons:** `0m 5s` looks awkward for fast responses. Adds visual noise when seconds-only is clearer.

#### Option B — Switch at 60s *(recommended)*

Below 60s: `(45s)`. At 60s and above: `(1m 0s)`, `(2m 5s)`, etc.

**Pros:** Best of both worlds — precise for fast responses, readable for long ones.

**Cons:** Minor format discontinuity at 60s (acceptable and expected by users).

**Recommendation: Option B.**

---

### Axis 2 — Format of the human-readable string

#### Option A — `Xm Ys` *(e.g. `2m 5s`)*

Compact, no leading zeros, universally understood.

#### Option B — `X min Y sec`

More verbose, no gain in clarity.

**Recommendation: Option A — `Xm Ys`.**

---

### Axis 3 — Default timeout

#### Option A — Keep `720` *(status quo)*

No change for existing deployments.

#### Option B — Change default to `0` (no timeout) *(recommended)*

Long-running tasks succeed by default. Users who want a safety net set `AI_TIMEOUT_SECS` explicitly.

**Recommendation: Option B.** The `⚠️ Stream cancelled` surprise is worse than a potentially long wait; users can always set `AI_TIMEOUT_SECS` to add a cap.

---

## Recommended Solution

- **Axis 1**: Option B — switch to human format at 60s elapsed.
- **Axis 2**: Option A — `Xm Ys` format.
- **Axis 3**: Option B — default `ai_timeout_secs = 0`.

Add a `_format_elapsed(secs: int) -> str` helper to `src/platform/common.py`:

```python
def _format_elapsed(secs: int) -> str:
    """Return a human-readable elapsed time string."""
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m {s}s"
```

Replace raw `{elapsed}s` in `thinking_ticker` with `_format_elapsed(elapsed)`.
Do the same for `{remaining}s` in the cancellation-warning branch.

---

## Architecture Notes

- **Single change point** — `thinking_ticker` in `src/platform/common.py` is shared by both `src/bot.py` and `src/platform/slack.py`. Changing it once is sufficient; no mirroring needed.
- **`_format_elapsed` is module-level** — makes it directly testable without instantiating any class.
- **`asyncio_mode = auto`** — all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **`_clock` injection** — the existing `_clock` parameter enables time-travel in tests; use it rather than patching `time.monotonic`.

---

## Config Variables

| Env var | Type | Old default | New default | Description |
|---------|------|-------------|-------------|-------------|
| `AI_TIMEOUT_SECS` | `int` | `720` | `0` | Hard timeout in seconds for any AI call. `0` = no timeout. |

No new env vars are introduced. All other `THINKING_*` vars are unchanged.

> **Migration note**: deployments that relied on the 720s auto-cancel must now set `AI_TIMEOUT_SECS=720` explicitly.

---

## Implementation Steps

### Step 1 — `src/config.py`: change default

```python
# In BotConfig, change:
ai_timeout_secs: int = 720
# to:
ai_timeout_secs: int = 0               # Hard timeout for any AI backend (0 = no timeout); env: AI_TIMEOUT_SECS
```

---

### Step 2 — `src/platform/common.py`: add helper and update ticker

Add `_format_elapsed` as a module-level function (before `thinking_ticker`):

```python
def _format_elapsed(secs: int) -> str:
    """Return elapsed time as a human-readable string.

    Under 60s: '45s'. At 60s and above: '2m 5s'.
    """
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m {s}s"
```

In `thinking_ticker`, replace every `{elapsed}s` and `{remaining}s` occurrence:

```python
# Before:
text = f"⏳ Still thinking… ({elapsed}s) — will cancel in {remaining}s"
# ...
text = f"⏳ Still thinking… ({elapsed}s)"
# ...
text = f"⏳ Still thinking… ({elapsed}s)"

# After:
text = f"⏳ Still thinking… ({_format_elapsed(elapsed)}) — will cancel in {_format_elapsed(remaining)}"
# ...
text = f"⏳ Still thinking… ({_format_elapsed(elapsed)})"
# ...
text = f"⏳ Still thinking… ({_format_elapsed(elapsed)})"
```

There are 3 text-assignment lines inside `thinking_ticker` — all three must use `_format_elapsed`.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | `ai_timeout_secs` default `720` → `0` |
| `src/platform/common.py` | **Edit** | Add `_format_elapsed()`; update 3 format strings in `thinking_ticker` |
| `tests/unit/test_common.py` | **Create** | Unit tests for `_format_elapsed` + updated ticker text assertions |
| `README.md` | **Edit** | Update `AI_TIMEOUT_SECS` default in env var table |
| `docs/features/thinking-ticker-ux.md` | **Edit** | Mark `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Mark ✅ |

---

## Dependencies

None. All stdlib (`divmod` is a built-in).

---

## Test Plan

### `tests/unit/test_common.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_format_elapsed_under_60s` | `_format_elapsed(45)` → `"45s"` |
| `test_format_elapsed_exactly_60s` | `_format_elapsed(60)` → `"1m 0s"` |
| `test_format_elapsed_125s` | `_format_elapsed(125)` → `"2m 5s"` |
| `test_format_elapsed_zero` | `_format_elapsed(0)` → `"0s"` |
| `test_format_elapsed_3600s` | `_format_elapsed(3600)` → `"60m 0s"` |
| `test_ticker_shows_seconds_below_60` | Ticker text at elapsed=45 contains `"45s"` (not `"0m 45s"`) |
| `test_ticker_shows_human_at_or_above_60` | Ticker text at elapsed=125 contains `"2m 5s"` |
| `test_ticker_cancel_warning_human` | Warning branch at elapsed=680 (timeout=720, warn=60) contains `"40s"` remaining |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_ai_timeout_default_is_zero` | `BotConfig().ai_timeout_secs == 0` |

---

## Documentation Updates

### `README.md`

Update the `AI_TIMEOUT_SECS` row in the env var table:

```markdown
| `AI_TIMEOUT_SECS` | `0` | Hard timeout in seconds for any AI call. `0` = no timeout (default). Set e.g. `720` to cancel after 12 minutes. |
```

---

## Version Bump

New env var default changes user-visible behaviour (timeout no longer fires by default). **MINOR** bump: `0.10.0` → `0.11.0`.

---

## Edge Cases and Open Questions

1. **`remaining` can go negative** — if `elapsed > timeout_secs` (race between ticker cancel and the asyncio timeout), `remaining` could be negative for one tick. `_format_elapsed` should handle this gracefully (it will produce `-1s` or `-0m 1s`). The ticker is cancelled immediately after the timeout fires so this is cosmetic only; no fix needed.
2. **Existing deployments with `AI_TIMEOUT_SECS=720` set explicitly** — unaffected.
3. **`AI_TIMEOUT_WARN_SECS` with `AI_TIMEOUT_SECS=0`** — warn is already a no-op when `timeout_secs == 0` (the `if timeout_secs > 0` guard skips the remaining calculation). No change needed.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no new failures.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` `AI_TIMEOUT_SECS` default updated to `0`.
- [ ] `docs/roadmap.md` entry marked ✅.
- [ ] `docs/features/thinking-ticker-ux.md` status changed to `Implemented`.
- [ ] `VERSION` bumped `0.10.0` → `0.11.0`.
- [ ] Ticker displays `"2m 5s"` for a 125s elapsed time on both Telegram and Slack.
- [ ] Ticker displays `"45s"` (not `"0m 45s"`) for a 45s elapsed time.
- [ ] Default `AI_TIMEOUT_SECS=0` means no cancellation occurs when env var is unset.
