"""A local MCP server behind OAuth, to try Settings' sign-in against without a real account.

    python tools/mcp_oauth_server.py [--port 59322] [--token-seconds 60]

It is the official SDK's own authorization server (metadata discovery, dynamic
client registration, PKCE, refresh, revocation) in front of one tool. The
consent page has an Allow and a Deny button. GET /stats counts registrations,
consents, tokens issued, refreshes, revocations and calls.
"""
from __future__ import annotations

import argparse
import html
import secrets
import time

import uvicorn
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken,
                                      construct_redirect_uri)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions, AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

STATS = {"registered": 0, "consented": 0, "denied": 0, "issued": 0, "refreshed": 0, "revoked": 0, "calls": 0}


class Provider:
    """Everything in memory: clients, pending consents, codes and tokens."""

    def __init__(self, base: str, token_seconds: int) -> None:
        self.base, self.token_seconds = base, token_seconds
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, tuple[str, AuthorizationParams]] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access: dict[str, AccessToken] = {}
        self.refresh: dict[str, RefreshToken] = {}

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        STATS["registered"] += 1
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params):
        ident = secrets.token_urlsafe(16)
        self.pending[ident] = (client.client_id, params)
        return f"{self.base}/consent?id={ident}"

    def approve(self, ident: str) -> str:
        client_id, params = self.pending.pop(ident)
        code = secrets.token_urlsafe(24)
        self.codes[code] = AuthorizationCode(
            code=code, scopes=params.scopes or ["tools"], expires_at=time.time() + 300, client_id=client_id,
            code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly, resource=params.resource)
        STATS["consented"] += 1
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    def deny(self, ident: str) -> str:
        _, params = self.pending.pop(ident)
        STATS["denied"] += 1
        return construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state)

    async def load_authorization_code(self, client, authorization_code):
        return self.codes.get(authorization_code)

    def _issue(self, client_id: str, scopes: list, resource) -> OAuthToken:
        access, refresh = "at_" + secrets.token_urlsafe(24), "rt_" + secrets.token_urlsafe(24)
        self.access[access] = AccessToken(token=access, client_id=client_id, scopes=scopes,
                                          expires_at=int(time.time()) + self.token_seconds, resource=resource)
        self.refresh[refresh] = RefreshToken(token=refresh, client_id=client_id, scopes=scopes, resource=resource)
        STATS["issued"] += 1
        return OAuthToken(access_token=access, expires_in=self.token_seconds, scope=" ".join(scopes),
                          refresh_token=refresh)

    async def exchange_authorization_code(self, client, authorization_code):
        self.codes.pop(authorization_code.code, None)
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token):
        found = self.refresh.get(refresh_token)
        return found if found and found.client_id == client.client_id else None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        self.refresh.pop(refresh_token.token, None)
        STATS["refreshed"] += 1
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token):
        found = self.access.get(token)
        if found and found.expires_at and found.expires_at < time.time():
            return None
        return found

    async def revoke_token(self, token):
        # Revoking either one ends the whole grant of that client.
        STATS["revoked"] += 1
        for table in (self.access, self.refresh):
            for key in [k for k, v in table.items() if v.client_id == token.client_id]:
                del table[key]


def build(port: int, token_seconds: int) -> MCPServer:
    base = f"http://127.0.0.1:{port}"
    provider = Provider(base, token_seconds)
    server = MCPServer(
        "oauth-check", instructions="A test server that needs a sign-in.", auth_server_provider=provider,
        auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp", validate_token_resource=False,
                          client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["tools"],
                                                                                default_scopes=["tools"]),
                          revocation_options=RevocationOptions(enabled=True), required_scopes=["tools"]))

    @server.tool(annotations={"readOnlyHint": True})
    def whoami() -> str:
        """Says that the caller is signed in."""
        STATS["calls"] += 1
        return "signed in to oauth-check"

    @server.custom_route("/consent", methods=["GET"])
    async def consent(request: Request):
        ident = request.query_params.get("id", "")
        if ident not in provider.pending:
            return HTMLResponse("<p>This request is not pending.</p>", status_code=400)
        client = provider.clients[provider.pending[ident][0]]
        name = html.escape(client.client_name or client.client_id)
        return HTMLResponse(
            f"<!doctype html><title>oauth-check</title><h1>Allow {name}?</h1>"
            f'<form method="post" action="/consent"><input type="hidden" name="id" value="{ident}">'
            '<button name="answer" value="allow" id="allow">Allow</button> '
            '<button name="answer" value="deny" id="deny">Deny</button></form>')

    @server.custom_route("/consent", methods=["POST"])
    async def answer(request: Request):
        form = await request.form()
        ident = str(form.get("id", ""))
        if ident not in provider.pending:
            return HTMLResponse("<p>This request is not pending.</p>", status_code=400)
        target = provider.approve(ident) if form.get("answer") == "allow" else provider.deny(ident)
        return RedirectResponse(target, status_code=302)

    @server.custom_route("/stats", methods=["GET"])
    async def stats(request: Request):
        return JSONResponse(STATS)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=59322)
    parser.add_argument("--token-seconds", type=int, default=60)
    args = parser.parse_args()
    app = build(args.port, args.token_seconds).streamable_http_app()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
