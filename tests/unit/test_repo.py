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


class TestPull:
    async def test_pull_no_repo(self, tmp_path, monkeypatch):
        import src.repo as repo_module
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        result = await repo_module.pull()
        assert "No repository" in result

    async def test_pull_success(self, tmp_path, monkeypatch):
        import src.repo as repo_module
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        (tmp_path / ".git").mkdir()

        call_num = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            proc = AsyncMock()
            proc.returncode = 0
            if call_num == 1:  # fetch
                proc.communicate = AsyncMock(return_value=(b"", b""))
            elif call_num == 2:  # rev-parse upstream
                proc.communicate = AsyncMock(return_value=(b"origin/develop\n", b""))
            else:  # reset --hard
                proc.communicate = AsyncMock(return_value=(b"HEAD is now at abc1234 Latest commit", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await repo_module.pull()
        assert "HEAD is now at" in result

    async def test_pull_fetch_failure(self, tmp_path, monkeypatch):
        import src.repo as repo_module
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
        (tmp_path / ".git").mkdir()

        async def fake_exec(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"fatal: unable to connect"))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await repo_module.pull()
        assert "fetch failed" in result


class TestStatus:
    async def test_status_returns_combined_output(self, tmp_path, monkeypatch):
        import src.repo as repo_module
        monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)

        async def fake_exec(*args, **kwargs):
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"M  file.py\n", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await repo_module.status()
        assert "M  file.py" in result


class TestConfigureGitAuth:
    async def test_no_op_when_token_empty(self):
        """configure_git_auth does nothing when token is blank."""
        import src.repo as repo_module
        from unittest.mock import AsyncMock, patch
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_proc:
            await repo_module.configure_git_auth("")
        mock_proc.assert_not_called()

    async def test_sets_git_insteadof(self):
        """configure_git_auth calls git config with URL rewriting args."""
        import src.repo as repo_module
        from unittest.mock import AsyncMock, MagicMock, patch
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
            await repo_module.configure_git_auth("mytoken")
        args = mock_exec.call_args[0]
        assert args[0] == "git"
        assert "mytoken" in " ".join(str(a) for a in args)
        assert "insteadOf" in " ".join(str(a) for a in args)
        assert "https://github.com/" in " ".join(str(a) for a in args)
