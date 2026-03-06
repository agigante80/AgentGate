import asyncio
import hashlib
import logging
from pathlib import Path

from src.config import REPO_DIR

logger = logging.getLogger(__name__)

_DETECTORS: list[tuple[str, list[str]]] = [
    ("package.json", ["npm", "install"]),
    ("pyproject.toml", ["pip", "install", "-e", "."]),
    ("requirements.txt", ["pip", "install", "-r", "requirements.txt"]),
    ("go.mod", ["go", "mod", "download"]),
]

_SENTINEL_DIR = Path("/data/.install_sentinels")


def _manifest_hash(manifest_path: Path) -> str:
    """Return a short hash of a manifest file's content."""
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16]


async def install_deps() -> str:
    _SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
    results: list[str] = []
    for marker, cmd in _DETECTORS:
        manifest = REPO_DIR / marker
        if not manifest.exists():
            continue
        sentinel = _SENTINEL_DIR / f"{marker.replace('/', '_')}.{_manifest_hash(manifest)}.ok"
        if sentinel.exists():
            logger.info("Skipping %s install — sentinel present (%s)", marker, sentinel.name)
            results.append(f"⏭️ {' '.join(cmd)} (cached — no changes in {marker})")
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
        if proc.returncode == 0:
            # Remove old sentinels for this marker, write new one
            for old in _SENTINEL_DIR.glob(f"{marker.replace('/', '_')}.*.ok"):
                old.unlink(missing_ok=True)
            sentinel.touch()
    return "\n---\n".join(results) if results else "No known package manifest found."
