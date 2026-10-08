r"""An agent for an energy analyst tracking new electricity infrastructure in the US.

    uv run python examples/pydantic_ai/energy_analyst.py \
        "Find solar farms built in central Illinois since 2021."

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
I'm an analyst at an energy research firm. I track new electricity infrastructure being built in
the US (utility-scale solar farms, battery storage, substations and wind farms) to estimate how
much capacity is coming online, and where.

For each site you find, tell me where it is (nearest town, county and state, plus coordinates),
and what kind of infrastructure it is,. Put the sites in a table. Say how confident
you are in each one, and leave out anything you haven't confirmed.

My coverage area is Illinois."""


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
