r"""An agent for a regional planner tracking where new housing is being built.

    uv run python examples/pydantic_ai/regional_planner.py \
        "Where around Phoenix has new housing gone up since 2020?"

The first run opens the browser to sign in. Needs ANTHROPIC_API_KEY.
"""

import asyncio
import sys

from _printing import run_and_print
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.toolsets import AbstractToolset

from lgnd_geo_sdk.pydantic_ai import toolset

INSTRUCTIONS = """\
I'm a planner at a regional planning agency in Arizona. We plan roads, water and schools for the
places people are moving to, so I keep track of new housing as it is built.

For each development you find, tell me where it is (the nearest town and the major roads around
it, plus coordinates), what kind of housing it is (single-family homes, apartments, or land graded
for homes not yet built), roughly how big it is, and when construction started, as closely as you
can tell. Put the developments in a table. Say how confident you are in each one, and leave out
anything you haven't confirmed in the imagery."""


def build_agent(tools: AbstractToolset, model: str = "anthropic:claude-opus-5-5") -> Agent:
    """Return the agent, with LGND Geo's tools."""
    return Agent(
        model,
        toolsets=[tools],
        instructions=INSTRUCTIONS,
        # Have Claude return a summary of its thinking, so it can be printed as it thinks.
        model_settings=AnthropicModelSettings(
            anthropic_thinking={"type": "adaptive", "display": "summarized"}
        ),
    )


async def main(question: str) -> None:
    """Run the agent on one question, printing what it does as it happens."""
    await run_and_print(build_agent(toolset()), question)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
