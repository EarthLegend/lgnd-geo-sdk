"""The Python SDK for LGND Geo.

The core here signs in and connects to LGND Geo's MCP server; it needs no agent framework.
A framework's adapter is a submodule named after it, installed with the extra of the same name:
`lgnd_geo_sdk.pydantic_ai.toolset()`, with `lgnd-geo-sdk[pydantic-ai]`.

To call the tools from code, without an agent:

```python
from lgnd_geo_sdk import client

async with client() as geo:
    result = await geo.call_tool("user_identity_get", {})
```
"""

from lgnd_geo_sdk.connection import (
    API_KEY_ENVIRONMENT_VARIABLE,
    CLIENT_ID_ENVIRONMENT_VARIABLE,
    CLIENT_SECRET_ENVIRONMENT_VARIABLE,
    DEFAULT_URL,
    DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE,
    SIGN_IN_ENVIRONMENT_VARIABLE,
    URL_ENVIRONMENT_VARIABLE,
    auth,
    client,
    default_token_directory,
    server_url,
)

__all__ = [
    "API_KEY_ENVIRONMENT_VARIABLE",
    "CLIENT_ID_ENVIRONMENT_VARIABLE",
    "CLIENT_SECRET_ENVIRONMENT_VARIABLE",
    "DEFAULT_URL",
    "DEVICE_CLIENT_ID_ENVIRONMENT_VARIABLE",
    "SIGN_IN_ENVIRONMENT_VARIABLE",
    "URL_ENVIRONMENT_VARIABLE",
    "auth",
    "client",
    "default_token_directory",
    "server_url",
]
