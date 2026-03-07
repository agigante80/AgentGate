"""Platform-agnostic helpers shared between Telegram and Slack bots."""
from src import history
from src.ai.adapter import AICLIBackend
from src.config import Settings


async def build_prompt(
    text: str, chat_id: str, settings: Settings, backend: AICLIBackend
) -> str:
    """Build the AI prompt, injecting conversation history for stateless backends."""
    if backend.is_stateful:
        return text
    hist = (
        await history.get_history(chat_id) if settings.bot.history_enabled else []
    )
    return history.build_context(hist, text)


async def save_to_history(
    chat_id: str, user_msg: str, response: str, settings: Settings
) -> None:
    """Persist an exchange to conversation history (if enabled)."""
    if settings.bot.history_enabled:
        await history.add_exchange(chat_id, user_msg, response)


def is_allowed_slack(channel_id: str, user_id: str, settings: Settings) -> bool:
    """Auth check for Slack: optionally restrict by channel and/or user list."""
    cfg = settings.slack
    if cfg.slack_channel_id and channel_id != cfg.slack_channel_id:
        return False
    if cfg.allowed_users:
        return user_id in cfg.allowed_users
    return True
