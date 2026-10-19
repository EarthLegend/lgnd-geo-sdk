"""The core: which server, the sign-in, where its tokens are kept, and the client."""

import sys
import types

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.auth import ClientCredentialsOAuthProvider, OAuth
from key_value.aio.stores.filetree import FileTreeStore
from mcp.client.auth import OAuthTokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from lgnd_geo_sdk import (
    DEFAULT_URL,
    auth,
    client,
    default_token_directory,
    server_url,
)
from lgnd_geo_sdk.connection import SIGN_IN_TIMEOUT_SECONDS, _DeviceOAuth


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
                    200,
                    json={
                        "resource": MCP_URL,
                        "authorization_servers": [AUTHORIZATION_SERVER],
                        # As LGND Geo advertises them: a person's scopes.
                        "scopes_supported": ["openid", "profile", "email", "offline_access"],
                    },
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


def test_a_machine_users_credentials_sign_in_without_the_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("LGND_GEO_CLIENT_ID", "client_m2m")
    monkeypatch.setenv("LGND_GEO_CLIENT_SECRET", "secret")

    credential = auth(MCP_URL, token_directory=tmp_path / "tokens")

    assert isinstance(credential, ClientCredentialsOAuthProvider)
    assert not (tmp_path / "tokens").exists()


@pytest.mark.parametrize("name", ["LGND_GEO_CLIENT_ID", "LGND_GEO_CLIENT_SECRET"])
def test_half_a_machine_users_credentials_is_refused(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "set")

    with pytest.raises(ValueError, match="set both"):
        auth(token_directory=tmp_path)


async def test_a_machine_user_gets_its_token_at_the_authorization_servers_token_endpoint(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LGND_GEO_CLIENT_ID", "client_m2m")
    monkeypatch.setenv("LGND_GEO_CLIENT_SECRET", "secret")
    sent: list[httpx2.Request] = []

    credential = auth(MCP_URL, token_directory=tmp_path)
    async with httpx2.AsyncClient(transport=sign_in_server(sent), auth=credential) as http:
        response = await http.get(MCP_URL)

    token_request = next(r for r in sent if r.method == "POST")
    assert response.status_code == 200
    assert str(token_request.url) == TOKEN_ENDPOINT
    assert b"grant_type=client_credentials" in token_request.content
    assert b"scope" not in token_request.content  # a person's scopes are refused to a machine
    assert sent[-1].headers["Authorization"] == "Bearer fresh"


DEVICE_ENDPOINT = f"{AUTHORIZATION_SERVER}/oauth2/device_authorization"


def device_sign_in_server(sent: list[httpx2.Request], *, pending: int) -> httpx2.MockTransport:
    """Return the servers for a device sign-in that the person confirms after `pending` polls."""
    polls = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal polls
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
                        "registration_endpoint": f"{AUTHORIZATION_SERVER}/oauth2/register",
                        "device_authorization_endpoint": DEVICE_ENDPOINT,
                    },
                )
            case "https://auth.test/oauth2/register":
                return httpx2.Response(
                    201,
                    json={
                        "client_id": "client_dcr",
                        "redirect_uris": ["http://localhost:1/callback"],
                        "token_endpoint_auth_method": "none",
                    },
                )
            case "https://auth.test/oauth2/device_authorization":
                return httpx2.Response(
                    200,
                    json={
                        "device_code": "device-secret",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": f"{AUTHORIZATION_SERVER}/device",
                        "verification_uri_complete": f"{AUTHORIZATION_SERVER}/device?user_code=ABCD-EFGH",
                        "expires_in": 300,
                        "interval": 0,
                    },
                )
            case "https://auth.test/oauth2/token":
                polls += 1
                if polls == 1:
                    return httpx2.Response(503, text="upstream unavailable")
                if polls == 2:
                    return httpx2.Response(400, json={"error": "slow_down"})
                if polls <= pending:
                    return httpx2.Response(400, json={"error": "authorization_pending"})
                return httpx2.Response(
                    200,
                    json={
                        "access_token": "device-token",
                        "refresh_token": "refresh",
                        "token_type": "Bearer",
                        "expires_in": 300,
                    },
                )
            case "https://geo.test/mcp":
                return httpx2.Response(200 if "Authorization" in request.headers else 401)
        raise httpx2.ConnectError(f"unexpected request to {request.url}", request=request)

    return httpx2.MockTransport(respond)


