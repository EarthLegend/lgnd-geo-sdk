# Working in lgnd-geo-sdk

The Python SDK for LGND Geo: connects agents and code to its MCP server
(EarthLegend/agentic-platform). The core, `lgnd_geo_sdk.connection`, is the server URL, the
sign-in (`auth()`) and a FastMCP client (`client()`). An agent framework's adapter hands those to the framework's own MCP support.
Agent frameworks run agents; this package does not.

## Rules

- Keep it to connecting and signing in. Anything an agent framework or FastMCP already does
  (agent loops, streaming, tool filtering, approval, OAuth) is used, not rebuilt.
- The core imports no agent framework. Each framework's adapter is a submodule named after it
  (`lgnd_geo_sdk.pydantic_ai`), with an extra of the same name in `pyproject.toml` for its
  dependency, tests in `tests/test_<framework>.py` and examples in `examples/<framework>/`.
  Adapters build on the core and take the same `url` and `token_directory`.
- Tests need no network and no API key.

## Commands

`make sync`, `make lint`, `make fmt`, `make test`, `make docs` (`make docs-serve` to preview).
