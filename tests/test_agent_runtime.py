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


@pytest.mark.asyncio
async def test_model_cannot_call_registered_but_disabled_tool():
    provider = MockProvider([
        AssistantTurn(tool_calls=(
            ToolCallRequest("call-disabled", "demo.greet", {"name": "Darshan"}),
        )),
        AssistantTurn(content="The requested tool was unavailable."),
    ])
    toolkit = ToolKit(provider, policy=AllowListPolicy({"demo.greet"}))
    toolkit.register_tool(GreetingTool())

    answer = await toolkit.run("Try greeting.", enabled_tools=[])

    assert answer == "The requested tool was unavailable."
    assert provider.calls[0]["tools"] == []
    assert "not enabled" in provider.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_agent_receives_host_messages_metadata_and_emits_lifecycle_events():
    from ultk.agents.runtime import AgentRuntime
    from ultk.execution import ToolDispatcher
    from ultk.registry import ToolRegistry

    captured = {}

    class ContextTool:
        spec = ToolSpec(
            name="demo.context",
            description="Return a trusted host context value",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

        async def invoke(self, arguments: dict, context: ToolContext) -> str:
            captured["profile_id"] = context.metadata["profile_id"]
            return context.metadata["profile_id"]

    provider = MockProvider([
        AssistantTurn(tool_calls=(
            ToolCallRequest("call-context", "demo.context", {}),
        )),
        AssistantTurn(content="Context received."),
    ])
    registry = ToolRegistry()
    registry.register(ContextTool())
    dispatcher = ToolDispatcher(registry, AllowListPolicy({"demo.context"}))
    runtime = AgentRuntime(provider, registry, dispatcher)
    events = []

    async def on_event(event):
        events.append(dict(event))

    answer = await runtime.run(
        "Use the current profile context.",
        session_id="profile-7:conversation-9",
        enabled_tools=["demo.context"],
        messages=[
            {"role": "system", "content": "Use tools only when needed."},
            {"role": "user", "content": "Use the current profile context."},
        ],
        tool_metadata={
            "profile_id": "profile-7",
            "conversation_id": "conversation-9",
        },
        on_event=on_event,
    )

    assert answer == "Context received."
    assert captured["profile_id"] == "profile-7"
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert [event["type"] for event in events] == [
        "model_turn_started",
        "model_turn_completed",
        "tool_call_started",
        "tool_call_completed",
        "model_turn_started",
        "model_turn_completed",
        "run_completed",
    ]
