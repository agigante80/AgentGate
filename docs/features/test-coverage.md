# Test Coverage Gaps

> Status: **Ongoing** | Priority: Medium | Last reviewed: 2026-03-12

Improve unit-test coverage of error paths, branching logic, and platform startup code that are currently not exercised by the test suite.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (`bot.py` for Telegram, `slack.py` for Slack). However, `slack.py` gaps are mostly I/O-bound (voice, Block Kit, Socket Mode) and are lower ROI; focus first on `bot.py`, `main.py`, `session.py`, `direct.py`.
2. **Backend** — All backends affected (error paths exist in all three).
3. **Stateful vs stateless** — Not applicable; this is a test-only change.
4. **Breaking change?** — No. Tests only. No version bump required.
5. **New dependency?** — No new production deps. `pytest-asyncio` (already present) handles async tests.
6. **Persistence** — No storage changes.
7. **Auth** — No credential changes.
8. **Coverage target** — Aim for ≥90% total (currently 83%). Every new branch must be explicitly tested or marked `# pragma: no cover` with a one-line comment.

---

## Problem Statement

1. **Error paths untested** — `asyncio.TimeoutError`, subprocess failures, and Telegram/Slack API exceptions in `bot.py`, `session.py`, and `direct.py` are not covered. A regression in these paths would go undetected.
2. **`main.py` startup logic at 50%** — config validation, SIGTERM teardown, and the Slack startup branch are entirely untested. Startup failures are the most disruptive class of bug.
3. **`build_app()` uncovered** — The handler registration block in `bot.py` is never exercised, so a wiring mistake (e.g., wrong handler attached to wrong command) would not be caught by CI.
4. **`direct.py` provider branches at 84%** — Anthropic-specific send/stream methods and stream exception handling are not tested, leaving the most-used production backend under-tested.

---

## Current Behaviour (as of v0.8.x)

| Module | Coverage | Uncovered lines | Gap description |
|--------|----------|-----------------|-----------------|
| `src/bot.py` | **89%** | 88-89, 111-112, 151-153, 167, 190, 196-200, 446, 472-494 | Streaming error edit, non-timeout `_stream_body`, transcriber warning, `history_enabled=False`, non-streaming `TimeoutError`, voice handler guard, `build_app()` wiring |
| `src/main.py` | **50%** | 23-24, 28-39, 44-53, 63-65, 87-104, 131, 137-153, 157 | `_read_version` OSError, `_log_startup_banner`, `_validate_config`, SIGTERM handler, Slack startup branch, `asyncio.run` exception |
| `src/ai/session.py` | **85%** | 44-45, 51-53, 78, 85-88, 97-98 | `CancelledError` kill path, general exception in `send()`, `stream()` exception, stdout drain inside stats-marker |
| `src/ai/direct.py` | **84%** | 71-75, 80-81, 120-130 | Anthropic client factory, `_anthropic_send`, `_anthropic_stream` |
| `src/ai/factory.py` | **79%** | 21, 27-30 | Unknown `AI_CLI` value branch, Codex/Direct factory branches |
| `src/ai/copilot.py` | **90%** | 20, 27 | Non-zero returncode path, stream non-zero returncode |

> **Key gap**: The 50% coverage on `main.py` means the entire startup sequence — the first code executed in production — has no automated test harness.

---

## Design Space

### Axis 1 — How to test `main.py` startup

#### Option A — Integration test with real asyncio.run *(risky)*

Spin up real `startup()`. Requires mocking `repo.clone`, `runtime.install_deps`, `history.init_db`, and platform startup. Fragile.

**Cons:** Complex setup, slow, easy to accidentally hit real services.

---

#### Option B — Unit-test individual private functions *(recommended)*

Test `_read_version()`, `_validate_config()`, `_log_startup_banner()`, and `_handle_sigterm()` in isolation. Mock `asyncio.get_running_loop()` for SIGTERM tests.

**Pros:** Fast, focused, each test covers exactly one branch.
**Cons:** Does not test the full `startup()` orchestration.

**Recommendation: Option B** — unit-test the private functions; integration test for the full `startup()` sequence can be added later if needed.

---

### Axis 2 — How to cover `build_app()` in `bot.py`

#### Option A — Assert handler count

Call `build_app(mock_settings, mock_backend, 0.0)` and assert `len(app.handlers[0]) == N`.

**Pros:** Simple, verifies wiring without invoking handlers.

**Recommendation: Option A** — one test verifying the app is constructed with the correct handler count.

---

## Recommended Solution

