# `@here` Broadcast Command Alias

> Status: **Implemented** | Priority: Medium | Last reviewed: 2026-03-15
> Implemented in: v0.20.0 (develop, commit `961daf2`)

Treat `@here`, `@channel`, and `@everyone` Slack mentions as broadcast prefix aliases — each active bot in the workspace processes the message independently using the same routing logic as a normal prefixed command.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.

| Reviewer | Round | Score | Date       | Notes |
|----------|-------|-------|------------|-------|
| GateCode | 1     | 9/10  | 2026-03-15 | Corrected outbound-strip function name (`_post_delegations`), test file name (`test_slack_bot.py`), aligned test plan with actuals, flagged 4 missing tests, added trusted-bot routing step to flow diagram |
| GateSec  | 1     | 9/10  | 2026-03-15 | All code refs verified; auth-before-broadcast correct; added trusted-bot broadcast edge case (F1) |
| GateDocs | 1     | 9/10  | 2026-03-15 | Created retroactive spec; problem statement, edge cases, and ACs all measurable; Slack-only scope clearly stated |

**Status**: ✅ Approved — R1 (GateCode 9/10, GateSec 9/10, GateDocs 9/10)
**Approved**: Yes — 2026-03-15

---

## ⚠️ Prerequisite Questions

1. **Scope** — Slack-only. Telegram has no `@here` / `@channel` / `@everyone` equivalent; this feature does not affect `src/bot.py`.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). Broadcast routes through the same `_run_ai_pipeline` path used by normal prefixed messages.
3. **Stateful vs stateless** — No difference. Broadcast text reaches `_run_ai_pipeline` / `_dispatch` identically to a prefixed command. History injection for stateless backends applies as normal.
4. **Breaking change?** — No. Existing messages are unaffected. Broadcasts that previously produced no bot response (when `PREFIX_ONLY=true`) now produce one — this is the intended new behaviour. **MINOR** version bump (`0.19.x → 0.20.0`).
5. **New dependency?** — None. `re.compile` (stdlib) already used in `slack.py`.
6. **Persistence** — None. Broadcast events are not stored separately; AI exchanges write to the standard history DB as normal.
7. **Auth** — No new secrets. `_is_allowed()` (the existing channel/user allowlist check) runs before the broadcast block and gates every event.
8. **`@here` with no text** — Silently ignored (empty `broadcast_text` after stripping returns early). Considered correct; a bare notification mention should never trigger bot responses.

---

## Problem Statement

1. **No broadcast addressing in multi-bot workspaces** — When two or more AgentGate instances share a Slack channel (e.g., `dev` bot + `sec` bot + `docs` bot), there is no ergonomic way to send the same command or question to all of them at once. Users must repeat the message three times with different prefixes.

2. **`@here` is the natural Slack idiom for "everyone present"** — Slack power-users already reach for `@here` to address all active members. Without this feature, typing `@here run pytest` does nothing (or sends a bare AI prompt to a single bot) — a confusing mismatch with user expectations.

3. **`PREFIX_ONLY` blocks legitimate broadcast use** — When a Slack workspace has `PREFIX_ONLY=true`, unprefixed messages are silently dropped. `@here <command>` — even though it is clearly an intentional, addressed message — would be silently ignored. This is the same ergonomic problem that `@mention` bypass already solves for individual bots.

Affected users: Slack workspace operators running multiple AgentGate instances per channel (the primary multi-agent pattern).

---

## Current Behaviour (as of v0.19.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Mention stripping (outbound) | `src/platform/slack.py:445` (`_post_delegations`) | `_SLACK_SPECIAL_MENTION_RE` already strips `<!here>` / `<!channel>` / `<!everyone>` from *outbound* delegation messages to prevent accidental re-broadcast |
| Inbound routing | `src/platform/slack.py:686` (message handler) | No special handling — broadcast messages fall through to the normal prefix check or `PREFIX_ONLY` gate |
| `PREFIX_ONLY` gate | `src/platform/slack.py:735` | Unprefixed messages are silently dropped when `PREFIX_ONLY=true` |

> **Key gap**: `<!here> gate run pytest` is treated as an unprefixed message and silently dropped under `PREFIX_ONLY`, even though the user's intent is identical to `gate run pytest`. Other bots with different prefixes never see it at all.

