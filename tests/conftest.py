"""Shared fixtures for all tests."""
import os
import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove real credentials from env so tests don't accidentally use them."""
    for key in ("TG_BOT_TOKEN", "TG_CHAT_ID", "GITHUB_TOKEN", "GITHUB_REPO",
                "COPILOT_GITHUB_TOKEN", "AI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