- **Axis 1**: Option B — unit-test `main.py` private functions in isolation
- **Axis 2**: Option A — assert handler registration count in `build_app()`

Target: raise total coverage from 83% to ≥90% by adding targeted tests for all listed uncovered lines.

---

## Architecture Notes

- **`asyncio_mode = auto`** — all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **`_make_settings` pattern** — use `MagicMock(spec=SettingsSubclass)` for settings mocks; see `tests/unit/test_bot.py` for the established pattern.
- **`conftest.py` autouse fixture** — strips real credential env vars automatically; do not re-implement.
- **`# pragma: no cover`** — any branch intentionally excluded (e.g., `if __name__ == "__main__"`) must carry this comment with a one-line explanation.
- **No subprocess calls** — use `AsyncMock` for `CopilotSession._spawn`; never call real subprocesses in unit tests.

---

## Config Variables

N/A — this is a test-only change. No new env vars.

---

## Implementation Steps

### Step 1 — `tests/unit/test_bot.py`: cover `bot.py` gaps

Add tests for:

- **`_stream_to_telegram` edit exception** (lines 88-89): mock `msg.edit_text` to raise `Exception`; assert stream continues without crashing.
- **`_stream_body` non-timeout path** (lines 111-112): set `timeout_secs=0`; assert stream completes via the `else` branch.
- **Transcriber `NotImplementedError`** (lines 151-153): mock `create_transcriber` to raise `NotImplementedError`; assert `_make_transcriber` returns `None` and logs a warning.
- **`history_enabled=False`** (line 167): set `settings.bot.history_enabled = False`; assert `history.get_history` is never called.
- **Non-streaming `TimeoutError`** (lines 196-200): mock `backend.send` to raise `asyncio.TimeoutError`; assert message is edited to the timeout warning.
- **Voice handler — transcriber None** (line 446): ensure `handle_voice` replies with the "disabled" message and returns early when `_transcriber is None`.
- **`build_app()` handler wiring** (lines 472-494): call `build_app(mock_settings, mock_backend, 0.0)` and assert the returned `Application` has the expected number of handlers.

---

### Step 2 — `tests/unit/test_main.py` (new file)

Create `tests/unit/test_main.py`. Cover:

- **`_read_version` OSError** (lines 23-24): patch `Path.read_text` to raise `OSError`; assert return is `"unknown"`.
- **`_log_startup_banner`** (lines 28-39): call with a mock settings object; assert no exception raised (smoke test).
- **`_validate_config` — Telegram missing token** (lines 44-53): assert `ValueError` raised when `bot_token=""`.
- **`_validate_config` — Slack missing token** (lines 44-53): assert `ValueError` raised when `slack_bot_token=""`.
- **`_validate_config` — Telegram valid** (lines 44-53): assert no exception raised with valid tokens.
- **`_validate_config` — Slack valid** (lines 44-53): assert no exception raised with valid Slack tokens.
- **`main()` config error** (line 157): patch `Settings.load` to raise `ValueError`; assert `sys.exit(1)` is called.

---

### Step 3 — `tests/unit/test_session.py` additions

Cover `src/ai/session.py` gaps:

- **`CancelledError` kill path** (lines 44-45): cancel the task during `send()`; assert `proc.kill()` is called.
- **General exception in `send()`** (lines 51-53): mock `_spawn` to raise `RuntimeError`; assert return starts with `"⚠️ Session error:"`.
- **`stream()` exception** (lines 85-88): mock stdout iteration to raise `RuntimeError`; assert yielded string starts with `"⚠️ Session error:"`.
- **Stdout drain inside stats-marker** (line 78): mock stdout to yield a chunk containing `"\n\nTotal usage est:"` followed by extra lines; assert those extra lines are not yielded.

---

### Step 4 — `tests/unit/test_direct.py` additions

Cover `src/ai/direct.py` gaps:

- **Anthropic client factory** (lines 71-75): call `_get_anthropic_client()` twice; assert only one `AsyncAnthropic` instance is created (lazy init + caching).
- **`_anthropic_send`** (lines 80-81): mock `client.messages.create`; assert return value matches `message.content[0].text`.
- **`_anthropic_stream`** (lines 120-130): mock `client.messages.stream` as an async context manager; assert chunks are yielded correctly.

---

### Step 5 — `tests/unit/test_factory.py` additions

Cover `src/ai/factory.py` gaps:

