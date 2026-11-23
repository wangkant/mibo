"""A question a step waits on as the measuring scripts find and answer it in the app's page (cardwait.py): the
character's message marked data-ask, answered by words typed in the chat box, or for a very important step by its
card's buttons. Each is an expression for the page to evaluate."""
from __future__ import annotations

import json

# The newest question not yet taken, marked taken: its words, or "".
TAKE = ("(() => { const q = [...document.querySelectorAll('.line[data-ask]')]"
        ".filter(n => !n.dataset.bench && !n.querySelector('.ask-card.answered')).pop();"
        " if (!q) return ''; q.dataset.bench = '1'; return q.innerText; })()")


def answer(yes: bool) -> str:
    """The newest question answered: its card's button when it has one, else 确定 or 不用了 typed in the chat box on
    screen and sent. Gives the words pressed or typed."""
    return ("(yes => { const q = [...document.querySelectorAll('.line[data-ask]')].pop();"
            " const b = q?.querySelector(`.ask-card-buttons .pa-btn-${yes ? 'primary' : 'secondary'}`);"
            " if (b) { b.click(); return b.innerText; }"
            " const box = [...document.querySelectorAll('.chat-input')].find(i => i.getClientRects().length);"
            " if (!box) return ''; const words = yes ? '确定' : '不用了'; box.value = words;"
            " box.dispatchEvent(new Event('input')); box.form.requestSubmit(); return words; })"
            f"({json.dumps(yes)})")
