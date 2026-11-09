import pytest

from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolContext, ToolSpec
from ultk.permissions import AllowListPolicy, DenyAllPolicy
from ultk.registry import ToolRegistry


class AddTool:
    spec = ToolSpec(
        name="math.add",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"math:compute"}),
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> int:
        return arguments["a"] + arguments["b"]


@pytest.mark.asyncio
async def test_dispatch_requires_policy_and_capability():
    registry = ToolRegistry()
    registry.register(AddTool())
    denied = ToolDispatcher(registry, DenyAllPolicy())
    result = await denied.execute(ToolCallRequest("1", "math.add", {"a": 2, "b": 3}))
    assert result.is_error

    allowed = ToolDispatcher(
        registry,
        AllowListPolicy({"math.add"}),
    )
    result = await allowed.execute(
        ToolCallRequest("2", "math.add", {"a": 2, "b": 3}),
        granted_capabilities=frozenset({"math:compute"}),
    )
    assert not result.is_error
    assert result.content == "5"


@pytest.mark.asyncio
async def test_invalid_arguments_never_invoke_tool():
    registry = ToolRegistry()
    registry.register(AddTool())
    dispatcher = ToolDispatcher(registry, AllowListPolicy({"math.add"}))
    result = await dispatcher.execute(
        ToolCallRequest("3", "math.add", {"a": "not-number", "b": 3}),
        granted_capabilities=frozenset({"math:compute"}),
    )
    assert result.is_error
    assert "Invalid arguments" in result.content


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_error():
    dispatcher = ToolDispatcher(ToolRegistry(), DenyAllPolicy())
    result = await dispatcher.execute(
        ToolCallRequest("missing-1", "missing.tool", {})
    )
    assert result.is_error
    assert "not registered" in result.content
