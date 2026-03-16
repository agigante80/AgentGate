import asyncio
import logging
import shlex
import subprocess
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin
from src.config import REPO_DIR  # noqa: F401 — test seam for monkeypatching
from src.executor import scrubbed_env
from src.registry import backend_registry

logger = logging.getLogger(__name__)


@backend_registry.register("codex", force=True)
class CodexBackend(SubprocessMixin, AICLIBackend):
    """Stateless-per-invocation backend using OpenAI's Codex CLI.

    Each AgentGate message spawns a fresh `codex exec --full-auto --color never
    --ephemeral --model <model> <prompt>` subprocess. Codex handles multi-step
    agentic execution within that single call (file edits, tool use, shell commands),
    but does NOT retain state across calls. AgentGate injects conversation history
    via build_prompt() (is_stateful = False pattern).
    """

    is_stateful = False

    def __init__(self, api_key: str, model: str = "gpt-5.3-codex", opts: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._opts = opts
        self._login()

    def _login(self) -> None:
        """Authenticate Codex CLI by piping the API key to `codex login --with-api-key`.

        Codex CLI (Rust) reads credentials from $CODEX_HOME/auth.json only;
        OPENAI_API_KEY env var is not read by `codex exec`. This mirrors the
        documented usage: `printenv OPENAI_API_KEY | codex login --with-api-key`.
        Runs synchronously at startup; credentials persist across restarts in the
        Docker volume at /data/.codex/auth.json.
        """
        result = subprocess.run(
            ["codex", "login", "--with-api-key"],
            input=self._api_key,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            logger.warning("codex login failed: %s", result.stderr.strip())
        else:
            logger.info("CodexBackend: authenticated via API key")

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        env = {**scrubbed_env(), "OPENAI_API_KEY": self._api_key}
        # --full-auto: low-friction sandboxed execution (-a on-request, --sandbox workspace-write)
        # Replaced by AI_CLI_OPTS when set — allows per-deployment approval policy override.
        approval_flags = shlex.split(self._opts) if self._opts else ["--full-auto"]
        # Always-on flags: --color never prevents ANSI codes in captured stdout;
        # --ephemeral avoids accumulating session files in /data across messages.
        fixed_flags = ["--color", "never", "--ephemeral"]
        cmd = ["codex", "exec"] + approval_flags + fixed_flags + ["--model", self._model, prompt]
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
