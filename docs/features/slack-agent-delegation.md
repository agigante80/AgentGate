# Slack: Agent-to-Agent Delegation via Sentinel Blocks

> Status: **Planned** | Priority: **High** | Last reviewed: 2026-01-01

Docs update: README.md and .env.example were updated to document `SLACK_DELETE_THINKING` and `SLACK_THREAD_REPLIES`.

When an AI agent wants to delegate work to a peer agent, it embeds the delegation request
inline in its response. Other agents only react to messages that start with their command
prefix, so buried delegation text is silently ignored. This feature introduces a structured
delegation sentinel that the bot detects and posts as a standalone new message.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Slack-only. Telegram is single-agent by design; no agent-to-agent messaging.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). The AI must be instructed to
   emit the sentinel; parsing is in the Slack delivery layer.
3. **Stateful vs stateless** — Not relevant. The sentinel is stripped from the response before
   saving to history, so both stateful and stateless backends see clean context.
4. **Breaking change?** — No. Delegation only activates when the AI emits `[DELEGATE: ...]`.
   Existing responses without the sentinel are unaffected. **MINOR** bump.
5. **New dependency?** — No. Sentinel parsing uses a simple regex.
6. **Persistence** — No new DB table. Delegation is fire-and-forget (post a new message).
7. **Auth** — No new secrets. `chat:write` (already required) covers posting the delegation
   message.
8. **Infinite loops** — Can agent B's response to A's delegation trigger another delegation
   back to A, creating a loop? Yes — this is a real risk. See Edge Cases section.

---

## Problem Statement

1. **Delegation is buried and ignored.** When agent A's AI response includes delegation text
   (e.g. "I'll ask GateSec to review this: sec please check…") in the middle of a paragraph,
   agent B (`sec`) never sees it. `_on_message()` only processes a message as a delegation
   candidate if it comes from a trusted bot **and** the text starts with B's prefix.

2. **No structured delegation protocol.** There is no agreed format for an agent to ask a
   peer agent for something. The AI invents ad-hoc wording that may or may not start with
   the right prefix.

3. **Delegation response visibility.** Even if an agent is asked correctly (prefix at start),
   its response is currently delivered as a message edit — which other agents ignore. This
   is addressed by `slack-final-response-new-message.md`; both features must be implemented
   together for end-to-end agent-to-agent workflows to function.

---

## Current Behaviour (as of v0.9.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Team context | `src/platform/slack.py:684` (`_build_team_context`) | Tells the AI its teammates' names and prefixes, but gives no delegation protocol |
| AI pipeline | `src/platform/slack.py:180` (`_run_ai_pipeline`) | AI response is delivered as-is; no post-processing for delegation markers |
| Agent routing | `src/platform/slack.py:262–273` (`_on_message`) | Trusted bot messages are only processed if text starts with `<prefix> ` |
| Skills files | `skills/dev-agent.md`, `skills/sec-agent.md`, `skills/docs-agent.md` | No delegation protocol documented |

> **Key gap**: There is no structured way for an AI agent to produce a delegation request that
> the bot can reliably parse and re-post as a standalone triggerable message.

---

## Code Review Notes (2026-03-13)

Verified against `src/platform/slack.py` on `develop`:

- **`import re` is inside `__init__`** (line 83), not at module level. The `_extract_delegations` helper must be a **module-level function** (not a method), so `import re` must be added to the top-of-file imports (after the existing `import` block around line 23–26). Step 1 covers this.
- **`_extract_delegations` as module-level function**: Since the function needs no `self`, define it at module level (similar to `_prefix()` at line 42). This keeps it testable in isolation.
- **Line numbers confirmed**: `_build_team_context()` is at line 684; trusted bot guard is at lines 262–273; `_run_ai_pipeline()` is at line 180. All match the Implementation Steps below.
- **`skills/` files** confirmed at `/repo/skills/dev-agent.md`, `sec-agent.md`, `docs-agent.md` — platform-neutral content only. Do not add delegation instructions there (Slack-specific).
- **Streaming path**: The `[DELEGATE: …]` sentinel may arrive in the final streaming chunks. Extraction runs on the **complete** `accumulated` string after `_stream_body()` completes, before `chat_postMessage` — no partial-sentinel risk. Step 4 covers this.
- **Interaction with 2.3**: When `SLACK_THREAD_REPLIES=true` is also enabled, delegation `chat_postMessage` calls must include `thread_ts`. Coordinate with `slack-thread-replies.md` Step 3/4; pass `thread_ts` through `_run_ai_pipeline()` to the delegation posting loop.

---

## Design Space

