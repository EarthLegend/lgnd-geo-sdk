# Getting Started

There are two ways to use LGND Geo's tools: bring your own agent and let it decide which tools to
call, or call them yourself from your own code.

## With an agent

With Pydantic AI:

```python
import asyncio

from pydantic_ai import Agent

from lgnd_geo_sdk.pydantic_ai import toolset


async def main() -> None:
    agent = Agent("anthropic:claude-opus-5-5", toolsets=[toolset()])
    result = await agent.run("Find solar farms built near Springfield, Illinois since 2021.")
    print(result.output)


asyncio.run(main())
```

## Without an agent

`client()` connects to LGND Geo and calls its tools. No model or API key needed.

```python
import asyncio

from lgnd_geo_sdk import client

SPRINGFIELD = {"lat": 39.8, "lon": -89.65, "radius_km": 50}


async def main() -> None:
    async with client() as geo:
        result = await geo.call_tool(
            "search_place_find", {"index": "naip", "text": "solar farm", "area": SPRINGFIELD}
        )
        print(result.content[0].text)


asyncio.run(main())
```

`client()` is a [FastMCP](https://gofastmcp.com) client; `await geo.list_tools()` lists the
tools, with each one's description and input schema.
