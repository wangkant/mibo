"""The MCP servers of one home, run by the app's page process: started with it, followed, stopped with it.

A local server is a program on the person's computer: it starts only after the
person allowed that exact command (this once or always, on the asking card in
the chat or on its row in Settings), never while the app runs as administrator,
in its own folder, with a cleaned environment and only the values its
configuration names. A remote server is reached with its headers, which never
leave this process. A server that stops is started again with a growing pause,
unless what stopped it needs the person (a missing program or value, a sign-in).
A missing npx or uvx is said before any start is asked for, with a download of
Node.js or uv into the home on the server's row (runtimes.py).
Values and sign-in tokens live in the system's credential store (secretstore.py).

A remote server that answers 401 needs a sign-in. Only the person's press on
Settings' row starts one: the SDK's OAuth client finds the server's
authorization server, registers Mibo, and the system browser shows the
consent page, which sends the browser back to this page process
(/signin/mcp, panels/tools.py). The SDK refreshes the tokens after that; a
grant that can no longer be refreshed goes back to "needs sign-in" without
opening anything. Signing out ends the grant at the server first.

The reply model reaches the tools through the character service, which asks
here (/api/mcp/offer, /find, /call: panels/tools.py). A local server that was
never allowed starts inside the call that needs it, on its card. A call that
pays or orders, changes a payment, deletes, or changes an account's security
or access (mcp_floor.hard, from the tool's name, parameters, description and
the arguments, whatever its hints say) is asked in the chat in every mode, with
no reviewer and no always-allow, and a yes to another kind of step earlier in
the turn does not reach it (cardwait.reaches); a tool marked destructive asks
too. A tool its provider marks read-only whose name reads by its own words
(mcp_floor.group_of) runs with no reviewer and no question; any other goes to
the reviewer on the person's own words, and is asked in the chat when it does
not pass, unless the person set it to always (that exact description).
Arguments holding a password, a code, a key or a card number are never sent.
Never, for a tool or for a server's tools that write, stops it. A question is
asked only while the person's own chat turn is under way, waits for them there
(cardwait.py), and only their own message typed in the app's chat box answers
it. What a server asks of the person during a call (elicitation) is a page they
choose to open in their browser, asked the same way, or a form they fill in on
the page, sent to the server and never to the model.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import mcp_schema, runtimes, secretstore
from . import mcp_tools as mt
from .cardwait import Card, risk_of
from .mcp_client import Connection, KeptTokens, McpError, describe, find_program, oauth_client, program_env, revoke
from .mcp_floor import asks_each_time, cut, group_of, hard
from .textproc import scrub_third_party_text

logger = logging.getLogger("agent.tools")

#: Seconds: a start (npx and uvx may first download the server), listing, one call.
START_TIMEOUT_S = 90.0
#: Seconds the person has to finish a sign-in in the browser.
SIGNIN_S = 600.0
#: Seconds the browser's return waits to say whether the sign-in worked.
SIGNIN_RESULT_S = 30.0
LIST_TIMEOUT_S = 30.0
CALL_TIMEOUT_S = 60.0
#: How often mcp.json is looked at for a change made by hand.
WATCH_S = 5.0
#: Pauses before a stopped server starts again, doubling; a server that ran this long starts over.
BACKOFF_S = (2.0, 60.0)
HEALTHY_S = 60.0
#: A tool list said to have changed is read again at most this often.
RELIST_S = 3.0
#: What a card asks, for the notification when the app window is not in front.
CARD_WHAT = {"mcp_start": ("启动「{server}」", "Start “{server}”"), "mcp_tool": ("使用工具「{tool}」", "Use the tool “{tool}”"),
             "mcp_ask": ("「{server}」请求填写信息", "“{server}” asks for information")}
#: Failures that need the person before a start is worth trying again.
NEEDS_PERSON = ("not_found", "missing_value", "oauth", "elevated", "http")
#: How a sign-in the person started can end without one, as the page names it ("failed" otherwise).
SIGNIN_ENDS = ("denied", "cancelled", "timeout", "registration")


class Runner:
    """One server: its configuration as written (references unfilled), and how it stands."""

    def __init__(self, name: str, spec: dict) -> None:
        self.name, self.spec = name, spec
        self.state, self.error, self.detail = "starting", "", ""
        self.tools: list[dict] = []
        self.cut = 0
        self.conn: Connection | None = None
        self.task: asyncio.Task | None = None
        self.retry_at = 0.0
        self.about = ""
        self.allowed_once = False
        self.declined = False
        self.wake = asyncio.Event()
        # Set before the task is cancelled: on Python 3.10 the SDK's task groups can swallow that cancel.
        self.stopped = False
        #: The sign-in the person started, while it is under way.
        self.attempt: Attempt | None = None
        #: The call of the person's turn under way ({"conversation", "name", "tool" as shown}): what the server
        #: asks of the person is shown only then.
        self.calling: dict | None = None

    @property
    def local(self) -> bool:
        return bool(self.spec.get("command"))


class Attempt:
    """One sign-in: the consent page's address and state, and the code the browser brings back."""

    def __init__(self, callback: str, lang: str) -> None:
        self.callback, self.lang = callback, lang
        self.url = self.state = ""
        self.code: asyncio.Future = asyncio.get_running_loop().create_future()
        self.done = asyncio.Event()
        self.error = ""

    async def opened(self, url: str) -> None:
        """The SDK's redirect handler: the consent page, in the system browser."""
        self.url = url
        self.state = parse_qs(urlsplit(url).query).get("state", [""])[0]
        await asyncio.to_thread(webbrowser.open, url)

    async def returned(self):
        """The SDK's callback handler: the code the browser brought back to /signin/mcp."""
        return await self.code


