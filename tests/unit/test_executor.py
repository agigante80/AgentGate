"""Unit tests for executor.py — is_destructive, truncate_output, summarize_if_long."""
import pytest

from src.executor import is_destructive, truncate_output, summarize_if_long


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

    async def test_summary_truncated_to_max(self):
        class FakeBackend:
            async def send(self, prompt):
                return "y" * 200  # returns too-long summary
        long_text = "x" * 200
        result = await summarize_if_long(long_text, 100, FakeBackend())
        assert len(result) <= 100