### Axis 1 — How the AI signals a delegation request

#### Option A — Prefix convention *(fragile, status quo)*

The AI is instructed to start its response (or a paragraph) with `sec <message>`. The bot
relies on the message starting at the channel root with the right prefix.

**Pros:**
- No parsing code needed.

**Cons:**
- AI embeds delegation in the middle of a longer response — prefix is never at the message start.
- Unreliable: the AI may use "GateSec" or "@sec" instead of the bare prefix.
- No way to separate the delegation from the main response.

---

#### Option B — Structured sentinel block *(recommended)*

The AI is instructed to emit a special sentinel at the **end** of its response:

```
[DELEGATE: sec Please review the following code for SQL injection: ...]
```

The bot uses a regex to detect `[DELEGATE: <prefix> <message>]`, strips the sentinel from the
displayed response, and posts `<prefix> <message>` as a new standalone message.

```python
import re

_DELEGATE_RE = re.compile(r'\[DELEGATE:\s*(\w+)\s+(.*?)\]', re.DOTALL)

def extract_delegations(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (cleaned_text, [(prefix, message), ...])."""
    delegations = []
    def _replace(m: re.Match) -> str:
        delegations.append((m.group(1).lower(), m.group(2).strip()))
        return ""
    cleaned = _DELEGATE_RE.sub(_replace, text).strip()
    return cleaned, delegations
```

**Pros:**
- Unambiguous: sentinel is always stripped before display.
- AI can include multiple delegation blocks.
- Prefix is inside the sentinel — bot posts `sec <message>` at the start of a new message,
  which the target agent recognises correctly.
- Sentinel instructions can be added to `_build_team_context()` — no skills file change needed.

**Cons:**
- AI must be reliably instructed to use this format (prompt engineering required).
- Hallucinated or malformed sentinels must be handled (regex simply ignores non-matching text).

---

#### Option C — Separate AI call for delegation

After the AI responds, make a second AI call asking "should you delegate anything?".

**Pros:**
- No sentinel format needed.

**Cons:**
- Doubles AI cost and latency for every message.
- Creates recursive AI call chains.

---

### Axis 2 — Where to add sentinel instructions

#### Option A — `_build_team_context()` only *(recommended)*

Add delegation protocol to the team context block that is already prepended to every AI prompt.
No change to skills files needed.

```python
# In _build_team_context():
lines.append(
    "To delegate a task to a team member, append a DELEGATE block at the END of your response:\n"
    "  [DELEGATE: <prefix> <message to send>]\n"
    "Example: [DELEGATE: sec Please review this code for XSS vulnerabilities: ...]"
)
```

**Pros:**
- Single point of truth; automatically applies to all agents.
- Skills files remain platform-neutral (loads for both Telegram and Slack).

**Cons:**
- Instructions are in the team context, not the skills — may be deprioritised by the model.

---

#### Option B — Skills files

Add a `## Delegation Protocol` section to each skills file.

**Pros:**
- Closer to the AI's operational context.

**Cons:**
- Skills files load for both Telegram and Slack; delegation is Slack-only.
- Must be maintained in three files.

**Recommendation: Option A** — team context is Slack-specific and authoritative for all agents.

---

### Axis 3 — Loop prevention

#### Option A — No loop prevention *(risky)*

Agents can delegate to each other indefinitely.

**Cons:**
- Infinite loops are possible and likely in multi-agent conversations.

---

#### Option B — Depth tracking via message metadata

Tag delegation messages with a depth header; refuse to delegate if depth exceeds a threshold.

**Cons:**
- Complex; requires parsing custom metadata from Slack messages.

---

#### Option C — Trusted bot messages cannot trigger delegation *(recommended)*

The simplest safe default: when a message comes from a trusted bot (agent-to-agent),
the bot processes only **prefix commands** (the existing behaviour), never the AI pipeline,
and therefore never emits delegation sentinels.

```python
# In _on_message(), trusted bot path (line 262–273):
# Already returns after _dispatch() — does NOT call _run_ai_pipeline()
# → delegation sentinels can ONLY come from human-triggered AI responses
```

**Pros:**
- Delegation chains are at most one hop: human → agent A → agent B (via delegation) → human.
- Zero additional code: this is already the behaviour in `_on_message()`.

**Cons:**
- Agent B cannot further delegate to agent C. Acceptable for v1.

**Recommendation: Option C** — the existing trusted-bot guard already prevents loops.

---

## Recommended Solution

- **Axis 1**: Option B — structured `[DELEGATE: prefix message]` sentinel
- **Axis 2**: Option A — instructions in `_build_team_context()` only
- **Axis 3**: Option C — trusted bot messages never trigger the AI pipeline (existing behaviour)