class Hub:
    def __init__(self, workspace) -> None:
        self.workspace = workspace
        self.home = Path(workspace.home)
        self.grants = mt.Grants(self.home)
        self.runners: dict[str, Runner] = {}
        self.bad: list[str] = []
        #: The card waiting for the person; panels/tools.py gives it the app window.
        self.cards = Card(workspace)
        #: For a card that is a server's form: the schema it was drawn from, and what the person filled in.
        self.card_schema: dict = {}
        self.filled: dict = {}
        self.busy = asyncio.Lock()
        self._stamp = None
        # Stops of servers the configuration dropped, held until they finish so the loop does not lose them.
        self._stopping: set[asyncio.Task] = set()
        #: Downloads of Node.js or uv the person started (runtimes.py), and why the last one of each failed.
        self.fetching: dict[str, asyncio.Task] = {}
        self.fetch_failed: dict[str, str] = {}

    # ---------------------------------------------------------- lifetime --

    async def run(self) -> None:
        """The page's whole life: start what may start, follow mcp.json, stop every server at the end."""
        try:
            while True:
                self.reconcile()
                await asyncio.sleep(WATCH_S)
        finally:
            runners, self.runners = list(self.runners.values()), {}
            await asyncio.gather(*(self._stop(r) for r in runners), return_exceptions=True)

    def _file_stamp(self):
        try:
            stat = mt.config_path(self.home).stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def reconcile(self, force: bool = False) -> None:
        stamp = self._file_stamp()
        if stamp == self._stamp and not force:
            return
        self._stamp = stamp
        config = mt.load_config(self.home) if stamp else {"mcpServers": {}, "bad": []}
        self.bad = config["bad"]
        servers = config["mcpServers"]
        for name in list(self.runners):
            runner = self.runners[name]
            if name not in servers or servers[name] != runner.spec:
                del self.runners[name]
                stopping = asyncio.ensure_future(self._stop(runner))
                self._stopping.add(stopping)
                stopping.add_done_callback(self._stopping.discard)
        for name, spec in servers.items():
            if name not in self.runners:
                runner = self.runners[name] = Runner(name, spec)
                runner.task = asyncio.ensure_future(self._keep(runner))

    async def _stop(self, runner: Runner) -> None:
        runner.stopped = True
        if runner.task is not None:
            runner.task.cancel()
            await asyncio.gather(runner.task, return_exceptions=True)
        if runner.conn is not None:
            await runner.conn.close()
            runner.conn = None

    def _held(self, spec: dict) -> dict:
        """The values the credential store holds for the MIBO_MCP_ names `spec` refers to."""
        names = {m.group(1) for m in mt.REF_RE.finditer(json.dumps(spec)) if m.group(1).startswith(mt.SECRET_PREFIX)}
        return {name: value for name in names if (value := secretstore.get(self.home, name))}

    def _set(self, runner: Runner, state: str, error: str = "", detail: str = "") -> None:
        runner.state, runner.error, runner.detail = state, error, detail[:2000]

    def may_start(self, runner: Runner) -> bool:
        return not runner.local or runner.allowed_once or self.grants.started(runner.name, runner.spec)

    def _found(self, runner: Runner) -> bool:
        """A local server's program is there, the runtimes Mibo fetched included."""
        spec = runner.spec
        return bool(find_program(spec["command"], program_env(runtimes.env(self.home, spec.get("env"))),
                                 spec.get("cwd") or str(mt.server_folder(self.home, runner.name))))

    async def _keep(self, runner: Runner) -> None:
        """Keep one server running while it is switched on and allowed; a fresh pause after each stop."""
        delay = BACKOFF_S[0]
        while True:
            runner.wake.clear()
            spec = await self._startable(runner)
            if spec is None:
                await runner.wake.wait()
                continue
            began = time.monotonic()
            code, detail = await self._session(runner, spec)
            if runner.stopped:
                return
            if time.monotonic() - began >= HEALTHY_S:
                delay = BACKOFF_S[0]
            if code in NEEDS_PERSON:
                self._set(runner, "signin" if code == "oauth" else "failed", code, detail)
                logger.warning("[Tools] %s stopped (%s); it waits for the person", runner.name, code)
                await runner.wake.wait()
                delay = BACKOFF_S[0]
                continue
            self._set(runner, "failed", code, detail)
            runner.retry_at = time.time() + delay
            logger.warning("[Tools] %s stopped (%s); trying again in %.0f s", runner.name, code, delay)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(runner.wake.wait(), delay)
            runner.retry_at = 0.0
            delay = min(delay * 2, BACKOFF_S[1])

    async def _startable(self, runner: Runner) -> dict | None:
        """The spec to start the server with, its values filled and its program's environment set; None, with the
        state saying why, while it may not start yet."""
        if runner.spec.get("disabled"):
            self._set(runner, "off")
            return None
        # A missing program is said before the person is asked to allow it.
        if runner.local and not self._found(runner):
            self._set(runner, "failed", "not_found", runner.spec["command"])
            return None
        if not self.may_start(runner):
            self._set(runner, "declined" if runner.declined else "waiting")
            return None
        spec, missing = mt.expand(runner.spec, self._held(runner.spec))
        if missing:
            self._set(runner, "failed", "missing_value", ", ".join(missing))
            return None
        if runner.local:
            from .shell.run import elevated
            if elevated():
                self._set(runner, "failed", "elevated")
                return None
            # A mirror for npx's or uvx's downloads where the vendor's registry does not answer; the server's own
            # env wins.
            reach_env = await runtimes.reach_env(self.home, spec["command"])
            spec = {**spec, "env": {**reach_env, **runtimes.env(self.home, spec.get("env"))}}
        return spec

    async def _session(self, runner: Runner, spec: dict) -> tuple[str, str]:
        """One run of the server, from its start until it stops: (why it stopped, the detail)."""
        # A sign-in the person started, or tokens kept from one: the SDK's OAuth client goes along.
        attempt, auth = runner.attempt, None
        if not runner.local and (attempt or KeptTokens(self.home, runner.name).signed_in()):
            store = KeptTokens(self.home, runner.name, attempt.callback if attempt else "")
            auth = oauth_client(spec["url"], store, attempt and attempt.opened, attempt and attempt.returned)
        self._set(runner, "signing_in" if attempt else "starting")
        try:
            runner.conn = Connection(spec, folder=mt.server_folder(self.home, runner.name), auth=auth,
                                     elicit=lambda request, runner=runner: self._elicit(runner, request))
            await runner.conn.open(SIGNIN_S if attempt else START_TIMEOUT_S)
            if attempt:
                store.keep_revocation(auth)
                self._finish(runner, "")
            runner.about = _about(runner.conn.instructions)
            await self._list(runner)
            self._set(runner, "connected")
            logger.info("[Tools] %s is connected with %d tools", runner.name, len(runner.tools))
            await self._follow(runner)
            code, detail = "exited", runner.conn.stderr_tail() if runner.local else ""
        except Exception as e:
            code, detail = describe(e)
            if code == "timeout" and attempt:
                code, detail = "oauth", "timeout"
            if code == "oauth":
                # Why a sign-in the person started did not finish; otherwise, whether a grant ran out.
                detail = (detail if detail in SIGNIN_ENDS else "failed") if attempt else "expired" if auth else ""
        if runner.attempt is not None:
            self._finish(runner, detail or code)
        if runner.conn is not None:
            await runner.conn.close()
            runner.conn = None
        runner.tools = []
        return code, detail

    async def _follow(self, runner: Runner) -> None:
        """Reads the tool list again each time the server says it changed, until the connection closes."""
        while not runner.conn.closed.is_set():
            changed = asyncio.ensure_future(runner.conn.changed.wait())
            closed = asyncio.ensure_future(runner.conn.closed.wait())
            await asyncio.wait({changed, closed}, return_when=asyncio.FIRST_COMPLETED)
            changed.cancel()
            closed.cancel()
            if not runner.conn.closed.is_set():
                # A flood of "changed" is read once every few seconds at most.
                await asyncio.sleep(RELIST_S)
                await self._list(runner)

    async def _list(self, runner: Runner) -> None:
        raw = await runner.conn.list_tools(LIST_TIMEOUT_S, mt.MAX_TOOLS + 1)
        tools = mt.clean_tools(raw)
        # Listing stops past the limit, so how many more is not known: the limit is what the page says.
        runner.cut = mt.MAX_TOOLS if len(tools) > mt.MAX_TOOLS else 0
        runner.tools = tools[:mt.MAX_TOOLS]

    def poke(self, name: str) -> None:
        runner = self.runners.get(name)
        if runner is not None:
            runner.wake.set()

    def fetch_runtime(self, name: str) -> None:
        """The person pressed a row's download of Node.js or uv: fetched in the background (runtimes.py), then
        every server that waited for its program looks again."""
        if name in self.fetching and not self.fetching[name].done():
            return
        self.fetch_failed.pop(name, None)
        self.fetching[name] = asyncio.ensure_future(self._fetch_runtime(name))

    async def _fetch_runtime(self, name: str) -> None:
        try:
            await runtimes.install(self.home, name)
        except ValueError as e:
            self.fetch_failed[name] = str(e)
            logger.warning("[Tools] %s was not fetched (%s)", name, e)
            return
        logger.info("[Tools] %s is ready for local servers", name)
        for runner in self.runners.values():
            if runner.error == "not_found":
                runner.wake.set()

    # ------------------------------------------------------------ sign-in --

    def sign_in(self, name: str, callback: str, lang: str) -> None:
        """The person pressed Sign in on a server that needs one; `callback` is where the browser returns,
        `lang` the language of the page it shows there."""
        runner = self.runners.get(name)
        if runner is None or runner.state != "signin":
            raise mt.ToolsError("tools_unknown_server")
        # A fresh registration with each sign-in: one the server has since forgotten would stop at its page.
        KeptTokens(self.home, name).clear()
        runner.attempt = Attempt(callback, lang)
        self._set(runner, "signing_in")
        runner.wake.set()

    def cancel_sign_in(self, name: str) -> None:
        runner = self.runners.get(name)
        if runner is not None and runner.attempt is not None and not runner.attempt.code.done():
            runner.attempt.code.set_exception(McpError("oauth", "cancelled"))

    def _finish(self, runner: Runner, error: str) -> None:
        attempt, runner.attempt = runner.attempt, None
        attempt.error = error
        attempt.done.set()

    async def returned(self, code: str, state: str, iss: str) -> tuple[str, str]:
        """The browser came back from a consent page: hands the code to the sign-in whose state it carries
        and waits for it to finish. (the sign-in's page language, "" when signed in or else why not)."""
        from mcp.client.auth import AuthorizationCodeResult
        attempt = next((r.attempt for r in self.runners.values() if r.attempt and r.attempt.state and state
                        and secrets.compare_digest(r.attempt.state.encode(), state.encode())), None)
        if attempt is None or attempt.code.done():
            return "", "link_invalid"
        if code:
            attempt.code.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss or None))
        else:
            attempt.code.set_exception(McpError("oauth", "denied"))
        try:
            await asyncio.wait_for(attempt.done.wait(), SIGNIN_RESULT_S)
        except asyncio.TimeoutError:
            return attempt.lang, "failed"
        return attempt.lang, attempt.error

    async def forget_sign_in(self, name: str) -> bool:
        """Ends the server's grant (revoked at the server first) and deletes what is kept of it; True when
        the server agreed to the revocation."""
        store = KeptTokens(self.home, name)
        record = store.read()
        revoked = await revoke(record)
        store.clear()
        return revoked

    async def sign_out(self, name: str) -> bool:
        """Signs out and starts the server over, which then needs a sign-in again."""
        revoked = await self.forget_sign_in(name)
        runner = self.runners.get(name)
        if runner is not None:
            await self._stop(runner)
            fresh = self.runners[name] = Runner(name, runner.spec)
            fresh.task = asyncio.ensure_future(self._keep(fresh))
        return revoked

    # ----------------------------------------------------------- the model --

    def connected(self) -> list[Runner]:
        return [r for r in self.runners.values() if r.state == "connected" and r.tools]

    def offer(self) -> dict:
        """What the reply model is told of the servers: `names`, every server not switched off (fixed while the
        configuration is), and `servers`, how each connected or waiting one stands now (find_tools' result), a
        connected one with its tools as the model is offered them (`shown`, less those set to never)."""
        lines = []
        for runner in self.runners.values():
            if runner.state == "connected" and runner.tools:
                lines.append({"name": runner.name, "about": runner.about or _sample(runner.tools),
                              "tools": len(runner.tools), "tool_names": [t["name"] for t in runner.tools],
                              "shown": [_shown(t) for t in runner.tools
                                        if self.grants.mode(runner.name, t)[0] != mt.NEVER]})
            elif runner.state in ("waiting", "declined", "starting") and not runner.spec.get("disabled"):
                lines.append({"name": runner.name, "about": "", "tools": 0, "state": runner.state})
        return {"names": [r.name for r in self.runners.values() if not r.spec.get("disabled")], "servers": lines}

    def find(self, query: str, server: str = "", k: int = 5) -> dict:
        """The few tools matching a search, with their parameters; a server's whole list when only a server
        is named."""
        pool = [r for r in self.connected() if not server or r.name == server]
        if server and server in self.runners and not pool:
            return {"status": "not_connected", "state": self.runners[server].state, "error": self.runners[server].error,
                    "tools": []}
        rows = []
        words = mcp_schema.words_of(query)
        for runner in pool:
            for tool in runner.tools:
                if self.grants.mode(runner.name, tool)[0] == mt.NEVER:
                    continue
                rank = mcp_schema.score(words, tool, runner.name) if words else 1.0
                if rank > 0:
                    rows.append((rank, runner.name, tool))
        rows.sort(key=lambda row: -row[0])
        if words and not rows:
            # Words that match no tool's own (another language, say): the whole lists, for the model to read.
            return {**self.find("", server, k), "unmatched": True}
        limit = 30 if not words else k
        return {"status": "ok", "tools": [{"server": name, **_shown(tool)} for _, name, tool in rows[:limit]],
                "servers": [r.name for r in self.connected()],
                # Not started, so their tools are not known yet: the model names one to start it.
                "waiting": [r.name for r in self.runners.values()
                            if r.state in ("waiting", "declined", "starting") and not r.spec.get("disabled")]}

    async def _ready(self, runner: Runner, conversation: str) -> dict | None:
        """The server connected, asking the person first to start a local program never allowed; what
        stands in the way otherwise. A no holds for that call only: the next call asks again."""
        if runner.state in ("waiting", "declined") and runner.local and not await self._ask_start(runner, conversation):
            return {"status": "start_declined" if runner.declined else "unanswered"}
        for _ in range(int(START_TIMEOUT_S * 2)):
            if runner.state not in ("starting", "waiting", "declined") or not self.turn_on(conversation):
                break
            await asyncio.sleep(0.5)
        if runner.state != "connected":
            return {"status": "not_connected", "state": runner.state, "error": runner.error}
        return None

    async def find_for(self, query: str, server: str, conversation: str) -> dict:
        """`find`, after starting a server the model named that waits for the person's leave."""
        runner = self.runners.get(server)
        if runner is not None and runner.state in ("waiting", "declined", "starting") and self.turn_on(conversation):
            async with self.busy:
                stands = await self._ready(runner, conversation)
            if stands:
                return {**stands, "tools": []}
        return self.find(query, server)

    async def call(self, server: str, tool_name: str, arguments, conversation: str) -> dict:
        """One call the model asked for: started if the person allows it, checked, asked about, run. With no server
        named, the one connected server that has the tool (a weak model may leave the server out)."""
        if not server:
            having = [r.name for r in self.connected() if any(t["name"] == tool_name for t in r.tools)] or \
                [name for name, r in self.runners.items() if not r.spec.get("disabled")]
            if len(having) != 1:
                return {"status": "unknown_anywhere"}
            server = having[0]
        runner = self.runners.get(server)
        if runner is None:
            return {"status": "unknown_server", "servers": [r.name for r in self.connected()]}
        if not self.turn_on(conversation):
            return {"status": "unwatched"}
        async with self.busy:
            stands = await self._ready(runner, conversation)
            if stands:
                return stands
            tool = next((t for t in runner.tools if t["name"] == tool_name), None)
            if tool is None:
                return {"status": "unknown_tool", "tools": [t["name"] for t in runner.tools][:30]}
            if not isinstance(arguments, dict):
                arguments = {}
            problem = mcp_schema.check_arguments(tool["inputSchema"], arguments)
            if problem:
                return {"status": "bad_arguments", "problem": problem, "parameters": _parameters(tool)}
            how, stopped = await self._permit(runner, tool, arguments, conversation)
            if stopped:
                return stopped
            return await self._run(runner, tool, arguments, how, conversation)

    async def _permit(self, runner: Runner, tool: dict, arguments: dict, conversation: str) -> tuple[str, dict | None]:
        """Whether the call may run: (how it went ahead, None), or ("", the outcome) when it does not run. The
        person's never, a secret in the arguments, the floor, the read group, the reviewer and the question in the
        chat, in that order."""
        server, tool_name = runner.name, tool["name"]
        mode, changed = self.grants.mode(server, tool)
        if mode == mt.NEVER:
            self._log(server, tool_name, arguments, "never")
            return "", {"status": "never"}
        from .review import carries_secret
        if carries_secret(json.dumps(arguments, ensure_ascii=False)):
            # A password, code, key or card number is never typed by the character, whatever the tool.
            self._log(server, tool_name, arguments, "secret")
            return "", {"status": "secret"}
        # Paying, deleting, an account's security or access: decided here before any reviewer, by what the
        # call does; it asks every time, in every mode.
        floor = hard(tool, arguments)
        how, passed = mode, None
        if floor or cut(arguments):
            how = mt.AUTO
        elif mode == mt.AUTO and group_of(tool) == "read":
            # Marked read-only by its provider, and a read by its name's own words: it runs.
            how = "read_only"
        elif mode == mt.AUTO and tool["hints"].get("destructiveHint") is not True:
            # The reviewer first, on the person's own words of this turn; a tool marked destructive skips it.
            passed = await self._review(server, tool, arguments)
            if passed.decision == "refuse":
                self._log(server, tool_name, arguments, "refused", "review", passed.reason)
                return "", {"status": "refused", "reason": passed.reason}
            how = "review" if passed.decision == "go" else how
        if how != mt.AUTO:
            return how, None
        card = self._tool_card(runner, tool, arguments, changed, floor)
        if passed is not None:
            # Why the reviewer did not pass it, in one line (the fold beside its question shows it, activity.js).
            card["review"] = passed.line(str(self.workspace.config().get("AGENT_LANG") or "zh"))
        answer = await self.ask(card, conversation, risk_of(floor))
        if answer in (None, "no"):
            status = "declined" if answer == "no" else "unanswered"
            self._log(server, tool_name, arguments, status, "review" if passed is not None else "",
                      passed.reason if passed is not None else "")
            return "", {"status": status}
        # The tool must still be the one the question showed.
        now = next((t for t in runner.tools if t["name"] == tool_name), None)
        if now is None or now["fp"] != tool["fp"] or runner.state != "connected":
            self._log(server, tool_name, arguments, "changed")
            return "", {"status": "changed"}
        return self.cards.how, None

    async def _run(self, runner: Runner, tool: dict, arguments: dict, how: str, conversation: str) -> dict:
        """The call itself, logged with how it went ahead."""
        server, tool_name = runner.name, tool["name"]
        runner.calling = {"conversation": conversation, "name": tool_name, "tool": tool["title"] or tool_name}
        try:
            result = await runner.conn.call_tool(tool_name, arguments, CALL_TIMEOUT_S)
        except McpError as e:
            self._log(server, tool_name, arguments, "failed", how, e.code)
            return {"status": "failed", "error": e.code}
        finally:
            runner.calling = None
        self._log(server, tool_name, arguments, "error" if result.is_error else "done", how, result.text)
        return {"status": "done", "how": how, "is_error": result.is_error, "left_out": result.left_out,
                "pictures": result.pictures, "text": result.text[: mcp_schema.RESULT_CHARS + 1],
                "title": tool["title"] or tool["name"]}

    async def _review(self, server: str, tool: dict, arguments: dict):
        """The reviewer's verdict on one call: the person's own messages of the turn under way, the tool's name and
        its maker's description as data, the arguments as the text it sends."""
        from . import acting, review
        from .crossing import turn_read
        request = await asyncio.to_thread(acting.asked, self.workspace)
        return await review.decide("tools", request, {
            "kind": "tool", "where": server, "target": [tool["title"] or tool["name"]], "effects": [],
            "text": json.dumps(arguments, ensure_ascii=False)[:2000], "page_says": tool["description"][:200]},
            ask=acting.reviewer(self.workspace), attended=True,
            lang=str(self.workspace.config().get("AGENT_LANG") or "zh"), read=turn_read(self.workspace))

    def _log(self, server: str, tool: str, arguments: dict, outcome: str, how: str = "", out: str = "") -> None:
        self.grants.log({"server": server, "tool": tool, "outcome": outcome, "how": how,
                         "args": json.dumps(arguments, ensure_ascii=False)[:1500], "out": str(out)[:1500]})

    # --------------------------------------------------------------- cards --

    def turn_on(self, conversation: str) -> bool:
        return self.cards.turn_on(conversation)

    async def ask(self, card: dict, conversation: str, risk: str = "act") -> str | None:
        """Says `card` in the chat and waits: "once" on the person's typed yes, "no" on any other message, None when
        nobody answered. A server's form is filled in on the page instead and answered by `press`."""
        names = {"server": card["server"], "tool": card.get("title") or card.get("tool") or ""}
        what = dict(zip(("zh", "en"), (text.format(**names) for text in CARD_WHAT[card["type"]])))
        form = card["type"] == "mcp_ask" and card["mode"] == "form"
        return await self.cards.ask(card, conversation, what, yes="once", no="no", risk=risk, typed=not form)

    def press(self, ident: str, answer: str, values=None) -> str:
        """The person's answer to a server's form, sent or not: "ok", "gone" for a form no longer up, or where the
        values do not fit what the server asked for."""
        card = self.cards.card
        if not self.cards.up(ident) or card["type"] != "mcp_ask" or card["mode"] != "form":
            return "gone"
        if answer == "once":
            self.filled, problem = mcp_schema.ask_content(card["fields"], self.card_schema, values)
            if problem:
                return problem
        self.cards.press(ident, answer)
        return "ok"

    def _start_card(self, runner: Runner) -> dict:
        """The server and the program it runs in one line (python · tiny_server.py); the exact command, folder and
        values under the question's fold."""
        return {"type": "mcp_start", "server": runner.name, "program": mt.program_of(runner.spec),
                "command": mt.command_line(runner.spec),
                "cwd": runner.spec.get("cwd") or str(mt.server_folder(self.home, runner.name)),
                "env": sorted(runner.spec.get("env") or {})}

    async def _ask_start(self, runner: Runner, conversation: str) -> bool:
        answer = await self.ask(self._start_card(runner), conversation)
        if answer is None:
            return False
        self.answer_start(runner.name, answer)
        return answer != "no"

    def answer_start(self, name: str, answer: str) -> None:
        """The person's answer to starting a local program: this once, always (that exact command), or no."""
        runner = self.runners.get(name)
        if runner is None:
            raise mt.ToolsError("tools_unknown_server")
        runner.declined = answer == "no"
        runner.allowed_once = answer in ("once", "always")
        if answer == "always":
            self.grants.allow_start(name, runner.spec)
        self.grants.log({"server": name, "outcome": "start_" + answer, "args": mt.command_line(runner.spec)})
        runner.wake.set()

    def _tool_card(self, runner: Runner, tool: dict, arguments: dict, changed: bool, floor: str = "") -> dict:
        raw = json.dumps(arguments, ensure_ascii=False, indent=2)
        destructive = tool["hints"].get("destructiveHint") is True
        return {"type": "mcp_tool", "server": runner.name, "tool": tool["name"], "title": tool["title"],
                "args": mcp_schema.plain_arguments(arguments),
                "raw": raw if len(raw) <= 4000 else raw[:4000] + "\n…",
                "destructive": destructive and not floor, "hard": floor, "changed": changed}

    async def _elicit(self, runner: Runner, request: dict) -> dict:
        """A server asks the person for something during a call of their turn: a form shown on the page for them to
        fill, or a page for them to open in their browser, asked in the chat. What they fill in goes to the server
        alone, never to the model. Outside such a call, or when nobody answers, it is cancelled; a form the page
        cannot draw, or an address that is not a web page, is declined."""
        calling = runner.calling
        if calling is None:
            return {"action": "cancel"}
        card = {"type": "mcp_ask", "server": runner.name, "tool": calling["tool"],
                "message": scrub_third_party_text(str(request.get("message") or ""))[:600],
                "mode": "url" if request.get("mode") == "url" else "form"}
        if card["mode"] == "url":
            url = str(request.get("url") or "")
            if urlsplit(url).scheme != "https" and urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
                return {"action": "decline"}
            card.update(url=url[:2000], host=urlsplit(url).hostname or "")
        else:
            schema = request.get("requestedSchema")
            card["fields"] = mcp_schema.ask_fields(schema)
            if card["fields"] is None:
                return {"action": "decline"}
            self.card_schema = schema
        answer = await self.ask(card, calling["conversation"])
        action = "cancel" if answer is None else "decline" if answer == "no" else "accept"
        self.grants.log({"server": runner.name, "tool": calling["name"], "outcome": "asked_" + action,
                         "args": card["mode"]})
        if action != "accept":
            return {"action": action}
        if card["mode"] == "url":
            await asyncio.to_thread(webbrowser.open, card["url"])
            return {"action": "accept"}
        return {"action": "accept", "content": self.filled}

    # ------------------------------------------------------------ settings --

    def view(self) -> dict:
        from .shell.run import elevated
        servers = []
        for name, runner in list(self.runners.items()):
            spec = runner.spec
            missing = set(mt.expand(spec, self._held(spec))[1])
            # A value is saved when its ${NAME} is one the app holds.
            values = [{"kind": row["kind"], "name": row["name"],
                       "set": row["ref"] and all(m.group(1) not in missing for m in mt.REF_RE.finditer(row["text"]))}
                      for row in mt.secret_names(spec)]
            tools = []
            for tool in runner.tools:
                mode, changed = self.grants.mode(name, tool)
                tools.append({"name": tool["name"], "title": tool["title"],
                              "description": tool["description"][:200], "mode": mode, "changed": changed,
                              "destructive": asks_each_time(tool), "hard": tool.get("hard", ""),
                              "group": group_of(tool)})
            # The runtime Mibo can fetch for a program that is missing: "node", "uv" or "".
            need = runtimes.needed(spec.get("command", "")) if runner.error == "not_found" else ""
            if need and not runtimes.offer(need):
                need = ""
            servers.append({
                "name": name, "kind": "program" if runner.local else "address",
                "command": mt.command_line(spec) if runner.local else "",
                "url": mt.masked(spec.get("url", "")), "sse": spec.get("type") == "sse",
                "values": values, "disabled": bool(spec.get("disabled")),
                "state": runner.state, "error": runner.error, "detail": runner.detail,
                "retry_in": max(0, round(runner.retry_at - time.time())) if runner.retry_at else 0,
                "tools": tools, "cut": runner.cut,
                "write": self.grants.group(name),
                "always_start": self.grants.started(name, spec) if runner.local else False,
                "folder": str(mt.server_folder(self.home, name)),
                "signed_in": not runner.local and KeptTokens(self.home, name).signed_in(),
                "signin_url": runner.attempt.url if runner.attempt else "",
                "need": need,
            })
        fetch = {}
        for name in runtimes.RELEASES:
            if offer := runtimes.offer(name):
                task = self.fetching.get(name)
                state = "fetching" if task and not task.done() else "failed" if name in self.fetch_failed \
                    else "ready" if runtimes.ready(self.home, name) else "missing"
                fetch[name] = {**offer, "state": state, "error": self.fetch_failed.get(name, "")}
        return {"servers": servers, "bad": self.bad, "elevated": elevated(), "runtimes": fetch}


# ---------------------------------------------------------------- helpers --

def _about(instructions: str) -> str:
    """What the server says it is for, in its first sentence, short."""
    text = " ".join(str(instructions or "").split())
    first = re.split(r"(?<=[.!?。！？])\s", text, maxsplit=1)[0]
    return first[:90]


def _sample(tools: list[dict]) -> str:
    """A server that says nothing of itself: a few of its tools' names."""
    return ", ".join(t["name"] for t in tools[:4]) + (", …" if len(tools) > 4 else "")


def _shown(tool: dict) -> dict:
    return {"tool": tool["name"], "title": tool["title"],
            "description": tool["description"][:mcp_schema.OFFER_DESCRIPTION_CHARS],
            "parameters": _parameters(tool), "readonly": group_of(tool) == "read"}


def _parameters(tool: dict) -> dict:
    """The tool's parameters as the model is offered them; none when its schema cannot be offered."""
    return mcp_schema.offer_schema(tool["inputSchema"]) or {"type": "object", "properties": {}}