- **Unknown `AI_CLI` value** (line 21): pass `ai_cli="unknown"` to `create_backend()`; assert `ValueError` is raised.
- **Codex backend selection** (lines 27-30): pass `ai_cli="codex"`; assert `CodexBackend` is returned.
- **Direct API backend selection** (lines 27-30): pass `ai_cli="api"`; assert `DirectAPIBackend` is returned.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `tests/unit/test_bot.py` | **Edit** | 7 new test cases for error paths, `build_app()` |
| `tests/unit/test_main.py` | **Create** | 7 new tests for `main.py` private functions |
| `tests/unit/test_session.py` | **Edit** | 4 new tests for `CopilotSession` error paths |
| `tests/unit/test_direct.py` | **Edit** | 3 new tests for Anthropic provider paths |
| `tests/unit/test_factory.py` | **Edit** | 3 new tests for unknown/Codex/Direct factory branches |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `pytest-asyncio` | ✅ Already installed | `asyncio_mode = auto` in `pytest.ini` |
| `pytest` | ✅ Already installed | |
| `unittest.mock` | ✅ stdlib | `MagicMock`, `AsyncMock`, `patch` |

---

## Test Plan

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_stream_edit_exception_ignored` | Telegram edit exception during streaming is silently ignored |
| `test_stream_no_timeout_branch` | `timeout_secs=0` uses the `else` branch (no `asyncio.wait_for`) |
| `test_make_transcriber_not_implemented` | `NotImplementedError` from factory returns `None`, logs warning |
| `test_run_ai_pipeline_history_disabled` | `history.get_history` not called when `history_enabled=False` |
| `test_non_streaming_timeout` | `TimeoutError` in `backend.send` edits message with warning text |
| `test_handle_voice_no_transcriber` | Reply "disabled" and return early when `_transcriber is None` |
| `test_build_app_handler_count` | `build_app()` registers expected number of handlers |

### `tests/unit/test_main.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_read_version_oserror` | Returns `"unknown"` when VERSION file is missing |
| `test_log_startup_banner_no_crash` | Smoke test — does not raise |
| `test_validate_config_telegram_missing_token` | `ValueError` when `TG_BOT_TOKEN` empty |
| `test_validate_config_telegram_missing_chat_id` | `ValueError` when `TG_CHAT_ID` empty |
| `test_validate_config_slack_missing_bot_token` | `ValueError` when `SLACK_BOT_TOKEN` empty |
| `test_validate_config_slack_missing_app_token` | `ValueError` when `SLACK_APP_TOKEN` empty |
| `test_validate_config_valid_telegram` | No exception with valid Telegram tokens |
| `test_main_config_error_exits` | `sys.exit(1)` called when `Settings.load()` raises |

### `tests/unit/test_session.py` additions

| Test | What it checks |
|------|----------------|
| `test_send_cancelled_kills_proc` | `CancelledError` triggers `proc.kill()` |
| `test_send_exception_returns_error_string` | Subprocess spawn error returns `"⚠️ Session error:"` |
| `test_stream_exception_yields_error` | stdout iteration error yields error string |
| `test_stream_drains_after_marker` | Lines after stats marker are not yielded |

### `tests/unit/test_direct.py` additions

| Test | What it checks |
|------|----------------|
| `test_anthropic_client_cached` | `_get_anthropic_client()` called twice returns same instance |
| `test_anthropic_send` | `_anthropic_send` calls API and returns `content[0].text` |
| `test_anthropic_stream` | `_anthropic_stream` yields chunks from stream |

### `tests/unit/test_factory.py` additions

| Test | What it checks |
|------|----------------|
| `test_unknown_backend_raises` | `create_backend("unknown")` raises `ValueError` |
| `test_codex_backend_selected` | `create_backend("codex")` returns `CodexBackend` |
| `test_direct_backend_selected` | `create_backend("api")` returns `DirectAPIBackend` |

---

## Documentation Updates

### `README.md`

No changes — this is an internal quality improvement with no user-visible behaviour change.

### `.github/copilot-instructions.md`

No changes needed.

### `docs/roadmap.md`

Mark item 1.1 as ✅ once total coverage reaches ≥90% and CI `--cov-fail-under` is raised to match.

---

## Version Bump

No version bump — this is a test-only change with no production code modifications.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] Total coverage (`pytest tests/ --cov=src --cov-report=term-missing`) reaches **≥ 90%**.
- [ ] No uncovered branch in any touched file is left without a `# pragma: no cover` comment.
- [ ] `docs/roadmap.md` item 1.1 is marked done (✅).
- [ ] `docs/features/test-coverage.md` status changed to `Implemented` on completion.
