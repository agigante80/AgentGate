"""
Gemini CLI backend — non-interactive subprocess mode.
Each query spawns `gemini -p <prompt> --yolo -o text` as a subprocess.
History is injected by the bot layer via build_prompt() (stateless pattern).
"""
import asyncio
import logging
import os
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin
from src.executor import scrubbed_env
from src.registry import backend_registry

logger = logging.getLogger(__name__)

TIMEOUT = 180  # seconds — hard cap to prevent process hangs


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
        # Re-inject the GitHub token as GH_TOKEN so the `gh` CLI and raw git
        # operations work inside run_shell_command calls. Gemini shell commands
        # inherit the subprocess env; we explicitly pass GH_TOKEN because
        # scrubbed_env() strips GITHUB_REPO_TOKEN for safety.
        if github_token := os.environ.get("GITHUB_REPO_TOKEN"):
            env["GH_TOKEN"] = github_token
            env["GITHUB_TOKEN"] = github_token
        # --yolo: auto-approve all Gemini tool calls (file reads, file writes, and shell
        # commands). Docker container isolation is the containment boundary — Gemini can
        # only affect what is mounted into the container. File changes are git-tracked.
        # -o text: force plain-text stdout so no ANSI codes or JSON UI decorations
        # bleed into the model response captured by send() / stream().
        # Non-interactive mode is handled by -p/--prompt (already in the command).
        safety_flags = ["--yolo", "-o", "text"]
        user_opts = shlex.split(self._opts) if self._opts else []
        # Strip any --approval-mode from user opts (conflicts with --yolo).
        filtered_opts: list[str] = []
        skip_next = False
        for o in user_opts:
            if skip_next:
                skip_next = False
                continue
            if o == "--approval-mode":
                skip_next = True
                continue
            if o.startswith("--approval-mode="):
                continue
            filtered_opts.append(o)
        extra = safety_flags + filtered_opts
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
