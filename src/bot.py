import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from src.ai.adapter import AICLIBackend
from src.config import Settings
from src import executor, repo, history

logger = logging.getLogger(__name__)

# Keyed by (chat_id, message_id) → shell command waiting for confirmation
_pending_cmds: dict[tuple, str] = {}

# Active AI requests: maps a description string → start timestamp
_active_ai: dict[str, float] = {}


def _is_allowed(update: Update, settings: Settings) -> bool:
    chat_id = str(update.effective_chat.id)
    if chat_id != settings.telegram.chat_id:
        return False
    if settings.telegram.allowed_users:
        user_id = update.effective_user.id if update.effective_user else None
        return user_id in settings.telegram.allowed_users
    return True


def _prefix(settings: Settings) -> str:
    # No separator: just lowercase prefix (e.g. "ta" → /tarun /tasync)
    return settings.bot.bot_cmd_prefix.lower().replace("-", "").replace("_", "")


async def _reply(update: Update, text: str) -> None:
    await update.effective_message.reply_text(text, parse_mode=None)


async def _stream_to_telegram(
    update: Update,
    backend: "AICLIBackend",
    prompt: str,
    max_chars: int,
) -> str:
    """Stream AI response chunks into a single Telegram message, editing it as chunks arrive.
    Throttled to ~1 edit/second to respect Telegram rate limits.
    Returns the final accumulated text.
    """
    msg = await update.effective_message.reply_text("🤖 Thinking…")
    accumulated = ""
    last_edit = time.monotonic()
    THROTTLE = 1.0  # seconds between edits

    async for chunk in backend.stream(prompt):
        accumulated += chunk
        now = time.monotonic()
        if now - last_edit >= THROTTLE:
            display = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
            try:
                await msg.edit_text(display + " ▌")
            except Exception:
                pass  # ignore flaky edits
            last_edit = now

    # Final edit — full text without cursor
    if len(accumulated) > max_chars:
        accumulated = accumulated[-max_chars:]
    try:
        await msg.edit_text(accumulated or "_(empty response)_")
    except Exception:
        pass
    return accumulated


