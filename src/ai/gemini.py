"""
Gemini CLI backend — non-interactive subprocess mode.
Each query spawns `gemini --non-interactive -p <prompt>` as a subprocess.
History is injected by the bot layer via build_prompt() (stateless pattern).
"""
import asyncio
import logging
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin
from src.executor import scrubbed_env
from src.registry import backend_registry

logger = logging.getLogger(__name__)

TIMEOUT = 180  # seconds — hard cap to prevent process hangs

# Flags that would override mandatory safety flags via CLI last-wins semantics.
_SAFETY_NEGATIONS: frozenset[str] = frozenset({"--interactive", "--tools"})


@backend_registry.register("gemini")
class GeminiBackend(SubprocessMixin, AICLIBackend):
    """Stateless backend using Google's official Gemini CLI."""

    is_stateful = False

    def __init__(self, api_key: str, model: str = "", opts: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._opts = opts

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        env = {**scrubbed_env(), "GEMINI_API_KEY": self._api_key}
        # Always prepend safety flags — never allow AI_CLI_OPTS to override them.
        # --non-interactive: prevents auth dialogs and interactive prompts in headless mode.
        # --no-tools: disables Gemini's built-in shell exec, file writes, and web search, which
        #   would otherwise bypass AgentGate's SHELL_ALLOWLIST, is_destructive() checks,
        #   confirmation dialogs, and audit logging entirely.
        safety_flags = ["--non-interactive", "--no-tools"]
        user_opts = shlex.split(self._opts) if self._opts else []
        # Strip flags that negate safety flags — most CLIs use last-wins semantics.
        # Match both bare (--tools) and value (--tools=shell) forms.
        user_opts = [
            o for o in user_opts
            if not any(o == neg or o.startswith(f"{neg}=") for neg in _SAFETY_NEGATIONS)
        ]
        extra = safety_flags + user_opts
        cmd = ["gemini", "-p", prompt] + extra
        if self._model:
            cmd += ["--model", self._model]
        return cmd, env

    async def send(self, prompt: str) -> str:
        cmd, env = self._make_cmd(prompt)
        try:
            proc = await self._spawn(cmd, env)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
                await proc.wait()  # reap zombie — prevent defunct gemini processes
            except Exception:
                pass
            return f"⚠️ Gemini timed out after {TIMEOUT}s."
        except Exception as exc:
            logger.exception("Gemini subprocess error")
            return f"⚠️ Gemini error: {exc}"
        if proc.returncode not in (0, None):
            err = stderr.decode().strip() or stdout.decode().strip()
            rc = proc.returncode
            suffix = {42: " (invalid input)", 53: " (turn limit exceeded)"}.get(rc, "")
            logger.error("gemini CLI error (rc=%d%s): %s", rc, suffix, err)
            return f"⚠️ Gemini error (rc={rc}{suffix}):\n{err}"
        return stdout.decode().strip()

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        cmd, env = self._make_cmd(prompt)
        try:
            proc = await self._spawn(cmd, env)
        except Exception as exc:
            logger.exception("Gemini stream error")
            yield f"⚠️ Gemini error: {exc}"
            return
        assert proc.stdout
        try:
            async for line in proc.stdout:
                yield line.decode()
        except Exception as exc:
            logger.exception("Gemini stream read error")
            yield f"\n⚠️ Gemini stream error: {exc}"
            return
        finally:
            await proc.wait()
        if proc.returncode not in (0, None):
            assert proc.stderr
            err = (await proc.stderr.read()).decode().strip()
            rc = proc.returncode
            suffix = {42: " (invalid input)", 53: " (turn limit exceeded)"}.get(rc, "")
            if err:
                logger.error("gemini CLI stream error (rc=%d%s): %s", rc, suffix, err)
                yield f"\n⚠️ Gemini error (rc={rc}{suffix}):\n{err}"
