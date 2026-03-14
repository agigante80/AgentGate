"""
Copilot CLI session using non-interactive subprocess mode (-p flag).
Each query spawns `copilot -p <prompt> [opts|--allow-all]` as a subprocess.
This avoids PTY/TUI complexity and the interactive folder-trust dialog.
"""
import asyncio
import logging
import re
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import SubprocessMixin
from src.config import REPO_DIR  # noqa: F401 — test seam for monkeypatching

logger = logging.getLogger(__name__)

# Strip usage stats footer appended by copilot -p to every response
_STATS_RE = re.compile(r"\n\nTotal usage est:.*", re.DOTALL)


class CopilotSession(SubprocessMixin):
    def __init__(self, model: str = "", env: dict | None = None, opts: str = "") -> None:
        self._model = model
        self._env = env
        self._opts = opts

    def _build_cmd(self, prompt: str) -> list[str]:
        args = ["copilot", "-p", prompt, "--silent"]  # --silent: no stats footer (v1.0.5+)
        if self._model:
            args += ["--model", self._model]
        # Empty opts → full-auto default; non-empty → verbatim (replaces defaults)
        args += shlex.split(self._opts) if self._opts else ["--allow-all"]
        return args

    async def send(self, prompt: str) -> str:
        proc = None
        try:
            proc = await self._spawn(self._build_cmd(prompt), self._env)
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            raise
        except Exception as exc:
            logger.exception("Copilot subprocess error")
            return f"⚠️ Session error: {exc}"
        if proc.returncode != 0:
            err = stderr.decode().strip() or stdout.decode().strip()
            logger.error("copilot CLI error (rc=%d): %s", proc.returncode, err)
            return f"⚠️ Copilot error (rc={proc.returncode}):\n{err}"
        return _strip_stats(stdout.decode())

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Yield stdout chunks as they arrive, stripping the stats footer."""
        _MARKER = "\n\nTotal usage est:"
        _KEEP = len(_MARKER)
        try:
            proc = await self._spawn(self._build_cmd(prompt), self._env)
        except Exception as exc:
            logger.exception("Copilot stream error")
            yield f"⚠️ Session error: {exc}"
            return
        buf = ""
        try:
            async for raw in proc.stdout:
                chunk = raw.decode()
                buf += chunk
                if _MARKER in buf:
                    # Yield content before the stats footer, then stop
                    clean = buf[: buf.index(_MARKER)]
                    if clean:
                        yield clean
                    # Drain remaining stdout (ignore stats)
                    async for _ in proc.stdout:
                        pass
                    break
                # Keep last _KEEP chars buffered so marker isn't split across yields
                if len(buf) > _KEEP:
                    safe, buf = buf[:-_KEEP], buf[-_KEEP:]
                    if safe:
                        yield safe
        except Exception as exc:
            logger.exception("Copilot stream error")
            yield f"⚠️ Session error: {exc}"
            return
        finally:
            await proc.wait()
        # Yield whatever remains (won't contain the stats footer)
        if buf:
            clean = _strip_stats(buf)
            if clean:
                yield clean
        if proc.returncode != 0:
            logger.error("copilot CLI stream error (rc=%d)", proc.returncode)
            yield f"\n⚠️ Copilot exited with rc={proc.returncode}"

    def close(self) -> None:
        pass  # No persistent process to clean up


def _strip_stats(text: str) -> str:
    """Remove the 'Total usage est:' footer that copilot -p appends."""
    return _STATS_RE.sub("", text).strip()
