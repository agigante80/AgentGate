"""Shared fixtures for all tests."""
import os
import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove real credentials from env so tests don't accidentally use them."""
    for key in ("TG_BOT_TOKEN", "TG_CHAT_ID", "GITHUB_TOKEN", "GITHUB_REPO",
                "COPILOT_GITHUB_TOKEN", "AI_API_KEY", "BRANCH", "GITHUB_REPO_TOKEN",
                "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID", "BOT_CMD_PREFIX"):
        monkeypatch.delenv(key, raising=False)
