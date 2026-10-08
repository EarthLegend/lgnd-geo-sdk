"""The core: which server, the sign-in, where its tokens are kept, and the client."""

import httpx2
from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import FileTreeStore
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from lgnd_geo_sdk import (
    DEFAULT_URL,
    auth,
    client,
    default_token_directory,
    server_url,
)
from lgnd_geo_sdk.connection import SIGN_IN_TIMEOUT_SECONDS


def test_the_default_server_is_lgnd_geo(monkeypatch):
    monkeypatch.delenv("LGND_GEO_MCP_URL", raising=False)

    assert server_url() == DEFAULT_URL


def test_the_environment_names_another_server(monkeypatch):
    monkeypatch.setenv("LGND_GEO_MCP_URL", "https://other.test/mcp")

    assert server_url() == "https://other.test/mcp"


def test_a_url_given_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("LGND_GEO_MCP_URL", "https://other.test/mcp")

    assert server_url("https://given.test/mcp") == "https://given.test/mcp"


def test_the_sign_in_is_for_the_default_server(tmp_path, monkeypatch):
    monkeypatch.delenv("LGND_GEO_MCP_URL", raising=False)

    credential = auth(token_directory=tmp_path)

    assert isinstance(credential, OAuth)
    assert credential.mcp_url == DEFAULT_URL


def test_the_sign_in_redirect_comes_back_to_a_free_local_port_chosen_per_run(tmp_path):
    # RFC 8252: a loopback redirect uses whatever port is free, not a fixed one.
    credential = auth(token_directory=tmp_path)

    assert credential._callback_port is None
    assert credential.redirect_port > 0


def test_sign_in_tokens_are_stored_on_disk_in_the_token_directory(tmp_path):
    credential = auth(token_directory=tmp_path / "tokens")

    assert isinstance(credential._token_storage, FileTreeStore)
    assert (tmp_path / "tokens").is_dir()


def test_the_sign_in_is_for_the_server_the_environment_names(tmp_path, monkeypatch):
    monkeypatch.setenv("LGND_GEO_MCP_URL", "https://other.test/mcp")

    assert auth(token_directory=tmp_path).mcp_url == "https://other.test/mcp"


def test_the_default_token_directory_is_under_dot_config_in_the_home_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "/elsewhere")

    assert default_token_directory() == tmp_path / ".config" / "lgnd_geo_sdk" / "tokens"


async def test_tokens_keyed_by_the_server_url_can_be_stored_and_read_back(tmp_path):
    # FastMCP keys stored tokens by the server URL, whose slashes are not a file name.
    store = auth(token_directory=tmp_path)._token_storage

    await store.put(key=DEFAULT_URL, value={"access_token": "a"}, collection="mcp-oauth-token")

    assert await store.get(key=DEFAULT_URL, collection="mcp-oauth-token") == {"access_token": "a"}


def test_the_client_signs_in_to_the_server(tmp_path, monkeypatch):
    monkeypatch.delenv("LGND_GEO_MCP_URL", raising=False)

    geo = client(token_directory=tmp_path)

    assert isinstance(geo, Client)
    assert geo.transport.url == DEFAULT_URL
    assert isinstance(geo.transport.auth, OAuth)


def test_connecting_the_client_waits_for_the_browser_sign_in(tmp_path):
    # The sign-in happens during the MCP handshake; a short connect timeout cuts it off.
    assert client(token_directory=tmp_path)._init_timeout == SIGN_IN_TIMEOUT_SECONDS


# A sign-in server for the refresh tests: LGND Geo's MCP server names its authorization server in
# its metadata, and that server, on another host, issues the tokens.
MCP_URL = "https://geo.test/mcp"
AUTHORIZATION_SERVER = "https://auth.test"
TOKEN_ENDPOINT = f"{AUTHORIZATION_SERVER}/oauth2/token"


def sign_in_server(sent: list[httpx2.Request]) -> httpx2.MockTransport:
    """Return the servers, recording each request in `sent`."""

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        match str(request.url):
            case "https://geo.test/.well-known/oauth-protected-resource/mcp":
                return httpx2.Response(
                    200, json={"resource": MCP_URL, "authorization_servers": [AUTHORIZATION_SERVER]}
                )
            case "https://auth.test/.well-known/oauth-authorization-server":
                return httpx2.Response(
                    200,
                    json={
                        "issuer": AUTHORIZATION_SERVER,
                        "authorization_endpoint": f"{AUTHORIZATION_SERVER}/oauth2/authorize",
                        "token_endpoint": TOKEN_ENDPOINT,
                        "response_types_supported": ["code"],
                    },
                )
            case "https://auth.test/oauth2/token":
                return httpx2.Response(
                    200,
                    json={"access_token": "fresh", "token_type": "Bearer", "expires_in": 3600},
                )
            case "https://geo.test/mcp":
                return httpx2.Response(200 if "Authorization" in request.headers else 401)
        return httpx2.Response(405)

    return httpx2.MockTransport(respond)


async def signed_in_earlier(
    tmp_path, sent: list[httpx2.Request], *, expires_in: int, issuer: str = AUTHORIZATION_SERVER
) -> OAuth:
    """Return a sign-in whose tokens, stored by an earlier run, expire in `expires_in` seconds."""
    credential = auth(MCP_URL, token_directory=tmp_path)
    credential.httpx_client_factory = lambda: httpx2.AsyncClient(transport=sign_in_server(sent))
    storage = credential.token_storage_adapter
    await storage.set_client_info(
        OAuthClientInformationFull(
            client_id="lgnd-geo-sdk",
            redirect_uris=["http://localhost:1/callback"],
            token_endpoint_auth_method="none",
            issuer=issuer,
        )
    )
    await storage.set_tokens(
        OAuthToken(access_token="stale", refresh_token="refresh", expires_in=expires_in)
    )
    return credential


async def test_an_expired_sign_in_is_refreshed_at_the_authorization_servers_token_endpoint(
    tmp_path,
):
    sent: list[httpx2.Request] = []
    credential = await signed_in_earlier(tmp_path, sent, expires_in=-60)

    async with httpx2.AsyncClient(transport=sign_in_server(sent), auth=credential) as http:
        response = await http.get(MCP_URL)

    assert response.status_code == 200
    assert [str(r.url) for r in sent if r.method == "POST"] == [TOKEN_ENDPOINT]


async def test_a_sign_in_still_valid_is_used_without_looking_up_the_authorization_server(
    tmp_path,
):
    sent: list[httpx2.Request] = []
    credential = await signed_in_earlier(tmp_path, sent, expires_in=3600)

    async with httpx2.AsyncClient(transport=sign_in_server(sent), auth=credential) as http:
        await http.get(MCP_URL)

    assert [str(r.url) for r in sent] == [MCP_URL]
    assert sent[0].headers["Authorization"] == "Bearer stale"


async def test_a_sign_in_from_another_authorization_server_is_not_refreshed(tmp_path):
    # SEP-2352: tokens are bound to the server that issued them; they are not sent to another.
    sent: list[httpx2.Request] = []
    credential = await signed_in_earlier(
        tmp_path, sent, expires_in=-60, issuer="https://elsewhere.test"
    )

    await credential._initialize()

    assert credential.context.current_tokens is None
    assert credential.context.client_info is None
    assert not [r for r in sent if r.method == "POST"]
