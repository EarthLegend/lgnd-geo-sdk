"""The connection to LGND Geo's MCP server: the server, the sign-in and a client."""

import os
import sys
from pathlib import Path
from typing import Any

import anyio
import httpx2
from fastmcp import Client
from fastmcp.client.auth import ClientCredentialsOAuthProvider, OAuth
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from mcp.client.auth import OAuthTokenError
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
CLIENT_ID_ENVIRONMENT_VARIABLE = "LGND_GEO_CLIENT_ID"
"""The environment variable holding a machine user's client id."""
CLIENT_SECRET_ENVIRONMENT_VARIABLE = "LGND_GEO_CLIENT_SECRET"
"""The environment variable holding a machine user's client secret."""
DEFAULT_URL = "https://geo.lgnd.ai/mcp"
"""The server URL used when none is given: LGND Geo's MCP server."""
SIGN_IN_ENVIRONMENT_VARIABLE = "LGND_GEO_SIGN_IN"
"""The environment variable that picks the sign-in: `browser` or `device`."""
DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE = "LGND_GEO_DEVICE_CLIENT_ID"
"""The environment variable naming the OAuth client a device sign-in uses, for another server."""
SIGN_IN_TIMEOUT_SECONDS = 300.0
"""How long connecting waits for the browser or device sign-in to finish."""

_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# The OAuth client each server's device sign-in uses, by server URL. The authorization server
# allows the device grant only to a client registered for it by LGND, not to one a client
# registers for itself.
_DEVICE_CLIENT_IDS: dict[str, str] = {DEFAULT_URL: "client_01M5B3CATMJQ3PA2X25NJ2KTF7"}


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


class _DeviceOAuth(_OAuth):
    """`_OAuth`, signing in on another device (RFC 8628) instead of through a local browser.

    For hosted notebooks such as Colab, whose browser cannot reach a callback on the notebook's
    machine. It prints a link and a code; the person opens the link in any browser, signs in and
    confirms the code, while this polls the authorization server's token endpoint. Tokens are
    stored and refreshed exactly as `_OAuth` does. It signs in with a fixed `client_id` and never
    registers a client.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._signed_in: httpx2.Response | None = None

    async def _perform_authorization(self) -> httpx2.Request:
        async with self.httpx_client_factory() as http:
            self._signed_in = await self._sign_in_on_another_device(http)
        # The base flow sends the request returned here and passes its answer to
        # `_handle_token_response`. The tokens are already in hand, and a device code is good for
        # one exchange, so it sends a harmless request instead and is handed the tokens below.
        return httpx2.Request("GET", str(self.context.oauth_metadata.issuer))

    async def _handle_token_response(self, response: httpx2.Response) -> None:
        signed_in, self._signed_in = self._signed_in, None
        await super()._handle_token_response(signed_in or response)

    async def _sign_in_on_another_device(self, http: httpx2.AsyncClient) -> httpx2.Response:
        """Print the link and code, then return the token endpoint's answer once confirmed."""
        context = self.context
        client_id = context.client_info.client_id
        request = {"client_id": client_id, "scope": context.client_metadata.scope or ""}
        if context.should_include_resource_param(context.protocol_version):
            request["resource"] = context.get_resource_url()
        started = await http.post(await self._device_authorization_endpoint(http), data=request)
        if started.status_code != 200:
            raise OAuthTokenError(f"Device sign-in could not start ({started.status_code})")
        grant = started.json()
        link = grant.get("verification_uri_complete") or grant["verification_uri"]
        print(
            f"To sign in to LGND Geo, open {link} and confirm the code {grant['user_code']}.",
            flush=True,
        )

        poll = {"grant_type": _DEVICE_CODE_GRANT, "device_code": grant["device_code"]}
        poll["client_id"] = client_id
        if "resource" in request:
            poll["resource"] = request["resource"]  # RFC 8707 §2.2: also on the token request
        interval = grant.get("interval", 5)
        with anyio.fail_after(
            min(grant.get("expires_in", SIGN_IN_TIMEOUT_SECONDS), SIGN_IN_TIMEOUT_SECONDS)
        ):
            while True:
                await anyio.sleep(interval)
                response = await http.post(self._get_token_endpoint(), data=poll)
                if response.status_code == 200:
                    return response
                error = response.json().get("error")
                if error == "slow_down":
                    interval += 5
                elif error != "authorization_pending":
                    raise OAuthTokenError(f"Device sign-in failed: {error}")

    async def _device_authorization_endpoint(self, http: httpx2.AsyncClient) -> str:
        """The `device_authorization_endpoint` of the authorization server's metadata."""
        for url in build_oauth_authorization_server_metadata_discovery_urls(
            self.context.auth_server_url, self.context.server_url
        ):
            response = await http.send(create_oauth_metadata_request(url))
            if response.status_code == 200:
                endpoint = response.json().get("device_authorization_endpoint")
                if isinstance(endpoint, str):
                    return endpoint
        raise OAuthTokenError("The authorization server does not offer device sign-in")


