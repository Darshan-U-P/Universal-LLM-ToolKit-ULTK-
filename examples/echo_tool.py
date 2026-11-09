"""Minimal example showing how to define and register a ULTK tool.

This example uses a mock provider because provider-specific adapters are
implemented independently from the framework core.
"""

import asyncio

from ultk import AllowListPolicy, AssistantTurn, ToolContext, ToolKit, ToolSpec
from ultk.providers.mock import MockProvider
from ultk.models import ToolCallRequest


class EchoTool:
    spec = ToolSpec(
        name="demo.echo",
        description="Return the supplied text.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> str:
        return arguments["text"]


async def main() -> None:
    provider = MockProvider([
        AssistantTurn(tool_calls=(
            ToolCallRequest("call-1", "demo.echo", {"text": "Hello from ULTK"}),
        )),
        AssistantTurn(content="The tool returned: Hello from ULTK"),
    ])
    toolkit = ToolKit(provider, policy=AllowListPolicy({"demo.echo"}))
    toolkit.register_tool(EchoTool())
    answer = await toolkit.run("Echo a greeting.", enabled_tools=["demo.echo"])
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
