import asyncio
import logging
from pathlib import Path

import git

REPO_DIR = Path("/repo")
logger = logging.getLogger(__name__)


async def clone(github_token: str, github_repo: str, branch: str) -> None:
    if (REPO_DIR / ".git").exists():
        logger.info("Repo already cloned at %s, skipping clone.", REPO_DIR)
        return
    if not github_repo:
        logger.warning("No GITHUB_REPO set and no existing repo — nothing to clone.")
        return
    url = f"https://x-token-auth:{github_token}@github.com/{github_repo.removeprefix('https://github.com/')}"
    logger.info("Cloning %s (branch: %s)…", github_repo, branch)
    await asyncio.to_thread(
        git.Repo.clone_from, url, REPO_DIR, branch=branch, depth=1
    )
    logger.info("Clone complete → %s", REPO_DIR)


async def pull() -> str:
    repo = await asyncio.to_thread(git.Repo, REPO_DIR)
    result = await asyncio.to_thread(repo.remotes.origin.pull)
    return "\n".join(str(r) for r in result)


async def status() -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_DIR), "status", "--short", "-b",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    log_proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_DIR), "log", "--oneline", "-3",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    log_out, _ = await log_proc.communicate()
    return f"{stdout.decode()}\n{log_out.decode()}".strip()
