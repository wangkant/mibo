"""What the page asks for itself while operate.Hands acts, put to the person on cards as Playwright's file
chooser, download and dialog events are handled: its alert closed and its words kept, its own confirm or prompt
answered Cancel and done again with OK on their yes, a file it wants given on their yes, a file it saves kept on
their yes. A mixin of operate.Hands: its state is set in Hands.__init__."""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from . import gate
from .opoutside import HEAR_S
from .opsaid import SAID
from .pagewords import clip, quote


def file_size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 ** 2 else f"{n / 1024 ** 2:.1f} MB"


class PageAsks:
    """What the page asks for itself, for operate.Hands."""

    async def _dialog(self, params: dict) -> None:
        """A page's own alert, confirm, prompt or leave-page question, answered at once: an alert closed, its words
        kept for the next line; OK for one that belongs to the press the person confirmed, or that they said yes to
        on its card (`_again`); Cancel for any other, kept for its card when a step opened it (act)."""
        kind = str(params.get("type") or "")
        words = clip(" ".join(str(params.get("message") or "").split()), 200)
        asks = gate.asks(words, str(params.get("url") or "")) if kind != "alert" else ""
        press = self._pressing
        again = self._again == (kind, words)
        ok = kind == "alert" or again or (press is not None and asks in ("dialog", "submit", press["kind"]))
        await self.tab.cdp("Page.handleJavaScriptDialog", {"accept": ok, **(
            {"promptText": str(params.get("defaultPrompt") or "")} if kind == "prompt" and ok else {})})
        said = quote(words) if words else "nothing"
        if self._noting:
            self._dialogs.append(f"{kind} {said}")
        if kind == "alert":
            self._told.append(f"[alert] the page said {said}; it was closed")
        elif again:
            return
        elif ok:
            self._told.append(f"[dialog] the page asked {said}; answered OK, as part of the press the person confirmed")
        elif self._acting and press is None:
            self._asked = {"type": kind, "words": words, "kind": asks}
        else:
            self._told.append(f"[dialog] the page asked {said} " + ("as the press went out, which is not what the "
                              "person confirmed" if press else "by itself") + "; answered Cancel")

    async def _card(self, kind: str, button: str, to: str, text: str, why: str, review: dict | None = None,
                    **more) -> dict | None:
        """A card for something the page asks for itself, with the page as the person sees it: their answer. With
        `review` (the action as the reviewer reads it) the mode is asked first: {"yes": True, "passed": line} when
        the reviewer passed it, {"turned": line} when it turned it down, else the card. An act answered before in
        this turn gets that answer again."""
        url = await self._url()
        card = {"id": secrets.token_urlsafe(8), "kind": kind, "site": gate.site_of(url), "url": url, "button": button,
                "to": to, "text": text, "label": "", "why": why, "skippable": False, **more}
        card["act"] = act = ("card", kind, card["site"], button, text)
        if act in self.kept:
            return self.kept[act]
        if review is not None:
            decision, passed, _ = await self._decided(kind, card["site"], review, where=url)
            if decision in ("go", "turned"):
                self.kept[act] = {"yes": True, "passed": passed} if decision == "go" else {"turned": passed}
                return self.kept[act]
        try:
            card["picture"] = await asyncio.wait_for(self.page.screenshot(), 3)
        except Exception:
            card["picture"] = ""
        answer = await self.ask(card)
        if answer is not None and not answer.get("waiting"):
            self.kept[act] = answer
        return answer

    async def _answered(self, action: dict, result: dict) -> dict:
        """The step opened the page's own confirm, prompt or leave-page question, answered Cancel: on a card now,
        and on the person's yes the step is done again with it answered OK."""
        asked, self._asked = self._asked, None
        said = quote(asked["words"]) if asked["words"] else "whether to leave the page"
        text = asked["words"] or (SAID[self.lang]["leave"] if asked["type"] == "beforeunload" else "")
        answer = await self._card(asked["kind"], "", "", text, f"the page's own {asked['type']}",
                                  review={"text": text, "page_says": asked["words"]})
        if answer and answer.get("turned"):
            return {**result, "status": "declined", "kind": asked["kind"],
                    "line": f"{result.get('line', '')}\n[declined] the page asked {said}; it was answered Cancel. "
                            f"{answer['turned']}".strip()}
        if answer and answer.get("waiting"):
            return {**result, "status": "waiting", "kind": asked["kind"], "result": answer["waiting"],
                    "line": f"{result.get('line', '')}\n[waiting] the page asked {said}; it was answered Cancel "
                            f"for now, and the card waits for the person's answer".strip()}
        if not (answer and answer.get("yes")):
            return {**result, "status": "declined", "kind": asked["kind"],
                    "line": f"{result.get('line', '')}\n[declined] the page asked {said}; the person "
                            f"{'said no' if answer else 'did not answer'}, so it was answered Cancel".strip()}
        self._again = (asked["type"], asked["words"])
        try:
            again = await self._act(action)
        finally:
            self._again = None
        self.confirmed = True
        return {**again, "kind": asked["kind"], "outside": True,
                "line": f"[dialog] the page asked {said}; "
                        f"{answer.get('passed') or 'the person said yes on a card'}, so the step was done again "
                        f"and it was answered OK\n{again.get('line', '')}"}

    async def _upload(self, action: dict) -> dict:
        """The step opened the page's file chooser (caught, never shown): a card names the file the person named
        (`file`, which surface.act checks was named this turn) or lets them choose one, and on their yes it goes into
        the page's file field. Nothing is chosen without that yes."""
        chooser, self._file = self._file, None
        if self.mode() == "read":
            return {"status": "failed", "kind": "upload", "line": "[read-only] the page asked for a file; the person "
                                                                  "set the browser to read only, so none was given"}
        ident, many = chooser["backendNodeId"], chooser.get("mode") == "selectMultiple"
        named = str(action.get("file") or "")
        files = [named] if named and Path(named).is_file() else []
        field = clip(self.page.last.get(ident, ("", ""))[1] or str((await self.page.facts(ident)).get("label") or ""), 40)
        # Only a file the person named goes to the reviewer; choosing one is theirs.
        answer = await self._card("upload", field, "、".join(Path(f).name for f in files), "\n".join(files),
                                  "the page asks for a file", many=many,
                                  review={"target": files, "page_says": field} if files else None)
        named = f" for {quote(field)}" if field else ""
        if answer and answer.get("turned"):
            return {"status": "declined", "kind": "upload",
                    "line": f"[declined] the page asked for a file{named}; nothing was chosen. {answer['turned']}"}
        if answer and answer.get("waiting"):
            return {"status": "waiting", "kind": "upload", "result": answer["waiting"],
                    "line": f"[waiting] the page asked for a file{named}; the card waits for the person's answer"}
        files = list(answer.get("files") or files) if answer and answer.get("yes") else []
        if not files:
            return {"status": "declined", "kind": "upload",
                    "line": f"[declined] the page asked for a file{named}; the person "
                            f"{'did not answer' if answer is None else 'gave none'}, so nothing was chosen"}
        files = files if many else files[:1]
        before = await self._seen(None)
        await self.page.cdp("DOM.setFileInputFiles", files=files, backendNodeId=ident)
        await asyncio.sleep(HEAR_S)
        self.confirmed = True
        gave = ", ".join(f"{Path(f).name} ({file_size(Path(f).stat().st_size)})" for f in files)
        return {"status": "ok", "kind": "upload", "outside": True,
                "line": f"[ok] gave {gave} to the page's file field{named}: "
                        f"{answer.get('passed') or 'the person chose it on a card'}"
                        + await self._changed(None, before, "[ok]")}

    async def _saved(self) -> str:
        """A card for each file the page began to save since the last look (the pane holds it meanwhile): saved
        to the download folder on the person's yes, dropped on no, and the run goes on either way."""
        lines = []
        for want in self.downloads():
            name = Path(want["path"]).name
            size = f" ({file_size(want['bytes'])})" if want["bytes"] else ""
            answer = await self._card("download", "", name + size, want["path"], "the page saves a file to this computer")
            yes = bool(answer and answer.get("yes"))
            await asyncio.to_thread(want["answer"], yes)
            self.confirmed = self.confirmed or yes
            lines.append(f"[download] {name}{size}: the person said yes on a card; it is saved as {want['path']}"
                         if yes else f"[declined] the page wanted to save {name}{size}; the person "
                         f"{'said no' if answer else 'did not answer'}, so nothing was saved")
        return "\n".join(lines)

    async def _page_said(self) -> str:
        """What the page said and saved by itself since the last step: its alerts and other dialogs, how its own
        navigations' cards were answered, and a card for each download."""
        navs, self._navs = self._navs, []
        for task, _ in navs:
            await task
        told, self._told = self._told, []
        return "\n".join(x for x in [*told, await self._saved()] if x)
