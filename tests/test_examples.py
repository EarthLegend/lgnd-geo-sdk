"""The examples run against a stand-in LGND Geo server."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import FastMCP
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.test import TestModel

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# the Pydantic AI examples import their helper as a sibling module, as running them does
sys.path.insert(0, str(EXAMPLES / "pydantic_ai"))
# a module whose name starts with an underscore is a helper, not an example
PYDANTIC_AI_AGENTS = sorted(
    path for path in (EXAMPLES / "pydantic_ai").glob("*.py") if not path.stem.startswith("_")
)


def load(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.parent.name}_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pydantic_ai_examples_are_the_two_agents():
    assert [path.stem for path in PYDANTIC_AI_AGENTS] == [
        "energy_analyst",
        "regional_planner",
    ]


@pytest.mark.parametrize("path", PYDANTIC_AI_AGENTS, ids=lambda path: path.stem)
async def test_a_pydantic_ai_agent_calls_lgnd_geos_tools(path):
    example = load(path)
    geo = FastMCP("lgnd-geo")

    @geo.tool
    def user_identity_get() -> str:
        """Who is signed in."""
        return "usr_1"

    model = TestModel(call_tools=["user_identity_get"], custom_output_text="done")
    result = await example.build_agent(MCPToolset(geo), model=model).run("who am i")

    assert result.output == "done"
    assert "usr_1" in str(result.all_messages())