**End-to-end flow:**

```
Human: "dev analyse the auth module for security issues"
  → GateCode AI responds:
      "I've reviewed auth.py. The token generation looks weak.
       [DELEGATE: sec Please review auth.py for token security: the generate_token()
       function uses random.random() instead of secrets.token_bytes()]"

  → Bot strips sentinel from displayed text, posts:
      Display (to channel): "I've reviewed auth.py. The token generation looks weak."
      New message (to channel): "sec Please review auth.py for token security: ..."

  → GateSec sees "sec Please review auth.py..." → routes to AI pipeline
  → GateSec AI responds (as new message, per slack-final-response-new-message.md):
      "⚠️ Confirmed: random.random() is not cryptographically secure. Use secrets.token_bytes(32)."

  → Human sees both responses in channel.
```

---

## Architecture Notes

- **Trusted bot guard** — `_on_message()` line 262–273: messages from trusted bots only
  dispatch prefix commands, never `_run_ai_pipeline()`. This is the loop-prevention mechanism
  for v1. Do NOT change this guard.
- **Trusted bot guard vs AI-to-AI delegation** — The end-to-end flow above shows "GateSec AI
  responds" to a delegation, but that only works because the delegation message is posted as a
  *new channel message starting with the target prefix*. This message arrives with the
  *sending bot's* `bot_id`, hits the trusted bot guard, and is dispatched via `_dispatch()`.
  If the delegated sub-command is a known prefix command (e.g. `run`, `sync`), `_dispatch()`
  handles it. If it is *not* a known command, `_dispatch()` replies with `❓ Unknown command`
  and the AI pipeline is **never** reached. In v1, delegation only triggers prefix commands
  on the target agent. For full AI-to-AI delegation, a future version would need a dedicated
  `delegate` subcommand in `_dispatch()` that explicitly calls `_run_ai_pipeline()` with a
  depth counter.
- **Sentinel stripping before history** — `common.save_to_history()` must receive the cleaned
  text (sentinel removed), not the raw AI output. This keeps conversation history clean.
- **Platform symmetry** — delegation is Slack-only; no change to `src/bot.py`.
- **`asyncio_mode = auto`** — tests remain `async def test_*` without decorator.
- **Skills files** — must stay platform-neutral. Do NOT add Slack-specific delegation
  instructions to skills files.

---

## Security Notes (added 2026-03-13)

### 🔴 RCE via delegation command injection

The AI can craft a delegation like `[DELEGATE: dev run rm -rf /]`. The bot posts
`dev run rm -rf /` as a new message → the target agent's trusted bot guard routes it to
`_dispatch()` → `sub = "run"` → `run_shell("rm -rf /")` executes in `REPO_DIR`. This is
**remote code execution**: anyone who can influence the AI's output (via prompt injection in
repo content, PR diffs, or direct conversation) can execute arbitrary shell commands on a
peer agent.

**Required mitigation — delegation command blocklist:**

Delegation messages from the AI must *never* start with an executable command sub-command.
Add a blocklist check before posting each delegation message:

```python
_BLOCKED_DELEGATION_SUBS = {
    "run", "sync", "git", "diff", "log", "restart", "clear", "confirm",
}

for prefix, msg in delegations:
    first_word = msg.split()[0].lower() if msg.split() else ""
    if first_word in _BLOCKED_DELEGATION_SUBS:
        logger.warning(
            "Blocked delegation with dangerous sub-command: prefix=%s sub=%s",
            prefix, first_word,
        )
        continue
    await client.chat_postMessage(channel=channel, text=f"{prefix} {msg}")
```

Alternatively (defence-in-depth): strip the target prefix before posting and only post the
*message body*, so the receiving agent's trusted bot path falls through to the unknown-command
handler (which just shows help). This is safer but changes the delegation protocol semantics.

### 🟡 No cap on delegation count per response

If the AI emits 50 `[DELEGATE: ...]` blocks (due to a prompt injection attack or model
hallucination), all 50 are posted. This could flood the channel and trigger rate limits.

**Required mitigation — `MAX_DELEGATIONS_PER_RESPONSE`:**

```python
_MAX_DELEGATIONS = 3

delegations = delegations[:_MAX_DELEGATIONS]
if len(all_delegations) > _MAX_DELEGATIONS:
    logger.warning(
        "Delegation cap exceeded: %d found, only posting %d",
        len(all_delegations), _MAX_DELEGATIONS,
    )
```

---

## Config Variables

No new env vars for v1. The sentinel format is fixed.

