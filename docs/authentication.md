# Authentication

## Browser sign-in

The first connection opens the browser to sign in. The tokens are stored in
`~/.config/lgnd_geo_sdk/tokens`, so later runs connect without it. Pass `token_directory=...` to
keep them elsewhere.

## Machine users

Scripts, CI and hosted notebooks such as Colab, where no browser can complete the sign-in, sign in
as a machine user instead. Set its credentials in the environment and connect as usual:

```bash
export LGND_GEO_CLIENT_ID=client_...
export LGND_GEO_CLIENT_SECRET=...
```

With both set, `auth()`, `client()` and the framework adapters use the OAuth client-credentials
grant and never open the browser. Tokens are kept in memory and fetched again when they expire.
Contact LGND for a machine user's credentials.

In Colab, keep them in the notebook's secrets and copy them into the environment first:

```python
import os
from google.colab import userdata

os.environ["LGND_GEO_CLIENT_ID"] = userdata.get("LGND_GEO_CLIENT_ID")
os.environ["LGND_GEO_CLIENT_SECRET"] = userdata.get("LGND_GEO_CLIENT_SECRET")
```

## Server

The server is LGND Geo's MCP server, `https://geo.lgnd.ai/mcp`, unless the `LGND_GEO_MCP_URL`
environment variable or `url=...` names another.
