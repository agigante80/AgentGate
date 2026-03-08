"""
Slack bot adapter for AgentGate.

Uses slack-bolt[async] in Socket Mode (WebSocket) — no public HTTPS endpoint needed.
Connects when PLATFORM=slack is set in the environment.

Commands are triggered by messages starting with the bot prefix (default: "gate"):
  gate run <cmd>   — run a shell command
  gate sync        — git pull
  gate git         — git status
  gate diff [n]    — git diff
  gate log [n]     — container logs
  gate status      — AI activity
  gate clear       — clear history
  gate restart     — restart AI backend
  gate confirm [on|off] — toggle destructive-command confirmation
  gate info        — project info
  gate help        — this message

All other messages are forwarded to the active AI backend.
Voice/audio file uploads are transcribed and forwarded to the AI.
"""
import logging
import time

from src import executor, repo, transcriber as transcriber_mod
from src.ai import factory as ai_factory
from src.ai.adapter import AICLIBackend
from src.config import Settings, VERSION
from src.platform import common
from src.ready_msg import build_ready_message, ai_label as _ai_label

logger = logging.getLogger(__name__)

# Sent as a placeholder while streaming — updated chunk by chunk
_THINKING = "🤖 Thinking…"


def _prefix(settings: Settings) -> str:
    return settings.bot.bot_cmd_prefix.lower().replace("-", "").replace("_", "")


def _init_transcriber(
    settings: Settings,
) -> "transcriber_mod.Transcriber | None":
    try:
        tx = transcriber_mod.create_transcriber(
            settings.voice, fallback_api_key=settings.ai.ai_api_key
        )
        return None if isinstance(tx, transcriber_mod.NullTranscriber) else tx
    except NotImplementedError as exc:
        logger.warning("Voice transcription unavailable: %s", exc)
        return None