Optional future extension:
| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `SLACK_MAX_DELEGATION_DEPTH` | `int` | `1` | Max hops for agent-to-agent delegation chains. Reserved for future use. |

---

## Implementation Steps

### Step 1 — `src/platform/slack.py`: add sentinel parser

Add `import re` to the **module-level** imports (top of file, alongside the existing stdlib imports — `asyncio`, `logging`, `time`). Currently `import re` only appears inside `__init__` at line 83; move it to module scope.

Then add a **module-level** regex and extraction helper (after `_THINKING` constant, around line 41):

```python
import re  # add to top-of-file imports

_DELEGATE_RE = re.compile(r'\[DELEGATE:\s*(\w+)\s+(.*?)\]', re.DOTALL)

def _extract_delegations(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Strip [DELEGATE: prefix msg] blocks from text, return (cleaned, [(prefix, msg)])."""
    delegations: list[tuple[str, str]] = []
    def _replace(m: re.Match) -> str:
        delegations.append((m.group(1).lower(), m.group(2).strip()))
        return ""
    cleaned = _DELEGATE_RE.sub(_replace, text).strip()
    return cleaned, delegations
```

Also remove the `import re` from inside `SlackBot.__init__` (line 83) since it will now be at module level.

---

### Step 2 — `src/platform/slack.py`: post delegation messages in `_run_ai_pipeline()`

After obtaining the final AI response (and before `save_to_history`), extract and post delegations.

> ⚠️ **Security**: apply the command blocklist and delegation cap (see *Security Notes*).

```python
_BLOCKED_DELEGATION_SUBS = {
    "run", "sync", "git", "diff", "log", "restart", "clear", "confirm",
}
_MAX_DELEGATIONS = 3

# After response is obtained (line ~230):
response, delegations = _extract_delegations(response)

if len(delegations) > _MAX_DELEGATIONS:
    logger.warning(
        "Delegation cap exceeded: %d found, only posting %d",
        len(delegations), _MAX_DELEGATIONS,
    )
    delegations = delegations[:_MAX_DELEGATIONS]

for prefix, msg in delegations:
    first_word = msg.split()[0].lower() if msg.split() else ""
    if first_word in _BLOCKED_DELEGATION_SUBS:
        logger.warning(
            "Blocked delegation with dangerous sub-command: prefix=%s sub=%s",
            prefix, first_word,
        )
        continue
    delegation_text = f"{prefix} {msg}"
    try:
        await client.chat_postMessage(channel=channel, text=delegation_text)
        logger.info("Delegation posted: %s → %s", self._bot_display_name, prefix)
    except Exception:
        logger.warning("Failed to post delegation to prefix=%s", prefix)

await common.save_to_history(channel, text, response, self._settings)
```

---

### Step 3 — `src/platform/slack.py`: update `_build_team_context()`

Add delegation protocol instructions to the team context:

```python
# At the end of _build_team_context(), before returning:
lines.append(
    "\nDelegation protocol (Slack): To request action from a team member, append a DELEGATE "
    "block at the END of your response:\n"
    "  [DELEGATE: <prefix> <full message to send>]\n"
    "The bot will strip the block from your displayed response and post it as a new message.\n"
    "Example: [DELEGATE: sec Please review auth.py for SQL injection vulnerabilities.]"
)
```

---

### Step 4 — Ensure sentinel is stripped before streaming final delivery

For streaming responses, the sentinel may arrive in the final chunks. The extraction must
happen on the **complete** accumulated response, after streaming ends, before posting:

```python
# In _stream_to_slack(), after streaming loop:
final = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
final, delegations = _extract_delegations(final)
await client.chat_postMessage(channel=channel, text=final or "_(empty response)_")
# ... delete thinking placeholder ...
for prefix, msg in delegations:
    await client.chat_postMessage(channel=channel, text=f"{prefix} {msg}")
return final
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/platform/slack.py` | **Edit** | Add `_extract_delegations()` helper; call in `_run_ai_pipeline()` and `_stream_to_slack()`; update `_build_team_context()` with delegation instructions |
| `tests/unit/test_slack_bot.py` | **Edit** | Add tests for sentinel extraction, delegation posting, and sentinel stripping from history |
| `docs/roadmap.md` | **Edit** | Mark feature done on completion |
| `docs/features/slack-agent-delegation.md` | **Edit** | Change status to `Implemented` after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `re` (stdlib) | ✅ Already available | Standard library regex module |
| `slack-bolt[async]` | ✅ Already installed | `client.chat_postMessage()` for delegation messages |

---

## Test Plan

