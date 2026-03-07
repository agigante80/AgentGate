"""
Copilot CLI session using non-interactive subprocess mode (-p flag).
Each query spawns `copilot -p <prompt> --allow-all` as a subprocess.
This avoids PTY/TUI complexity and the interactive folder-trust dialog.
"""
import asyncio
import logging
import re
from collections.abc import AsyncGenerator

from src.ai.adapter import SubprocessMixin
from src.config import REPO_DIR  # noqa: F401 — test seam for monkeypatching

TIMEOUT = 180

logger = logging.getLogger(__name__)

# Strip usage stats footer appended by copilot -p to every response
_STATS_RE = re.compile(r"\n\nTotal usage est:.*", re.DOTALL)


class CopilotSession(SubprocessMixin):
    def __init__(self, model: str = "", env: dict | None = None) -> None:
        self._model = model
        self._env = env

    def _build_cmd(self, prompt: str) -> list[str]:
        args = ["copilot", "-p", prompt, "--allow-all"]
        if self._model:
            args += ["--model", self._model]
        return args

    async def send(self, prompt: str) -> str:
        try:
            proc = await self._spawn(self._build_cmd(prompt), self._env)
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return f"⚠️ Copilot timed out after {TIMEOUT}s."
        except Exception as exc:
            logger.exception("Copilot subprocess error")
            return f"⚠️ Session error: {exc}"
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

    def close(self) -> None:
        pass  # No persistent process to clean up


def _strip_stats(text: str) -> str:
    """Remove the 'Total usage est:' footer that copilot -p appends."""
    return _STATS_RE.sub("", text).strip()
