"""A tool error reaches the model as text it can act on, so it can correct the call and retry.

LGND Geo's tools refuse a call with `CODE: message`, where the message says what to give
instead. Here an in-process MCP server refuses the first call; the model must see that text.
"""

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

REFUSAL = "MOVE_REFUSED: on naip, `index` is naip or s2, not landsat"


def server() -> FastMCP:
    mcp = FastMCP("lgnd-geo")

    @mcp.tool
    def discover_area_view(index: str) -> str:
        """View an area."""
        if index != "naip":
            raise ToolError(REFUSAL)
        return "12 cells"

    return mcp


async def test_a_refused_call_is_sent_back_to_the_model_with_the_servers_text():
    seen: list[str] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        """Call with a wrong index, then with the one the refusal asks for, then answer."""
        calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
        seen.extend(str(p.content) for p in messages[-1].parts if isinstance(p, RetryPromptPart))
        if not calls:
            return ModelResponse(parts=[ToolCallPart("discover_area_view", {"index": "landsat"})])
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("discover_area_view", {"index": "naip"})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(model), toolsets=[MCPToolset(server())])

    result = await agent.run("look at the area")

    assert result.output == "done"
    assert any(REFUSAL in text for text in seen)
