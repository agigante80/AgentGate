import functools
import logging
import time
from collections.abc import Callable

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.ai.adapter import AICLIBackend
from src.config import Settings
from src import executor, history, repo

logger = logging.getLogger(__name__)


# ── Pure helper functions (imported by tests) ───────────────────────────────

def _is_allowed(update: Update, settings: Settings) -> bool:
    chat_id = str(update.effective_chat.id)
    if chat_id != settings.telegram.chat_id:
        return False
    if settings.telegram.allowed_users:
        user_id = update.effective_user.id if update.effective_user else None
        return user_id in settings.telegram.allowed_users
    return True


def _prefix(settings: Settings) -> str:
    return settings.bot.bot_cmd_prefix.lower().replace("-", "").replace("_", "")


async def _reply(update: Update, text: str) -> None:
    await update.effective_message.reply_text(text, parse_mode=None)


async def _stream_to_telegram(
    update: Update,
    backend: AICLIBackend,
    prompt: str,
    max_chars: int,
    throttle_secs: float = 1.0,
) -> str:
    """Stream AI response into a Telegram message, editing it as chunks arrive."""
    msg = await update.effective_message.reply_text("🤖 Thinking…")
    accumulated = ""
    last_edit = time.monotonic()

    async for chunk in backend.stream(prompt):
        accumulated += chunk
        now = time.monotonic()
        if now - last_edit >= throttle_secs:
            display = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
            try:
                await msg.edit_text(display + " ▌")
            except Exception:
                logger.debug("Telegram edit skipped (rate-limited or unchanged)")
            last_edit = now

    final = accumulated[-max_chars:] if len(accumulated) > max_chars else accumulated
    try:
        await msg.edit_text(final or "_(empty response)_")
    except Exception:
        logger.debug("Telegram final edit skipped")
    return final


# ── Auth decorator ───────────────────────────────────────────────────────────

def _requires_auth(method: Callable) -> Callable:
    """Skip handler silently if the sender is not in the allowlist."""
    @functools.wraps(method)
    async def wrapper(self: "_BotHandlers", update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update, self._settings):
            return
        await method(self, update, ctx)
    return wrapper


# ── Handler class ────────────────────────────────────────────────────────────