---

## Design Space

### Axis 1 — Where to intercept the broadcast mention

#### Option A — Strip at receive time, before prefix check *(recommended — implemented)*

Detect `_SLACK_SPECIAL_MENTION_RE` in the raw event text early in the message handler — after auth but before the prefix check. Strip all mention tokens, then route `broadcast_text` through the same prefix/dispatch logic as a normal message.

```python
if _SLACK_SPECIAL_MENTION_RE.search(text):
    broadcast_text = _SLACK_SPECIAL_MENTION_RE.sub("", text).strip()
    if not broadcast_text:
        return
    # ... same prefix routing as normal messages
```

**Pros:**
- Reuses all existing routing logic (prefix, dispatch, AI pipeline) unchanged
- Bypasses `PREFIX_ONLY` intentionally — semantically correct (same as `@mention`)
- Each bot instance independently receives and acts on the same Slack event

**Cons:**
- Bot responses are parallel and unsynchronised — users see N replies. Expected and documented.

**Recommendation: Option A** — minimal implementation surface; correct semantics; zero new state.

---

#### Option B — Server-side broadcast coordinator

A single "coordinator" bot forwards the stripped message to other bots via the `TRUSTED_AGENT_BOT_IDS` delegation channel.

**Pros:** Single response stream; avoids N parallel replies.

**Cons:** Requires a designated coordinator; defeats the purpose of independent bot isolation; adds latency and failure modes.

**Rejected** — over-engineered for the use case.

---

### Axis 2 — Which mention variants trigger the broadcast

#### Option A — `@here` only

**Pros:** Minimal; `@here` is the most common.

**Cons:** `@channel` and `@everyone` carry the same semantic intent in Slack. Inconsistent.

#### Option B — `@here`, `@channel`, `@everyone` *(implemented)*

Single regex: `r"<!(channel|here|everyone)>"`.

**Pros:** Consistent with Slack's own grouping of these mentions. No surprising gaps.

**Cons:** None material.

**Recommendation: Option B** — already the natural set; handled in one regex.

---

## Recommended Solution

- **Axis 1**: Option A — strip at receive time, before prefix check
- **Axis 2**: Option B — all three Slack group mentions

Runtime flow:

```
Slack event → subtype? (edit/delete) → return (ignored)
           → bot_id? (trusted agent) → prefix-only routing → return
           → auth check (_is_allowed) → denied? → return
           → files? → handle_files → return
           → empty? → return
           → <!here|channel|everyone> in text?
               → strip all mention tokens → broadcast_text
               → broadcast_text empty? → return (silent)
               → broadcast_text starts with "{prefix} "?
                   → parse sub / args → _dispatch (utility) or _run_ai_pipeline (AI)
               → else → _run_ai_pipeline(broadcast_text)  ← bare AI prompt without prefix
           → @mention? → _run_ai_pipeline
           → prefix? → _dispatch or _run_ai_pipeline
           → PREFIX_ONLY? → return
           → else → _run_ai_pipeline
```

Each active bot in the channel runs this flow independently. All respond in parallel. The user sees one reply per bot — this is the intended broadcast semantics.

---

## Architecture Notes

- **Slack-only** — `src/bot.py` (Telegram) is not changed. Telegram has no group-mention concept.
- **Auth runs first** — `_is_allowed(channel, user)` executes before the broadcast block. An unauthorised user's broadcast is silently dropped, same as any other message.
- **`PREFIX_ONLY` bypass is intentional** — the comment at line 688 documents this explicitly. `@here` carries the same "I am explicitly addressing you" semantics as a direct `@mention`; treating it as an unprefixed message would be wrong.
- **`_SLACK_SPECIAL_MENTION_RE` dual use** — the regex is also applied at line 444 to strip inbound mentions from outbound AI text. Do not remove or scope it to one use.
- **`is_stateful` unchanged** — broadcast text enters `_run_ai_pipeline` or `_dispatch` identically to a normal message. History injection for stateless backends applies as normal.
- **Thread context preserved** — `thread_ts` is forwarded through both `_dispatch` and `_run_ai_pipeline` calls in the broadcast branch. Replies stay in the originating thread.
- **`REPO_DIR` / `DB_PATH`** — no new paths introduced; always import from `src/config.py`.

