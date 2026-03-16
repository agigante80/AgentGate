"""
Tests for GeminiBackend (src/ai/gemini.py).
All subprocess I/O is fully mocked — no real gemini process is spawned.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.gemini import GeminiBackend, TIMEOUT


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def _make_proc(stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.wait = AsyncMock()
    lines = stdout.splitlines(keepends=True)
    proc.stdout.__aiter__ = MagicMock(return_value=_AsyncIter(lines))
    return proc


# ── Construction ───────────────────────────────────────────────────────────────

class TestConstruction:
    def test_stores_fields(self):
        b = GeminiBackend(api_key="k", model="gemini-2.5-pro", opts="--debug")
        assert b._api_key == "k"
        assert b._model == "gemini-2.5-pro"
        assert b._opts == "--debug"

    def test_not_stateful(self):
        assert GeminiBackend(api_key="k").is_stateful is False


# ── _make_cmd ─────────────────────────────────────────────────────────────────

class TestMakeCmd:
    def test_default_cmd_has_non_interactive(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("hello")
        assert "--non-interactive" in cmd

    def test_default_cmd_has_no_tools(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("hello")
        assert "--no-tools" in cmd

    def test_prompt_in_cmd(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("my prompt")
        assert "-p" in cmd
        assert "my prompt" in cmd

    def test_env_does_not_contain_other_secrets(self):
        """scrubbed_env() must have stripped other AgentGate secrets from the env."""
        import os
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret", "SLACK_BOT_TOKEN": "xoxb-secret"}):
            b = GeminiBackend(api_key="AIzaXYZ")
            _, env = b._make_cmd("hello")
        assert "OPENAI_API_KEY" not in env
        assert "SLACK_BOT_TOKEN" not in env

    def test_env_contains_api_key(self):
        b = GeminiBackend(api_key="AIzaXYZ")
        _, env = b._make_cmd("hello")
        assert env["GEMINI_API_KEY"] == "AIzaXYZ"

    def test_model_flag_added_when_set(self):
        b = GeminiBackend(api_key="k", model="gemini-2.5-pro")
        cmd, _ = b._make_cmd("hi")
        assert "--model" in cmd
        assert "gemini-2.5-pro" in cmd

    def test_model_flag_absent_when_empty(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("hi")
        assert "--model" not in cmd

    def test_custom_opts_appended_after_safety_flags(self):
        """Safety flags are always prepended; custom opts are additive, not replacing."""
        b = GeminiBackend(api_key="k", opts="--yolo")
        cmd, _ = b._make_cmd("hi")
        assert "--non-interactive" in cmd
        assert "--no-tools" in cmd
        assert "--yolo" in cmd

    def test_custom_opts_parsed_with_shlex(self):
        b = GeminiBackend(api_key="k", opts="--debug --sandbox")
        cmd, _ = b._make_cmd("hi")
        assert "--debug" in cmd
        assert "--sandbox" in cmd
        assert "--non-interactive" in cmd
        assert "--no-tools" in cmd

    def test_safety_negation_flags_stripped(self):
        """Flags that negate mandatory safety flags are stripped from user opts."""
        b = GeminiBackend(api_key="k", opts="--tools --interactive --debug")
        cmd, _ = b._make_cmd("hi")
        assert "--tools" not in cmd
        assert "--interactive" not in cmd
        assert "--debug" in cmd
        assert "--non-interactive" in cmd
        assert "--no-tools" in cmd

    def test_safety_negation_value_forms_stripped(self):
        """--tools=shell and --interactive=true must also be blocked (value-form bypass)."""
        b = GeminiBackend(api_key="k", opts="--tools=shell --interactive=true --debug")
        cmd, _ = b._make_cmd("hi")
        assert not any(c.startswith("--tools") for c in cmd if c != "--no-tools")
        assert not any(c.startswith("--interactive") for c in cmd if c != "--non-interactive")
        assert "--debug" in cmd
        assert "--non-interactive" in cmd
        assert "--no-tools" in cmd


# ── send() ─────────────────────────────────────────────────────────────────────

class TestSend:
    async def test_send_success(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"Hello from Gemini")
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert result == "Hello from Gemini"

    async def test_send_error_rc1(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"auth error", returncode=1)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "⚠️" in result
        assert "auth error" in result

    async def test_send_error_rc42_invalid_input(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"bad prompt", returncode=42)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "invalid input" in result

    async def test_send_error_rc53_turn_limit(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"rate limit", returncode=53)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "turn limit" in result

    async def test_send_timeout(self):
        b = GeminiBackend(api_key="k")
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = AsyncMock()
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert f"{TIMEOUT}s" in result
        assert "⚠️" in result


# ── stream() ───────────────────────────────────────────────────────────────────

class TestStream:
    async def test_stream_yields_lines(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"line1\nline2\n")
        with patch.object(b, "_spawn", return_value=proc):
            chunks = [c async for c in b.stream("hello")]
        assert "".join(chunks).strip() == "line1\nline2"

    async def test_stream_error_appended(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"partial", stderr=b"stream error", returncode=1)
        with patch.object(b, "_spawn", return_value=proc):
            chunks = [c async for c in b.stream("hello")]
        full = "".join(chunks)
        assert "⚠️" in full
        assert "stream error" in full


# ── clear_history ──────────────────────────────────────────────────────────────

class TestClearHistory:
    def test_clear_history_does_not_raise(self):
        b = GeminiBackend(api_key="k")
        b.clear_history()  # no-op inherited from AICLIBackend — must not raise
