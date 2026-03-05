import asyncio
import logging
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


async def startup(settings: Settings) -> None:
    start_time = time.time()

    logger.info("Cloning repository…")
    await repo.clone(
        settings.github.github_token,
        settings.github.github_repo,
        settings.github.branch,
    )

    logger.info("Installing dependencies…")
    dep_result = await runtime.install_deps()
    logger.info(dep_result)

    logger.info("Initializing conversation history DB…")
    await history.init_db()

    logger.info("Initializing AI backend: %s", settings.ai.ai_cli)
    backend = create_backend(settings.ai)

    from src.bot import build_app, _prefix
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
        logger.info("Bot is running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()


def main() -> None:
    try:
        settings = Settings.load()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        asyncio.run(startup(settings))
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
