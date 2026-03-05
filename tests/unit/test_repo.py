"""Unit tests for repo.py — URL construction, skip-if-cloned guard."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import src.repo as repo_module


class TestCloneUrlConstruction:
    async def test_skips_if_git_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        (tmp_path / ".git").mkdir()
        # clone_from should NOT be called
        with patch("git.Repo.clone_from") as mock_clone:
            await repo_module.clone("token", "owner/repo", "main")
            mock_clone.assert_not_called()

    async def test_skips_if_no_repo_set(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        with patch("git.Repo.clone_from") as mock_clone:
            await repo_module.clone("token", "", "main")
            mock_clone.assert_not_called()

    async def test_clone_called_with_correct_url(self, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        with patch("asyncio.to_thread", new=AsyncMock()) as mock_thread:
            await repo_module.clone("mytoken", "owner/repo", "main")
            args = mock_thread.call_args[0]
            url = args[1]  # second positional arg to clone_from
            assert "mytoken" in url
            assert "owner/repo" in url
            assert url.startswith("https://")

    @pytest.mark.parametrize("repo_input,expected_path", [
        ("owner/repo", "owner/repo"),
        ("https://github.com/owner/repo", "owner/repo"),
    ])
    async def test_strips_github_prefix(self, tmp_path, monkeypatch, repo_input, expected_path):
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        with patch("asyncio.to_thread", new=AsyncMock()) as mock_thread:
            await repo_module.clone("tok", repo_input, "main")
            url = mock_thread.call_args[0][1]
            assert expected_path in url