class SlackBot:
    """
    Slack bot that mirrors AgentGate's Telegram functionality.
    All handler methods receive plain Python arguments (str, list[str]) —
    Slack-specific I/O happens only in _send, _edit, _stream_to_slack.
    """

    def __init__(
        self, settings: Settings, backend: AICLIBackend, start_time: float
    ) -> None:
        from slack_bolt.async_app import AsyncApp

        self._settings = settings
        self._backend = backend
        self._start_time = start_time
        self._p = _prefix(settings)
        # (channel, ts) -> pending shell command awaiting confirmation
        self._pending_cmds: dict[tuple[str, str], str] = {}
        # prompt[:60] -> start timestamp for active AI requests
        self._active_ai: dict[str, float] = {}
        self._confirm_destructive: bool = settings.bot.confirm_destructive
        self._transcriber = _init_transcriber(settings)

        self._app = AsyncApp(token=settings.slack.slack_bot_token)
        self._register_handlers()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _is_allowed(self, channel: str, user: str) -> bool:
        return common.is_allowed_slack(channel, user, self._settings)

    async def _send(self, say, text: str) -> dict:
        """Post a new message; return the Slack API response (includes ts)."""
        return await say(text)

    async def _edit(self, client, channel: str, ts: str, text: str) -> None:
        """Update a previously posted message."""
        try:
            await client.chat_update(channel=channel, ts=ts, text=text)
        except Exception:
            logger.debug("Slack edit skipped")

    async def _stream_to_slack(
        self, say, client, channel: str, prompt: str
    ) -> str:
        resp = await say(_THINKING)
        ts = resp["ts"]
        accumulated = ""
        last_edit = time.monotonic()
        throttle = self._settings.bot.stream_throttle_secs
        max_chars = self._settings.bot.max_output_chars

        async for chunk in self._backend.stream(prompt):
            accumulated += chunk
            now = time.monotonic()
            if now - last_edit >= throttle:
                display = (
                    accumulated[-max_chars:]
                    if len(accumulated) > max_chars
                    else accumulated
                )
                await self._edit(client, channel, ts, display + " ▌")
                last_edit = now

        final = (
            accumulated[-max_chars:]
            if len(accumulated) > max_chars
            else accumulated
        )
        await self._edit(client, channel, ts, final or "_(empty response)_")
        return final

    async def _run_ai_pipeline(
        self, say, client, text: str, channel: str
    ) -> None:
        key = text[:60]
        self._active_ai[key] = time.time()
        try:
            prompt = await common.build_prompt(
                text, channel, self._settings, self._backend
            )
            if self._settings.bot.stream_responses:
                response = await self._stream_to_slack(say, client, channel, prompt)
            else:
                resp = await say(_THINKING)
                ts = resp["ts"]
                response = await self._backend.send(prompt)
                response = await executor.summarize_if_long(
                    response, self._settings.bot.max_output_chars, self._backend
                )
                await self._edit(
                    client, channel, ts, response or "_(empty response)_"
                )
            await common.save_to_history(channel, text, response, self._settings)
        except Exception as exc:
            logger.exception("AI backend error")
            await say(f"⚠️ Error: {exc}")
        finally:
            self._active_ai.pop(key, None)

    # ── Message event router ──────────────────────────────────────────────

    def _register_handlers(self) -> None:
        self._app.event("message")(self._on_message)
        self._app.action("confirm_run")(self._on_confirm_run)
        self._app.action("cancel_run")(self._on_cancel_run)

    async def _on_message(self, event: dict, say, client) -> None:
        """Route incoming messages: prefix commands or AI forwarding."""
        channel = event.get("channel", "")
        user = event.get("user", "")
        text = (event.get("text") or "").strip()

        # Ignore bot messages and message edits
        if event.get("subtype") or event.get("bot_id"):
            return
        if not self._is_allowed(channel, user):
            return

        # Voice/audio file uploads → transcribe and forward to AI
        if event.get("files"):
            await self._handle_files(event, say, client, channel)
            return

        if not text:
            return

        p = self._p
        lower = text.lower()
        # Parse "{p} <subcommand> [args…]" prefix
        if lower.startswith(f"{p} ") or lower == p:
            parts = text.split(maxsplit=2)
            sub = parts[1].lower() if len(parts) > 1 else ""
            args_str = parts[2] if len(parts) > 2 else ""
            args = args_str.split() if args_str else []
            await self._dispatch(sub, args, say, client, channel)
        else:
            await self._run_ai_pipeline(say, client, text, channel)

    async def _dispatch(
        self,
        sub: str,
        args: list[str],
        say,
        client,
        channel: str,
    ) -> None:
        table = {
            "run": self._cmd_run,
            "sync": self._cmd_sync,
            "git": self._cmd_git,
            "diff": self._cmd_diff,
            "log": self._cmd_log,
            "status": self._cmd_status,
            "clear": self._cmd_clear,
            "restart": self._cmd_restart,
            "confirm": self._cmd_confirm,
            "info": self._cmd_info,
            "help": self._cmd_help,
        }
        handler = table.get(sub)
        if handler is None:
            if sub:
                await say(f"❓ Unknown command: `{sub}`")
            await self._cmd_help([], say, client, channel)
            return
        await handler(args, say, client, channel)

    # ── Utility commands ──────────────────────────────────────────────────

    async def _cmd_run(
        self, args: list[str], say, client, channel: str
    ) -> None:
        cmd = " ".join(args)
        if not cmd:
            await say(f"Usage: `{self._p} run <shell command>`")
            return
        needs_confirm = (
            self._confirm_destructive
            and executor.is_destructive(cmd)
            and not executor.is_exempt(cmd, self._settings.bot.skip_confirm_keywords)
        )
        if needs_confirm:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⚠️ Destructive command:\n```{cmd}```\n\nConfirm?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Run"},
                            "action_id": "confirm_run",
                            "value": cmd,
                            "style": "danger",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Cancel"},
                            "action_id": "cancel_run",
                        },
                    ],
                },
            ]
            resp = await client.chat_postMessage(
                channel=channel, text=f"⚠️ Confirm: {cmd}", blocks=blocks
            )
            self._pending_cmds[(channel, resp["ts"])] = cmd
        else:
            await say("⏳ Running…")
            result = await executor.run_shell(
                cmd, self._settings.bot.max_output_chars
            )
            await say(f"```\n{result}\n```")

    async def _cmd_sync(
        self, args: list[str], say, client, channel: str
    ) -> None:
        await say("⏳ Pulling latest changes…")
        result = await repo.pull()
        await say(f"✅ Synced\n{result}")

    async def _cmd_git(
        self, args: list[str], say, client, channel: str
    ) -> None:
        result = await repo.status()
        await say(f"```\n{result}\n```")

    async def _cmd_diff(
        self, args: list[str], say, client, channel: str
    ) -> None:
        arg = args[0] if args else ""
        if not arg:
            ref = "HEAD~1 HEAD"
        elif arg.isdigit():
            ref = f"HEAD~{arg} HEAD"
        else:
            ref = f"{arg} HEAD"
        result = await executor.run_shell(
            f"git diff {ref} --stat && echo '---' && git diff {ref}",
            self._settings.bot.max_output_chars,
        )
        await say(f"```\n{result or '(no changes)'}\n```")

    async def _cmd_log(
        self, args: list[str], say, client, channel: str
    ) -> None:
        try:
            n = int(args[0]) if args else 20
            n = max(1, min(n, 200))
        except ValueError:
            await say(f"Usage: `{self._p} log [lines]` — e.g. `{self._p} log 50`")
            return
        result = await executor.run_shell(
            (
                f"tail -n {n} /proc/1/fd/1 2>/dev/null"
                f" || journalctl -n {n} --no-pager 2>/dev/null"
                f" || echo '(log not accessible)'"
            ),
            self._settings.bot.max_output_chars,
        )
        await say(f"```\n{result}\n```")

    async def _cmd_status(
        self, args: list[str], say, client, channel: str
    ) -> None:
        if self._active_ai:
            lines = ["🔄 AI is currently processing:\n"]
            for prompt, ts in self._active_ai.items():
                elapsed = int(time.time() - ts)
                lines.append(f"  • {prompt[:60]}… ({elapsed}s ago)")
            await say("\n".join(lines))
        else:
            await say("✅ AI is idle — ready for your next message.")

    async def _cmd_confirm(
        self, args: list[str], say, client, channel: str
    ) -> None:
        arg = (args[0].lower() if args else "").strip()
        if arg == "off":
            self._confirm_destructive = False
            await say(
                "⚡ Confirmation prompts *disabled* for this session.\n"
                "Destructive commands will run immediately."
            )
        elif arg == "on":
            self._confirm_destructive = True
            await say("🛡 Confirmation prompts *enabled* for this session.")
        else:
            state = "enabled 🛡" if self._confirm_destructive else "disabled ⚡"
            source = (
                "default"
                if self._confirm_destructive
                == self._settings.bot.confirm_destructive
                else "session override"
            )
            skipped = (
                f"\nSkip-list: `{', '.join(self._settings.bot.skip_confirm_keywords)}`"
                if self._settings.bot.skip_confirm_keywords
                else ""
            )
            await say(f"Confirmation prompts: *{state}* ({source}){skipped}")

    async def _cmd_clear(
        self, args: list[str], say, client, channel: str
    ) -> None:
        if self._settings.bot.history_enabled:
            await __import__("src.history", fromlist=["clear_history"]).clear_history(
                channel
            )
        self._backend.clear_history()
        await say("🗑 Conversation history cleared.")

    async def _cmd_restart(
        self, args: list[str], say, client, channel: str
    ) -> None:
        await say("🔄 Restarting AI backend…")
        try:
            self._backend.close()
            self._backend = ai_factory.create_backend(self._settings.ai)
            await say(f"✅ AI backend restarted ({self._settings.ai.ai_cli})")
        except Exception as exc:
            logger.exception("Backend restart failed")
            await say(f"⚠️ Restart failed: {exc}")

    async def _cmd_help(
        self, args: list[str], say, client, channel: str
    ) -> None:
        p = self._p
        text = (
            f"🤖 *AgentGate v{VERSION} — Slack Command Reference*\n\n"
            f"*Send messages starting with `{p} <command>`:*\n\n"
            f"`{p} run <cmd>` — run a shell command in the repo\n"
            f"`{p} sync` — git pull (fetch latest changes)\n"
            f"`{p} git` — git status\n"
            f"`{p} diff [n|sha]` — git diff (default: last commit)\n"
            f"`{p} log [n]` — tail last n container log lines (default 20)\n"
            f"`{p} status` — check if AI is busy\n"
            f"`{p} clear` — clear conversation history\n"
            f"`{p} restart` — restart AI backend session\n"
            f"`{p} confirm [on|off]` — toggle/query confirmation prompts\n"
            f"`{p} info` — project & bot info\n"
            f"`{p} help` — this message\n\n"
            f"*AI commands:*\n"
            f"Any other message is sent directly to the AI.\n\n"
            f"*Voice messages:*\n"
            f"Upload an audio file to transcribe and forward to the AI.\n"
            f"Requires `WHISPER_PROVIDER=openai`."
        )
        await say(text)

    async def _cmd_info(
        self, args: list[str], say, client, channel: str
    ) -> None:
        uptime_s = int(time.time() - self._start_time)
        h, remainder = divmod(uptime_s, 3600)
        m, s = divmod(remainder, 60)
        ai = _ai_label(self._settings)
        confirm_state = "enabled 🛡" if self._confirm_destructive else "disabled ⚡"
        voice_state = (
            f"enabled ({self._settings.voice.whisper_provider})"
            if self._transcriber
            else "disabled"
        )
        tag = self._settings.bot.image_tag
        version_line = f"v{VERSION}" + (f" `:{tag}`" if tag else "")
        text = (
            f"ℹ️ *AgentGate Info* — {version_line}\n\n"
            f"📁 Repo: `{self._settings.github.github_repo}`\n"
            f"🌿 Branch: `{self._settings.github.branch}`\n"
            f"🤖 AI: `{ai}`\n"
            f"💬 Platform: Slack\n"
            f"📏 Max output: `{self._settings.bot.max_output_chars}` chars\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 Active AI tasks: `{len(self._active_ai)}`\n"
            f"🛡 Confirmations: `{confirm_state}`\n"
            f"🎙️ Voice: `{voice_state}`"
        )
        await say(text)

    # ── Block Kit action handlers ─────────────────────────────────────────

    async def _on_confirm_run(self, ack, action, client, body) -> None:
        await ack()
        channel = body["channel"]["id"]
        ts = body["message"]["ts"]
        cmd = self._pending_cmds.pop((channel, ts), None)
        if cmd is None:
            await client.chat_update(
                channel=channel, ts=ts, text="❌ Command expired.", blocks=[]
            )
            return
        await client.chat_update(
            channel=channel, ts=ts, text=f"⏳ Running:\n```{cmd}```", blocks=[]
        )
        result = await executor.run_shell(
            cmd, self._settings.bot.max_output_chars
        )
        await client.chat_postMessage(
            channel=channel, text=f"```\n{result}\n```"
        )

    async def _on_cancel_run(self, ack, action, client, body) -> None:
        await ack()
        channel = body["channel"]["id"]
        ts = body["message"]["ts"]
        self._pending_cmds.pop((channel, ts), None)
        await client.chat_update(
            channel=channel, ts=ts, text="❌ Cancelled.", blocks=[]
        )

    # ── Voice/audio file handling ─────────────────────────────────────────

    async def _handle_files(
        self, event: dict, say, client, channel: str
    ) -> None:
        if self._transcriber is None:
            await say(
                "🎙️ Voice messages are disabled."
                " Set WHISPER_PROVIDER=openai to enable."
            )
            return

        files = event.get("files", [])
        audio_file = next(
            (
                f
                for f in files
                if (f.get("mimetype") or "").startswith("audio")
                or f.get("filetype") in ("mp3", "mp4", "ogg", "wav", "m4a", "webm")
            ),
            None,
        )
        if audio_file is None:
            return

        resp = await say("🎙️ Transcribing…")
        ts = resp["ts"]
        try:
            url = audio_file.get("url_private") or audio_file.get("url_private_download")
            if not url:
                await self._edit(client, channel, ts, "⚠️ Could not get audio URL.")
                return
            import aiohttp
            headers = {"Authorization": f"Bearer {self._settings.slack.slack_bot_token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as r:
                    audio_bytes = await r.read()
            filename = audio_file.get("name") or "voice.mp3"
            text = await self._transcriber.transcribe(audio_bytes, filename)
        except Exception as exc:
            logger.exception("Transcription error")
            await self._edit(client, channel, ts, f"⚠️ Transcription failed: {exc}")
            return

        await self._edit(client, channel, ts, f"🎙️ I heard: _{text}_")
        await self._run_ai_pipeline(say, client, text, channel)

    # ── Startup ───────────────────────────────────────────────────────────

    async def run_async(self) -> None:
        """Start the Slack Socket Mode connection."""
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

        handler = AsyncSocketModeHandler(
            self._app, self._settings.slack.slack_app_token
        )
        await handler.start_async()

    async def send_ready_message(self, client=None) -> None:
        """Post the 🟢 Ready message to the configured channel."""
        channel = self._settings.slack.slack_channel_id
        if not channel:
            logger.info("SLACK_CHANNEL_ID not set — skipping ready message.")
            return
        text = build_ready_message(self._settings, VERSION, self._p)
        if client is None:
            client = self._app.client
        await client.chat_postMessage(channel=channel, text=text)
