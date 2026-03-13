# Broadcast via `<!here>` (`<!here> <prompt or command>`)

> Status: **Implemented in v0.12.0** | Priority: Medium | Last reviewed: 2026-03-13

Slack users can prefix any message with `<!here>` to broadcast it to all active AgentGate bots simultaneously — each bot receives the message independently and responds with its own perspective. Works for both AI prompts and utility subcommands (`sync`, `status`, etc.).

---

## ⚠️ Prerequisite Questions

1. **Scope** — Slack-only. Telegram does not have an equivalent "address all" mention primitive.
2. **Backend** — Applies to all AI backends; broadcast just changes *who receives* the message, not *how it's processed*.
3. **Stateful vs stateless** — No interaction: each bot routes to its own `_run_ai_pipeline()` normally after stripping `<!here>`.
4. **Breaking change?** — No. Currently `<!here>` in an incoming message is silently ignored (passed to AI pipeline or dropped by `PREFIX_ONLY`). This is a new detection path; existing behaviour is unchanged for messages without `<!here>`.
5. **New dependency?** — None. `_SLACK_SPECIAL_MENTION_RE` already exists at `slack.py:56`.
6. **Persistence** — No storage needed.
7. **Auth** — No new secrets. Existing `_is_allowed()` check still applies — unauthenticated users cannot use broadcast.
8. **Spam risk** — Three bots all replying simultaneously is intentional but should be documented. No additional Slack API permissions are needed.

---

## Problem Statement

1. **No broadcast mechanism** — There is no way to send a single message that all bots act on. Users must send `dev sync`, `sec sync`, `docs sync` as three separate messages.
2. **`<!here>` silently no-ops** — Users naturally try `<!here> sync` expecting all bots to respond; nothing happens.
3. **Prompt broadcast impossible** — There is no way to ask all agents the same AI question simultaneously (e.g., "everyone review this code snippet").

---

## Current Behaviour (as of v0.11.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Incoming message routing | `src/platform/slack.py:366+` (`_on_message`) | No detection of `<!here>` in incoming text; falls through to prefix/AI routing |
| Outgoing delegation sanitisation | `src/platform/slack.py:263` (`_post_delegations`) | `_SLACK_SPECIAL_MENTION_RE` strips `<!here>` from *outgoing* delegation posts — correct security measure, must stay |
| Regex definition | `src/platform/slack.py:56` | `_SLACK_SPECIAL_MENTION_RE = re.compile(r"<!(channel|here|everyone)>")` — already exists, reusable |

> **Key gap**: Incoming `<!here>` from a human is never matched; there is no broadcast path. The regex exists only for outgoing sanitisation.

---

## Design Space

### Axis 1 — Where to insert the broadcast detection

#### Option A — After `_is_allowed()`, before prefix check *(recommended)*

```python
# In _handle_message(), after _is_allowed() and file/voice handling:
if _SLACK_SPECIAL_MENTION_RE.search(text):
    broadcast_text = _SLACK_SPECIAL_MENTION_RE.sub("", text).strip()
    if broadcast_text:
        await self._run_ai_pipeline(say, client, broadcast_text, channel, thread_ts=thread_ts)
    return
```

**Pros:**
- Auth guard already passed (`_is_allowed()` runs before this)
- `_run_ai_pipeline` handles both commands (`sync`, `status`) and AI prompts transparently
- Zero new code paths for commands vs prompts — same logic, just a new entry point
- `<!here>` stripped before forwarding — bots don't see the literal `<!here>` in their prompt

**Cons:**
- `<!channel>` and `<!everyone>` would also trigger broadcast — acceptable, same semantic intent

**Recommendation: Option A** — minimal, reuses existing infrastructure, correct auth ordering.

---

#### Option B — New dedicated `_handle_broadcast()` method

Separate method with its own routing logic.

**Pros:** Cleaner separation of concerns.

**Cons:** More code for the same outcome; `_run_ai_pipeline` already handles both command and AI routing, so separation adds no value here.

---

### Axis 2 — Command routing inside `_run_ai_pipeline`

