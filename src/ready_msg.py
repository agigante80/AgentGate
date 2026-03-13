"""Shared helpers for building the AgentGate ready / info messages."""
from src.config import Settings


def ai_label(settings: Settings) -> str:
    """Human-readable AI backend + model string."""
    cli = settings.ai.ai_cli
    model = settings.ai.ai_model
    if cli == "api" and settings.ai.direct.ai_provider:
        label = f"{cli}/{settings.ai.direct.ai_provider}"
    else:
        label = cli
    if model:
        label += f" ({model})"
    return label


def build_ready_message(settings: Settings, version: str, prefix: str, use_slash: bool = True) -> str:
    """Build the 🟢 Ready message shown on startup and by /gate info."""
    ai = ai_label(settings)
    tag = settings.bot.image_tag
    version_line = f"v{version}" + (f" `:{tag}`" if tag else "")
    cmd = f"/{prefix}" if use_slash else prefix
    return (
        f"🟢 *AgentGate Ready* — {version_line}\n"
        f"📁 `{settings.github.github_repo}` | 🌿 `{settings.github.branch}`\n"
        f"🤖 AI: `{ai}`\n"
        f"Type `{cmd} help` for commands | `{cmd} info` for full status"
    )
