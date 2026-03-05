import asyncio
import logging
import os
from pathlib import Path

from src.ai.adapter import AICLIBackend
from src.ai.session import CopilotSession

REPO_DIR = Path("/repo")
TIMEOUT = 180
logger = logging.getLogger(__name__)


class CopilotBackend(AICLIBackend):
    is_stateful = True  # PTY session maintains its own multi-turn state
    def __init__(self, model: str = "") -> None:
        self._model = model
        env = {**os.environ}
        if model:
            env["COPILOT_MODEL"] = model
        self._session = CopilotSession(model=model, env=env)

    async def send(self, prompt: str) -> str:
        return await self._session.send(prompt)
