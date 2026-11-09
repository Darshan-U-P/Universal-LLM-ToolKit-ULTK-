import pytest

from ultk.exceptions import DuplicateToolError, ToolSchemaError
from ultk.models import ToolContext, ToolSpec
from ultk.registry import ToolRegistry


class EchoTool:
    spec = ToolSpec(
        name="test.echo",
        description="Echo a message",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> str:
        return arguments["message"]


def test_register_and_project_schema():
    registry = ToolRegistry()
    registry.register(EchoTool())
    assert registry.get("test.echo") is not None
    assert registry.provider_schemas()[0]["function"]["name"] == "test.echo"


def test_duplicate_registration_is_rejected():
    registry = ToolRegistry()
    registry.register(EchoTool())
    with pytest.raises(DuplicateToolError):
        registry.register(EchoTool())


def test_invalid_schema_is_rejected():
    class InvalidTool(EchoTool):
        spec = ToolSpec("bad", "bad", {"type": "not-a-json-schema-type"})

    with pytest.raises((ToolSchemaError, ValueError)):
        ToolRegistry().register(InvalidTool())
