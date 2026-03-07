import asyncio
import logging

from src.ai.adapter import AICLIBackend
from src.config import REPO_DIR

logger = logging.getLogger(__name__)

_DESTRUCTIVE_KEYWORDS = ("push", "merge", "rm ", "remove", "force", " -f ", "--force", "drop", "delete")


def is_destructive(cmd: str) -> bool:
    return any(kw in cmd for kw in _DESTRUCTIVE_KEYWORDS)


def is_exempt(cmd: str, skip_keywords: list[str]) -> bool:
    """Return True if cmd matches any keyword in the skip list (confirmation bypassed)."""
    return any(kw in cmd for kw in skip_keywords if kw)


def truncate_output(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > max_chars:
            break
        kept.append(line)
        total += len(line) + 1
    kept.reverse()
    return f"⚠️ Output truncated — showing last {len(kept)} of {len(lines)} lines:\n" + "\n".join(kept)


async def run_shell(cmd: str, max_chars: int) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=str(REPO_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    rc_line = f"\n[exit {proc.returncode}]"
    return truncate_output(output + rc_line, max_chars)


async def summarize_if_long(text: str, max_chars: int, backend: AICLIBackend) -> str:
    if len(text) <= max_chars:
        return text
    summary = await backend.send(f"Summarize in under {max_chars} characters:\n\n{text}")
    return summary[:max_chars]
