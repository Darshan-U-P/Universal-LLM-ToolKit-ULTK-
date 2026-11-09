"""Provider-neutral LLM adapter contract."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from ultk.models import AssistantTurn


class ProviderAdapter(Protocol):
    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> AssistantTurn:
        """Return one assistant turn, optionally containing proposed tool calls."""