async def test_a_device_sign_in_prints_a_link_and_polls_through_an_outage_until_confirmed(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("lgnd_geo_sdk.connection._SLOW_DOWN_SECONDS", 0)
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "device")
    monkeypatch.setenv("LGND_GEO_DEVICE_CLIENT_ID", "client_sdk")
    sent: list[httpx2.Request] = []
    transport = device_sign_in_server(sent, pending=4)
    credential = auth(MCP_URL, token_directory=tmp_path)
    credential.httpx_client_factory = lambda: httpx2.AsyncClient(transport=transport)

    async with httpx2.AsyncClient(transport=transport, auth=credential) as http:
        response = await http.get(MCP_URL)

    started = next(r for r in sent if str(r.url) == DEVICE_ENDPOINT)
    polls = [r for r in sent if str(r.url) == TOKEN_ENDPOINT]
    assert response.status_code == 200
    assert sent[-1].headers["Authorization"] == "Bearer device-token"
    assert b"resource=https%3A%2F%2Fgeo.test%2Fmcp" in started.content
    assert len(polls) == 5  # an unreadable 503, slow_down, two pending, then the tokens
    assert all(b"device_code=device-secret" in poll.content for poll in polls)
    assert all(b"client_id=client_sdk" in r.content for r in [started, *polls])
    assert not [r for r in sent if r.url.path == "/oauth2/register"]
    # No request after the confirmed poll but the retried call: the poll's answer is the token.
    assert [str(r.url) for r in sent[-2:]] == [TOKEN_ENDPOINT, MCP_URL]
    assert "https://auth.test/device?user_code=ABCD-EFGH" in capsys.readouterr().out
    assert (await credential.token_storage_adapter.get_tokens()).access_token == "device-token"


def test_colab_signs_in_on_another_device(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    monkeypatch.setenv("LGND_GEO_DEVICE_CLIENT_ID", "client_sdk")

    assert isinstance(auth(token_directory=tmp_path), _DeviceOAuth)


def test_the_browser_sign_in_can_be_chosen_in_colab(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "browser")

    assert not isinstance(auth(token_directory=tmp_path), _DeviceOAuth)


def test_an_unknown_sign_in_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "magic")

    with pytest.raises(ValueError, match="LGND_GEO_SIGN_IN"):
        auth(token_directory=tmp_path)


def test_a_device_sign_in_needs_a_client_for_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "device")

    with pytest.raises(ValueError, match="LGND_GEO_DEVICE_CLIENT_ID"):
        auth("https://elsewhere.test/mcp", token_directory=tmp_path)


def test_the_default_server_has_a_device_sign_in(tmp_path, monkeypatch):
    monkeypatch.delenv("LGND_GEO_MCP_URL", raising=False)
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "device")

    assert isinstance(auth(token_directory=tmp_path), _DeviceOAuth)


async def test_the_browser_and_device_sign_ins_keep_their_credentials_apart(tmp_path, monkeypatch):
    browser = auth(MCP_URL, token_directory=tmp_path)
    await browser.token_storage_adapter.set_client_info(
        OAuthClientInformationFull(
            client_id="client_dcr",
            redirect_uris=["http://localhost:1/callback"],
            token_endpoint_auth_method="none",
        )
    )
    await browser.token_storage_adapter.set_tokens(OAuthToken(access_token="browser"))
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "device")
    monkeypatch.setenv("LGND_GEO_DEVICE_CLIENT_ID", "client_sdk")

    device = auth(MCP_URL, token_directory=tmp_path)
    await device._initialize()  # stores its fixed client
    await device.token_storage_adapter.set_tokens(OAuthToken(access_token="device"))

    assert device.context.current_tokens is None  # not the browser sign-in's
    assert (await device.token_storage_adapter.get_client_info()).client_id == "client_sdk"
    assert (await browser.token_storage_adapter.get_tokens()).access_token == "browser"
    assert (await browser.token_storage_adapter.get_client_info()).client_id == "client_dcr"


@pytest.mark.parametrize("sign_in", ["browser", "device"])
def test_the_token_directory_may_be_a_string(tmp_path, monkeypatch, sign_in):
    # As a notebook passes it.
    monkeypatch.setenv("LGND_GEO_SIGN_IN", sign_in)
    monkeypatch.setenv("LGND_GEO_DEVICE_CLIENT_ID", "client_sdk")

    auth(MCP_URL, token_directory=str(tmp_path / "tokens"))

    assert (tmp_path / "tokens").is_dir()


async def test_a_denied_device_sign_in_stops_polling(tmp_path, monkeypatch):
    monkeypatch.setenv("LGND_GEO_SIGN_IN", "device")
    monkeypatch.setenv("LGND_GEO_DEVICE_CLIENT_ID", "client_sdk")
    credential = auth(MCP_URL, token_directory=tmp_path)
    polls: list[httpx2.Request] = []

    def deny(request: httpx2.Request) -> httpx2.Response:
        polls.append(request)
        return httpx2.Response(400, json={"error": "access_denied"})

    await credential._initialize()
    credential._get_token_endpoint = lambda: TOKEN_ENDPOINT
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(deny)) as http:
        with pytest.raises(OAuthTokenError, match="access_denied"):
            await credential._poll_until_confirmed(
                http, {"device_code": "device-secret", "interval": 0, "expires_in": 60}
            )

    assert len(polls) == 1
