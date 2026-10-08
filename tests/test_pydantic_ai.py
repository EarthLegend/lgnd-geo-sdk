"""The Pydantic AI adapter: LGND Geo's MCP server as a toolset."""

import importlib
import sys

import pytest
from fastmcp.client.auth import OAuth

from lgnd_geo_sdk import DEFAULT_URL
from lgnd_geo_sdk.connection import SIGN_IN_TIMEOUT_SECONDS
from lgnd_geo_sdk.pydantic_ai import toolset


def test_the_toolset_is_lgnd_geos_server(tmp_path, monkeypatch):
    monkeypatch.delenv("LGND_GEO_MCP_URL", raising=False)

    assert toolset(token_directory=tmp_path).client.transport.url == DEFAULT_URL


def test_the_toolset_signs_in_through_the_browser(tmp_path):
    assert isinstance(toolset(token_directory=tmp_path).client.transport.auth, OAuth)


def test_the_toolset_passes_the_servers_instructions_to_the_model(tmp_path):
    assert toolset(token_directory=tmp_path).include_instructions is True


def test_connecting_waits_for_the_browser_sign_in(tmp_path):
    # The sign-in happens during the MCP handshake; Pydantic AI's 5 s default cut it off.
    assert toolset(token_directory=tmp_path).client._init_timeout == SIGN_IN_TIMEOUT_SECONDS


def test_without_the_extra_importing_the_adapter_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "pydantic_ai.mcp", None)
    monkeypatch.delitem(sys.modules, "lgnd_geo_sdk.pydantic_ai")

    with pytest.raises(ImportError, match=r"lgnd-geo-sdk\[pydantic-ai\]"):
        importlib.import_module("lgnd_geo_sdk.pydantic_ai")
