import asyncio
import hashlib
import logging
from pathlib import Path

from src.config import REPO_DIR
from src.executor import scrubbed_env

logger = logging.getLogger(__name__)

_DETECTORS: list[tuple[str, list[str]]] = []

_SENTINEL_DIR = Path("/data/.install_sentinels")


def register_detector(manifest: str, cmd: list[str]) -> None:
    """Register a dependency detector.

    All registered detectors are logged at INFO level so operators can audit
    what commands will run at startup.
    """
    _DETECTORS.append((manifest, cmd))
    logger.info("Dep detector registered: %s → %s", manifest, cmd)


# Built-in registrations
register_detector("package.json",     ["npm", "install"])
register_detector("pyproject.toml",   ["pip", "install", "-e", "."])
register_detector("requirements.txt", ["pip", "install", "-r", "requirements.txt"])
register_detector("go.mod",           ["go", "mod", "download"])


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
            env=scrubbed_env(),
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