### `tests/unit/test_slack_delegation.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_extract_delegations_single` | Single `[DELEGATE: sec msg]` is stripped and returned |
| `test_extract_delegations_multiple` | Two `[DELEGATE: ...]` blocks both extracted |
| `test_extract_delegations_none` | No sentinel → cleaned text equals input |
| `test_extract_delegations_multiline` | Multiline delegation message is captured correctly |
| `test_extract_delegations_malformed` | `[DELEGATE: ]` (no prefix/msg) → ignored, text unchanged |

### `tests/unit/test_slack_delegation_security.py` (new file — security)

| Test | What it checks |
|------|----------------|
| `test_blocked_sub_run` | `[DELEGATE: dev run rm -rf /]` → delegation is *not* posted |
| `test_blocked_sub_sync` | `[DELEGATE: dev sync]` → delegation is *not* posted |
| `test_blocked_sub_git` | `[DELEGATE: dev git push --force]` → delegation is *not* posted |
| `test_allowed_sub_review` | `[DELEGATE: sec review auth.py]` → delegation *is* posted (not in blocklist) |
| `test_cap_exceeded` | 5 delegations emitted → only first 3 posted, warning logged |
| `test_cap_not_exceeded` | 2 delegations emitted → both posted, no warning |

### `tests/unit/test_slack_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_delegation_posts_new_message` | When AI response contains sentinel, `chat_postMessage` called for delegation |
| `test_delegation_stripped_from_display` | Displayed response does not contain the sentinel block |
| `test_delegation_stripped_from_history` | `save_to_history` receives cleaned text, not raw AI output |
| `test_delegation_failure_is_silent` | If `chat_postMessage` raises for delegation, main response still delivered |
| `test_trusted_bot_no_delegation` | Messages from trusted bots do not trigger `_run_ai_pipeline()` (loop prevention) |

---

## Documentation Updates

### `docs/guides/multi-agent-slack.md`

Add a new **Agent Delegation** section explaining:
- The `[DELEGATE: prefix message]` sentinel format
- How the bot strips it and posts it
- The loop-prevention guarantee (delegation chains are max one hop in v1)
- Example multi-agent workflow

### `docs/roadmap.md`

Mark this feature as done (✅) when merged to `main`.

---

## Version Bump

New behaviour with a safe default (delegation only activates when the AI emits a sentinel;
existing responses without a sentinel are unchanged).

**Expected bump**: `MINOR` → `0.10.0` (coordinate with `slack-final-response-new-message.md`)

---

## Edge Cases and Open Questions

1. **Infinite delegation loops** — Addressed by Option C (Axis 3): trusted bot messages
   never trigger the AI pipeline. Delegation chains are at most one hop in v1.

2. **Hallucinated sentinels** — The AI may emit `[DELEGATE: ...]` without being asked.
   The regex extracts all matching blocks unconditionally. Worst case: an unintended message
   is sent to the wrong agent. Mitigation: the target agent will handle it as a normal message.

3. **Delegation to unknown prefix** — If the AI delegates to a prefix that no agent uses,
   the message is posted to the channel but no agent reacts. This is harmless.

4. **Sentinel in streaming response** — The `[DELEGATE: ...]` block may be split across
   streaming chunks. Extraction runs on the **complete** accumulated response after streaming
   ends, not on individual chunks — no partial-sentinel problem.

5. **Delegation message thread scope** — If `SLACK_THREAD_REPLIES=true` is also enabled
   (see `slack-thread-replies.md`), delegation messages should be posted in the same thread
   as the main response, so the target agent sees them in context.

6. **Multiple delegations in one response** — The regex handles this: `_extract_delegations()`
   returns a list of `(prefix, message)` tuples, all of which are posted.

7. **`gate restart` interaction** — No persistent state. `gate restart` is unaffected.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `docs/guides/multi-agent-slack.md` updated with delegation protocol section.
- [ ] `docs/roadmap.md` entry is marked done (✅).
- [ ] `docs/features/slack-agent-delegation.md` status changed to `Implemented`.
- [ ] `VERSION` file bumped.
- [ ] Responses without sentinel are completely unaffected (regression test).
- [ ] Delegation message starts with the target prefix and is posted as a new channel message.
- [ ] Sentinel is stripped from both displayed response and saved history.
- [ ] Trusted bot messages cannot trigger delegation (loop prevention verified by test).
- [ ] **(Security)** Delegations with blocked sub-commands (`run`, `sync`, `git`, `diff`, etc.) are rejected and logged.
- [ ] **(Security)** At most `_MAX_DELEGATIONS` (3) delegation messages are posted per response.
- [ ] **(Security)** Security tests in `test_slack_delegation_security.py` pass.
