"""One chat of the app page as the runtime database keeps it: its conversation with the character and every
message the page shows."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from . import channels, db, life

# The chat that is the character's own: what it finds arrives there. The others are plain chats.
MAIN_CHAT = "main"
# A plain chat is named by the first message sent in it, cut to TITLE_FIRST; a name given may be longer.
TITLE_FIRST, TITLE_MAX = 40, 60


def stored_names(message: dict) -> set:
    """The stored pictures and files a message shows: the character's picture, a question's picture under its
    fold, the person's attachments."""
    return {message.get("picture"), ((message.get("ask") or {}).get("detail") or {}).get("picture"),
            *(a.get("name") for a in message.get("attachments") or ())} - {None}


def memories(rows) -> list[dict]:
    """Kept items as a message carries them: {id, text}, at most six."""
    return [{"id": str(r.get("id") or "")[:64], "text": str(r.get("text") or "")[:200]}
            for r in rows or [] if isinstance(r, dict) and r.get("id")][:6]


def now_iso() -> str:
    return datetime.fromtimestamp(life.clock()).astimezone().isoformat(timespec="seconds")


class PageChat:
    """One chat of the page: its own conversation with the character and every
    message the page shows, kept in the runtime database (db.py): a row for the
    chat in page_chats, one per message in page_messages. Rows of another kind
    in page_messages are not this class's and are left as they are."""

    def __init__(self, store: db.Db, ident: str = MAIN_CHAT, row: tuple | None = None, messages=()):
        self.store, self.id = store, ident
        self.conversation, self.title, self.at, self.seq = row or (secrets.token_hex(12), "", "", 0)
        # {seq: the message as stored}: what a save compares with to write only what changed.
        self._stored = dict(messages)
        self._wipe = False
        # A 无痕对话's mark of a cleared context, held here as it has no rows (`summary`).
        self.mark: dict | None = None
        # The secrets said in this chat since the page started, masked wherever a reply repeats them.
        self._secrets: dict = {}
        self.history = [json.loads(body) for body in self._stored.values()]
        for message in self.history:
            # Sent while the page process ended: shown as not answered, to send again.
            if message.pop("pending", None):
                message["failed"] = "interrupted"
            # A question its process left waiting waits no more.
            if (message.get("ask") or {}).get("state") in ("waiting", "left"):
                message["ask"]["state"] = "unanswered"

    def tag(self) -> str:
        return hashlib.sha256(self.conversation.encode()).hexdigest()[:12]

    def append(self, entries: list[dict]) -> list[dict]:
        self.at = now_iso()
        for entry in entries:
            self.seq += 1
            entry["seq"] = self.seq
            # When it was said: the page draws its days and times from this.
            entry.setdefault("at", self.at)
        self.history = self.history + entries
        return entries

    def view(self, after: int | None = None) -> dict:
        """The chat as the page shows it; with `after`, only what came since that number.
        `chat` changes when a new chat starts, so the page knows to start over."""
        messages = [dict(m) for m in self.history if after is None or m["seq"] > after]
        summary = self.summary()
        return {"messages": messages, "chat": self.tag(), "last": self.seq,
                **({"private": True} if self.private else {}), **({"summary": summary} if summary else {})}

    def summary(self) -> dict | None:
        """The chat's checkpoint, which the character keeps as this chat's summary row (dm.py): {"text", "from":
        the time of the first turn still read whole, "at": when it was written}, or the mark of a cleared context
        (no text, "cleared": true); None before either."""
        if self.private:
            return self.mark
        rows = self.store.read("SELECT body FROM page_messages WHERE chat = ? AND kind = 'summary'", (self.id,))
        return json.loads(rows[0][0]) if rows else None

    def reset(self) -> None:
        self.conversation = secrets.token_hex(12)
        self.history = []
        self.mark = None
        self._wipe = True

    @property
    def private(self) -> bool:
        """A 无痕对话: kept in this process only, and never in the character's record or memory."""
        return channels.private_chat(self.conversation)

    def _mask(self, messages: list[dict]) -> None:
        """No ID or card number, password or code is kept in the page's copy (secretwords.mask): not in a line, its
        steps or the chat's title, nor where a reply repeats a password of theirs without its word."""
        from . import secretwords

        def masked(text: str) -> str:
            return secretwords.mask(text, self._secrets)[0]

        for m in messages:
            if m.get("role") == "user" and isinstance(m.get("text"), str):
                self._secrets.update(secretwords.secret_values(m["text"]))
        self.title = masked(self.title)
        for m in messages:
            if isinstance(m.get("text"), str):
                m["text"] = masked(m["text"])
            for step in m.get("trace") or []:
                step.update((key, masked(step[key])) for key in ("what", "out") if isinstance(step.get(key), str))
            for entry in m.get("activity") or []:
                entry["line"] = masked(entry["line"])

    def save(self) -> set:
        """Write the messages that changed, masked, and remove those that left, in one transaction; the stored
        pictures and files of the messages that left. A 无痕对话 is never written."""
        if self.private:
            return set()
        changed = [m for m in self.history
                   if self._stored.get(m["seq"]) != json.dumps(m, ensure_ascii=False)]
        self._mask(changed)
        bodies = {m["seq"]: self._stored.get(m["seq"]) for m in self.history}
        bodies.update((m["seq"], json.dumps(m, ensure_ascii=False)) for m in changed)
        left = [seq for seq in self._stored if seq not in bodies]
        with self.store.write() as conn:
            if self._wipe:
                conn.execute("DELETE FROM page_messages WHERE chat = ?", (self.id,))
            conn.execute("INSERT OR REPLACE INTO page_chats VALUES (?,?,?,?,?)",
                         (self.id, self.conversation, self.title, self.at, self.seq))
            conn.executemany("DELETE FROM page_messages WHERE chat = ? AND seq = ?", [(self.id, s) for s in left])
            conn.executemany("INSERT OR REPLACE INTO page_messages(chat, seq, body) VALUES (?,?,?)",
                             [(self.id, m["seq"], bodies[m["seq"]]) for m in changed])
        gone = set().union(*(stored_names(json.loads(self._stored[s])) for s in left))
        self._stored, self._wipe = bodies, False
        return gone

    def delete(self) -> set:
        """The chat and its messages leave the database; the stored pictures and files they showed."""
        with self.store.write() as conn:
            conn.execute("DELETE FROM page_messages WHERE chat = ?", (self.id,))
            conn.execute("DELETE FROM page_chats WHERE id = ?", (self.id,))
        self.store.scrubbed()
        return set().union(*map(stored_names, self.history))

    def listed(self) -> dict:
        return {"id": self.id, "title": self.title, "at": self.at, **({"private": True} if self.private else {})}

    def shared(self) -> list[dict]:
        """The messages that brought something the character found, oldest first."""
        return [m for m in self.history if (m.get("card") or {}).get("id")]