class _BotHandlers:
    def __init__(self, settings: Settings, backend: AICLIBackend, start_time: float) -> None:
        self._settings = settings
        self._backend = backend
        self._start_time = start_time
        self._p = _prefix(settings)
        # (chat_id, message_id) → shell command waiting for confirmation
        self._pending_cmds: dict[tuple, str] = {}
        # prompt[:60] → start timestamp for active AI requests
        self._active_ai: dict[str, float] = {}

    # ── Utility commands ──────────────────────────────────────────────────

    @_requires_auth
    async def cmd_run(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cmd = " ".join(ctx.args) if ctx.args else ""
        if not cmd:
            await _reply(update, f"Usage: /{self._p}run <shell command>")
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
            self._pending_cmds[(update.effective_chat.id, msg.message_id)] = cmd
        else:
            await update.effective_message.reply_text("⏳ Running…")
            result = await executor.run_shell(cmd, self._settings.bot.max_output_chars)
            await _reply(update, f"```\n{result}\n```")

    @_requires_auth
    async def cmd_sync(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("⏳ Pulling latest changes…")
        result = await repo.pull()
        await _reply(update, f"✅ Synced\n{result}")

    @_requires_auth
    async def cmd_git(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        result = await repo.status()
        await _reply(update, f"```\n{result}\n```")

    @_requires_auth
    async def cmd_status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if self._active_ai:
            lines = ["🔄 AI is currently processing:\n"]
            for prompt, ts in self._active_ai.items():
                elapsed = int(time.time() - ts)
                lines.append(f"  • {prompt[:60]}… ({elapsed}s ago)")
            await _reply(update, "\n".join(lines))
        else:
            await _reply(update, "✅ AI is idle — ready for your next message.")

    @_requires_auth
    async def cmd_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        p = self._p
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

    @_requires_auth
    async def cmd_info(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uptime_s = int(time.time() - self._start_time)
        h, remainder = divmod(uptime_s, 3600)
        m, s = divmod(remainder, 60)
        ai_label = self._settings.ai.ai_cli
        if self._settings.ai.ai_cli == "copilot" and self._settings.ai.copilot_model:
            ai_label += f" ({self._settings.ai.copilot_model})"
        elif self._settings.ai.ai_cli == "codex":
            ai_label += f" ({self._settings.ai.codex_model})"
        elif self._settings.ai.ai_cli == "api" and self._settings.ai.ai_model:
            ai_label += f" / {self._settings.ai.ai_provider} ({self._settings.ai.ai_model})"
        text = (
            f"ℹ️ *TeleAgent Info*\n\n"
            f"📁 Repo: `{self._settings.github.github_repo}`\n"
            f"🌿 Branch: `{self._settings.github.branch}`\n"
            f"🤖 AI backend: `{ai_label}`\n"
            f"⌨️ Prefix: `/{self._p}`\n"
            f"📏 Max output: `{self._settings.bot.max_output_chars}` chars\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 Active AI tasks: `{len(self._active_ai)}`"
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    @_requires_auth
    async def cmd_clear(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        if self._settings.bot.history_enabled:
            await history.clear_history(chat_id)
        self._backend.clear_history()
        await _reply(update, "🗑 Conversation history cleared.")

    # ── Callback & AI forwarding ──────────────────────────────────────────

    async def callback_handler(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        key = (update.effective_chat.id, query.message.message_id)
        cmd = self._pending_cmds.pop(key, None)
        if query.data == "cancel_run" or cmd is None:
            await query.edit_message_text("❌ Cancelled.")
            return
        await query.edit_message_text(f"⏳ Running:\n`{cmd}`", parse_mode="Markdown")
        result = await executor.run_shell(cmd, self._settings.bot.max_output_chars)
        await query.message.reply_text(f"```\n{result}\n```", parse_mode="Markdown")

    @_requires_auth
    async def forward_to_ai(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.effective_message.text or ""
        if not text:
            return
        chat_id = str(update.effective_chat.id)
        key = text[:60]
        self._active_ai[key] = time.time()
        try:
            if self._backend.is_stateful:
                prompt = text
            else:
                hist = await history.get_history(chat_id) if self._settings.bot.history_enabled else []
                prompt = history.build_context(hist, text)

            if self._settings.bot.stream_responses:
                response = await _stream_to_telegram(
                    update, self._backend, prompt,
                    self._settings.bot.max_output_chars,
                    self._settings.bot.stream_throttle_secs,
                )
            else:
                msg = await update.effective_message.reply_text("🤖 Thinking…")
                response = await self._backend.send(prompt)
                response = await executor.summarize_if_long(
                    response, self._settings.bot.max_output_chars, self._backend
                )
                await msg.edit_text(response or "_(empty response)_")

            if self._settings.bot.history_enabled:
                await history.add_exchange(chat_id, text, response)
        except Exception as exc:
            logger.exception("AI backend error")
            await _reply(update, f"⚠️ Error: {exc}")
        finally:
            self._active_ai.pop(key, None)


# ── App factory ──────────────────────────────────────────────────────────────

def build_app(settings: Settings, backend: AICLIBackend, start_time: float) -> Application:
    app = Application.builder().token(settings.telegram.bot_token).build()
    h = _BotHandlers(settings, backend, start_time)
    p = _prefix(settings)

    app.add_handler(CommandHandler(f"{p}run", h.cmd_run))
    app.add_handler(CommandHandler(f"{p}sync", h.cmd_sync))
    app.add_handler(CommandHandler(f"{p}git", h.cmd_git))
    app.add_handler(CommandHandler(f"{p}status", h.cmd_status))
    app.add_handler(CommandHandler(f"{p}clear", h.cmd_clear))
    app.add_handler(CommandHandler(f"{p}help", h.cmd_help))
    app.add_handler(CommandHandler(f"{p}info", h.cmd_info))
    app.add_handler(CallbackQueryHandler(h.callback_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, h.forward_to_ai))
    # Forward all other /commands to AI as plain text
    app.add_handler(MessageHandler(filters.COMMAND, h.forward_to_ai))

    return app
