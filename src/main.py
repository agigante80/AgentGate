import asyncio
import logging
import os
import pathlib
import signal
import sys
import time

from src.config import Settings
from src.ai.factory import create_backend
from src import repo, runtime, history
from src.config import REPO_DIR
from src.logging_setup import configure_logging
from src.ready_msg import build_ready_message
logger = logging.getLogger(__name__)

_HEALTH_FILE = pathlib.Path("/tmp/healthy")
_VERSION_FILE = pathlib.Path(__file__).parent.parent / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _log_startup_banner(settings: Settings, version: str) -> None:
    sep = "=" * 56
    logger.info(sep)
    logger.info("AgentGate v%s", version)
    logger.info("  Platform : %s", settings.platform)
    logger.info("  AI       : %s", settings.ai.ai_cli)
    logger.info("  Repo     : %s", settings.github.github_repo)
    logger.info("  Branch   : %s", settings.github.branch)
    logger.info("  Log level: %s", settings.log.log_level.upper())
    logger.info("  Log dir  : %s", settings.log.log_dir or "(stdout only)")
    logger.info("  Python   : %s", sys.version.split()[0])
    logger.info("  PID      : %s", os.getpid())
    logger.info(sep)


def _validate_config(settings: Settings) -> None:
    """Raise if the required tokens for the selected platform are missing."""
    if settings.platform == "telegram":
        if not settings.telegram.bot_token:
            raise ValueError("TG_BOT_TOKEN is required when PLATFORM=telegram")
        if not settings.telegram.chat_id:
            raise ValueError("TG_CHAT_ID is required when PLATFORM=telegram")
    elif settings.platform == "slack":
        if not settings.slack.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required when PLATFORM=slack")
        if not settings.slack.slack_app_token:
            raise ValueError("SLACK_APP_TOKEN is required when PLATFORM=slack")
        if not settings.slack.slack_channel_id:
            raise ValueError(
                "SLACK_CHANNEL_ID is required when PLATFORM=slack — "
                "set it to the channel where the bot should operate"
            )


async def _startup_telegram(settings: Settings, backend, start_time: float) -> None:
    from src.bot import build_app, _prefix

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_sigterm(*_):
        logger.info("Received SIGTERM, shutting down…")
        backend.close()
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    app = build_app(settings, backend, start_time)
    p = _prefix(settings)
    ready_msg = build_ready_message(settings, _read_version(), p)

    async with app:
        await app.bot.send_message(
            chat_id=settings.telegram.chat_id,
            text=ready_msg,
            parse_mode="Markdown",
        )
        _HEALTH_FILE.touch()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot is running. Press Ctrl+C to stop.")
        await stop_event.wait()


async def _startup_slack(settings: Settings, backend, start_time: float) -> None:
    from src.platform.slack import SlackBot

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    bot = SlackBot(settings, backend, start_time)

    def _handle_sigterm(*_):
        logger.info("Received SIGTERM, shutting down…")
        backend.close()
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    await bot.send_ready_message()
    _HEALTH_FILE.touch()
    logger.info("Slack bot is running. Press Ctrl+C to stop.")
    await bot.run_async()


async def _install_commit_msg_hook() -> None:
    """Install a commit-msg hook that warns if secrets are committed.

    The hook is installed unconditionally — git history is permanent and
    ALLOW_SECRETS only controls output redaction, not commit-time scanning.
    """
    hooks_dir = REPO_DIR / ".git" / "hooks"
    hook_file = hooks_dir / "commit-msg"
    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_script = (
            "#!/usr/bin/env python3\n"
            "\"\"\"Warn if commit message or staged diff contain common secret patterns.\"\"\"\n"
            "import os, re, subprocess, sys\n"
            "_PATTERNS = [\n"
            "    re.compile(r'ghp_[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'xoxb-[A-Za-z0-9\\-]{36,}'),\n"
            "    re.compile(r'xoxp-[A-Za-z0-9\\-]{36,}'),\n"
            "    re.compile(r'xapp-[A-Za-z0-9\\-]{36,}'),\n"
            "    re.compile(r'sk-[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'github_pat_[A-Za-z0-9_]{36,}'),\n"
            "    re.compile(r'Bearer\\s+[A-Za-z0-9\\-._~+/]{36,}=*'),\n"
            "    re.compile(r'https?://[^\\s@]+:[^\\s@]+@[^\\s]+'),\n"
            "]\n"
            "_SKIP_PATHS = ('tests/', 'test_', '.md', '.txt')\n"
            "def check(text):\n"
            "    for p in _PATTERNS:\n"
            "        if p.search(text): return True\n"
            "    return False\n"
            "def filter_diff(diff):\n"
            "    \"\"\"Return diff lines excluding test files and comment-like additions.\"\"\"\n"
            "    lines = []; in_skip = False\n"
            "    for line in diff.splitlines():\n"
            "        if line.startswith('diff --git'):\n"
            "            in_skip = any(s in line for s in _SKIP_PATHS)\n"
            "        if not in_skip and line.startswith('+') and not line.startswith('+++'):\n"
            "            lines.append(line)\n"
            "    return '\\n'.join(lines)\n"
            "if os.environ.get('ALLOW_SECRETS') == 'true':\n"
            "    sys.exit(0)\n"
            "msg = open(sys.argv[1]).read()\n"
            "raw_diff = subprocess.run(['git', 'diff', '--cached'], capture_output=True, text=True).stdout\n"
            "diff = filter_diff(raw_diff)\n"
            "if check(msg) or check(diff):\n"
            "    print('\\033[31m[commit-msg hook] WARNING: possible secret detected in commit. ')\n"
            "    print('Run with ALLOW_SECRETS=true to bypass this warning.\\033[0m')\n"
            "    sys.exit(1)\n"
        )
        hook_file.write_text(hook_script)
        hook_file.chmod(0o755)
        logger.info("Commit-msg hook installed at %s", hook_file)
    except Exception:
        logger.warning("Could not install commit-msg hook at %s", hook_file, exc_info=True)


async def startup(settings: Settings) -> None:
    start_time = time.time()

    token = settings.github.github_repo_token
    logger.info("Cloning repository…")
    await repo.clone(
        token,
        settings.github.github_repo,
        settings.github.branch,
    )
    await repo.configure_git_auth(token)
    await _install_commit_msg_hook()

    logger.info("Installing dependencies…")
    dep_result = await runtime.install_deps()
    logger.info(dep_result)

    logger.info("Initializing conversation history DB…")
    await history.init_db()

    logger.info("Initializing AI backend: %s", settings.ai.ai_cli)
    backend = create_backend(settings.ai)

    logger.info("Starting platform: %s", settings.platform)
    if settings.platform == "slack":
        await _startup_slack(settings, backend, start_time)
    else:
        await _startup_telegram(settings, backend, start_time)


def main() -> None:
    version = _read_version()
    try:
        settings = Settings.load()
        _validate_config(settings)
    except Exception as exc:
        # Basic fallback logging before configure_logging has run
        logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    configure_logging(settings.log.log_level, settings.log.log_dir)
    _log_startup_banner(settings, version)

    try:
        asyncio.run(startup(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
