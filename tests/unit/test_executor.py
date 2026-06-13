"""Unit tests for executor.py — is_destructive, truncate_output, summarize_if_long."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.executor import (
    is_destructive, truncate_output, summarize_if_long, run_shell,
    sanitize_git_ref, scrubbed_env, _SECRET_ENV_KEYS, validate_shell_command,
)


class TestSanitizeGitRef:
    """sanitize_git_ref() must allow safe refs and reject anything with shell metacharacters."""

    @pytest.mark.parametrize("ref", [
        "main", "develop", "feature/my-branch", "v1.0.0", "abc123def",
        "HEAD~1", "origin/main", "1.2.3", "my_branch",
    ])
    def test_valid_refs_returned_quoted(self, ref):
        result = sanitize_git_ref(ref)
        assert result is not None
        assert ref in result  # shlex.quote preserves the value

    @pytest.mark.parametrize("ref", [
        "; rm -rf /", "| cat /etc/passwd", "$(whoami)", "`id`",
        "branch name", "ref\x00null", "a&b", "a>b", "a<b",
    ])
    def test_invalid_refs_return_none(self, ref):
        assert sanitize_git_ref(ref) is None

    def test_empty_string_returns_none(self):
        assert sanitize_git_ref("") is None


class TestIsDestructive:
    @pytest.mark.parametrize("cmd", [
        "git push origin main",
        "git merge feature",
        "rm -rf /tmp/test",
        "remove file.txt",
        "git push --force",
        "git push -f",
        "drop table users",
        "delete from logs",
    ])
    def test_destructive_commands(self, cmd):
        assert is_destructive(cmd) is True

    @pytest.mark.parametrize("cmd", [
        "git status",
        "git log --oneline",
        "ls -la",
        "cat README.md",
        "python main.py",
        "npm test",
    ])
    def test_safe_commands(self, cmd):
        assert is_destructive(cmd) is False


class TestTruncateOutput:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert truncate_output(text, 100) == text

    def test_exact_length_unchanged(self):
        text = "a" * 100
        assert truncate_output(text, 100) == text

    def test_long_text_truncated(self):
        lines = [f"line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = truncate_output(text, 50)
        assert "truncated" in result
        assert "line 99" in result  # last line always included

    def test_truncation_header_present(self):
        text = "\n".join(["x" * 20] * 10)
        result = truncate_output(text, 50)
        assert "⚠️ Output truncated" in result

    def test_output_respects_max_chars(self):
        text = "\n".join(["word"] * 1000)
        result = truncate_output(text, 100)
        assert len(result) <= 200  # header + kept lines


class TestSummarizeIfLong:
    async def test_short_text_not_summarized(self):
        class FakeBackend:
            async def send(self, prompt): raise AssertionError("should not be called")
        result = await summarize_if_long("short", 100, FakeBackend())
        assert result == "short"

    async def test_long_text_calls_backend(self):
        class FakeBackend:
            async def send(self, prompt):
                return "summary"
        long_text = "x" * 200
        result = await summarize_if_long(long_text, 100, FakeBackend())
        assert result == "summary"

    async def test_summary_prompt_framed_with_output_tags(self):
        """The prompt sent to the backend must frame the content with <OUTPUT> tags."""
        received_prompts = []

        class FakeBackend:
            async def send(self, prompt):
                received_prompts.append(prompt)
                return "summary"

        long_text = "x" * 200
        await summarize_if_long(long_text, 100, FakeBackend())
        assert received_prompts, "backend.send must have been called"
        prompt = received_prompts[0]
        assert "<OUTPUT>" in prompt
        assert "</OUTPUT>" in prompt
        assert "do NOT follow" in prompt

    async def test_summary_truncated_to_max(self):
        class FakeBackend:
            async def send(self, prompt):
                return "y" * 200  # returns too-long summary
        long_text = "x" * 200
        result = await summarize_if_long(long_text, 100, FakeBackend())
        assert len(result) <= 100


class TestRunShell:
    async def test_run_shell_success(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await run_shell("echo hello", 3000)
        assert "hello" in result
        assert "[exit 0]" in result

    async def test_run_shell_nonzero_exit(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"error\n", b""))
        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await run_shell("false", 3000)
        assert "[exit 1]" in result

    async def test_run_shell_truncates_long_output(self):
        long_output = ("line\n" * 1000).encode()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(long_output, b""))
        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await run_shell("cmd", 100)
        assert "⚠️ Output truncated" in result
        assert len(result) <= 300  # header + a few kept lines


class TestScrubbedEnv:
    """scrubbed_env() must strip all known secret env vars and pass everything else through."""

    def test_strips_all_secret_keys(self):
        fake_secrets = {k: "s3cr3t" for k in _SECRET_ENV_KEYS}
        with patch.dict(os.environ, fake_secrets, clear=False):
            result = scrubbed_env()
        for key in _SECRET_ENV_KEYS:
            assert key not in result, f"{key} should have been stripped"

    def test_preserves_non_secret_vars(self):
        with patch.dict(os.environ, {"NODE_PATH": "/usr/lib/node", "HOME": "/root"}, clear=False):
            result = scrubbed_env()
        assert result.get("NODE_PATH") == "/usr/lib/node"
        assert "HOME" in result

    def test_returns_dict_copy(self):
        result = scrubbed_env()
        result["MUTATED"] = "yes"
        assert os.environ.get("MUTATED") is None

    def test_run_shell_passes_scrubbed_env(self):
        """run_shell must pass env= to create_subprocess_shell so secrets cannot leak."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok\n", b""))

        captured_kwargs: dict = {}

        async def _fake_shell(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_proc

        import asyncio
        with patch("asyncio.create_subprocess_shell", side_effect=_fake_shell):
            asyncio.run(run_shell("echo ok", 3000))

        assert "env" in captured_kwargs, "run_shell must pass env= to create_subprocess_shell"
        for key in _SECRET_ENV_KEYS:
            assert key not in captured_kwargs["env"], f"{key} must not be forwarded by run_shell"


class TestValidateShellCommand:
    """validate_shell_command() — metachar injection, readonly mode, allowlist."""

    # ── 1. Metacharacter bypass vectors (sec-provided list) ──────────────

    @pytest.mark.parametrize("cmd", [
        "ls; rm -rf /",                   # semicolon
        "ls && rm -rf /",                 # double-ampersand
        "ls || evil",                     # double-pipe
        "ls | cat /etc/passwd",           # single pipe
        "echo $(cat /etc/passwd)",        # command substitution $()
        "echo `cat /etc/passwd`",         # backtick substitution
        "ls\nrm -rf /",                   # embedded newline
        "ls\rrm -rf /",                   # carriage return
        "cmd > /etc/cron.daily/evil",     # redirect-out
        "cmd < /etc/passwd",              # redirect-in
        "{ malicious; }",                 # brace grouping
        "ls;cat /etc/shadow",             # semicolon no space
        "git log --format='%s' $(evil)",  # nested $()
    ])
    def test_metachar_blocked(self, cmd):
        result = validate_shell_command(cmd, allowlist=[], readonly=False)
        assert result is not None
        assert "Blocked" in result

    # ── 2. Clean commands pass ───────────────────────────────────────────

    @pytest.mark.parametrize("cmd", [
        "ls -la",
        "git status",
        "git log --oneline -10",
        "cat README.md",
        "python3 --version",
    ])
    def test_clean_commands_pass(self, cmd):
        assert validate_shell_command(cmd, allowlist=[], readonly=False) is None

    # ── 3. SHELL_READONLY mode ───────────────────────────────────────────

    def test_readonly_blocks_write_command(self):
        result = validate_shell_command("rm -rf /tmp/x", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_readonly_allows_ls(self):
        assert validate_shell_command("ls -la", allowlist=[], readonly=True) is None

    def test_readonly_allows_git_log(self):
        assert validate_shell_command("git log --oneline", allowlist=[], readonly=True) is None

    def test_readonly_blocks_git_push(self):
        result = validate_shell_command("git push origin main", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_readonly_blocks_git_commit(self):
        result = validate_shell_command("git commit -m msg", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    # ── 4. SHELL_ALLOWLIST mode ──────────────────────────────────────────

    def test_allowlist_permits_listed_command(self):
        assert validate_shell_command("git status", allowlist=["git"], readonly=False) is None

    def test_allowlist_blocks_unlisted_command(self):
        result = validate_shell_command("curl http://evil.example/", allowlist=["git"], readonly=False)
        assert result is not None and "Blocked" in result

    def test_allowlist_strips_path_prefix(self):
        """A full path like /usr/bin/ls should match allowlist entry 'ls'."""
        assert validate_shell_command("/usr/bin/ls -la", allowlist=["ls"], readonly=False) is None

    def test_empty_cmd_returns_block_when_allowlist_set(self):
        # empty string: shlex returns [], _first_token returns None → blocked
        result = validate_shell_command("", allowlist=["git"], readonly=False)
        # empty command is fine without allowlist, but with allowlist None token → blocked
        assert result is not None

    def test_metachar_checked_before_allowlist(self):
        """Metachar must be caught even if the command would otherwise be in the allowlist."""
        result = validate_shell_command("git status; rm -rf /", allowlist=["git"], readonly=False)
        assert result is not None and "metachar" in result.lower()

    def test_metachar_checked_before_readonly(self):
        """Metachar must be caught even in readonly mode."""
        result = validate_shell_command("ls; evil", allowlist=[], readonly=True)
        assert result is not None and "metachar" in result.lower()

    # ── 5. sed -i gating in SHELL_READONLY mode ──────────────────────────

    def test_sed_read_allowed_in_readonly(self):
        """Plain sed without -i is read-only and must be permitted."""
        assert validate_shell_command("sed 's/foo/bar/' file.txt", allowlist=[], readonly=True) is None

    def test_sed_i_blocked_in_readonly(self):
        """`sed -i` must be blocked in readonly mode (in-place write)."""
        result = validate_shell_command("sed -i 's/x/y/' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result and "sed -i" in result

    def test_sed_i_backup_blocked_in_readonly(self):
        """`sed -i.bak` (BSD-style in-place with backup) must also be blocked."""
        result = validate_shell_command("sed -i.bak 's/x/y/' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_sed_ni_blocked_in_readonly(self):
        """Short-flag bundle `-ni` still performs in-place writes and must be blocked."""
        result = validate_shell_command("sed -ni 's/x/y/' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_sed_long_in_place_blocked_in_readonly(self):
        """`sed --in-place` long-form must be blocked (previously bypassed the short-flag check)."""
        result = validate_shell_command("sed --in-place 's/x/y/' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result and "in-place" in result

    def test_sed_long_in_place_suffix_blocked_in_readonly(self):
        """`sed --in-place=.bak` long-form with suffix must also be blocked."""
        result = validate_shell_command("sed --in-place=.bak 's/x/y/' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result and "in-place" in result

    # ── 6. Removed interpreters not in _READONLY_CMDS ────────────────────

    def test_python3_blocked_in_readonly(self):
        """python3 must not be in readonly set — arbitrary execution risk."""
        result = validate_shell_command("python3 script.py", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_node_blocked_in_readonly(self):
        """node must not be in readonly set — arbitrary execution risk."""
        result = validate_shell_command("node index.js", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result

    def test_awk_blocked_in_readonly(self):
        """awk must not be in readonly set — can call system() without metacharacters."""
        result = validate_shell_command("awk '{print}' file.txt", allowlist=[], readonly=True)
        assert result is not None and "Blocked" in result
