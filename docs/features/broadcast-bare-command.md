# Broadcast bare-command dispatch (`@here sync`, `@channel run …`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-14

When a user broadcasts a bare utility subcommand (e.g. `@here sync`), every bot should
execute it as if the user had addressed them directly (e.g. `dev sync`, `sec sync`).
Currently the broadcast router misclassifies bare subcommands as AI prompts.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/broadcast-bare-command.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 8/10 | 2026-03-14 | Code snippet verified accurate against live `slack.py:507–510`; `_KNOWN_SUBS` ref correct; auth claim confirmed fixed by GateSec; two blocking gaps: (1) "Files to Change" still says *create* `test_slack_broadcast.py` — must be *extend* `TestBroadcast` in `test_slack_bot.py`; (2) OQ6/OQ7 have no resolution decision or AC — spec should either document-as-expected-behaviour or add a warning step |
| GateSec  | 1 | 8/10 | 2026-03-14 | Auth claim corrected (OQ3→Architecture Notes fix); added OQ6 multi-bot `run` amplification risk; added OQ7 `@here confirm off` mass-disarm; OQ3 `confirm` edge case verified safe |
| GateDocs | 1 | 8/10 | 2026-03-14 | Architecture Notes auth claim is wrong (auth IS enforced at line 473, before broadcast block); test file should extend existing TestBroadcast class, not create new file; README placement needs section name |
| GateDocs | 2 | 9/10 | 2026-03-14 | Fixed: test target corrected to extend `TestBroadcast` in `test_slack_bot.py`; README placement now specifies `## Slack` section; OQ6 resolved (document-as-expected + warning deferred to Future Work); OQ7 resolved (emit warning on broadcast `confirm off`; full block deferred). -1 for OQ7 warning AC not yet added to Acceptance Criteria checklist — low risk, spec is fully implementable. |

**Status**: ⏳ Round 2 complete (GateDocs 9/10) — GateCode and GateSec Round 2 required
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Slack-only. Telegram has no @here / @channel / @everyone concept.
2. **Backend** — All AI backends are unaffected; this is pure routing logic.
3. **Stateful vs stateless** — Not applicable; we never reach the AI pipeline for dispatched commands.
4. **Breaking change?** — No. Users who currently send `@here sync` get an unwanted AI response;
   after this fix they get the correct command response. No env var or API surface changes.
5. **New dependency?** — None.
6. **Persistence** — None required.
7. **Auth** — No new secrets. The existing `_is_allowed` / `PREFIX_ONLY` guards still apply.
8. **Args support** — `@here run ls -la` should work like `dev run ls -la`. The broadcast router
   must pass arguments through, not just the subcommand name.

---

## Problem Statement

1. **Bare subcommand misrouted as AI prompt** — `@here sync` strips the `@here` token and leaves
   `"sync"` as the broadcast text. Because `"sync"` does not start with the bot's own prefix
   (e.g. `"dev "`), the broadcast router falls to `_run_ai_pipeline("sync", …)`. Every bot
   receives `"sync"` as a free-text prompt and returns an AI-generated answer instead of running
   the `sync` command.

2. **Inconsistency with prefixed broadcast** — `@here dev sync` works correctly (dispatches the
   command) but `@here sync` does not, even though both express the same intent. Users have no
   way to broadcast a command without redundantly repeating each bot's prefix.

3. **All known subcommands affected** — `run`, `sync`, `git`, `diff`, `log`, `status`, `clear`,
   `restart`, `confirm`, `info`, `help` all share this defect.

---

## Current Behaviour (as of v0.18.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Broadcast router | `src/platform/slack.py:490–510` (`message_handler`) | Strips `@here`/`@channel`/`@everyone` token, then checks `broadcast_text.startswith(f"{p} ")`. If False, immediately calls `_run_ai_pipeline`. |
| Dispatch | `src/platform/slack.py:501` | `sub_b in _KNOWN_SUBS` check only runs when the text already starts with the bot's prefix — unreachable for bare subcommands. |
| `_KNOWN_SUBS` | `src/platform/slack.py:64` | Contains all utility subcommand names. Not consulted during the bare-text branch. |

> **Key gap**: The broadcast router has only two code paths — _prefixed_ (starts with `{p} `) and
> _everything else_ (→ AI). There is no path for bare known subcommands, so `@here sync` becomes
> an AI prompt.

---

## Design Space

### Axis 1 — Where to detect bare subcommands in the broadcast path

#### Option A — Extend the broadcast `else` branch *(recommended)*

In the existing `else` branch (reached when `broadcast_text` does NOT start with the bot prefix),
check whether the first token is a known subcommand before falling through to `_run_ai_pipeline`.

