"""
Tests for CopilotSession (src/ai/session.py) — subprocess -p mode.
No real process is spawned; asyncio.create_subprocess_exec is fully mocked.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.session import CopilotSession, _strip_stats


# ── Helpers ──────────────────────────────────────────────────────────────────

class _FakeProcess:
    """Minimal mock for asyncio subprocess."""

    def __init__(self, stdout_lines: list, returncode: int = 0):
        self.returncode = returncode
        self._lines = iter(stdout_lines)
        self.stdout = self
        self.stderr = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._lines)
        except StopIteration:
            raise StopAsyncIteration

    async def communicate(self):
        data = b"".join(list(self._lines))
        return data, b""

    async def wait(self):
        return self.returncode

    def terminate(self):
        pass


# ── _strip_stats ──────────────────────────────────────────────────────────────

def test_strip_stats_removes_footer():
    text = "Hello world\n\nTotal usage est:        1 Premium request\nAPI time spent: 1s"
    assert _strip_stats(text) == "Hello world"


def test_strip_stats_passthrough_no_footer():
    assert _strip_stats("plain response") == "plain response"


def test_strip_stats_strips_whitespace():
    assert _strip_stats("  hi  ") == "hi"


# ── _build_cmd ────────────────────────────────────────────────────────────────

def test_build_cmd_no_model():
    s = CopilotSession()
    assert s._build_cmd("hello") == ["copilot", "-p", "hello", "--silent", "--allow-all"]


def test_build_cmd_with_model():
    s = CopilotSession(model="gpt-4o")
    assert s._build_cmd("q") == ["copilot", "-p", "q", "--silent", "--model", "gpt-4o", "--allow-all"]


def test_build_cmd_empty_opts_defaults_to_allow_all():
    s = CopilotSession(opts="")
    assert "--allow-all" in s._build_cmd("q")


def test_build_cmd_custom_opts_replaces_allow_all():
    s = CopilotSession(opts="--allow-url github.com --allow-all-tools")
    cmd = s._build_cmd("q")
    assert "--allow-url" in cmd
    assert "github.com" in cmd
    assert "--allow-all-tools" in cmd
    assert "--allow-all" not in cmd


def test_build_cmd_custom_opts_with_model():
    s = CopilotSession(model="gpt-4o", opts="--allow-all-tools")
    cmd = s._build_cmd("q")
    assert "--model" in cmd
    assert "gpt-4o" in cmd
    assert "--allow-all-tools" in cmd
    assert "--allow-all" not in cmd


# ── send ──────────────────────────────────────────────────────────────────────

class TestSend:
    @pytest.mark.asyncio
    async def test_send_returns_stripped_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        raw = b"Hello!\n\nTotal usage est:        1 Premium request\nAPI time: 1s"
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(raw, b""))
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await CopilotSession().send("hi")
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_send_cancelled_error_kills_proc(self, tmp_path, monkeypatch):
        """CancelledError inside send() must kill the subprocess and re-raise."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        proc = MagicMock()
        proc.kill = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(asyncio.CancelledError):
                await CopilotSession().send("hi")
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_exception_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("boom"))):
            result = await CopilotSession().send("hi")
        assert "Session error" in result


# ── stream ────────────────────────────────────────────────────────────────────

class TestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        lines = [b"A" * 50, b"B" * 50]
        proc = _FakeProcess(lines)
        proc.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            chunks = []
            async for c in CopilotSession().stream("q"):
                chunks.append(c)
        assert "".join(chunks).strip() != ""

    @pytest.mark.asyncio
    async def test_stream_strips_stats_footer(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        lines = [b"Hi!\n\nTotal usage est:        1 Premium request\n"]
        proc = _FakeProcess(lines)
        proc.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = "".join([c async for c in CopilotSession().stream("q")])
        assert "Total usage est" not in result
        assert "Hi!" in result

    @pytest.mark.asyncio
    async def test_stream_exception_yields_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("fail"))):
            chunks = [c async for c in CopilotSession().stream("q")]
        assert any("Session error" in c for c in chunks)


# ── close ─────────────────────────────────────────────────────────────────────

def test_close_is_noop():
    CopilotSession().close()  # must not raise


# ── send error paths ──────────────────────────────────────────────────────────

class TestSendErrorPaths:
    async def test_send_nonzero_returncode_returns_error(self, tmp_path, monkeypatch):
        """Non-zero returncode in send() returns a formatted error string."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"something went wrong"))
        proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await CopilotSession().send("hi")
        assert "Copilot error" in result
        assert "rc=1" in result

    async def test_send_cancelled_error_kill_raises_is_swallowed(self, tmp_path, monkeypatch):
        """If proc.kill() itself raises during CancelledError, the inner exception is swallowed."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        proc = MagicMock()
        proc.kill = MagicMock(side_effect=OSError("no such process"))
        proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(asyncio.CancelledError):
                await CopilotSession().send("hi")
        # kill() was attempted even though it raised
        proc.kill.assert_called_once()


# ── stream error paths ────────────────────────────────────────────────────────

class TestStreamErrorPaths:
    async def test_stream_drains_remaining_after_stats_marker(self, tmp_path, monkeypatch):
        """Lines after the stats marker are drained (not yielded) to cover line 78."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        # Two chunks: content with marker, then extra junk that should be drained
        lines = [
            b"Hi!\n\nTotal usage est:        1 Premium request\n",
            b"this should be drained and never yielded\n",
        ]
        proc = _FakeProcess(lines)
        proc.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = "".join([c async for c in CopilotSession().stream("q")])
        assert "drained" not in result
        assert "Total usage est" not in result

    async def test_stream_exception_inside_loop_yields_error(self, tmp_path, monkeypatch):
        """Exception raised during stdout iteration (after _spawn) yields an error string."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)

        class _BrokenStdout:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise RuntimeError("pipe broken")

        proc = MagicMock()
        proc.stdout = _BrokenStdout()
        proc.wait = AsyncMock(return_value=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            chunks = [c async for c in CopilotSession().stream("q")]
        assert any("Session error" in c for c in chunks)

    async def test_stream_nonzero_returncode_appends_warning(self, tmp_path, monkeypatch):
        """When stream finishes but returncode != 0, a warning chunk is appended."""
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        proc = _FakeProcess([b"partial output\n"], returncode=2)
        proc.wait = AsyncMock(return_value=2)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            chunks = [c async for c in CopilotSession().stream("q")]
        combined = "".join(chunks)
        assert "rc=2" in combined

