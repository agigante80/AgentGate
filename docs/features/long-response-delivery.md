# Long-Response Delivery Without Head Truncation

> Status: **Implemented** | Priority: High | Last reviewed: 2026-03-14 | GateSec R2: 9/10

## Overview

Both the Telegram and Slack bots previously used `accumulated[-max_output_chars:]` when
delivering the final AI response, silently dropping the *beginning* of any reply longer
than `max_output_chars` (default 3 000 chars).  The user would only ever see the tail of
long answers.

Streaming live-updates still clip to `max_output_chars` for the typing preview — the
in-progress "▌" indicator only ever shows the most recent window.  Only the **final
delivery** (once streaming ends) is affected by this fix.

## Environment Variables

No new env vars.  Existing `MAX_OUTPUT_CHARS` (default `3000`) still governs the
streaming preview window; it is no longer involved in final delivery.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_OUTPUT_CHARS` | `3000` | Streaming preview window only |

## Design

### Telegram delivery strategy (`_deliver_telegram`)

| Response length | Behaviour |
|---|---|
| ≤ 4 096 chars | Single message (edit streaming placeholder) |
| 4 097 – 16 384 chars | Up to 4 sequential messages, split at paragraph / sentence / newline / hard-cut |
| > 16 384 chars (> 4 chunks) | Editing placeholder to a note + `reply_document()` with `response.txt` |

Constants in `src/bot.py`:
```python
_TG_MAX_CHARS  = 4096   # Telegram's hard per-message limit
_TG_MAX_CHUNKS = 4      # max sequential messages before file fallback
```

### Slack delivery strategy (`_deliver_slack`)

| Response length | Behaviour |
|---|---|
| ≤ 3 000 chars | Single message (unchanged fast path) |
| 3 001 – 12 000 chars | Block Kit multi-section message (one API call, multiple `section` blocks) |
| > 12 000 chars | Editing placeholder to a note + `files_upload_v2` snippet |

Constants in `src/platform/slack.py`:
```python
_SLACK_BLOCK_LIMIT       = 3_000   # max chars per section block / single message
_SLACK_SNIPPET_THRESHOLD = 12_000  # above this → file upload
```

### `split_text` helper (`src/platform/common.py`)

Shared by both platforms.  Splits text into chunks of at most `chunk_size` characters,
preferring split points in this priority order:

1. Paragraph boundary (`\n\n`)
2. Sentence boundary (`". "`)
3. Single newline (`\n`)
4. Hard cut at `chunk_size` (last resort, no data loss)

```python
def split_text(text: str, chunk_size: int) -> list[str]: ...
```

## Acceptance Criteria

- [ ] AI responses ≤ 4 096 chars delivered as a single Telegram message.
- [ ] AI responses 4 097–16 384 chars delivered as 2–4 sequential Telegram messages; no content is dropped.
- [ ] AI responses > 16 384 chars on Telegram delivered as a `response.txt` document with a note.
- [ ] AI responses ≤ 3 000 chars delivered as a single Slack message (no regression).
- [ ] AI responses 3 001–12 000 chars delivered as a Block Kit multi-section message in one `chat_postMessage` / `chat_update` call.
- [ ] AI responses > 12 000 chars on Slack delivered as a `files_upload_v2` snippet with a note replacing the placeholder.
- [ ] `split_text()` never drops characters; `"".join(split_text(t, n)) == t` for all inputs.
- [ ] Streaming preview window unchanged (still clips to `MAX_OUTPUT_CHARS`).
- [ ] All 8 `TestSplitText` unit tests pass.
- [ ] `_deliver_telegram` single-message branch: edit streaming placeholder (5 `TestDeliverTelegram` cases).
- [ ] `_deliver_telegram` multi-chunk branch: first chunk edits placeholder, subsequent chunks are new replies.
- [ ] `_deliver_telegram` file-upload branch: note edits placeholder, `reply_document()` called.
- [ ] `_deliver_telegram` edit failure does not raise (graceful degradation).
- [ ] `_deliver_slack` single-message branch: edits existing `ts` or posts new message (6 `TestDeliverSlack` cases).
- [ ] `_deliver_slack` multi-block branch: `chat_update`/`chat_postMessage` called with `blocks` payload.
- [ ] `_deliver_slack` file-upload branch: `files_upload_v2` called.
- [ ] `_deliver_slack` multi-block API error falls back to plain text without raising.

## Files Changed

| File | Change |
|---|---|
| `src/platform/common.py` | Added `split_text()` helper |
| `src/bot.py` | Added `_deliver_telegram()`; import `io` for `BytesIO` file fallback |
| `src/platform/slack.py` | Added `_deliver_slack()`; constants `_SLACK_BLOCK_LIMIT`, `_SLACK_SNIPPET_THRESHOLD` |
| `tests/unit/test_platform_common.py` | 8 new `TestSplitText` test cases |
| `tests/unit/test_bot.py` | 5 new `TestDeliverTelegram` test cases (branch routing + error handling) |
| `tests/unit/test_slack_bot.py` | 6 new `TestDeliverSlack` test cases (branch routing + fallback) |

## Implementation Notes

- The fix is intentionally asymmetric: Telegram uses sequential messages, Slack uses
  Block Kit blocks.  The delivery model matches each platform's native affordances.
- The fix applies to both streaming and non-streaming paths on both platforms.  The
  streaming placeholder (`▌`) is updated from the same message handle as the typing
  preview throughout.  On completion, `_deliver_telegram` / `_deliver_slack` takes over
  and may replace, extend, or file-upload as appropriate.  Non-streaming paths pass the
  "🤖 Thinking…" placeholder as `streaming_msg` / `existing_ts` so the same functions
  handle both paths identically — no separate non-streaming delivery code path exists.
- `files_upload_v2` is the current Slack Files API endpoint (v1 deprecated).

## Open Questions

| # | Question | Status |
|---|---|---|
| OQ1 | Should `_TG_MAX_CHUNKS` and `_SLACK_SNIPPET_THRESHOLD` be configurable via env vars? | Open |
| OQ2 | Should the streaming preview truncate from the *head* instead of the tail (show the latest content, which is current behaviour)? | Accepted — tail is correct UX for streaming |
| OQ3 | *Security* — `_deliver_slack()` Block Kit multi-block path (3 001–12 000 chars) sends chunks via `client.chat_postMessage(**kwargs)` directly, bypassing `_reply()`/`_edit()` which apply `self._redactor.redact()`. Secrets in AI responses could leak in multi-section Slack messages. Fix: apply `self._redactor.redact(text)` before splitting so all chunks and the fallback notification text are redacted. | Fixed — `redacted = self._redactor.redact(text)` applied before `split_text()` in `_deliver_slack()` |
| OQ4 | *Security* — Non-streaming paths bypass delivery functions entirely. `_run_ai_pipeline` (Telegram) sends via `reply_text()` and the Slack non-streaming branch sends via `_reply()` — neither uses `_deliver_telegram()`/`_deliver_slack()`. If `summarize_if_long()` produces output > 4 096 chars (e.g. the AI ignores the length instruction), Telegram will reject the API call. | Fixed — non-streaming Telegram path now calls `_deliver_telegram(update, msg, response)` using the thinking placeholder as `streaming_msg`; non-streaming Slack path now calls `_deliver_slack(client, channel, ts_or_None, response, thread_ts)` where `ts_or_None` is `None` when `slack_delete_thinking=True` (placeholder already deleted) or `ts` otherwise (edits placeholder in-place). |
| OQ5 | *Spec accuracy* — AC 9 says "All 10 `TestSplitText` unit tests pass" but only 8 tests exist: `test_short_text_returned_as_single_chunk`, `test_exact_chunk_size_not_split`, `test_splits_at_paragraph_boundary`, `test_splits_at_sentence_boundary`, `test_splits_at_newline`, `test_hard_cuts_when_no_boundary`, `test_no_data_loss`, `test_empty_string`. Corrected to 8 in this review. | Fixed |
| OQ6 | *Resilience* — Both delivery functions catch all exceptions with bare `except Exception` and log at WARNING/DEBUG. If `reply_document()` or `files_upload_v2` fails after the "Response is too long" note is sent, the user sees the note but never receives the file, and the full response is silently lost. Consider a fallback (e.g. re-try, or append first N chars inline). | Open |

## Team Review

| Reviewer | Round | Score | Notes |
|---|---|---|---|
| GateCode | R1 | 8/10 | OQ3 confirmed and fixed (redact before split — single-call fix). OQ4 valid concern (non-streaming bypasses delivery functions — OQ open). OQ5 confirmed (file header corrected to 8 tests). OQ6 valid resilience gap (open). CI fixed: spec status line updated to required format. |
| GateSec | R1 | 8/10 | Redaction bypass in Slack multi-block path (OQ3), non-streaming paths skip delivery functions (OQ4), test count corrected 10→8 (OQ5), silent file-upload failure (OQ6). Streaming redaction and file-upload redaction verified correct. `split_text` is sound — no injection or data-loss vectors. |
| GateDocs | R1 | 8/10 | Design/AC/Implementation Notes are accurate and asymmetric Telegram/Slack behaviour is well-described. Three gaps: (1) OQ4 must have an explicit disposition (fix now OR defer-with-issue) — "Open" with no decision is a blocker for approval; (2) test plan covers only `split_text` — `_deliver_telegram` and `_deliver_slack` each have 3-branch routing + error paths that have no spec-level test cases; (3) Implementation Notes claim delivery functions are called "on completion" — this is only true for the streaming path; non-streaming path (the OQ4 bug) calls `reply_text()`/`_reply()` directly, subtly contradicting the narrative. OQ6 (silent file-upload failure) is acceptable as deferred. |
| GateCode | R2 | 9/10 | OQ4 fixed: non-streaming Telegram routed through `_deliver_telegram(update, msg, response)`; non-streaming Slack routed through `_deliver_slack` with `ts_or_None` depending on `slack_delete_thinking`. 11 new delivery routing tests added (5 `TestDeliverTelegram` + 6 `TestDeliverSlack`), all pass. Implementation Notes updated to remove contradictory narrative. OQ6 (silent file-upload failure) remains open and acceptable as deferred. Shared -1: OQ6 deferred without a tracked issue number — should link a GitHub issue before final approval. |
| GateSec | R2 | 9/10 | OQ4 verified fixed on both platforms. *Telegram*: `redactor.redact(response)` applied before `_deliver_telegram()` — all chunks receive pre-redacted text. *Slack*: `_deliver_slack()` is called with unredacted text but every internal path applies redaction — fast path via `_reply()`/`_edit()` wrappers, multi-block via `self._redactor.redact(text)` before `split_text()` (OQ3 fix intact), file-upload via `self._redactor.redact(text)` on content kwarg. No bypass vectors remain. Test coverage: 5 `TestDeliverTelegram` + 6 `TestDeliverSlack` exercise all branch/error paths including empty-text, multi-chunk routing, file fallback, and API-error graceful degradation. Shared -1: asymmetric redaction pattern (Telegram redacts pre-delivery in caller; Slack redacts internally per-path in `_deliver_slack`) is correct but fragile — a future maintainer copying one pattern into the other could introduce a gap. Recommend adding a code comment noting the intentional difference. OQ6 (silent file-upload failure) acceptable as deferred. |
