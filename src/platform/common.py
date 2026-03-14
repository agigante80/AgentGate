"""Platform-agnostic helpers shared between Telegram and Slack bots."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from src import history
from src.history import ConversationStorage
from src.ai.adapter import AICLIBackend
from src.config import Settings

logger = logging.getLogger(__name__)


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


async def finalize_thinking(
    edit_fn: Callable[[str], Awaitable[None]],
    elapsed_secs: int,
    show_elapsed: bool,
) -> None:
    """Edit the thinking placeholder to show total elapsed time (if enabled).

    When show_elapsed is False this is a no-op, leaving the placeholder as-is.
    """
    if show_elapsed:
        label = _format_elapsed(elapsed_secs)
        try:
            await edit_fn(f"🤖 Thought for {label}")
        except Exception:
            logger.debug("Could not update thinking placeholder with elapsed time")


async def build_prompt(
    text: str, chat_id: str, settings: Settings, backend: AICLIBackend, storage: ConversationStorage
) -> str:
    """Build the AI prompt, injecting conversation history for stateless backends."""
    if backend.is_stateful:
        return text
    turns = settings.bot.history_turns
    hist = (
        await storage.get_history(chat_id, limit=turns)
        if settings.bot.history_enabled and turns > 0
        else []
    )
    return history.build_context(hist, text)


async def save_to_history(
    chat_id: str, user_msg: str, response: str, settings: Settings, storage: ConversationStorage
) -> None:
    """Persist an exchange to conversation history (if enabled).

    Callers MUST redact *response* and *user_msg* before calling this method.
    """
    if settings.bot.history_enabled:
        await storage.add_exchange(chat_id, user_msg, response)


_PARAGRAPH_SEP = "\n\n"
_SENTENCE_SEP = ". "


def split_text(text: str, chunk_size: int) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters.

    Prefers splitting at paragraph boundaries (double newline), then sentence
    boundaries (``". "``), then single newlines, and finally hard-cuts at
    *chunk_size* as a last resort.  Returns a list with at least one element.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break

        # Search for the best split point within the allowed window
        window = remaining[:chunk_size]
        pos = window.rfind(_PARAGRAPH_SEP)
        if pos != -1:
            split_at = pos + len(_PARAGRAPH_SEP)
        else:
            pos = window.rfind(_SENTENCE_SEP)
            if pos != -1:
                split_at = pos + len(_SENTENCE_SEP)
            else:
                pos = window.rfind("\n")
                split_at = pos + 1 if pos != -1 else chunk_size

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    return chunks


def is_allowed_slack(channel_id: str, user_id: str, settings: Settings) -> bool:
    """Auth check for Slack: optionally restrict by channel and/or user list."""
    cfg = settings.slack
    if cfg.slack_channel_id and channel_id != cfg.slack_channel_id:
        return False
    if cfg.allowed_users:
        return user_id in cfg.allowed_users
    return True