```python
else:
    parts_b = broadcast_text.split(maxsplit=1)
    sub_b = parts_b[0].lower()
    args_b = (parts_b[1].split() if len(parts_b) > 1 else [])
    if sub_b in _KNOWN_SUBS:
        await self._dispatch(sub_b, args_b, say, client, channel, thread_ts=thread_ts)
    else:
        await self._run_ai_pipeline(
            say, client, broadcast_text, channel, thread_ts=thread_ts, user_id=user
        )
```

**Pros:**
- Minimal delta — touches only the existing `else` branch (~5 lines).
- Consistent: same `_KNOWN_SUBS` set used by all other routing paths.
- Args flow through naturally (`@here run ls -la` → sub=`run`, args=`["ls", "-la"]`).

**Cons:**
- None — this is a pure bug fix.

**Recommendation: Option A** — smallest correct change; no new abstractions needed.

#### Option B — Unify the prefixed and bare paths into a shared helper

Refactor the broadcast block into a `_route_broadcast(text, …)` helper that normalises both
`"dev sync"` and `"sync"` to `(sub="sync", args=[])` before dispatching.

**Pros:**
- Cleaner long-term; reduces code duplication across the three routing blocks.

**Cons:**
- Larger diff; refactoring risk for a pure bug fix; deferred to a future clean-up.

---

### Axis 2 — Handling `@here {unknown_word}` (non-subcommand, non-prefix)

#### Option A — Status quo: still falls to `_run_ai_pipeline` *(recommended)*

If `broadcast_text` is, say, `"summarise the last 10 commits"`, none of the tokens match
`_KNOWN_SUBS` and it correctly routes to the AI.

**Recommendation: Option A** — no change needed for this case.

---

## Recommended Solution

- **Axis 1**: Option A — extend the broadcast `else` branch.
- **Axis 2**: Option A — non-subcommand bare broadcasts continue to the AI pipeline.

**Runtime flow for `@here sync`:**

```
user posts "@here sync"
  → _SLACK_SPECIAL_MENTION_RE.search hits
  → broadcast_text = "sync"
  → lower_b = "sync"
  → NOT startswith("dev ")          # existing check — False
  → else branch:
      sub_b = "sync"                # NEW: parse first token
      "sync" in _KNOWN_SUBS         # NEW: True
      → _dispatch("sync", [], …)   # NEW: dispatch as utility command
```

**Runtime flow for `@here summarise the code`:**

```
  → broadcast_text = "summarise the code"
  → NOT startswith("dev ")
  → else branch:
      sub_b = "summarise"
      "summarise" NOT in _KNOWN_SUBS
      → _run_ai_pipeline("summarise the code", …)   # unchanged
```

---

## Architecture Notes

- **`_KNOWN_SUBS`** (`src/platform/slack.py:64`) is the authoritative set. The fix uses it
  directly — no duplication.
- **Telegram** — not affected; Telegram has no broadcast mechanism.
- **`PREFIX_ONLY`** — broadcast bypasses `PREFIX_ONLY` intentionally (same as `@mention`);
  this fix preserves that behaviour.
- **Thread context** — `thread_ts` is passed through unchanged.
- **Trusted-agent routing** — unaffected; trusted agents never reach the broadcast block.
- **`_is_allowed`** — `_is_allowed()` is called at line 473, *before* the broadcast block
  (line 491). Unauthorized users are rejected before broadcast routing runs. The new bare-
  subcommand path inherits this existing auth gate — no change to auth surface.

---

## Config Variables

None. This is a pure routing bug fix; no new env vars required.

---

## Implementation Steps

### Step 1 — `src/platform/slack.py`: extend the broadcast `else` branch

Locate the `else:` block inside the `if _SLACK_SPECIAL_MENTION_RE.search(text):` section
(currently `src/platform/slack.py` around line 506). Replace:

```python
            else:
                await self._run_ai_pipeline(
                    say, client, broadcast_text, channel, thread_ts=thread_ts, user_id=user
                )
```

With:

