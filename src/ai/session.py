"""
Persistent pexpect PTY session for the Copilot CLI interactive mode.
Keeps one long-running `copilot` process alive per backend instance.
"""
import asyncio
import logging
import queue as _queue
import re
import threading
import time
from collections.abc import AsyncGenerator

import pexpect

from src.config import REPO_DIR
PROMPT_RE = re.compile(r"\n?>\s*$")  # copilot CLI prompt is "> "
TIMEOUT = 180

logger = logging.getLogger(__name__)


class CopilotSession:
    def __init__(self, model: str = "", env: dict | None = None) -> None:
        self._model = model
        self._env = env
        self._child: pexpect.spawn | None = None

    def _spawn(self) -> pexpect.spawn:
        cmd = "copilot"
        args = ["--allow-all"]
        if self._model:
            args += ["--model", self._model]
        logger.info("Spawning copilot PTY session…")
        child = pexpect.spawn(
            cmd, args,
            cwd=str(REPO_DIR),
            env=self._env,
            encoding="utf-8",
            timeout=TIMEOUT,
            echo=False,
        )
        idx = child.expect(
            [PROMPT_RE, re.compile(r"authenticate|login|auth", re.I), pexpect.TIMEOUT],
            timeout=30,
        )
        if idx != 0:
            raise RuntimeError(
                "Copilot auth failed — check COPILOT_GITHUB_TOKEN has 'Copilot Requests' permission"
            )
        logger.info("Copilot session ready.")
        return child

    def _ensure(self) -> pexpect.spawn:
        if self._child is None or not self._child.isalive():
            self._child = self._spawn()
        return self._child

    # ── Blocking send (runs in thread via asyncio.to_thread) ─────────────

    async def send(self, prompt: str) -> str:
        return await asyncio.to_thread(self._sync_send, prompt)

    def _sync_send(self, prompt: str) -> str:
        try:
            child = self._ensure()
            child.sendline(prompt)
            child.expect(PROMPT_RE, timeout=TIMEOUT)
            output = child.before or ""
            return _strip_ansi(output.strip())
        except pexpect.TIMEOUT:
            self._child = None
            return f"⚠️ Copilot session timed out after {TIMEOUT}s."
        except pexpect.EOF:
            self._child = None
            return "⚠️ Copilot session ended unexpectedly."
        except Exception as exc:
            self._child = None
            logger.exception("PTY session error")
            return f"⚠️ Session error: {exc}"

    # ── Streaming send (PTY → thread-safe queue → async generator) ───────

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Yield PTY output chunks as they arrive, bridged via a thread-safe queue."""
        q: _queue.SimpleQueue[str | None] = _queue.SimpleQueue()
        t = threading.Thread(target=self._sync_stream_to_queue, args=(prompt, q), daemon=True)
        t.start()

        while True:
            try:
                item = q.get_nowait()
            except _queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield item

        t.join(timeout=1)

    def _sync_stream_to_queue(self, prompt: str, q: "_queue.SimpleQueue[str | None]") -> None:
        try:
            child = self._ensure()
            child.sendline(prompt)
            acc = ""
            start = time.monotonic()
            while True:
                if time.monotonic() - start > TIMEOUT:
                    q.put(f"⚠️ Copilot session timed out after {TIMEOUT}s.")
                    q.put(None)
                    return
                try:
                    chunk = _strip_ansi(child.read_nonblocking(size=256, timeout=0.2))
                    acc += chunk
                    if PROMPT_RE.search(acc):
                        clean = PROMPT_RE.sub("", acc).strip()
                        if clean:
                            q.put(clean)
                        q.put(None)
                        return
                    if chunk:
                        q.put(chunk)
                except pexpect.TIMEOUT:
                    continue
                except pexpect.EOF:
                    clean = _strip_ansi(acc).strip()
                    if clean:
                        q.put(clean)
                    q.put(None)
                    self._child = None
                    return
        except Exception as exc:
            logger.exception("PTY stream error")
            q.put(f"⚠️ Session error: {exc}")
            q.put(None)

    def close(self) -> None:
        if self._child and self._child.isalive():
            self._child.sendline("/exit")
            self._child.close()
        self._child = None


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
