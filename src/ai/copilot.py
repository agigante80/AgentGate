import logging
import os

from src.ai.adapter import AICLIBackend
from src.ai.session import CopilotSession
logger = logging.getLogger(__name__)


class CopilotBackend(AICLIBackend):
    is_stateful = True  # PTY session maintains its own multi-turn state
    def __init__(self, model: str = "") -> None:
        self._model = model
        self._env = {**os.environ}
        if model:
            self._env["COPILOT_MODEL"] = model
        self._session = CopilotSession(model=model, env=self._env)

    async def send(self, prompt: str) -> str:
        return await self._session.send(prompt)

    def clear_history(self) -> None:
        self._session.close()
        self._session = CopilotSession(model=self._model, env=self._env)

    def close(self) -> None:
        self._session.close()