def _signs_in_on_another_device() -> bool:
    """Whether to sign in on another device: `LGND_GEO_SIGN_IN`, else only in Colab."""
    choice = os.environ.get(SIGN_IN_ENVIRONMENT_VARIABLE)
    if choice not in (None, "browser", "device"):
        raise ValueError(
            f"{SIGN_IN_ENVIRONMENT_VARIABLE} must be 'browser' or 'device', not {choice!r}"
        )
    return choice == "device" or (choice is None and "google.colab" in sys.modules)


def auth(
    url: str | None = None, *, token_directory: Path | None = None
) -> OAuth | ClientCredentialsOAuthProvider:
    """Return the sign-in to LGND Geo's MCP server.

    With `LGND_GEO_CLIENT_ID` and `LGND_GEO_CLIENT_SECRET` set, this signs in as that machine
    user: the OAuth client-credentials grant, with no browser, for scripts, CI and hosted
    notebooks. Its tokens are kept in memory; a new one is a single request.

    Otherwise this is the OAuth 2.1 sign-in: the first run opens the browser, and the tokens are
    stored in `token_directory`, so later runs sign in without it. In Colab, or with
    `LGND_GEO_SIGN_IN=device`, the first run instead prints a link and a code to confirm in any
    browser, since the notebook's own browser cannot reach it.

    Args:
        url: The MCP server URL. Defaults to `server_url()`.
        token_directory: Where browser sign-in tokens are stored. Defaults to
            `default_token_directory()`.

    Returns:
        A FastMCP `OAuth` or `ClientCredentialsOAuthProvider`: an `httpx2.Auth` that any MCP
        client on the `mcp` 2 SDK can sign in with.

    Raises:
        ValueError: Only one of `LGND_GEO_CLIENT_ID` and `LGND_GEO_CLIENT_SECRET` is set,
            `LGND_GEO_SIGN_IN` is neither `browser` nor `device`, or a device sign-in has no
            client for the server.
    """
    client_id = os.environ.get(CLIENT_ID_ENVIRONMENT_VARIABLE)
    client_secret = os.environ.get(CLIENT_SECRET_ENVIRONMENT_VARIABLE)
    if client_id and client_secret:
        return ClientCredentialsOAuthProvider(
            server_url(url), client_id=client_id, client_secret=client_secret
        )
    if client_id or client_secret:
        raise ValueError(
            f"set both {CLIENT_ID_ENVIRONMENT_VARIABLE} and {CLIENT_SECRET_ENVIRONMENT_VARIABLE} "
            "to sign in as a machine user, or neither to sign in through the browser"
        )
    mcp_url = server_url(url)
    sign_in, fixed_client = _OAuth, {}
    if _signs_in_on_another_device():
        device_client_id = os.environ.get(DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE)
        device_client_id = device_client_id or _DEVICE_CLIENT_IDS.get(mcp_url)
        if not device_client_id:
            raise ValueError(
                f"{mcp_url} has no device sign-in; set {DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE} "
                "to the OAuth client to use"
            )
        sign_in, fixed_client = _DeviceOAuth, {"client_id": device_client_id}
    directory = token_directory or default_token_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return sign_in(
        mcp_url=mcp_url,
        **fixed_client,
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
        first time unless a machine user's credentials are set; see `auth`.

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
