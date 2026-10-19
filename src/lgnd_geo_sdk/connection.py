"""The connection to LGND Geo's MCP server: the server, the sign-in and a client."""

import os
import sys
from collections.abc import AsyncGenerator
from contextlib import aclosing
from pathlib import Path

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
DEFAULT_URL = "https://geo.lgnd.ai/mcp"
"""The server URL used when none is given: LGND Geo's MCP server."""
SIGN_IN_TIMEOUT_SECONDS = 300.0
"""How long connecting waits for the browser or device sign-in to finish."""
SIGN_IN_ENVIRONMENT_VARIABLE = "LGND_GEO_SIGN_IN"
"""The environment variable that picks the sign-in: `browser` or `device`."""
DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE = "LGND_GEO_DEVICE_CLIENT_ID"
"""The environment variable naming the OAuth client a device sign-in uses, for another server."""
CLIENT_ID_ENVIRONMENT_VARIABLE = "LGND_GEO_CLIENT_ID"
"""The environment variable holding a machine user's client id."""
CLIENT_SECRET_ENVIRONMENT_VARIABLE = "LGND_GEO_CLIENT_SECRET"
"""The environment variable holding a machine user's client secret."""

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

    _signed_in: httpx2.Response | None = None

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        """`_OAuth`'s flow, answering the device sign-in's token request with its own response.

        The base flow sends the token request `_perform_authorization` returns and processes the
        answer. A device code is good for one exchange, which the polling has already made, so
        that request is not sent again: its response goes straight back into the flow.
        """
        async with aclosing(super().async_auth_flow(request)) as flow:
            response = None
            while True:
                try:
                    outgoing = await flow.asend(response)
                except StopAsyncIteration:
                    return
                if self._signed_in is not None and outgoing is self._signed_in.request:
                    response, self._signed_in = self._signed_in, None
                else:
                    response = yield outgoing

    async def _perform_authorization(self) -> httpx2.Request:
        async with self.httpx_client_factory() as http:
            grant = await self._start_device_sign_in(http)
            link = grant.get("verification_uri_complete") or grant["verification_uri"]
            print(
                f"To sign in to LGND Geo, open {link} and confirm the code {grant['user_code']}.",
                flush=True,
            )
            self._signed_in = await self._poll_until_confirmed(http, grant)
        return self._signed_in.request

    async def _start_device_sign_in(self, http: httpx2.AsyncClient) -> dict:
        """The device authorization response: the codes, the link and how often to poll."""
        context = self.context
        start = {"client_id": context.client_info.client_id}
        if context.client_metadata.scope:
            start["scope"] = context.client_metadata.scope
        if context.should_include_resource_param(context.protocol_version):
            start["resource"] = context.get_resource_url()
        response = await http.post(await self._device_authorization_endpoint(http), data=start)
        if response.status_code != 200:
            raise OAuthTokenError(f"Device sign-in could not start ({response.status_code})")
        return response.json()

    async def _poll_until_confirmed(self, http: httpx2.AsyncClient, grant: dict) -> httpx2.Response:
        """The token endpoint's answer once the person confirms the code (RFC 8628 §3.4-3.5)."""
        poll = {
            "grant_type": _DEVICE_CODE_GRANT,
            "device_code": grant["device_code"],
            "client_id": self.context.client_info.client_id,
        }
        interval = grant.get("interval", 5)
        timeout = min(grant.get("expires_in", SIGN_IN_TIMEOUT_SECONDS), SIGN_IN_TIMEOUT_SECONDS)
        with anyio.move_on_after(timeout):
            while True:
                await anyio.sleep(interval)
                try:
                    response = await http.post(self._get_token_endpoint(), data=poll)
                    if response.status_code == 200:
                        return response
                    body = response.json()
                except (httpx2.HTTPError, ValueError):
                    continue  # A dropped request or an unreadable answer: poll again.
                error = body.get("error") if isinstance(body, dict) else None
                if error == "slow_down":
                    interval += 5
                elif error not in (None, "authorization_pending"):
                    raise OAuthTokenError(f"Device sign-in failed: {error}")
        # The authorization server answers a denied code as still pending, until it expires.
        raise OAuthTokenError("Device sign-in was not confirmed in time, or was denied")

    async def _device_authorization_endpoint(self, http: httpx2.AsyncClient) -> str:
        """The `device_authorization_endpoint` of the authorization server's metadata.

        Fetched again because the `mcp` SDK's metadata model, which the flow already holds, drops
        this field.
        """
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


def _machine_user(mcp_url: str) -> ClientCredentialsOAuthProvider | None:
    """The machine user's sign-in, if `LGND_GEO_CLIENT_ID` and `LGND_GEO_CLIENT_SECRET` are set."""
    client_id = os.environ.get(CLIENT_ID_ENVIRONMENT_VARIABLE)
    client_secret = os.environ.get(CLIENT_SECRET_ENVIRONMENT_VARIABLE)
    if client_id and client_secret:
        return ClientCredentialsOAuthProvider(
            mcp_url, client_id=client_id, client_secret=client_secret
        )
    if client_id or client_secret:
        raise ValueError(
            f"set both {CLIENT_ID_ENVIRONMENT_VARIABLE} and {CLIENT_SECRET_ENVIRONMENT_VARIABLE} "
            "to sign in as a machine user, or neither to sign in as a person"
        )
    return None


def _device_client_id(mcp_url: str) -> str:
    """The OAuth client a device sign-in to `mcp_url` uses: the environment's, or LGND's."""
    configured = os.environ.get(DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE)
    client_id = configured or _DEVICE_CLIENT_IDS.get(mcp_url)
    if not client_id:
        raise ValueError(
            f"{mcp_url} has no device sign-in; set {DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE} "
            "to the OAuth client to use"
        )
    return client_id


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
        token_directory: Where a person's sign-in tokens are stored. Defaults to
            `default_token_directory()`.

    Returns:
        A FastMCP `OAuth` or `ClientCredentialsOAuthProvider`: an `httpx2.Auth` that any MCP
        client on the `mcp` 2 SDK can sign in with.

    Raises:
        ValueError: Only one of `LGND_GEO_CLIENT_ID` and `LGND_GEO_CLIENT_SECRET` is set,
            `LGND_GEO_SIGN_IN` is neither `browser` nor `device`, or a device sign-in has no
            client for the server.
    """
    mcp_url = server_url(url)
    if machine_user := _machine_user(mcp_url):
        return machine_user
    # The browser sign-in registers a client of its own (`client_id=None`); the device sign-in
    # uses the server's fixed one.
    device_client_id = _device_client_id(mcp_url) if _signs_in_on_another_device() else None
    directory = token_directory or default_token_directory()
    if device_client_id:
        # Apart from the browser sign-in's: each stores a client and tokens the other cannot use.
        directory = directory / f"device-{device_client_id}"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return (_DeviceOAuth if device_client_id else _OAuth)(
        mcp_url=mcp_url,
        client_id=device_client_id,
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
        The client. It connects when entered (`async with`), signing in the first time; see
        `auth`.

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
        # A person's sign-in runs inside the connect handshake.
        init_timeout=SIGN_IN_TIMEOUT_SECONDS,
    )
