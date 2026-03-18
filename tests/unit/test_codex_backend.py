"""
Tests for CodexBackend (src/ai/codex.py).
All subprocess I/O is fully mocked — no real codex process is spawned.
`subprocess.run` is patched globally (autouse) so `_login()` never calls the real CLI.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.ai.codex import CodexBackend


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_subprocess_run():
    """Prevent real `codex login` subprocess calls in every test."""
    with patch("src.ai.codex.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="Successfully logged in", stderr="")
        yield mock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_proc(stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.wait = AsyncMock()
    # Make proc.stdout async-iterable yielding lines
    lines = stdout.splitlines(keepends=True)
    proc.stdout.__aiter__ = MagicMock(return_value=aiter_from_list(lines))
    return proc


class _AsyncIter:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def aiter_from_list(items):
    return _AsyncIter(items)


# ── Construction ──────────────────────────────────────────────────────────────

class TestConstruction:
    def test_stores_api_key_and_model(self):
        backend = CodexBackend(api_key="sk-test", model="o3")
        assert backend._api_key == "sk-test"
        assert backend._model == "o3"

    def test_default_model(self):
        backend = CodexBackend(api_key="sk-test")
        assert backend._model == "gpt-5.3-codex"

    def test_not_stateful(self):
        assert CodexBackend(api_key="k").is_stateful is False

    def test_login_called_on_init(self, mock_subprocess_run):
        CodexBackend(api_key="sk-mykey")
        mock_subprocess_run.assert_called_once_with(
            ["codex", "login", "--with-api-key"],
            input="sk-mykey",
            text=True,
            capture_output=True,
        )


# ── _login ────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_success_logs_info(self, mock_subprocess_run, caplog):
        import logging
        mock_subprocess_run.return_value = MagicMock(returncode=0, stderr="")
        with caplog.at_level(logging.INFO, logger="src.ai.codex"):
            CodexBackend(api_key="sk-x")
        assert any("authenticated" in r.message for r in caplog.records)

    def test_login_failure_logs_warning(self, mock_subprocess_run, caplog):
        import logging
        mock_subprocess_run.return_value = MagicMock(returncode=1, stderr="some error")
        with caplog.at_level(logging.WARNING, logger="src.ai.codex"):
            CodexBackend(api_key="sk-x")
        assert any("failed" in r.message for r in caplog.records)

    def test_login_no_op_when_codex_not_installed(self, mock_subprocess_run, caplog):
        """_login() must not raise when the codex binary is absent (e.g. CI)."""
        import logging
        mock_subprocess_run.side_effect = FileNotFoundError("codex not found")
        with caplog.at_level(logging.DEBUG, logger="src.ai.codex"):
            backend = CodexBackend(api_key="sk-x")  # must not raise
        assert backend is not None
        assert any("not found" in r.message for r in caplog.records)


# ── _make_cmd ─────────────────────────────────────────────────────────────────

class TestMakeCmd:
    def test_includes_prompt_and_model(self):
        backend = CodexBackend(api_key="sk-x", model="o4")
        cmd, env = backend._make_cmd("hello world")
        assert "codex" in cmd
        assert "exec" in cmd
        assert "hello world" in cmd
        assert "--model" in cmd
        assert "o4" in cmd

    def test_env_contains_api_key(self):
        backend = CodexBackend(api_key="sk-test")
        _, env = backend._make_cmd("prompt")
        assert env["OPENAI_API_KEY"] == "sk-test"

    def test_default_opts_bypasses_sandbox(self):
        backend = CodexBackend(api_key="sk-x")
        cmd, _ = backend._make_cmd("prompt")
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--full-auto" not in cmd
        assert "--approval-mode" not in cmd

    def test_always_on_flags_present(self):
        """--color never and --ephemeral are always included regardless of opts."""
        backend = CodexBackend(api_key="sk-x")
        cmd, _ = backend._make_cmd("prompt")
        assert "--color" in cmd
        idx = cmd.index("--color")
        assert cmd[idx + 1] == "never"
        assert "--ephemeral" in cmd

    def test_custom_opts_replaces_full_auto(self):
        backend = CodexBackend(api_key="sk-x", opts="-s danger-full-access")
        cmd, _ = backend._make_cmd("prompt")
        assert "danger-full-access" in cmd
        assert "--full-auto" not in cmd
        # Always-on flags are still present
        assert "--color" in cmd
        assert "--ephemeral" in cmd

    def test_custom_opts_passthrough(self):
        backend = CodexBackend(api_key="sk-x", opts="--search --add-dir /extra")
        cmd, _ = backend._make_cmd("prompt")
        assert "exec" in cmd
        assert "--search" in cmd
        assert "--add-dir" in cmd
        assert "/extra" in cmd
        assert "--full-auto" not in cmd


# ── send ─────────────────────────────────────────────────────────────────────

class TestSend:
    async def test_returns_stdout_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = _make_proc(stdout=b"Hello from codex\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            result = await backend.send("hi")
        assert result == "Hello from codex"

    async def test_returns_error_on_non_zero_exit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = _make_proc(stdout=b"", stderr=b"rate limited", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            result = await backend.send("hi")
        assert "error" in result.lower() or "Codex" in result
        assert "rate limited" in result

    async def test_uses_stdout_as_error_when_stderr_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = _make_proc(stdout=b"some output", stderr=b"", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            result = await backend.send("hi")
        assert "some output" in result

    async def test_timeout_kills_process(self, tmp_path, monkeypatch):
        import asyncio as _asyncio
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()

        async def _hang():
            raise _asyncio.TimeoutError()

        proc.communicate = AsyncMock(side_effect=_asyncio.TimeoutError())
        # Second communicate() call (after kill) returns empty output
        proc.communicate = AsyncMock(side_effect=[_asyncio.TimeoutError(), (b"", b"")])
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            result = await backend.send("hi")
        assert "timed out" in result.lower()
        proc.kill.assert_called_once()

    async def test_error_output_truncated(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        big_err = b"x" * 10_000
        proc = _make_proc(stdout=b"", stderr=big_err, returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            result = await backend.send("hi")
        from src.ai.codex import _MAX_ERR_CHARS
        assert len(result) <= len("⚠️ Codex error:\n") + _MAX_ERR_CHARS + 50  # small tolerance


# ── stream ────────────────────────────────────────────────────────────────────

class TestStream:
    async def test_yields_lines(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = _make_proc(stdout=b"line1\nline2\n", returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            chunks = [c async for c in backend.stream("prompt")]
        assert any("line1" in c for c in chunks)
        assert any("line2" in c for c in chunks)

    async def test_appends_error_on_non_zero_exit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.codex.REPO_DIR", tmp_path)
        proc = _make_proc(stdout=b"partial\n", stderr=b"crash", returncode=2)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            backend = CodexBackend(api_key="sk-x")
            chunks = [c async for c in backend.stream("prompt")]
        full = "".join(chunks)
        assert "crash" in full or "error" in full.lower()
