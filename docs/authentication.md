# Authentication

`auth()`, `client()` and the framework adapters sign in with one of four methods, chosen from the
environment in this order.

| Method | Set | Signs in as |
| --- | --- | --- |
| API key | `LGND_GEO_API_KEY` | the person who created the key |
| Machine user | `LGND_GEO_CLIENT_ID` and `LGND_GEO_CLIENT_SECRET` | the machine user |
| Device sign-in | `LGND_GEO_SIGN_IN=device` | the person who confirms the code |
| Browser sign-in | nothing (the default) | the person who signs in |

Setting an API key together with a machine user's credentials is an error.

## API key

The key is sent with every request.

## Machine user

The SDK uses the OAuth client-credentials grant. It keeps tokens in memory and fetches a new one
when they expire.

## Device sign-in

The first connection prints a link and a code. Open the link in any browser, sign in and confirm
the code. A server other than LGND Geo's needs `LGND_GEO_DEVICE_CLIENT_ID`, the OAuth client its
device sign-in uses.

## Browser sign-in

The first connection opens the browser to sign in. `LGND_GEO_SIGN_IN=browser` selects it
explicitly.

The two person sign-ins store their tokens in `~/.config/lgnd_geo_sdk/tokens`, so later runs
connect without signing in again. Pass `token_directory=...` to keep them elsewhere.

## Server

The server is LGND Geo's MCP server, `https://geo.lgnd.ai/mcp`, unless the `LGND_GEO_MCP_URL`
environment variable or `url=...` names another.
