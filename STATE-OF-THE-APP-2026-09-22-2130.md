# State of the App — 2026-09-22 21:30 PT

Written by Claude Desktop at the close of P11 EA-9 live setup. The previous note
(`docs/archive/state/STATE-OF-THE-APP-2026-09-21-2300.md`) covers everything before P11 went live.

## Where main is

- Version **0.64.0** (`pyproject.toml`, `neurosearch/__init__.py`, `web/js/state.js`, `index.html` meta).
  Extension unchanged (1.9.6).
- Full suite **2,471 passed, 0 failed** (Cowork Linux VM, temp DBs). `neurosearch release-check` was **not** run
  (heavyweight, Mac-side).
- Publishing works from the Cowork VM with the committed publisher (`tools/publish_request.py` → PASS receipts).

## P11 — external AI access is live for Kyle

Kyle's own ChatGPT (Pro, Developer mode) reads and writes his Neuro projects:

```
ChatGPT → Secure MCP Tunnel (tunnel_6ab30bc…, LaunchAgent com.neurosearch.tunnel) → Neuro /ext/mcp/
sign-in: WorkOS AuthKit (staging), CIMD client https://chatgpt.com/oauth/<id>/client.json
token checks in Neuro: signature · issuer · aud = tunnel-service URL (NEUROSEARCH_OAUTH_AUDIENCE) · expiry
link: owner approves the pending sign-in in Neuro (banner) — ChatGPT blocks pasted nsi_ codes
```

Measured live (EA-9A–F): read (list/open/consult), explicit write → committed fact quoting the user, inferred
write → held in "Waiting for your review", inferred project → `confirm_project`, late save from a normal chat,
catch-up read in a fresh chat, file attached before Neuro was mentioned → original kept (after S83). Pro allowed
writes, so `account_tier_write_unavailable` does not apply to Kyle.

Fixed from live failures today: owner-approved sign-ins (S82); strict `openai/fileParams` schema, tolerant
`client_capabilities`, descriptive (not directive) tool text that ChatGPT no longer flags as "Suspicious
Instruction", account-level approval banner, Settings auto-refresh (S83).

## Not done / open

- **Gio (9G) not started.** For a personal ChatGPT account the tunnel is associated via that person's personal
  Platform organization (OpenAI docs). Plan: add Gio's `org-…` ID to the tunnel; if that is refused, a second
  tunnel in Gio's org served by a second tunnel-client profile on Kyle's Mac. Gio's guide: Claude Doc
  "Connect your ChatGPT to Neuro".
- **Neuro server auto-start** is written (`tools/server_agent.py`, `com.neurosearch.server`,
  `tools/install_server_agent.sh`) but **not installed** — needs one run on the Mac.
- Runtime key for the tunnel (`CONTROL_PLANE_API_KEY`) never expires and appeared in a chat; rotate to a
  90-day key.
- WorkOS is the **staging** environment; fine for two users.
- The Mac must be awake for collaborators to reach Neuro.
