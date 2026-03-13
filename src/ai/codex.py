import asyncio
import logging
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin
from src.config import REPO_DIR  # noqa: F401 — test seam for monkeypatching
logger = logging.getLogger(__name__)


class CodexBackend(SubprocessMixin, AICLIBackend):
    """Stateful backend that delegates to the Codex CLI subprocess."""

    def __init__(self, api_key: str, model: str = "o3", opts: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._opts = opts

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        import os
        env = {**os.environ, "OPENAI_API_KEY": self._api_key}
        # Empty opts → full-auto default; non-empty → verbatim (replaces defaults)
        extra = shlex.split(self._opts) if self._opts else ["--approval-mode", "full-auto"]
        cmd = ["codex", prompt] + extra + ["--model", self._model]
        return cmd, env

    async def _create_subprocess(self, prompt: str) -> asyncio.subprocess.Process:
        cmd, env = self._make_cmd(prompt)
        return await self._spawn(cmd, env)

    async def send(self, prompt: str) -> str:
        proc = await self._create_subprocess(prompt)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode().strip() or stdout.decode().strip()
            logger.error("codex CLI error: %s", err)
            return f"⚠️ Codex error:\n{err}"
        return stdout.decode().strip()

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        proc = await self._create_subprocess(prompt)
        assert proc.stdout
        async for line in proc.stdout:
            yield line.decode()
        await proc.wait()
        if proc.returncode != 0:
            assert proc.stderr
            err = (await proc.stderr.read()).decode().strip()
            if err:
                logger.error("codex CLI stream error: %s", err)
                yield f"\n⚠️ Codex error:\n{err}"
