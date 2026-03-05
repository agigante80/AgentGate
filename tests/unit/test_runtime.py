"""Unit tests for runtime.py — dependency detection."""
import pytest
from unittest.mock import AsyncMock, patch
from pathlib import Path

import src.runtime as runtime_module


class TestInstallDeps:
    async def test_no_manifest_returns_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runtime_module, "REPO_DIR", tmp_path)
        result = await runtime_module.install_deps()
        assert "No known package manifest" in result

    async def test_detects_package_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runtime_module, "REPO_DIR", tmp_path)
        (tmp_path / "package.json").write_text("{}")
        with patch("asyncio.create_subprocess_exec") as mock_proc:
            mock_proc.return_value = AsyncMock(
                communicate=AsyncMock(return_value=(b"ok", b"")),
                returncode=0,
            )
            result = await runtime_module.install_deps()
        assert "npm" in result

    async def test_detects_pyproject_toml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runtime_module, "REPO_DIR", tmp_path)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        with patch("asyncio.create_subprocess_exec") as mock_proc:
            mock_proc.return_value = AsyncMock(
                communicate=AsyncMock(return_value=(b"ok", b"")),
                returncode=0,
            )
            result = await runtime_module.install_deps()
        assert "pip" in result

    async def test_failed_install_marked_with_x(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runtime_module, "REPO_DIR", tmp_path)
        (tmp_path / "requirements.txt").write_text("nonexistent-pkg==0.0.0")
        with patch("asyncio.create_subprocess_exec") as mock_proc:
            mock_proc.return_value = AsyncMock(
                communicate=AsyncMock(return_value=(b"error output", b"")),
                returncode=1,
            )
            result = await runtime_module.install_deps()
        assert "❌" in result
