# lgnd-geo-sdk

The Python SDK for [LGND Geo](https://lgnd.ai): connect AI agents and your own code to its
tools for searching aerial and satellite imagery.

- [**Documentation**](https://earthlegend.github.io/lgnd-geo-sdk/)
- [**Examples**](examples/pydantic_ai/)

## Example

```
pip install "lgnd-geo-sdk[pydantic-ai]" "pydantic-ai-slim[anthropic]"
```

```python
import asyncio

from pydantic_ai import Agent

from lgnd_geo_sdk.pydantic_ai import toolset


async def main() -> None:
    agent = Agent("anthropic:claude-opus-5-5", toolsets=[toolset()])
    result = await agent.run("Where around Phoenix has new housing gone up since 2020?")
    print(result.output)


asyncio.run(main())
```