```python
            else:
                parts_b = broadcast_text.split(maxsplit=1)
                sub_b = parts_b[0].lower()
                args_b = parts_b[1].split() if len(parts_b) > 1 else []
                if sub_b in _KNOWN_SUBS:
                    await self._dispatch(sub_b, args_b, say, client, channel, thread_ts=thread_ts)
                else:
                    await self._run_ai_pipeline(
                        say, client, broadcast_text, channel, thread_ts=thread_ts, user_id=user
                    )
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/platform/slack.py` | **Edit** | Extend broadcast `else` branch (~7 lines) |
| `tests/unit/test_slack_bot.py` | **Extend** — add to existing `TestBroadcast` class | Add test cases for bare-subcommand broadcast routing |
| `docs/features/broadcast-bare-command.md` | **Edit** | Mark status `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Add entry; mark done after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| None | — | Pure logic change; no new packages. |

---

## Test Plan

### `tests/unit/test_slack_bot.py` — extend `TestBroadcast` class

| Test | What it checks |
|------|----------------|
| `test_broadcast_bare_known_sub_dispatched` | `@here sync` → `_dispatch("sync", [], …)` called; `_run_ai_pipeline` NOT called |
| `test_broadcast_bare_known_sub_with_args` | `@here run ls -la` → `_dispatch("run", ["ls", "-la"], …)` |
| `test_broadcast_bare_unknown_word_to_ai` | `@here summarise code` → `_run_ai_pipeline` called with `"summarise code"` |
| `test_broadcast_prefixed_still_works` | `@here dev sync` → `_dispatch("sync", [], …)` (existing path unchanged) |
| `test_broadcast_prefixed_ai_still_works` | `@here dev what does this do?` → `_run_ai_pipeline` (existing path unchanged) |
| `test_broadcast_empty_after_strip` | `@here` alone → returns without error |
| `test_broadcast_all_known_subs` | Parameterised over every entry in `_KNOWN_SUBS`; each dispatches correctly |

---

## Documentation Updates

### `README.md`

Add a bullet under the `## Slack` section (after the `PREFIX_ONLY` env var description):

> `@here <command>` or `@channel <command>` — broadcasts a utility command to all bots simultaneously. Works with bare subcommands (e.g. `@here sync`) as well as prefixed ones (e.g. `@here dev sync`).

### `docs/roadmap.md`

Add a new entry and mark done after merge.

---

## Version Bump

This is a bug fix with no new env vars or API surface changes.

**Expected bump**: `PATCH` → `0.18.x+1`

---

## Roadmap Update

```markdown
| 2.17 | ✅ Broadcast bare-command dispatch — `@here sync` routes correctly | [→ features/broadcast-bare-command.md](features/broadcast-bare-command.md) |
```

---

## Edge Cases and Open Questions

1. **`@here {prefix}` with no subcommand** (e.g. `@here dev`) — currently dispatches with
   `sub_b = ""` via the existing prefixed branch. Unchanged by this fix.

2. **Mixed-case subcommands** (e.g. `@here Sync`) — `parts_b[0].lower()` normalises to `"sync"`;
   consistent with existing prefix-path handling.

3. **`@here confirm`** — `confirm` is in `_KNOWN_SUBS`; will now dispatch. Existing `confirm`
   dispatch handler requires a pending confirmation token; if none exists it should already
   handle the "nothing to confirm" case gracefully. Verify during implementation.

4. **Future `_KNOWN_SUBS` additions** — The fix automatically picks up any new subcommand added
   to `_KNOWN_SUBS`; no secondary change needed.

5. **`@channel` and `@everyone`** — `_SLACK_SPECIAL_MENTION_RE` matches all three variants;
   the fix applies identically to all.

6. **[SEC] Multi-bot shell execution amplification** — `@here run <cmd>` dispatches to
   `_cmd_run` on *every* bot instance simultaneously. Non-destructive commands execute on all
   bots without any aggregate confirmation. For destructive commands, each bot prompts
   independently — the user must confirm N times. Consider: (a) documenting this as expected
   behaviour, or (b) adding a broadcast-specific warning like "⚠️ This command will run on
   all N active bots." before execution.

   **Resolution (GateDocs R2)**: Document as expected behaviour. The existing per-bot destructive-command confirmation gate already applies on each instance. A broadcast-specific warning banner is deferred to Future Work (see below).

7. **[SEC] `@here confirm off` mass-disarm** — broadcasting `confirm off` disables
   destructive-command confirmation on *all* bot instances in a single message. This silently
   removes the safety net across the entire workspace. Consider: (a) requiring `confirm off`
   to be addressed to a specific bot (no broadcast), or (b) emitting a prominent warning when
   confirmation is disabled via broadcast.

   **Resolution (GateDocs R2)**: Emit a prominent warning when `confirm off` is received via broadcast. The implementation should detect the broadcast context and prefix the response with `⚠️ Confirmation guard disabled via broadcast — all N active bots affected.` Blocking broadcast of `confirm off` entirely is deferred to Future Work.

---

## Acceptance Criteria

- [ ] `@here sync` dispatches as a utility command on every bot instance (no AI response).
- [ ] `@here run <cmd>` with arguments dispatches with args correctly.
- [ ] `@here <free text>` (non-subcommand) still routes to the AI pipeline unchanged.
- [ ] `@here dev sync` (prefixed) still works as before.
- [ ] `@here confirm off` emits a broadcast-context warning before disabling confirmation.
- [ ] All new unit tests pass.
- [ ] `pytest tests/ -v --tb=short` — zero failures.
- [ ] `ruff check src/` — no new issues.
- [ ] `README.md` Slack section updated.
- [ ] `docs/roadmap.md` entry added.
- [ ] `VERSION` bumped (PATCH).
- [ ] Telegram behaviour unchanged (no regression).
