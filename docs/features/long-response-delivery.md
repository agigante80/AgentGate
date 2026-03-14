# Long-Response Delivery Without Head Truncation

> Status: Implemented

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
- [ ] All 10 `TestSplitText` unit tests pass.

## Files Changed

| File | Change |
|---|---|
| `src/platform/common.py` | Added `split_text()` helper |
| `src/bot.py` | Added `_deliver_telegram()`; import `io` for `BytesIO` file fallback |
| `src/platform/slack.py` | Added `_deliver_slack()`; constants `_SLACK_BLOCK_LIMIT`, `_SLACK_SNIPPET_THRESHOLD` |
| `tests/unit/test_platform_common.py` | 10 new `TestSplitText` test cases |

## Implementation Notes

- The fix is intentionally asymmetric: Telegram uses sequential messages, Slack uses
  Block Kit blocks.  The delivery model matches each platform's native affordances.
- The streaming placeholder (`▌`) is updated from the same message handle as the typing
  preview throughout.  On completion, `_deliver_telegram` / `_deliver_slack` takes over
  and may replace, extend, or file-upload as appropriate.
- `files_upload_v2` is the current Slack Files API endpoint (v1 deprecated).

## Open Questions

| # | Question | Status |
|---|---|---|
| OQ1 | Should `_TG_MAX_CHUNKS` and `_SLACK_SNIPPET_THRESHOLD` be configurable via env vars? | Open |
| OQ2 | Should the streaming preview truncate from the *head* instead of the tail (show the latest content, which is current behaviour)? | Accepted — tail is correct UX for streaming |

## Team Review

| Reviewer | Round | Score | Notes |
|---|---|---|---|
| GateCode | R1 | — | Author |
