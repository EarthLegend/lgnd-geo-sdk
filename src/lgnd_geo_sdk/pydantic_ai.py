"""LGND Geo's MCP server as a Pydantic AI toolset.

Needs the `pydantic-ai` extra: `pip install "lgnd-geo-sdk[pydantic-ai]"`.
"""

from pathlib import Path

from lgnd_geo_sdk.connection import SIGN_IN_TIMEOUT_SECONDS, auth, server_url

try:
    from pydantic_ai.mcp import MCPToolset
except ImportError as error:
    raise ImportError(
        "lgnd_geo_sdk.pydantic_ai needs the pydantic-ai extra: "
        'pip install "lgnd-geo-sdk[pydantic-ai]"'
    ) from error


def toolset(url: str | None = None, *, token_directory: Path | None = None) -> MCPToolset:
    """Return LGND Geo's MCP server as a Pydantic AI toolset.

    The server's instructions, which say how its tools fit together, are passed to the model.
    Use Pydantic AI's toolset methods to narrow it: `.filtered(...)` to allow only some tools,
    `.approval_required(...)` to ask before calls.

    Args:
        url: The MCP server URL. Defaults to `lgnd_geo_sdk.server_url()`.
        token_directory: Where sign-in tokens are stored. Defaults to
            `lgnd_geo_sdk.default_token_directory()`.

    Returns:
        The toolset, to pass to `pydantic_ai.Agent(toolsets=[...])`. It signs in through the
        browser the first time; see `lgnd_geo_sdk.auth`.

    Example:
        ```python
        agent = Agent("anthropic:claude-opus-5-5", toolsets=[toolset()])
        result = await agent.run("Find solar farms near Springfield, Illinois.")
        print(result.output)
        ```
    """
    return MCPToolset(
        server_url(url),
        auth=auth(url, token_directory=token_directory),
        include_instructions=True,
        # The browser sign-in runs inside the connect handshake; Pydantic AI's 5 s cuts it off.
        init_timeout=SIGN_IN_TIMEOUT_SECONDS,
    )
