# ChatGPT integration — verified status

**Bottom line: MinSync core does not depend on ChatGPT. On ChatGPT Free, custom MCP execution is not available; no workaround is implemented or attempted.**

## What official sources say (checked 2026-10)
- ChatGPT connects only to **remote HTTPS** MCP servers (Streamable HTTP/SSE) via Developer Mode / custom apps. A local stdio server on your PC is unreachable from ChatGPT's cloud — `https://developers.openai.com` (developer mode / MCP apps guides).
- **Secure MCP Tunnel** bridges a private/local MCP server to ChatGPT, but requires: a tunnel created in OpenAI Platform (needs an API account, `Tunnels Read+Use` runtime key; `Read+Manage` to create), the tunnel associated with the target ChatGPT workspace, **and** separately-granted ChatGPT developer-mode access. It does not lift plan limits — https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- Plan availability is restrictive and has shifted over time: OpenAI's help center currently documents full MCP (incl. write actions) for **Business / Enterprise / Edu** workspaces (admin-enabled); Pro is documented as read/fetch in developer mode; **Free (and per help center, Plus) cannot create custom MCP connectors** — https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt . Third-party summaries disagree with each other (rollout history), so treat the help center for your exact workspace as authoritative and verify in-product.
- The OpenAI API's MCP tool is a separate product surface, billed via API usage; it does not consume ChatGPT subscription limits and is not "ChatGPT integration".

## Therefore
- ❌ Not claimed: "ChatGPT Free gets unlimited MinSync tool calls" — false; do not rely on it.
- ❌ Not built: fake plugins, browser-session interception, unofficial endpoints, public unauthenticated exposure of MinSync.
- ✅ If you have Business/Enterprise/Edu + Platform access: run MinSync locally, create a Secure MCP Tunnel (`tunnel_id` + scoped runtime key, kept out of git/logs), create a developer-mode app in ChatGPT choosing **Tunnel** connection, run a tool-scan, then do a real end-to-end call (`health_check` → `run_command`) from ChatGPT before calling it working. Until that test is done in your workspace, status = unverified.
- ✅ Working alternative today: OpenCode (or any local MCP client) + your own model backend — see `MCP_SETUP.md`. This is a local client, not ChatGPT, and is not presented as such.
