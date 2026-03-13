"""Platform-agnostic helpers shared between Telegram and Slack bots."""
import asyncio
import time
from collections.abc import Awaitable, Callable

from src import history
from src.ai.adapter import AICLIBackend
from src.config import Settings


def _format_elapsed(secs: int) -> str:
    """Return elapsed time as a human-readable string.

    Under 60s: '45s'. At 60s and above: '2m 5s'.
    """
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    return f"{m}m {s}s"


async def thinking_ticker(
    edit_fn: Callable[[str], Awaitable[None]],
    slow_threshold: int,
    update_interval: int,
    timeout_secs: int,
    warn_before_secs: int,
    _clock: Callable[[], float] = time.monotonic,
) -> None:
    """Background task: edits the 'Thinking…' placeholder with elapsed time.

    Sleeps for slow_threshold seconds first (quiet for fast responses).
    After that, edits every update_interval seconds.
    When timeout is set and remaining time <= warn_before_secs, adds a warning.
    Cancelled externally when the AI call completes or is timed out.

    _clock is injectable for testing so tests don't need to patch the global
    time.monotonic (which is also used internally by the asyncio event loop).
    """
    start = _clock()
    await asyncio.sleep(slow_threshold)
    while True:
        elapsed = int(_clock() - start)
        if timeout_secs > 0:
            remaining = timeout_secs - elapsed
            if remaining <= warn_before_secs:
                text = f"⏳ Still thinking… ({_format_elapsed(elapsed)}) — will cancel in {_format_elapsed(remaining)}"
            else:
                text = f"⏳ Still thinking… ({_format_elapsed(elapsed)})"
        else:
            text = f"⏳ Still thinking… ({_format_elapsed(elapsed)})"
        await edit_fn(text)
        await asyncio.sleep(update_interval)


async def build_prompt(
    text: str, chat_id: str, settings: Settings, backend: AICLIBackend
) -> str:
    """Build the AI prompt, injecting conversation history for stateless backends."""
    if backend.is_stateful:
        return text
    turns = settings.bot.history_turns
    hist = (
        await history.get_history(chat_id, limit=turns)
        if settings.bot.history_enabled and turns > 0
        else []
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
