"""One whole turn through the page: the person's message posted to /api/chat, each question the turn raises
answered as the page does, by what the person types in the chat box or a card's button (/api/confirm), and what came
of it read back: the chat's messages in order (the request, each question and answer, the reply), its steps, its
sources, the questions, and what reached the model, round by round."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# The question routes the page polls (chat.js), one per place a step can wait.
CARD_ROUTES = {
    "shell": "/api/shell/card",
    "desk": "/api/programs/card",
    "mcp": "/api/mcp/card",
    "turnon": "/api/turnon/card",
    "settings": "/api/settings/card",
    "schedule": "/api/schedule/card",
    "operate": "/api/browser/confirm",
}
POLL_S = 0.05
# What the person types for a plain answer, and the button of a card pressed for "act" and "decline"; any other
# answer is typed as it is.
TYPED = {"yes": "确定", "no": "不用了"}
PRESSED = {"act": "yes", "decline": "no"}


def _answer(app, kind: str, card: dict, answer: str) -> dict:
    """Answers one question as the page does: an MCP server's form by its own controls, a card's button by its
    choice, every other answer by the person's message typed in the chat box. What /api/confirm said."""
    if card.get("typed") is False:
        app.post("/api/mcp/card", {"id": card["id"], "answer": "once" if answer == "yes" else "no"}, own_page=True)
        return {}
    if answer in PRESSED:
        return app.post("/api/confirm", {"id": card["id"], "choice": PRESSED[answer]}, own_page=True).json()
    return app.post("/api/confirm", {"id": card["id"], "text": TYPED.get(answer, answer)}, own_page=True).json()


@dataclass
class TurnResult:
    status: int
    reply: str
    entries: list
    cards: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    # Every message the turn added to the chat, the person's among them, in order.
    messages: list = field(default_factory=list)

    @property
    def questions(self) -> list:
        """The questions the turn said in the chat, as the character's messages."""
        return [entry for entry in self.entries if entry.get("ask")]

    @property
    def trace(self) -> list:
        """The steps the reply took, as stored with it for activity.js to draw."""
        return [step for entry in self.entries for step in entry.get("trace") or []]

    @property
    def sources(self) -> list:
        return [source for entry in self.entries for source in entry.get("sources") or []]

    def asked(self, purpose: str = "reply") -> list:
        """The bodies of this turn's model requests of one purpose, in order."""
        return [r["body"] for r in self.requests if r.get("purpose") == purpose]

    def calls(self) -> list:
        """Every tool call the model made this turn, as {"id", "name", "arguments"}, in order."""
        made = []
        for body in self.asked():
            for message in body["messages"]:
                for one in message.get("tool_calls") or []:
                    if all(one["id"] != m["id"] for m in made):
                        made.append({"id": one["id"], **one["function"]})
        return made

    def result_of(self, call_id: str) -> str | None:
        """The result the app passed back to the model for one call, read from the next request; None when no
        request carried it."""
        for body in self.asked():
            for message in body["messages"]:
                if message.get("role") == "tool" and message.get("tool_call_id") == call_id:
                    return message["content"]
        return None


def run_turn(app, message: str, *script, cards="yes", conversation: str = "main",
             attachments: list | None = None) -> TurnResult:
    """Send `message` in a chat, with `attachments` as chat.js sends them ({"kind": "picture", "data": base64});
    `script` rounds are queued on the model first. `cards` answers every question: "yes" (typed as 确定), "no"
    (typed as 不用了), any other message typed as it is, or a list taken in order. Fails when the model was asked
    something no script covers or a scripted round was never asked for."""
    model = app.model
    model.script(*script)
    seen = len(model.requests)
    answers = [cards] if isinstance(cards, str) else list(cards)
    raised: list = []
    done = threading.Event()
    sent: dict = {}

    def post() -> None:
        try:
            sent["response"] = app.post("/api/chat", {"text": message, "chat": conversation,
                                                      "attachments": attachments or []}, timeout=300)
        finally:
            done.set()

    threading.Thread(target=post, daemon=True).start()
    while not done.wait(POLL_S):
        for kind, route in CARD_ROUTES.items():
            card = app.get(route).json().get("card")
            if card and all(card["id"] != c["card"]["id"] for c in raised):
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                raised.append({"kind": kind, "card": card, "answer": answer})
                raised[-1]["said"] = _answer(app, kind, card, answer)
    response = sent["response"]
    model.check()
    assert model.left() == 0, f"{model.left()} scripted reply round(s) were never asked for"
    body = response.json()
    messages = body.get("messages") or []
    entries = [m for m in messages if m.get("role") != "user"]
    return TurnResult(response.status_code, str(body.get("reply") or ""), entries, raised, model.requests[seen:],
                      messages)
