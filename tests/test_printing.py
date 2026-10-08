"""The examples' helper prints the model's thinking, each tool call and the answer as they happen."""

import sys
from pathlib import Path

from fastmcp import FastMCP
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.function import AgentInfo, DeltaThinkingPart, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "pydantic_ai"))
from _printing import run_and_print


def server() -> FastMCP:
    mcp = FastMCP("lgnd-geo")

    @mcp.tool
    def user_identity_get() -> str:
        """Who is signed in."""
        return "usr_1"

    return mcp


async def test_a_run_prints_the_tool_call_then_the_answer(capsys):
    agent = Agent(
        TestModel(call_tools=["user_identity_get"], custom_output_text="You are usr_1."),
        toolsets=[MCPToolset(server())],
    )

    await run_and_print(agent, "who am i")

    out = capsys.readouterr().out
    assert out.index("→ user_identity_get") < out.index("✓ done") < out.index("You are usr_1.")


async def test_a_run_prints_the_models_thinking_before_its_tool_call(capsys):
    async def model(messages, _info: AgentInfo):
        """Think, then call the tool; once it has returned, answer."""
        if len(messages) == 1:
            yield {0: DeltaThinkingPart(content="I should check ")}
            yield {0: DeltaThinkingPart(content="who is signed in.")}
            yield {1: DeltaToolCall(name="user_identity_get", json_args="{}")}
        else:
            yield "You are usr_1."

    agent = Agent(FunctionModel(stream_function=model), toolsets=[MCPToolset(server())])

    await run_and_print(agent, "who am i")

    out = capsys.readouterr().out
    assert out.index("I should check who is signed in.") < out.index("→ user_identity_get")
    assert out.index("→ user_identity_get") < out.index("You are usr_1.")
