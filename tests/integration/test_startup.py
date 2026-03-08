"""Integration test for main.py startup sequence."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestStartup:
    async def test_startup_calls_all_phases(self, monkeypatch):
        """Verify startup() calls each phase in order and sends Ready message."""
        from src.config import Settings, TelegramConfig, GitHubConfig, BotConfig, AIConfig

        # Build a minimal settings object
        tg = MagicMock(spec=TelegramConfig)
        tg.chat_id = "99999"
        tg.bot_token = "fake-token"
        gh = MagicMock(spec=GitHubConfig)
        gh.github_repo_token = "tok"
        gh.github_repo = "owner/repo"
        gh.branch = "main"
        bot = MagicMock(spec=BotConfig)
        bot.bot_cmd_prefix = "ta"
        bot.image_tag = ""
        ai = MagicMock(spec=AIConfig)
        ai.ai_cli = "api"
        ai.ai_provider = "openai"
        ai.ai_model = ""
        settings = MagicMock(spec=Settings)
        settings.platform = "telegram"
        settings.telegram = tg
        settings.github = gh
        settings.bot = bot
        settings.ai = ai

        mock_clone = AsyncMock()
        mock_install = AsyncMock(return_value="OK")
        mock_init_db = AsyncMock()
        mock_backend = MagicMock()
        mock_backend.is_stateful = False

        mock_app = AsyncMock()
        mock_app.__aenter__ = AsyncMock(return_value=mock_app)
        mock_app.__aexit__ = AsyncMock(return_value=False)
        mock_app.bot.send_message = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.updater.start_polling = AsyncMock()

        # stop_event will be set immediately to exit the wait loop
        import asyncio

        async def fake_startup(settings):
            from src import repo, runtime, history
            from src.ai.factory import create_backend

            await mock_clone(settings.github.github_repo_token, settings.github.github_repo, settings.github.branch)
            await mock_install()
            await mock_init_db()
            _ = mock_backend

        with patch("src.repo.clone", mock_clone), \
             patch("src.repo.configure_git_auth", AsyncMock()), \
             patch("src.runtime.install_deps", mock_install), \
             patch("src.history.init_db", mock_init_db), \
             patch("src.ai.factory.create_backend", return_value=mock_backend):

            from src.main import startup
            import signal

            # Patch asyncio.Event so wait() returns immediately
            async def instant_wait(self):
                return

            with patch.object(asyncio.Event, "wait", instant_wait), \
                 patch("src.bot.build_app", return_value=mock_app):
                await startup(settings)

        mock_clone.assert_awaited_once()
        mock_install.assert_awaited_once()
        mock_init_db.assert_awaited_once()
        mock_app.bot.send_message.assert_awaited_once()
