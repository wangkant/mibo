"""GitHub notifications as a source, through the OAuth device flow.

The person enters a short code on github.com and the app gets a token with the
`notifications` scope only. GET /notifications takes only OAuth-app tokens and
classic personal access tokens; when GitHub refuses the token there, the page
asks for a classic token instead, made on a pre-filled settings page.
The token is kept in the home's .env as GITHUB_READ_TOKEN; what was seen, in
`<runtime>/accounts/github.json`.

A look reads the unread notifications (304 when nothing changed costs nothing)
and keeps each thread that is new or changed as one library item. Review
requests and mentions count as ones that fit the person.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from ..library import Item
from .base import AccountError, Connector, iso

logger = logging.getLogger("agent.accounts.github")

# Registered by the app's author; empty until then.
GITHUB_CLIENT_ID = ""
ENV_ID = "PERSONAGENT_GITHUB_CLIENT_ID"
ENV_KEY = "GITHUB_READ_TOKEN"
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
PAT_URL = "https://github.com/settings/tokens/new?scopes=notifications&description=personagent"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"
TIMEOUT_S = 20
# A first look shows only the last two days.
FIRST_DAYS = 2
PAGE = 50
EXCERPT_MAX = 600
FITS = ("review_requested", "mention", "team_mention")
REASONS = {"review_requested": "Review requested", "mention": "You were mentioned",
           "team_mention": "Your team was mentioned", "assign": "Assigned to you",
           "author": "On your thread", "comment": "New comment", "state_change": "State changed",
           "ci_activity": "CI activity", "subscribed": "Watching", "manual": "Subscribed",
           "security_alert": "Security alert", "invitation": "Invitation",
           "approval_requested": "Approval requested"}
SUBJECTS = {"PullRequest": "Pull request", "Issue": "Issue", "Release": "Release", "Commit": "Commit",
            "Discussion": "Discussion", "CheckSuite": "Checks"}


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "personagent"}


def page_url(thread: dict) -> str:
    """The github.com page a notification is about; the API names only its own address."""
    subject = thread.get("subject") or {}
    repo = str((thread.get("repository") or {}).get("html_url") or "https://github.com")
    api = str(subject.get("url") or "")
    kind = subject.get("type")
    tail = api.split("/repos/", 1)[1].split("/", 2)[2] if "/repos/" in api else ""
    if kind == "PullRequest" and tail.startswith("pulls/"):
        return f"{repo}/pull/{tail[6:]}"
    if kind in ("Issue", "Commit") and tail:
        return f"{repo}/{tail.replace('commits/', 'commit/', 1)}"
    # Releases, discussions and checks have no page of their own in the answer.
    where = {"Release": "releases", "Discussion": "discussions", "CheckSuite": "actions"}.get(kind, "")
    return f"{repo}/{where}#notification-{thread['id']}" if where else f"{repo}#notification-{thread['id']}"


def to_item(thread: dict, now: float) -> Item:
    subject = thread.get("subject") or {}
    repo = str((thread.get("repository") or {}).get("full_name") or "")
    reason = str(thread.get("reason") or "")
    said = " · ".join(x for x in (REASONS.get(reason, reason.replace("_", " ")),
                                   SUBJECTS.get(subject.get("type"), str(subject.get("type") or "")), repo) if x)
    at = parse_time(thread.get("updated_at"), now)
    return Item(url=page_url(thread), site=f"GitHub · {repo}"[:80], kind="post",
                title=str(subject.get("title") or repo)[:200], author=repo[:120], description=said[:EXCERPT_MAX],
                published=datetime.fromtimestamp(at, timezone.utc).isoformat(),
                seen_at=min(int(at), int(now)), fits=reason in FITS, why="")


def parse_time(text, now: float) -> float:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return now


class GitHub(Connector):
    key = "github"
    name = ("GitHub", "GitHub")
    how = "code"
    warn = None
    reads = ("Your GitHub notifications: review requests, mentions and the threads you watch. "
             "It cannot read your code or private messages, and never writes.",
             "你的 GitHub 通知：请你审阅、提到你、以及你关注的讨论。它读不到你的代码，也不会写任何东西。")

    def __init__(self, workspace):
        super().__init__(workspace)
        self._device: dict = {}

    def state(self) -> dict:
        return {"login": "", "last": 0, "error": "", "threads": {}, "modified": "", "paste": False, **self.load()}

    def token(self) -> str:
        return self.env(ENV_KEY)

    def app(self) -> str:
        return self.client_id(GITHUB_CLIENT_ID, ENV_ID)

    async def start(self, values: dict) -> dict:
        pasted = str(values.get("token") or "").strip()
        if pasted:
            await self._connect(pasted)
            return {"done": True}
        if self.state()["paste"]:
            return {"fields": [{"key": "token", "label": ("Personal access token (classic)", "个人访问令牌（classic）"),
                                "secret": True,
                                "help": ("Open the link, scroll down, choose Generate token and paste it here. "
                                         "Only the notifications box is ticked.",
                                         "打开链接，拉到最下面点 Generate token，把令牌粘贴到这里。只勾选了 notifications。")}],
                    "link": PAT_URL}
        if not self.app():
            raise AccountError("github_not_ready")
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            answer = await self._post(http, DEVICE_URL, {"client_id": self.app(), "scope": "notifications"})
        if "device_code" not in answer:
            # GitHub answers an unknown client id with "Not Found".
            raise AccountError("github_not_ready" if answer.get("error") in ("device_flow_disabled", "Not Found")
                               else "github_failed")
        now, every = time.time(), int(answer.get("interval") or 5)
        self._device = {"code": answer["device_code"], "every": every, "next": now + every,
                        "until": now + int(answer.get("expires_in") or 900)}
        return {"code": answer["user_code"], "verify": answer.get("verification_uri") or "https://github.com/login/device"}

    async def poll(self) -> dict:
        if self.view()["connected"] and not self._device:
            return {"state": "done", "error": ""}
        device, now = self._device, time.time()
        if not device or now > device["until"]:
            self._device = {}
            return {"state": "expired", "error": "github_expired"}
        if now < device["next"]:
            return {"state": "pending", "error": ""}
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            answer = await self._post(http, TOKEN_URL, {"client_id": self.app(), "device_code": device["code"],
                                                       "grant_type": GRANT})
        error = answer.get("error")
        if error == "slow_down":
            device["every"] = int(answer.get("interval") or device["every"] + 5)
        if error in ("authorization_pending", "slow_down"):
            device["next"] = now + device["every"]
            return {"state": "pending", "error": ""}
        self._device = {}
        if error == "expired_token":
            return {"state": "expired", "error": "github_expired"}
        if error == "access_denied":
            return {"state": "failed", "error": "github_denied"}
        if not answer.get("access_token"):
            return {"state": "failed", "error": "github_failed"}
        try:
            await self._connect(str(answer["access_token"]))
        except AccountError as failed:
            if str(failed) == "github_token_refused":
                # Next start asks for a classic token instead.
                self.change(lambda s: s.update(paste=True))
            return {"state": "failed", "error": str(failed)}
        return {"state": "done", "error": ""}

    async def _post(self, http: httpx.AsyncClient, url: str, data: dict) -> dict:
        try:
            response = await http.post(url, data=data, headers={"Accept": "application/json"})
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise AccountError("github_unreachable") from None

    async def _connect(self, token: str) -> None:
        """Keep `token` once GitHub has shown its notifications to it."""
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=headers(token)) as http:
            try:
                probe = await http.get(API + "/notifications", params={"per_page": 1})
                user = await http.get(API + "/user")
            except httpx.HTTPError:
                raise AccountError("github_unreachable") from None
        if probe.status_code == 401:
            raise AccountError("github_token_invalid")
        if probe.status_code in (403, 404):
            raise AccountError("github_token_refused")
        if probe.status_code >= 400:
            raise AccountError("github_failed")
        login = str((user.json() if user.status_code == 200 else {}).get("login") or "")
        await asyncio.to_thread(self.keep_env, {ENV_KEY: token})

        def put(state: dict) -> None:
            if state.get("login") != login:
                state.clear()       # another account: what the last one saw does not carry over
            state.update(login=login or "GitHub", error="", paste=False)

        self.change(put)

    async def look(self) -> int:
        token, state = self.token(), self.state()
        if not token or not state["login"]:
            return 0
        now = time.time()
        params = {"per_page": PAGE}
        sent = dict(headers(token))
        if state["modified"]:
            sent["If-Modified-Since"] = state["modified"]
        else:
            params["since"] = datetime.fromtimestamp(now - FIRST_DAYS * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=sent) as http:
                response = await http.get(API + "/notifications", params=params)
        except httpx.HTTPError:
            self.change(lambda s: s.update(error="github_unreachable"))
            return 0
        if response.status_code == 304:
            self.change(lambda s: s.update(last=int(now), error=""))
            return 0
        if response.status_code >= 400:
            code = "github_token_invalid" if response.status_code == 401 else "github_failed"
            self.change(lambda s: s.update(error=code))
            return 0
        threads = response.json()
        known = state["threads"]
        fresh = [t for t in threads if known.get(str(t["id"])) != t.get("updated_at")]
        items = [to_item(t, now) for t in fresh]

        await asyncio.to_thread(self.keep_items, items)
        modified = response.headers.get("Last-Modified", "")

        def record(s: dict) -> None:
            # Only the threads still unread are remembered; one read on GitHub and changed again comes back.
            s.update(threads={str(t["id"]): t.get("updated_at") for t in threads}, modified=modified,
                     last=int(now), error="")

        self.change(record)
        logger.info("github: a look kept %d notifications", len(items))
        return len(items)

    def view(self) -> dict:
        state = self.state()
        connected = bool(self.token() and state["login"])
        return {"connected": connected, "account": state["login"] if connected else "",
                "last": iso(state["last"]) if connected else "",
                "problem": state["error"] if connected else "", "ready": bool(self.app()) or state["paste"],
                "choices": []}

    async def revoke(self) -> None:
        # What it already brought stays in the feed, like the mail's.
        self._device = {}
        await asyncio.to_thread(self.keep_env, {ENV_KEY: ""})
        self.forget()
