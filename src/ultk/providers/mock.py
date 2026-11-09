"""Deterministic provider test double."""

from __future__ import annotations

from collections import deque
from typing import Mapping, Sequence

from ultk.exceptions import ConfigurationError
from ultk.models import AssistantTurn


class MockProvider:
    def __init__(self, turns: Sequence[AssistantTurn]) -> None:
        self._turns = deque(turns)
        self.calls: list[dict] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> AssistantTurn:
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self._turns:
            raise ConfigurationError("MockProvider has no scripted turns remaining.")
        return self._turns.popleft()
