import asyncio
import logging

import git

from src.config import REPO_DIR
logger = logging.getLogger(__name__)


async def clone(github_repo_token: str, github_repo: str, branch: str) -> None:
    if (REPO_DIR / ".git").exists():
        logger.info("Repo already cloned at %s, skipping clone.", REPO_DIR)
        return
    if not github_repo:
        logger.warning("No GITHUB_REPO set and no existing repo — nothing to clone.")
        return
    url = f"https://x-token-auth:{github_repo_token}@github.com/{github_repo.removeprefix('https://github.com/')}"
    logger.info("Cloning %s (branch: %s)…", github_repo, branch)
    await asyncio.to_thread(
        git.Repo.clone_from, url, REPO_DIR, branch=branch, depth=1
    )
    logger.info("Clone complete → %s", REPO_DIR)


async def configure_git_auth(token: str) -> None:
    """Configure git globally to inject token for all github.com HTTPS operations."""
    if not token:
        return
    url_prefix = f"https://x-token-auth:{token}@github.com/"
    proc = await asyncio.create_subprocess_exec(
        "git", "config", "--global",
        f"url.{url_prefix}.insteadOf", "https://github.com/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("git config auth failed: %s", stderr.decode().strip())
    else:
        logger.info("Git global auth configured for github.com")


async def pull() -> str:
    if not (REPO_DIR / ".git").exists():
        return "⚠️ No repository cloned yet — nothing to pull."
    # Use fetch + reset --hard instead of gitpython pull() to avoid failures
    # when the container has local changes (repo is ephemeral; remote is authoritative).
    fetch_proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_DIR), "fetch", "--prune", "origin",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, fetch_err = await fetch_proc.communicate()
    if fetch_proc.returncode != 0:
        return f"⚠️ git fetch failed:\n{fetch_err.decode().strip()}"

    # Determine the remote tracking branch (e.g. origin/develop)
    branch_proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_DIR), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    branch_out, _ = await branch_proc.communicate()
    upstream = branch_out.decode().strip() if branch_proc.returncode == 0 else "origin/HEAD"

    reset_proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(REPO_DIR), "reset", "--hard", upstream,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    reset_out, reset_err = await reset_proc.communicate()
    if reset_proc.returncode != 0:
        return f"⚠️ git reset failed:\n{reset_err.decode().strip()}"
    return reset_out.decode().strip()


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