---

## Config Variables

No new env vars. This feature is always enabled when `PLATFORM=slack`.

> If a future iteration needs an opt-out, add `BROADCAST_ENABLED: bool = Field(True, env="BROADCAST_ENABLED")` to `BotConfig` and gate the block on it.

---

## Implementation Steps

### Step 1 — `src/platform/slack.py`: add `_SLACK_SPECIAL_MENTION_RE` (already present)

The regex was already defined for outbound stripping:

```python
# line 84
_SLACK_SPECIAL_MENTION_RE = re.compile(r"<!(channel|here|everyone)>")
```

No change needed.

---

### Step 2 — `src/platform/slack.py`: add broadcast block in the message handler

Insert after the "empty text" guard and before the `@mention` block (~line 686):

```python
# Broadcast trigger: <!here>, <!channel>, or <!everyone> → strip and re-route.
# Each bot instance runs this independently; all active bots respond in parallel.
# Bypasses PREFIX_ONLY intentionally (same semantic as @mention).
if _SLACK_SPECIAL_MENTION_RE.search(text):
    broadcast_text = _SLACK_SPECIAL_MENTION_RE.sub("", text).strip()
    if not broadcast_text:
        return
    p = self._p
    lower_b = broadcast_text.lower()
    if lower_b.startswith(f"{p} ") or lower_b == p:
        parts_b = broadcast_text.split(maxsplit=2)
        sub_b = parts_b[1].lower() if len(parts_b) > 1 else ""
        args_b = parts_b[2].split() if len(parts_b) > 2 else []
        if sub_b in _KNOWN_SUBS or not sub_b:
            await self._dispatch(sub_b, args_b, say, client, channel, thread_ts=thread_ts, user_id=user)
        else:
            await self._run_ai_pipeline(
                say, client, broadcast_text[len(p):].strip(), channel, thread_ts=thread_ts, user_id=user
            )
    else:
        await self._run_ai_pipeline(
            say, client, broadcast_text, channel, thread_ts=thread_ts, user_id=user
        )
    return
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/platform/slack.py` | **Edit** | Add broadcast block in message handler; `_SLACK_SPECIAL_MENTION_RE` already present |
| `docs/features/here-broadcast-command.md` | **Create** | This file |
| `docs/roadmap.md` | **Edit** | Add entry for this feature; mark ✅ on merge to main |

> `src/bot.py`, `src/config.py`, `README.md`, `.env.example`, `docker-compose.yml.example` are **not changed** — Slack-only feature, no new env vars.

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `re` (stdlib) | ✅ Already used | `_SLACK_SPECIAL_MENTION_RE` already defined in `slack.py` |

---

## Test Plan

### `tests/unit/test_slack_bot.py` additions

The following tests are written and passing (class `TestBroadcastRouting`). Four edge-case tests from the original plan are still missing — see the AC checklist below.

| Test (actual name) | What it checks |
|------|----------------|
| `test_broadcast_ai_prompt_goes_to_pipeline` | `<!here> pull latest and review it` (no prefix) → `_run_ai_pipeline` called with stripped text |
| `test_broadcast_own_prefix_command_dispatches` | `<!here> gate sync` → `_dispatch("sync", …)` called once |
| `test_broadcast_other_prefix_goes_to_ai` | Bot prefix `sec`; message `<!here> dev sync` → `_run_ai_pipeline` called (prefix mismatch → AI prompt) |
| `test_broadcast_empty_after_strip_is_noop` | `<!here>` with no payload → handler returns; neither dispatch nor pipeline called |
| `test_broadcast_channel_trigger` | `<!channel> tell me the status` → `_run_ai_pipeline` called |
| `test_broadcast_everyone_trigger` | `<!everyone> who are you?` → `_run_ai_pipeline` called |
| `test_broadcast_blocked_for_unauthorized_user` | Unauthorised user sends `<!here> do something` → neither dispatch nor pipeline called |

**Missing tests (should be added before closing the feature):**

