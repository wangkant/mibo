"""One vocabulary for conversation keys, across every channel.

A conversation's key names it for routing (transport, locks, buffers) and
for memory (the chat logs) alike:

    channel        key
    -----------------------------------
    QQ group       "123456"
    QQ DM          "private:777"
    connector room "telegram:c1"
    connector DM   "private:telegram:1"

The mapping lives here alone; call sites must not re-derive it.
"""
from __future__ import annotations

#: Prefix the key of a one-to-one conversation.
DM_ROUTING_PREFIX = "private:"

#: The platform a bare (un-namespaced) key belongs to.
NATIVE_PLATFORM = "qq"

#: The platform name in the keys of the app's chats (dm.chat_key). Stored in ids, so keep it.
PAGE_PLATFORM = "browser"

#: How the conversation of a 无痕对话 of the page starts: a chat that reads no memory and leaves none.
PRIVATE_CHAT = "incognito-"


def private_chat(key: str) -> bool:
    """Is this conversation, its user id or its key a 无痕对话: never logged, kept on disk or folded."""
    return str(key or "").rsplit(":", 1)[-1].startswith(PRIVATE_CHAT)


def is_dm(routing_key: str) -> bool:
    """Is this key a one-to-one conversation rather than a room."""
    return str(routing_key or "").startswith(DM_ROUTING_PREFIX)


def platform_of(key: str) -> str:
    """The platform of a key. `private:` marks a DM, not a platform."""
    value = str(key or "")
    value = value[len(DM_ROUTING_PREFIX):] if is_dm(value) else value
    # A bare `<uid>`, and an empty platform (`private::9`), are native.
    if ":" not in value:
        return NATIVE_PLATFORM
    return value.split(":", 1)[0] or NATIVE_PLATFORM


def dm_routing_key(user_id: str) -> str:
    """The routing/memory key for a one-to-one conversation with `user_id`."""
    return f"{DM_ROUTING_PREFIX}{user_id}"


def dm_user(routing_key: str) -> str:
    """Who a one-to-one key is with; "" for a room."""
    key = str(routing_key or "")
    return key[len(DM_ROUTING_PREFIX):] if is_dm(key) else ""
