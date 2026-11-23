"""Lines a module adds to a turn's context: each registers a provider (said, chat, window) -> lines, and the prompt
(prompt.py) appends what they give after its own context, in the order they registered. `window` is the model's
window in tokens, for a provider whose list grows with it."""
from __future__ import annotations

from collections.abc import Callable

Provider = Callable[[str, str, int], list]

_PROVIDERS: list[Provider] = []


def register(provider: Provider) -> None:
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def lines(said: str, chat: str, window: int) -> list[str]:
    """Every provider's lines for the person's message `said` in the chat `chat`, in registration order."""
    return [str(line) for provider in _PROVIDERS for line in provider(said, chat, window) or []]
