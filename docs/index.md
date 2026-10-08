# lgnd-geo-sdk

The Python SDK for LGND Geo: connect AI agents and your own code to LGND Geo's tools for
searching aerial and satellite imagery.

- **Bring your own agent**: LGND Geo's tools as a toolset for your agent framework.
- **Or no agent at all**: call the tools from your own code, with no model needed.

## Installation

```
pip install lgnd-geo-sdk

# with Pydantic AI, and your model provider's extra
pip install "lgnd-geo-sdk[pydantic-ai]" "pydantic-ai-slim[anthropic]"
```

Head to [Getting Started](getting-started.md) to dig in.

## Supported agent frameworks

| Framework | Extra | Tools for the agent |
| --- | --- | --- |
| [Pydantic AI](https://pydantic.dev/docs/ai/) | `lgnd-geo-sdk[pydantic-ai]` | `lgnd_geo_sdk.pydantic_ai.toolset()` |

Using another framework? [Open an issue](https://github.com/EarthLegend/lgnd-geo-sdk/issues) and
we'll add it.
