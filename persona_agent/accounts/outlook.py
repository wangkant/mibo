"""Outlook, Hotmail and Microsoft 365 mail, read-only, through Microsoft Graph.

The person signs in with Microsoft in the system browser (OAuth with PKCE,
coming back to an http://localhost listener); where no browser can be opened
here, with a device code instead. personagent is a public client: there is no
secret, only the app's id, which the author registers (OUTLOOK_CLIENT_ID, or
PERSONAGENT_OUTLOOK_CLIENT_ID in the environment). It asks for Mail.Read and
offline_access only. The refresh token is kept in the home's .env and replaced
by the new one each time it is used; one unused for 90 days runs out.

A look reads the inbox's messages since the last look (the last two days the
first time), newest first, and keeps the same mail mailbox.py keeps:
newsletters and notifications (what Outlook sorts into Other, or what the
headers say was sent to many), personal letters too when the person allows
them in the mail settings. Nothing read here goes anywhere but the library on
this computer.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from .. import mailbox
from ..library import Item, item_id
from .base import AccountError, Connector, Loopback, iso, utc_iso

logger = logging.getLogger("agent.outlook")

# Registered by the author later; until then the page shows Outlook as coming soon.
OUTLOOK_CLIENT_ID = ""
CLIENT_ENV = "PERSONAGENT_OUTLOOK_CLIENT_ID"
TOKEN_ENV = "OUTLOOK_REFRESH_TOKEN"
# "common": personal Microsoft accounts and work or school ones alike.
AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
GRAPH = "https://graph.microsoft.com/v1.0"
# openid and profile only bring the account's name back with the tokens.
SCOPES = "openid profile offline_access https://graph.microsoft.com/Mail.Read"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
TIMEOUT_S = 20
SIGNIN_S = 10 * 60
LOOK_MAX = 40
PAGES_MAX = 5
KEEP_MAX = mailbox.KEEP_MAX
FIELDS = ("id,subject,from,receivedDateTime,bodyPreview,body,webLink,inferenceClassification,"
          "internetMessageHeaders")


def http() -> httpx.AsyncClient:
    """Tests put a client with a stand-in transport here."""
    return httpx.AsyncClient(timeout=TIMEOUT_S)


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(client_id: str, redirect: str, verifier: str, state: str) -> str:
    return f"{AUTHORITY}/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect, "response_mode": "query",
        "scope": SCOPES, "state": state, "code_challenge": challenge(verifier),
        "code_challenge_method": "S256", "prompt": "select_account"})


def account_name(id_token: str) -> str:
    """Who signed in, from the id token's claims; it came straight from Microsoft, so it is not checked."""
    try:
        part = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return ""
    return str(claims.get("preferred_username") or claims.get("email") or claims.get("name") or "")[:254]


async def token_request(data: dict) -> tuple[int, dict]:
    try:
        async with http() as client:
            answer = await client.post(f"{AUTHORITY}/token", data=data)
    except httpx.HTTPError:
        raise AccountError("outlook_unreachable") from None
    try:
        body = answer.json()
    except ValueError:
        body = {}
    return answer.status_code, body if isinstance(body, dict) else {}


def refusal(error: str) -> str:
    """Microsoft's error name as one of ours."""
    if error in ("access_denied", "authorization_declined", "consent_required", "interaction_required"):
        return "outlook_denied"
    if error in ("expired_token", "invalid_grant"):
        return "outlook_expired"
    return "outlook_failed"


def headers_of(message: dict) -> dict:
    return {str(h.get("name") or "").title(): str(h.get("value") or "")
            for h in message.get("internetMessageHeaders") or [] if isinstance(h, dict)}


def to_item(message: dict, now: float) -> Item:
    sender = (message.get("from") or {}).get("emailAddress") or {}
    address, name = str(sender.get("address") or ""), " ".join(str(sender.get("name") or "").split())
    body = (message.get("body") or {}).get("content") or ""
    words = mailbox.clean(body) if (message.get("body") or {}).get("contentType") == "text" else ""
    if len(words) < 40:
        words = mailbox.clean(mailbox.html_text(body)) if body else ""
    excerpt = " ".join((words or str(message.get("bodyPreview") or "")).split())[:mailbox.EXCERPT_MAX]
    title = " ".join(str(message.get("subject") or "").split())[:200]
    site = name[:80] or address
    when = _moment(message.get("receivedDateTime"))
    # Found when it arrived, so the feed's freshness follows the mail; a clock ahead counts as now.
    return Item(url=str(message.get("webLink") or ""), site=site, kind="article",
                title=title or excerpt[:80] or site, author=address, description=excerpt,
                published=when.isoformat() if when else "",
                seen_at=min(int(when.timestamp()), int(now)) if when else 0, fits=False, why="")


def _moment(value) -> Optional[datetime]:
    try:
        when = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


