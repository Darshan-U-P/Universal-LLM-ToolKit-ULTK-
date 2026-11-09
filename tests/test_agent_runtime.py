import pytest

from ultk.models import AssistantTurn, ToolCallRequest, ToolContext, ToolSpec
from ultk.permissions import AllowListPolicy
from ultk.providers.mock import MockProvider
from ultk.toolkit import ToolKit


class GreetingTool:
    spec = ToolSpec(
        name="demo.greet",
        description="Return a greeting",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> str:
        return f"Hello, {arguments['name']}!"


@pytest.mark.asyncio
async def test_agent_calls_tool_then_returns_final_answer():
    provider = MockProvider([
        AssistantTurn(tool_calls=(
            ToolCallRequest("call-1", "demo.greet", {"name": "Darshan"}),
        )),
        AssistantTurn(content="The greeting is Hello, Darshan!"),
    ])
    toolkit = ToolKit(provider, policy=AllowListPolicy({"demo.greet"}))
    toolkit.register_tool(GreetingTool())

    answer = await toolkit.run(
        "Greet Darshan",
        enabled_tools=["demo.greet"],
    )

    assert answer == "The greeting is Hello, Darshan!"
    assert len(provider.calls) == 2
    assert provider.calls[0]["tools"][0]["function"]["name"] == "demo.greet"
    assert provider.calls[1]["messages"][-1]["content"] == "Hello, Darshan!"