| Planned test name | What it should check |
|---|---|
| `test_broadcast_whitespace_only_ignored` | `<!here>   ` (whitespace only after strip) → same silent return as bare mention |
| `test_broadcast_prefix_only_bypassed` | `PREFIX_ONLY=true`; `<!here> gate status` → `_dispatch` called (broadcast bypasses the PREFIX_ONLY gate) |
| `test_broadcast_thread_ts_preserved` | Broadcast in a thread → `_dispatch` and `_run_ai_pipeline` receive correct `thread_ts` |
| `test_broadcast_multiple_mentions_stripped` | `<!here> <!channel> gate status` → both tokens stripped; `_dispatch("status", …)` called once |

---

## Documentation Updates

### `README.md`

No update required — this feature has no user-visible env var and the Slack usage section already implies prefix-based addressing. A brief note in the Slack section may be added at the team's discretion:

> _Tip: prefix your command with `@here`, `@channel`, or `@everyone` to broadcast it to all active bots in the channel simultaneously._

### `.env.example` and `docker-compose.yml.example`

No changes — no new env vars.

### `docs/roadmap.md`

Add entry and mark ✅ on merge to `main`:

```markdown
| 2.X | ✅ `@here` broadcast command alias — group mentions route to all active bots | [→ features/here-broadcast-command.md](features/here-broadcast-command.md) |
```

---

## Version Bump

This feature adds new behaviour with no breaking changes and no new env vars.

**Expected bump**: **MINOR** (`0.19.x → 0.20.0`) — already shipped in `v0.20.0`.

---

## Edge Cases and Open Questions

> All open questions below are resolved. Answers match the current implementation.

1. **`@here` with no text** — `broadcast_text` is empty after stripping; handler returns silently. Correct: a bare notification mention should not trigger bot responses.

2. **Multiple mention tokens in one message** — `<!here> <!channel> gate status` → `_SLACK_SPECIAL_MENTION_RE.sub("", text)` replaces all occurrences; `broadcast_text` becomes `gate status`. Handled correctly.

3. **`@here` with another bot's prefix** — If this bot's prefix is `gate` and the message is `@here dev status`, `broadcast_text` is `dev status`. This does not match `gate`, so the `else` branch fires: `_run_ai_pipeline(say, client, "dev status", …)`. The `dev`-prefixed bot will have dispatched correctly when it processes the same event. Resolved: correct behaviour — each bot responds only to its own prefix; the text is an AI prompt for bots with a different prefix.

4. **`@here` in a Slack thread** — `thread_ts` is passed through both `_dispatch` and `_run_ai_pipeline` in the broadcast branch. All bot replies land in the originating thread. Resolved: confirmed by code inspection at lines 700, 703, 707.

5. **`@here run <destructive cmd>`** — Auth runs before the broadcast block. If the user is allowed, `gate run <cmd>` goes through `_dispatch("run", …)` which applies the same confirmation-dialog logic as a direct `gate run` command. No safety regression.

6. **Race condition between bots** — Each bot instance is an independent process; they do not share in-flight state for broadcast events. All respond in parallel. Users see N replies. This is documented as intended behaviour.

7. **`gate restart` interaction** — Broadcast handling is stateless (no new background tasks or file handles). `gate restart` cleans up correctly.

8. **Slack thread scope** — Replies respect existing thread context (`thread_ts` preserved). Broadcast to a thread root produces thread replies from all bots.

9. **Trusted bot sends `@here`** — A trusted agent (matched via `bot_id` in `TRUSTED_AGENT_BOT_IDS`) that sends `<!here> gate status` is handled by the trusted-bot block (line 644), which checks for `{prefix} ` at the start of the raw text. Since the text starts with `<!here>` — not the prefix — it does not match, and the handler returns silently at line 668. The message never reaches the broadcast block (line 689). Resolved: correct behaviour — trusted bots should address a specific bot by prefix, not broadcast. Broadcast mentions in trusted-bot messages are safely ignored.

---

## GateSec R1 Findings

> Round 1 security review — 2026-03-15

All 10 spec claims verified against `src/platform/slack.py` at commit `c3fdae9`. Line numbers, function names, regex patterns, and control-flow ordering are accurate.

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| F1 | 🟢 Non-blocking | Trusted-bot broadcast edge case undocumented — `<!here> gate status` from a trusted bot is silently dropped because the trusted-bot handler (line 644) checks for prefix at text start, not after mention stripping. Added to Edge Cases §9. | Resolved inline |

