"""Redact secrets from outgoing text."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"

# ── Pattern-based detection ───────────────────────────────────────────────────

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),               # GitHub PAT (classic)
    re.compile(r"gho_[A-Za-z0-9]{36,}"),               # GitHub OAuth token
    re.compile(r"ghs_[A-Za-z0-9]{36,}"),               # GitHub server-to-server
    re.compile(r"ghr_[A-Za-z0-9]{36,}"),               # GitHub refresh token
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),       # GitHub fine-grained PAT
    re.compile(r"xoxb-[A-Za-z0-9\-]{20,}"),            # Slack bot token
    re.compile(r"xoxp-[A-Za-z0-9\-]{20,}"),            # Slack user token
    re.compile(r"xapp-[A-Za-z0-9\-]{20,}"),            # Slack app-level token
    re.compile(r"xoxs-[A-Za-z0-9\-]{20,}"),            # Slack session token
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                # OpenAI API key
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}=*"), # Authorization header
    re.compile(r"https?://[^\s@]+:[^\s@]+@[^\s]+"),    # URL with embedded creds
]


class SecretRedactor:
    """Redact known secret values and common secret patterns from text."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = not settings.bot.allow_secrets
        self._known_values: list[str] = []
        if self._enabled:
            self._known_values = self._collect_secrets(settings)
            logger.info(
                "Secret redaction enabled (%d known values, %d patterns)",
                len(self._known_values), len(_SECRET_PATTERNS),
            )

    @staticmethod
    def _collect_secrets(settings: Settings) -> list[str]:
        """Gather non-empty secret values from all config sub-objects."""
        candidates: list[str] = []
        try:
            candidates.append(settings.telegram.bot_token)
        except AttributeError:
            pass
        try:
            candidates.append(settings.slack.slack_bot_token)
            candidates.append(settings.slack.slack_app_token)
        except AttributeError:
            pass
        try:
            candidates.append(settings.github.github_repo_token)
        except AttributeError:
            pass
        try:
            candidates.append(settings.ai.ai_api_key)
        except AttributeError:
            pass
        try:
            candidates.append(settings.ai.codex.codex_api_key)
        except AttributeError:
            pass
        try:
            candidates.append(settings.voice.whisper_api_key)
        except AttributeError:
            pass
        # Only include values that are long enough to avoid false-positive matches
        return [v for v in candidates if v and len(v) >= 8]

    def redact(self, text: str) -> str:
        """Return text with secrets replaced by [REDACTED]."""
        if not self._enabled or not text:
            return text
        # Value-based: replace known secret values first
        for secret in self._known_values:
            if secret in text:
                text = text.replace(secret, _REDACTED)
        # Pattern-based: replace common secret formats
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(_REDACTED, text)
        return text

    def redact_git_commit_cmd(self, cmd: str) -> str:
        """If cmd is a git commit, redact secrets from the commit message."""
        if not self._enabled:
            return cmd
        if "git commit" not in cmd and "git -c" not in cmd and "git -C" not in cmd:
            return cmd
        return self.redact(cmd)
