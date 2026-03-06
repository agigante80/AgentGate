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
    assert s._build_cmd("hello") == ["copilot", "-p", "hello", "--allow-all"]


def test_build_cmd_with_model():
    s = CopilotSession(model="gpt-4o")
    assert s._build_cmd("q") == ["copilot", "-p", "q", "--allow-all", "--model", "gpt-4o"]


# ── send ──────────────────────────────────────────────────────────────────────

class TestSend:
    @pytest.mark.asyncio
    async def test_send_returns_stripped_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        raw = b"Hello!\n\nTotal usage est:        1 Premium request\nAPI time: 1s"
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(raw, b""))
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await CopilotSession().send("hi")
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_send_timeout_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ai.session.REPO_DIR", tmp_path)
        proc = MagicMock()
        proc.terminate = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await CopilotSession().send("hi")
        assert "timed out" in result

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