**Security checklist:**

- ✅ **Auth guard ordering** — `_is_allowed()` at line 671 runs before broadcast block at line 689. Unauthorised broadcasts are dropped with audit record.
- ✅ **PREFIX_ONLY bypass semantics** — Broadcast bypass mirrors `@mention` bypass (line 711). Both represent explicit user-addressed messages; treating them as unprefixed would be wrong.
- ✅ **Broadcast input path safety** — Stripped text enters the same `_dispatch()` / `_run_ai_pipeline()` paths as normal messages. Destructive commands (`gate run rm -rf`) still trigger confirmation dialogs via `_dispatch("run", …)`.
- ✅ **ReDoS resistance** — `r"<!(channel|here|everyone)>"` is simple alternation with no nested quantifiers. No risk.
- ✅ **Re-broadcast loop prevention** — `_post_delegations()` at line 445 strips `<!here>` / `<!channel>` / `<!everyone>` from outbound AI text, preventing a bot's response from triggering other bots.
- ✅ **Empty/whitespace injection** — `.strip()` + `if not broadcast_text: return` (lines 690–692) blocks empty and whitespace-only payloads.
- ✅ **Thread context preservation** — `thread_ts` passed in all 3 call sites within the broadcast block (lines 700, 703, 707).
- ✅ **No new secrets, endpoints, or subprocess paths** — Slack-only feature; no config changes; no new attack surface.

---

## GateDocs R1 Findings

> Round 1 docs review — 2026-03-15

This file was created as a retroactive spec matching the already-implemented broadcast block (`src/platform/slack.py:686–708`). GateCode R1 corrected function/test-file references and flagged 4 missing tests. GateSec R1 added the trusted-bot broadcast edge case (§9) and the full security checklist.

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| F1 | 🟡 Blocking | `docs/roadmap.md` AC inconsistency — GateCode marked `[x]` for the roadmap entry but no entry existed. Lint policy (`lint_docs.py`) requires Implemented specs to be *absent* from the roadmap (enforced by `roadmap-sync`). AC reworded to reflect actual policy; checkbox set to `[x]` with clarifying note. | Resolved inline |

**Docs checklist:**

- ✅ Problem statement covers all three user-facing pain points
- ✅ Edge cases section — 9 resolved items, all concrete and implementation-verified
- ✅ Acceptance criteria — all measurable; partial AC flagged with `[~]` and gap detail
- ✅ Design Space — both axes documented with pros/cons and explicit recommendations
- ✅ Test Plan — actual test names verified; 4 missing tests explicitly listed
- ✅ `docs/roadmap.md` — Implemented specs are removed by `roadmap-sync` per lint policy; no entry needed (AC corrected below)
- ✅ Scope boundary (Slack-only) stated in ≥ 3 places

---

## Acceptance Criteria

> The feature is *done* when ALL of the following are true.

- [x] `<!here>`, `<!channel>`, and `<!everyone>` prefixes route to `_dispatch` or `_run_ai_pipeline` identically to a normally prefixed message.
- [x] A bare `@here` (no text after stripping) is silently ignored.
- [x] `PREFIX_ONLY=true` does not suppress broadcast messages (bypass is intentional and documented).
- [x] Auth check (`_is_allowed`) runs before the broadcast block; unauthorised broadcasts are dropped.
- [x] `thread_ts` is preserved in all broadcast routing paths.
- [x] `pytest tests/ -v --tb=short` passes with no failures.
- [x] `ruff check src/` reports no new linting issues.
- [x] `docs/roadmap.md` — Implemented specs are absent from the roadmap (removed by `roadmap-sync` per lint policy; no manual entry required).
- [x] `docs/features/here-broadcast-command.md` status is `Implemented` (already set; marked ✅ on merge to `main` per convention).
- [~] Core broadcast unit tests present and passing in `tests/unit/test_slack_bot.py` (7/11 scenarios covered — 4 missing: whitespace-only, PREFIX_ONLY bypass, thread_ts, multiple mentions). _(open — add missing 4 tests before closing feature)_
- [ ] `README.md` Slack section updated with broadcast tip _(optional, team discretion)_.