def build_app(settings: Settings, backend: AICLIBackend, start_time: float) -> Application:
    app = Application.builder().token(settings.telegram.bot_token).build()

    p = _prefix(settings)
    repo_name = settings.github.github_repo.split("/")[-1]

    async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        cmd = " ".join(ctx.args) if ctx.args else ""
        if not cmd:
            await _reply(update, f"Usage: /{p}run <shell command>")
            return
        if executor.is_destructive(cmd):
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Run", callback_data="confirm_run"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_run"),
            ]])
            msg = await update.effective_message.reply_text(
                f"⚠️ Destructive command:\n`{cmd}`\n\nConfirm?",
                reply_markup=kb,
                parse_mode="Markdown",
            )
            _pending_cmds[(update.effective_chat.id, msg.message_id)] = cmd
        else:
            await update.effective_message.reply_text("⏳ Running…")
            result = await executor.run_shell(cmd, settings.bot.max_output_chars)
            await _reply(update, f"```\n{result}\n```")

    async def cmd_sync(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        await update.effective_message.reply_text("⏳ Pulling latest changes…")
        result = await repo.pull()
        await _reply(update, f"✅ Synced\n{result}")

    async def cmd_git(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        result = await repo.status()
        await _reply(update, f"```\n{result}\n```")

    async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        if _active_ai:
            lines = ["🔄 AI is currently processing:\n"]
            for prompt, ts in _active_ai.items():
                elapsed = int(time.time() - ts)
                lines.append(f"  • {prompt[:60]}… ({elapsed}s ago)")
            await _reply(update, "\n".join(lines))
        else:
            await _reply(update, "✅ AI is idle — ready for your next message.")

    async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        text = (
            f"🤖 *TeleAgent — Command Reference*\n\n"
            f"*Utility commands:*\n"
            f"/{p}run `<cmd>` — run a shell command in the repo\n"
            f"/{p}sync — git pull (fetch latest changes)\n"
            f"/{p}git — git status + recent commits\n"
            f"/{p}status — check if AI is busy\n"
            f"/{p}clear — clear conversation history\n"
            f"/{p}info — project & bot info\n"
            f"/{p}help — this message\n\n"
            f"*AI commands (forwarded to AI CLI):*\n"
            f"Any other text or /command is sent directly to the AI.\n"
            f"Examples: `/init`, `/plan`, `/review`, `/diff`, `/model`\n\n"
            f"*Destructive shell commands* (push, merge, rm, force) require confirmation."
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    async def cmd_info(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        uptime_s = int(time.time() - start_time)
        h, remainder = divmod(uptime_s, 3600)
        m, s = divmod(remainder, 60)
        ai_label = settings.ai.ai_cli
        if settings.ai.ai_cli == "copilot" and settings.ai.copilot_model:
            ai_label += f" ({settings.ai.copilot_model})"
        elif settings.ai.ai_cli == "codex":
            ai_label += f" ({settings.ai.codex_model})"
        elif settings.ai.ai_cli == "api" and settings.ai.ai_model:
            ai_label += f" / {settings.ai.ai_provider} ({settings.ai.ai_model})"
        text = (
            f"ℹ️ *TeleAgent Info*\n\n"
            f"📁 Repo: `{settings.github.github_repo}`\n"
            f"🌿 Branch: `{settings.github.branch}`\n"
            f"🤖 AI backend: `{ai_label}`\n"
            f"⌨️ Prefix: `/{p}`\n"
            f"📏 Max output: `{settings.bot.max_output_chars}` chars\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 Active AI tasks: `{len(_active_ai)}`"
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    async def callback_handler(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        key = (update.effective_chat.id, query.message.message_id)
        cmd = _pending_cmds.pop(key, None)
        if query.data == "cancel_run" or cmd is None:
            await query.edit_message_text("❌ Cancelled.")
            return
        await query.edit_message_text(f"⏳ Running:\n`{cmd}`", parse_mode="Markdown")
        result = await executor.run_shell(cmd, settings.bot.max_output_chars)
        await query.message.reply_text(f"```\n{result}\n```", parse_mode="Markdown")

    async def forward_to_ai(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        text = update.effective_message.text or ""
        if not text:
            return
        chat_id = str(update.effective_chat.id)
        key = text[:60]
        _active_ai[key] = time.time()
        try:
            if backend.is_stateful:
                prompt = text
            else:
                hist = await history.get_history(chat_id) if settings.bot.history_enabled else []
                prompt = history.build_context(hist, text)

            if settings.bot.stream_responses:
                response = await _stream_to_telegram(update, backend, prompt, settings.bot.max_output_chars)
            else:
                msg = await update.effective_message.reply_text("🤖 Thinking…")
                response = await backend.send(prompt)
                response = await executor.summarize_if_long(response, settings.bot.max_output_chars, backend)
                await msg.edit_text(response or "_(empty response)_")

            if settings.bot.history_enabled:
                await history.add_exchange(chat_id, text, response)
        except Exception as exc:
            logger.exception("AI backend error")
            await _reply(update, f"⚠️ Error: {exc}")
        finally:
            _active_ai.pop(key, None)

    async def cmd_clear(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, settings):
            return
        chat_id = str(update.effective_chat.id)
        if settings.bot.history_enabled:
            await history.clear_history(chat_id)
        backend.clear_history()
        await _reply(update, "🗑 Conversation history cleared.")

    app.add_handler(CommandHandler(f"{p}run", cmd_run))
    app.add_handler(CommandHandler(f"{p}sync", cmd_sync))
    app.add_handler(CommandHandler(f"{p}git", cmd_git))
    app.add_handler(CommandHandler(f"{p}status", cmd_status))
    app.add_handler(CommandHandler(f"{p}clear", cmd_clear))
    app.add_handler(CommandHandler(f"{p}help", cmd_help))
    app.add_handler(CommandHandler(f"{p}info", cmd_info))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_to_ai))
    # Forward all other /commands to AI as plain text
    app.add_handler(MessageHandler(filters.COMMAND, forward_to_ai))

    return app
