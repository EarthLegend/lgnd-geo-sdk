"""The connection to LGND Geo's MCP server: the server, the sign-in and a client."""

import os
from pathlib import Path

from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    credentials_match_issuer,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    issuers_match,
    validate_metadata_issuer,
)

URL_ENVIRONMENT_VARIABLE = "LGND_GEO_MCP_URL"
"""The environment variable that overrides the server URL."""
DEFAULT_URL = "https://geo.lgnd.ai/mcp"
"""The server URL used when none is given: LGND Geo's MCP server."""
SIGN_IN_TIMEOUT_SECONDS = 300.0
"""How long connecting waits for the browser sign-in to finish."""


def server_url(url: str | None = None) -> str:
    """Return the URL of LGND Geo's MCP server.

    Args:
        url: A URL to use instead of the configured one.

    Returns:
        `url` if given, else `LGND_GEO_MCP_URL` if set, else `DEFAULT_URL`.
    """
    return url or os.environ.get(URL_ENVIRONMENT_VARIABLE) or DEFAULT_URL


def default_token_directory() -> Path:
    """Return the default directory for stored sign-in tokens.

    Returns:
        `~/.config/lgnd_geo_sdk/tokens`.
    """
    return Path.home() / ".config" / "lgnd_geo_sdk" / "tokens"


class _OAuth(OAuth):
    """FastMCP's `OAuth`, refreshing tokens stored by an earlier run at the right server.

    The `mcp` SDK learns the authorization server's token endpoint only on a 401. A new run
    whose stored access token has expired refreshes before any 401, so it posts to the MCP
    server's `/token` instead, which refuses it ("Token refresh failed: 405"), and signs in
    through the browser again. This looks the authorization server up first, as the SDK does
    on a 401.
    """

    async def _initialize(self) -> None:
        await super()._initialize()
        context = self.context
        if (
            context.oauth_metadata is None
            and not context.is_token_valid()
            and context.can_refresh_token()
        ):
            await self._discover_authorization_server()

    async def _discover_authorization_server(self) -> None:
        """Look up the authorization server, as `OAuthClientProvider._auth_flow` does on a 401.

        Credentials bound to another authorization server (SEP-2352) are dropped, not refreshed.
        """
        context = self.context
        async with self.httpx_client_factory() as http:
            for url in build_protected_resource_metadata_discovery_urls(None, context.server_url):
                response = await http.send(create_oauth_metadata_request(url))
                resource = await handle_protected_resource_response(response)
                if resource:
                    await self._validate_resource_match(resource)
                    context.protected_resource_metadata = resource
                    context.auth_server_url = self._select_authorization_server(
                        [str(server) for server in resource.authorization_servers]
                    )
                    break

            issuer = self._expected_issuer()
            if context.client_info and not credentials_match_issuer(
                context.client_info, issuer, context.client_metadata_url
            ):
                context.client_info = None
                context.clear_tokens()
                return

            for url in build_oauth_authorization_server_metadata_discovery_urls(
                context.auth_server_url, context.server_url
            ):
                response = await http.send(create_oauth_metadata_request(url))
                found, metadata = await handle_auth_metadata_response(response)
                if not found:
                    break
                if metadata:
                    # Without resource metadata, a root issuer may end in a slash (as in the SDK).
                    if context.auth_server_url is None and issuers_match(
                        str(metadata.issuer), issuer
                    ):
                        issuer = str(metadata.issuer)
                    validate_metadata_issuer(metadata, issuer)
                    context.oauth_metadata = metadata
                    break


def auth(url: str | None = None, *, token_directory: Path | None = None) -> OAuth:
    """Return the sign-in to LGND Geo's MCP server.

    This is the OAuth 2.1 sign-in: the first run opens the browser, and the tokens are stored in
    `token_directory`, so later runs sign in without it.

    Args:
        url: The MCP server URL. Defaults to `server_url()`.
        token_directory: Where sign-in tokens are stored. Defaults to
            `default_token_directory()`.

    Returns:
        A FastMCP `OAuth`: an `httpx2.Auth` that any MCP client on the `mcp` 2 SDK can sign in
        with.
    """
    directory = token_directory or default_token_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return _OAuth(
        mcp_url=server_url(url),
        client_name="lgnd-geo-sdk",
        # FastMCP keys the tokens by server URL; the strategies make such keys safe file names.
        token_storage=FileTreeStore(
            data_directory=directory,
            key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
            collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
        ),
        callback_timeout=SIGN_IN_TIMEOUT_SECONDS,
    )


def client(url: str | None = None, *, token_directory: Path | None = None) -> Client:
    """Return a FastMCP client for LGND Geo's MCP server, to call its tools from code.

    Args:
        url: The MCP server URL. Defaults to `server_url()`.
        token_directory: Where sign-in tokens are stored. Defaults to
            `default_token_directory()`.

    Returns:
        The client. It connects when entered (`async with`), signing in through the browser the
        first time; see `auth`.

    Example:
        ```python
        async with client() as geo:
            result = await geo.call_tool("user_identity_get", {})
            print(result.content[0].text)
        ```
    """
    return Client(
        server_url(url),
        auth=auth(url, token_directory=token_directory),
        # The browser sign-in runs inside the connect handshake.
        init_timeout=SIGN_IN_TIMEOUT_SECONDS,
    )
