import asyncio
import logging
from pathlib import Path

REPO_DIR = Path("/repo")
logger = logging.getLogger(__name__)

_DETECTORS: list[tuple[str, list[str]]] = [
    ("package.json", ["npm", "install"]),
    ("pyproject.toml", ["pip", "install", "-e", "."]),
    ("requirements.txt", ["pip", "install", "-r", "requirements.txt"]),
    ("go.mod", ["go", "mod", "download"]),
]


async def install_deps() -> str:
    results: list[str] = []
    for marker, cmd in _DETECTORS:
        if not (REPO_DIR / marker).exists():
            continue
        logger.info("Detected %s → running %s", marker, " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        status = "✅" if proc.returncode == 0 else "❌"
        results.append(f"{status} {' '.join(cmd)}\n{out.decode()[-500:]}")
    return "\n---\n".join(results) if results else "No known package manifest found."