class Attempt:
    """One sign-in under way: its state, and the task that finishes it."""

    def __init__(self):
        self.state, self.error = "pending", ""
        self.started = time.monotonic()
        self.task: Optional[asyncio.Task] = None
        self.loopback: Optional[Loopback] = None

    def end(self, state: str, error: str = "") -> None:
        if self.state == "pending":
            self.state, self.error = state, error

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
        if self.loopback:
            self.loopback.close()


class Outlook(Connector):
    key = "outlook"
    private = "mail"
    name = ("Outlook / Hotmail", "Outlook / Hotmail 邮箱")
    how = "browser"
    warn = None
    reads = ("Reads your inbox, never changes or sends anything: newsletters and notifications, and personal "
             "letters only if you allow them in the mail settings.",
             "只读收件箱，不改动、不发送任何邮件：读订阅邮件和通知；私人信件只在你在邮件设置里允许后才读。")

    def __init__(self, workspace):
        super().__init__(workspace)
        self.attempt: Optional[Attempt] = None
        self._access: tuple[str, float] = ("", 0.0)

    def client(self) -> str:
        return self.client_id(OUTLOOK_CLIENT_ID, CLIENT_ENV)

    # -- connecting

    async def start(self, values: dict) -> dict:
        client_id = self.client()
        if not client_id:
            raise AccountError("outlook_not_ready")
        if self.attempt:
            self.attempt.stop()
            self.attempt = None
        if values.get("browser") is False:
            answer = await self._device_code(client_id)
            self.attempt = attempt = Attempt()
            attempt.task = asyncio.create_task(self._wait_device(attempt, client_id, answer))
            return {"code": str(answer["user_code"]), "verify": str(answer["verification_uri"])}
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(24)
        self.attempt = attempt = Attempt()
        attempt.loopback = await Loopback().open()
        url = authorize_url(client_id, attempt.loopback.redirect, verifier, state)
        attempt.task = asyncio.create_task(self._wait_browser(attempt, client_id, verifier, state))
        return {"browser": url}

    async def _device_code(self, client_id: str) -> dict:
        try:
            async with http() as client:
                answer = await client.post(f"{AUTHORITY}/devicecode", data={"client_id": client_id, "scope": SCOPES})
            body = answer.json()
        except httpx.HTTPError:
            raise AccountError("outlook_unreachable") from None
        except ValueError:
            raise AccountError("outlook_failed") from None
        if answer.status_code != 200 or not body.get("user_code") or not body.get("device_code"):
            raise AccountError(refusal(str(body.get("error") or "")))
        return body

    async def _wait_browser(self, attempt: Attempt, client_id: str, verifier: str, state: str) -> None:
        try:
            query = await attempt.loopback.wait(SIGNIN_S)
        except asyncio.TimeoutError:
            attempt.end("expired", "outlook_expired")
            return
        if not secrets.compare_digest(str(query.get("state") or "").encode(), state.encode()):
            attempt.end("failed", "outlook_failed")
        elif not query.get("code"):
            attempt.end("failed", refusal(str(query.get("error") or "")))
        else:
            await self._finish(attempt, {"client_id": client_id, "grant_type": "authorization_code",
                                         "code": query["code"], "redirect_uri": attempt.loopback.redirect,
                                         "code_verifier": verifier, "scope": SCOPES})

    async def _wait_device(self, attempt: Attempt, client_id: str, answer: dict) -> None:
        every = float(answer.get("interval") or 5)
        until = time.monotonic() + float(answer.get("expires_in") or 900)
        data = {"client_id": client_id, "grant_type": DEVICE_GRANT, "device_code": answer["device_code"]}
        while time.monotonic() < until:
            await asyncio.sleep(every)
            try:
                status, body = await token_request(data)
            except AccountError:
                continue            # the network came and went: try at the next interval
            error = str(body.get("error") or "")
            if status == 200:
                await self._finish(attempt, None, body)
                return
            if error == "slow_down":
                every += 5
            elif error != "authorization_pending":
                attempt.end("expired" if error == "expired_token" else "failed", refusal(error))
                return
        attempt.end("expired", "outlook_expired")

    async def _finish(self, attempt: Attempt, data: Optional[dict], tokens: Optional[dict] = None) -> None:
        """Exchange the code (or take the tokens), keep the refresh token, and say who signed in."""
        try:
            if tokens is None:
                status, tokens = await token_request(data)
                if status != 200:
                    attempt.end("failed", refusal(str(tokens.get("error") or "")))
                    return
            if not tokens.get("refresh_token") or not tokens.get("access_token"):
                attempt.end("failed", "outlook_failed")
                return
            account = account_name(str(tokens.get("id_token") or "")) or "Outlook"
            await asyncio.to_thread(self.keep_env, {TOKEN_ENV: str(tokens["refresh_token"])})
            self._access = (str(tokens["access_token"]), time.monotonic() + float(tokens.get("expires_in") or 0) - 60)
            await asyncio.to_thread(self.change, lambda s: (s.clear(), s.update(account=account)))
            attempt.end("done")
        except AccountError as error:
            attempt.end("failed", str(error))

    async def poll(self) -> dict:
        attempt = self.attempt
        if attempt is None:
            connected = (await asyncio.to_thread(self.view))["connected"]
            return {"state": "done", "error": ""} if connected else {"state": "expired", "error": "outlook_expired"}
        return {"state": attempt.state, "error": attempt.error}

    # -- reading

    async def access_token(self) -> str:
        token, until = self._access
        if token and time.monotonic() < until:
            return token
        refresh = self.env(TOKEN_ENV)
        if not refresh:
            raise AccountError("outlook_not_connected")
        status, tokens = await token_request({"client_id": self.client(), "grant_type": "refresh_token",
                                              "refresh_token": refresh, "scope": SCOPES})
        if status != 200 or not tokens.get("access_token"):
            raise AccountError(refusal(str(tokens.get("error") or "")))
        # Microsoft hands out a new refresh token each time: the old one is kept no longer.
        if tokens.get("refresh_token") and tokens["refresh_token"] != refresh:
            await asyncio.to_thread(self.keep_env, {TOKEN_ENV: str(tokens["refresh_token"])})
        self._access = (str(tokens["access_token"]), time.monotonic() + float(tokens.get("expires_in") or 0) - 60)
        return self._access[0]

    async def messages(self, since: str) -> list[dict]:
        """The inbox's messages received since `since`, newest first, at most PAGES_MAX pages of them."""
        address = f"{GRAPH}/me/mailFolders/inbox/messages"
        params: Optional[dict] = {"$filter": f"receivedDateTime ge {since}", "$orderby": "receivedDateTime desc",
                                  "$top": str(LOOK_MAX), "$select": FIELDS}
        found: list[dict] = []
        for _ in range(PAGES_MAX):
            page = await self._page(address, params)
            found += [m for m in page.get("value") or [] if isinstance(m, dict)]
            # The next page is older; its link carries the query.
            address, params = str(page.get("@odata.nextLink") or ""), None
            if not address:
                return found
        logger.info("outlook: more than %d messages since %s, the older ones were left unread", len(found), since)
        return found

    async def _page(self, address: str, params: Optional[dict]) -> dict:
        for again in (False, True):
            token = await self.access_token()
            try:
                async with http() as client:
                    answer = await client.get(address, params=params,
                                              headers={"Authorization": f"Bearer {token}",
                                                       "Prefer": 'outlook.body-content-type="text"'})
            except httpx.HTTPError:
                raise AccountError("outlook_unreachable") from None
            if answer.status_code == 401 and not again:
                self._access = ("", 0.0)
                continue
            if answer.status_code in (429, 503, 504):
                raise AccountError("outlook_limited")
            if answer.status_code in (401, 403):
                raise AccountError("outlook_denied")
            if answer.status_code != 200:
                raise AccountError("outlook_failed")
            try:
                page = answer.json()
            except ValueError:
                raise AccountError("outlook_failed") from None
            return page if isinstance(page, dict) else {}
        raise AccountError("outlook_denied")

    async def look(self) -> int:
        state = await asyncio.to_thread(self.load)
        if not (self.env(TOKEN_ENV) and state.get("account")):
            return 0
        now = time.time()
        since = state.get("since") or utc_iso(now - mailbox.DAYS * 86400)
        try:
            found = await self.messages(since)
        except AccountError as error:
            logger.info("outlook: a look failed (%s)", error)
            await asyncio.to_thread(self.change, lambda s, code=str(error): s.update(problem=code))
            return 0
        letters = (await asyncio.to_thread(mailbox.load_state, self.runtime()))["letters"]
        chosen = [m for m in found if m.get("webLink") and (
            letters or m.get("inferenceClassification") == "other" or mailbox.bulk(headers_of(m)))]

        def keep() -> int:
            known = self.known()
            fresh = [to_item(m, now) for m in chosen if item_id(str(m["webLink"])) not in known]
            return self.keep_items(fresh[:KEEP_MAX])

        kept = await asyncio.to_thread(keep)
        newest = max((str(m.get("receivedDateTime") or "") for m in found), default="") or since

        def record(state: dict) -> None:
            state.update(since=newest, last=int(now), problem="")

        await asyncio.to_thread(self.change, record)
        logger.info("outlook: a look kept %d of %d new messages", kept, len(found))
        return kept

    def view(self) -> dict:
        state = self.load()
        connected = bool(self.env(TOKEN_ENV) and state.get("account"))
        return {"connected": connected, "account": state.get("account", "") if connected else "",
                "last": iso(state.get("last")) if connected else "",
                "problem": state.get("problem", "") if connected else "",
                "ready": bool(self.client()), "choices": []}

    async def revoke(self) -> None:
        # Microsoft has no way to take back one app's refresh token: forgetting it is the end of it here.
        # What it already brought stays in the feed, like the mail's.
        if self.attempt:
            self.attempt.stop()
            self.attempt = None
        self._access = ("", 0.0)
        await asyncio.to_thread(self.keep_env, {TOKEN_ENV: ""})
        await asyncio.to_thread(self.forget)

    async def close(self) -> None:
        if self.attempt:
            self.attempt.stop()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                if self.attempt.task:
                    await self.attempt.task
