import asyncio
import logging
import signal
import sys
import time

from src.config import Settings
from src.ai.factory import create_backend
from src import repo, runtime, history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    ready_msg = (
        f"🟢 *TeleAgent Ready*\n"
        f"📁 `{settings.github.github_repo}` | 🌿 `{settings.github.branch}`\n"
        f"🤖 AI: `{settings.ai.ai_cli}`\n"
        f"Type `/{p}help` for commands"
    )

    async with app:
        await app.bot.send_message(
            chat_id=settings.telegram.chat_id,
            text=ready_msg,
            parse_mode="Markdown",
        )
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
    logger.info("Slack bot is running. Press Ctrl+C to stop.")
    await bot.run_async()


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
    try:
        settings = Settings.load()
        _validate_config(settings)
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        asyncio.run(startup(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
