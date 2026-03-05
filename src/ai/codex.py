import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from src.ai.adapter import AICLIBackend

REPO_DIR = Path("/repo")
logger = logging.getLogger(__name__)


class CodexBackend(AICLIBackend):
    def __init__(self, api_key: str, model: str = "o3") -> None:
        self._api_key = api_key
        self._model = model

    def _make_proc_args(self, prompt: str) -> tuple[list[str], dict]:
        import os
        env = {**os.environ, "OPENAI_API_KEY": self._api_key}
        cmd = ["codex", prompt, "--approval-mode", "auto", "--model", self._model]
        return cmd, env

    async def send(self, prompt: str) -> str:
        cmd, env = self._make_proc_args(prompt)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode().strip() or stdout.decode().strip()
            logger.error("codex CLI error: %s", err)
            return f"⚠️ Codex error:\n{err}"
        return stdout.decode().strip()

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        cmd, env = self._make_proc_args(prompt)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdout
        async for line in proc.stdout:
            yield line.decode()
        await proc.wait()
        if proc.returncode != 0:
            assert proc.stderr
            err = (await proc.stderr.read()).decode().strip()
            if err:
                yield f"\n⚠️ Codex error:\n{err}"
