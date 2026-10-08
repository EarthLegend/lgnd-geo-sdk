# Authentication

## Browser sign-in

The first connection opens the browser to sign in. The tokens are stored in
`~/.config/lgnd_geo_sdk/tokens`, so later runs connect without it. Pass `token_directory=...` to
keep them elsewhere.

## Server

The server is LGND Geo's MCP server, `https://geo.lgnd.ai/mcp`, unless the `LGND_GEO_MCP_URL`
environment variable or `url=...` names another.