No change needed. `_run_ai_pipeline` already detects known subcommands like `sync` via the existing prefix dispatch table — but only when the text starts with the bot's own prefix. For broadcast, the text arrives without a prefix.

**Decision**: Pass the stripped broadcast text directly to `_run_ai_pipeline`. Subcommand detection happens inside via the existing logic. Commands without a prefix will fall through to the AI pipeline — which is correct: `sync` without a prefix becomes an AI question, while `gate sync` is a command. This is the desired behaviour: broadcast commands should use the full prefix form: `<!here> gate sync` or `<!here> dev sync` (the bot only responds to its own prefix even in broadcast mode).

Wait — actually this means broadcast works the same as sending an unprefixed message. Each bot will only respond to its own prefix. So `<!here> sync` sends `sync` to the AI pipeline of each bot (since it has no prefix). `<!here> gate sync` would also fail since `gate` isn't anyone's prefix.

**Revised approach**: Strip `<!here>` and pass the remainder verbatim to `_run_ai_pipeline`. This means:
- `<!here> dev sync` → each bot gets `dev sync` → only the dev bot dispatches the sync command; sec and docs treat it as an AI prompt starting with "dev sync". This is not ideal.
- `<!here> sync` → each bot gets `sync` → all bots forward to AI (since `sync` alone isn't a prefix command) — acceptable

**Better approach for commands**: Use the same logic as the `@mention` trigger — strip `<!here>` and then pass through the *full routing logic* (prefix check + AI fallback), not just the AI pipeline. This means calling the routing block directly:

```python
if _SLACK_SPECIAL_MENTION_RE.search(text):
    broadcast_text = _SLACK_SPECIAL_MENTION_RE.sub("", text).strip()
    if not broadcast_text:
        return
    # Re-route: prefix command or AI prompt
    p = self._p
    lower = broadcast_text.lower()
    if lower.startswith(f"{p} ") or lower == p:
        parts = broadcast_text.split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else ""
        args_str = parts[2] if len(parts) > 2 else ""
        args = args_str.split() if args_str else []
        if sub in {"run", "sync", "git", "diff", "log", "status", "clear", "restart", "confirm", "info", "help"} or not sub:
            await self._dispatch(sub, args, say, client, channel, thread_ts=thread_ts)
        else:
            await self._run_ai_pipeline(say, client, broadcast_text[len(p):].strip(), channel, thread_ts=thread_ts)
    else:
        await self._run_ai_pipeline(say, client, broadcast_text, channel, thread_ts=thread_ts)
    return
```

This means `<!here> dev sync` → each bot checks if `dev sync` starts with its own prefix. Only the dev bot dispatches `sync`. The other bots forward "dev sync" to their AI pipeline — which is fine and probably informative. Users who want all bots to run a command should use `<!here> sync` with no prefix (goes to AI) or — for true broadcast of commands — use the per-prefix form and let each bot handle its own.

**Recommendation**: Full re-routing (prefix check + AI fallback) for maximum flexibility.

---

## Recommended Solution

- **Axis 1**: Option A — detect `<!here>` after `_is_allowed()`, before prefix routing
- **Axis 2**: Full re-routing — same prefix-check + AI-fallback logic as normal messages

End-to-end flow:
```
User sends: <!here> dev sync
↓
Each bot's _handle_message() receives it
↓
_is_allowed() check passes
↓
_SLACK_SPECIAL_MENTION_RE detects <!here> → strips to "dev sync"
↓
Prefix check: does "dev sync" start with this bot's prefix?
  → dev bot: YES → dispatches sync command
  → sec bot: NO  → AI pipeline ("dev sync" forwarded as AI prompt)
  → docs bot: NO → AI pipeline ("dev sync" forwarded as AI prompt)

User sends: <!here> pull latest and review the changes
↓
Each bot receives it
↓
Strip <!here> → "pull latest and review the changes"
↓
No prefix match for any bot → all three forward to their own AI pipeline
↓
dev, sec, docs all respond with their own perspective
```

---

## Architecture Notes

- **Slack-only** — `bot.py` (Telegram) has no equivalent mechanism; no changes needed there.
- **Auth ordering is critical** — broadcast detection must happen *after* `_is_allowed()` so unauthenticated users cannot exploit it.
- **Outgoing sanitisation stays** — `_SLACK_SPECIAL_MENTION_RE.sub("", msg)` in `_post_delegations` (line 263) must remain to prevent delegated messages from re-triggering `<!here>` in other bots.
- **`asyncio_mode = auto`** — tests don't need `@pytest.mark.asyncio`.
- **No config flag needed** — broadcast is unconditional for authenticated users; there is no reason to disable it.

---

## Config Variables

No new env vars. This feature is always-on for authenticated Slack users.

---

## Implementation Steps

### Step 1 — `src/platform/slack.py`: add broadcast detection in `_on_message`

Insert **after** the `_is_allowed()` (line 411) / file-handling (415) / empty-text (418) guards, and **before** the `@mention` trigger (line 422).

> *Important*: the subcommand set `{"run", "sync", …}` is now duplicated in three places: `_dispatch` table (line 461), trusted-bot routing (line 403), and this block. Extract to a module-level constant (e.g. `_KNOWN_SUBS`) shared by all three to prevent drift.

```python
# Broadcast trigger: <!here>, <!channel>, or <!everyone> → strip and re-route
if _SLACK_SPECIAL_MENTION_RE.search(text):
    broadcast_text = _SLACK_SPECIAL_MENTION_RE.sub("", text).strip()
    if not broadcast_text:
        return
    p = self._p
    lower = broadcast_text.lower()
    if lower.startswith(f"{p} ") or lower == p:
        parts = broadcast_text.split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else ""
        args_str = parts[2] if len(parts) > 2 else ""
        args = args_str.split() if args_str else []
        if sub in {"run", "sync", "git", "diff", "log", "status", "clear", "restart", "confirm", "info", "help"} or not sub:
            await self._dispatch(sub, args, say, client, channel, thread_ts=thread_ts)
        else:
            await self._run_ai_pipeline(
                say, client, broadcast_text[len(p):].strip(), channel, thread_ts=thread_ts
            )
    else:
        await self._run_ai_pipeline(say, client, broadcast_text, channel, thread_ts=thread_ts)
    return
```

Exact insertion point: after line 418 (`if not text: return` guard), before line 422 (`@mention` trigger block).

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/platform/slack.py` | **Edit** | Add ~15-line broadcast detection block in `_handle_message` |
| `README.md` | **Edit** | Add broadcast feature bullet and usage example |
| `docs/features/broadcast-here.md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Remove entry after implementation |

---

## Dependencies

No new dependencies.

---

## Test Plan

Add to `tests/unit/test_slack_bot.py` (following existing `_make_settings` / `_make_update` pattern):

```python
class TestBroadcast:
    """Tests for <!here> broadcast routing."""

    async def test_broadcast_ai_prompt_all_bots(self):
        """<!here> <prompt> → AI pipeline called with stripped text."""
        bot = _make_slack_bot(prefix="dev")
        event = _make_slack_event(text="<!here> review this code")
        # Assert _run_ai_pipeline called with "review this code"

    async def test_broadcast_own_prefix_command(self):
        """<!here> dev sync → bot with prefix 'dev' dispatches sync."""
        bot = _make_slack_bot(prefix="dev")
        event = _make_slack_event(text="<!here> dev sync")
        # Assert _dispatch called with sub="sync"

    async def test_broadcast_other_prefix_goes_to_ai(self):
        """<!here> sec status → bot with prefix 'dev' forwards to AI (not dispatch)."""
        bot = _make_slack_bot(prefix="dev")
        event = _make_slack_event(text="<!here> sec status")
        # Assert _run_ai_pipeline called (not _dispatch)

    async def test_broadcast_empty_after_strip_is_noop(self):
        """<!here> with no trailing text → no pipeline call."""
        bot = _make_slack_bot(prefix="dev")
        event = _make_slack_event(text="<!here>")
        # Assert neither _dispatch nor _run_ai_pipeline called

    async def test_broadcast_requires_auth(self):
        """Unauthenticated user sending <!here> → blocked by _is_allowed."""
        # Assert bot does not respond

    async def test_broadcast_channel_trigger(self):
        """<!channel> behaves identically to <!here>."""
        # Assert _run_ai_pipeline called

    async def test_broadcast_everyone_trigger(self):
        """<!everyone> behaves identically to <!here>."""
        # Assert _run_ai_pipeline called

    async def test_outgoing_delegation_still_sanitised(self):
        """<!here> in a delegation message is still stripped before posting."""
        # Verify _post_delegations strips <!here> from outgoing text (regression guard)
```

---

## Documentation Updates

### `README.md`

Add to the Slack features section:

```markdown
- **Broadcast** — Prefix any message with `<!here>` to send it to all active agents simultaneously. Each bot responds independently with its own perspective. Works for both AI prompts and commands.
```

---

## Version Bump

**MINOR** — new feature, no breaking changes, `0.11.x` → `0.12.0`.

---

## Security Considerations

1. *Delegation amplification* — A broadcast reaches all bots simultaneously. Each bot's AI response may contain `[DELEGATE: ...]` blocks, so a single `<!here>` message can produce up to 3× the normal delegation volume. This is bounded by the existing `_MAX_DELEGATIONS` cap (per response) and the 1-hop delegation chain limit — but operators should be aware of the multiplier effect. No code change needed; the existing caps are sufficient.

2. *Subcommand set duplication* — The feature doc's code sample hardcodes `{"run", "sync", "git", "diff", "log", "status", "clear", "restart", "confirm", "info", "help"}`. This is the _third_ copy of this set (after `_dispatch` table at line 461 and trusted-bot routing at line 403). If a new subcommand is added to `_dispatch` but not to the broadcast block, it would silently fall through to the AI pipeline instead of dispatching. *Recommendation*: extract to a module-level `_KNOWN_SUBS` constant shared by all three call sites.

3. *Destructive command safety preserved* — `<!here> dev run rm -rf /` routes to `_dispatch("run", ...)` → `_cmd_run` → `is_destructive()` check → confirmation flow. The existing safety net is not bypassed by broadcast.

4. *Outgoing re-trigger prevention* — `_post_delegations` (line 262) strips `<!here>` from outgoing delegation text before posting. Bot responses go through `_reply()`, not `_on_message()`, so they cannot re-trigger broadcast. AI message events have `subtype` set, which is rejected at line 380. No re-trigger vector exists.

5. *Secret redaction* — All broadcast responses flow through `_run_ai_pipeline` → `_reply()` / `_send()` / `_edit()`, which apply `SecretRedactor`. No bypass.

---

## Edge Cases and Open Questions

1. **`<!here>` with whitespace only** — Handled: `broadcast_text.strip()` → empty → early return.
2. **Multiple `<!here>` in one message** — `_SLACK_SPECIAL_MENTION_RE.sub("", text)` strips all occurrences. Result is the message body with all special mentions removed.
3. **Trusted bot sending `<!here>`** — Trusted bots are routed through the bot-only code path before reaching the broadcast check, so they are unaffected.
4. **Thread context** — `thread_ts` is passed through; broadcast respects `SLACK_THREAD_REPLIES` setting.
5. **`PREFIX_ONLY=true`** — Broadcast bypasses `PREFIX_ONLY` (same as `@mention` trigger). This is intentional — `<!here>` is an explicit user action.
6. **Spam** — Three bots all replying at once is the intended behaviour. No rate-limiting added.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no new failures.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `<!here> <prompt>` causes all bots to respond with their own AI answer.
- [ ] `<!here> <own-prefix> sync` causes the matching bot to dispatch `sync`; others forward to AI.
- [ ] `<!here>` with no trailing text is a no-op.
- [ ] Outgoing delegation sanitisation is unaffected (regression test passes).
- [ ] `README.md` updated with broadcast usage example.
- [ ] `VERSION` bumped to `0.12.0`.
- [ ] `docs/roadmap.md` entry added, then removed on completion.
- [ ] Feature doc status changed to `Implemented` on merge.
