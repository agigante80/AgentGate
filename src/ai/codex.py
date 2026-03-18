import asyncio
import logging
import os
import shlex
import subprocess
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin
from src.config import REPO_DIR  # noqa: F401 — test seam for monkeypatching
from src.executor import scrubbed_env
from src.registry import backend_registry

logger = logging.getLogger(__name__)

TIMEOUT = 300  # seconds — hard cap; Codex agentic tasks can run long but 5 min is a safe ceiling
_MAX_ERR_CHARS = 2_000  # truncate runaway error output sent back to the user


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

    def _ensure_auth(self) -> None:
        """Re-authenticate Codex CLI before every invocation.

        Codex CLI (Rust) reads credentials from $CODEX_HOME/auth.json only;
        OPENAI_API_KEY env var is not read by `codex exec`. Because Codex is an
        agentic tool that can run arbitrary shell commands, a task (e.g. /init)
        may itself invoke `codex login` with test credentials, silently corrupting
        auth.json. Re-running login before every send()/stream() call guarantees
        the correct key is always in place.

        Also verifies the written key matches self._api_key and warns if not.
        No-ops gracefully when the `codex` binary is not installed (e.g. in CI).
        """
        try:
            result = subprocess.run(
                ["codex", "login", "--with-api-key"],
                input=self._api_key,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.debug("codex binary not found — skipping login (not running in Docker?)")
            return
        if result.returncode != 0:
            logger.warning("codex login failed: %s", result.stderr.strip())
            return
        logger.debug("CodexBackend: auth refreshed")
        # Verify the written key matches to catch silent corruption early.
        try:
            import json as _json
            import os as _os
            codex_home = _os.environ.get("CODEX_HOME") or _os.path.expanduser("~/.codex")
            auth_path = _os.path.join(codex_home, "auth.json")
            stored = _json.loads(open(auth_path).read()).get("OPENAI_API_KEY", "")
            if stored != self._api_key:
                logger.warning(
                    "codex auth.json key mismatch after login (stored %d chars, expected %d) — "
                    "possible interference from a Codex shell command",
                    len(stored), len(self._api_key),
                )
        except Exception:
            pass  # verification is best-effort; never block the request

    def _login(self) -> None:
        """Initial login at construction time — delegates to _ensure_auth()."""
        self._ensure_auth()

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        env = {**scrubbed_env(), "OPENAI_API_KEY": self._api_key}
        # Re-inject the GitHub token as GH_TOKEN so `gh` CLI and raw git operations
        # work in model shell commands. scrubbed_env() strips GITHUB_REPO_TOKEN.
        if github_token := os.environ.get("GITHUB_REPO_TOKEN"):
            env["GH_TOKEN"] = github_token
            env["GITHUB_TOKEN"] = github_token
        # --dangerously-bypass-approvals-and-sandbox: removes the workspace-write network sandbox
        # so model shell commands (git fetch, curl, etc.) have full outbound access.
        # Docker is the external isolation boundary; intended for exactly this use case.
        # Replaced by AI_CLI_OPTS when set — allows per-deployment policy override.
        approval_flags = shlex.split(self._opts) if self._opts else ["--dangerously-bypass-approvals-and-sandbox"]
        # Always-on flags: --color never prevents ANSI codes in captured stdout;
        # --ephemeral avoids accumulating session files in /data across messages.
        fixed_flags = ["--color", "never", "--ephemeral"]
        cmd = ["codex", "exec"] + approval_flags + fixed_flags + ["--model", self._model, prompt]
        return cmd, env

    async def _create_subprocess(self, prompt: str) -> asyncio.subprocess.Process:
        self._ensure_auth()
        cmd, env = self._make_cmd(prompt)
        return await self._spawn(cmd, env)

    async def send(self, prompt: str) -> str:
        proc = await self._create_subprocess(prompt)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error("codex timed out after %ss", TIMEOUT)
            return f"⚠️ Codex timed out after {TIMEOUT}s."
        if proc.returncode != 0:
            err = stderr.decode().strip() or stdout.decode().strip()
            err = err[-_MAX_ERR_CHARS:] if len(err) > _MAX_ERR_CHARS else err
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
