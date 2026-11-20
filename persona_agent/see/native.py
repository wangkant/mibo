"""Vendor computer-use tools, mapped onto the same pictures and actions.

What blocks using them from this app today: llm.py speaks only OpenAI-style
/chat/completions. Anthropic's computer toolset lives on the Messages API,
OpenAI's `computer` tool on the Responses API, Gemini's `computer_use` on the
Gemini API; through OpenRouter all three were rejected or silently dropped
when tried on 2026-11-19 (Messages: "Unknown server-tool shorthand";
/chat/completions and /responses: answered 200 with the tool removed, the model
then writing prose or a JSON point of its own). So a native tool is reachable
only with the person's own key to that vendor, through a client for that
vendor's API that llm.py does not have, plus that vendor's safety
acknowledgements (OpenAI's pending_safety_checks, Gemini's safety_decision),
which must become this app's cards, never be acknowledged by code.

What can be done cleanly, and is here: turning one native action into the
action dict `ask.read` gives (points as picture pixels of the frame that was
sent), so the same gate, cards, input and check after serve a native tool
once such a client exists, and the screenshot the tool wants back. Each
vendor's own batching (Anthropic and OpenAI send several actions a turn) is
the caller's: act in order, stop at the first that is not ok, answer the rest
as not done.
"""
from __future__ import annotations

from .frame import Frame

ANTHROPIC_TOOL = "computer_toolset_20260801"


def anthropic_tools(frame: Frame) -> list[dict]:
    """The tool entry for a Messages API request. The toolset takes its size from the screenshots returned;
    they must stay under 2576 px on the long edge (Opus 4.7 and later) or 1568 px (earlier), which
    frame.LONG_EDGE (1280) is."""
    return [{"type": ANTHROPIC_TOOL, "name": "computer"}]


def _keys(text: str) -> str:
    """xdotool-style "ctrl+shift+s" (Anthropic) or a list (OpenAI) -> "Ctrl+Shift+S"."""
    names = {"return": "Enter", "enter": "Enter", "esc": "Escape", "escape": "Escape", "tab": "Tab",
             "backspace": "Backspace", "delete": "Delete", "space": "Space", "up": "ArrowUp", "down": "ArrowDown",
             "left": "ArrowLeft", "right": "ArrowRight", "page_up": "PageUp", "page_down": "PageDown",
             "pageup": "PageUp", "pagedown": "PageDown", "home": "Home", "end": "End", "ctrl": "Ctrl",
             "control": "Ctrl", "shift": "Shift", "alt": "Alt"}
    parts = [p.strip() for p in str(text).replace(" ", "+").split("+") if p.strip()]
    return "+".join(names.get(p.lower(), p.upper() if len(p) == 1 else p) for p in parts)


def from_anthropic(name: str, args: dict) -> dict:
    """One tool_use block of the toolset (its name is the action) -> our action, or {"do": "look"} for a
    screenshot, or {"do": "unsupported"} for what is not offered (holding keys or the button down alone)."""
    at = tuple(float(v) for v in args["coordinate"]) if args.get("coordinate") else None
    if name == "screenshot":
        return {"do": "look"}
    if name in ("left_click", "double_click") and at:
        return {"do": "double_click" if name == "double_click" else "click", "at": at, "target": ""}
    if name == "left_click_drag" and at and args.get("start_coordinate"):
        return {"do": "drag", "at": tuple(float(v) for v in args["start_coordinate"]), "to": at, "target": ""}
    if name == "scroll" and at:
        direction = args.get("scroll_direction") or args.get("direction")
        if direction in ("up", "down"):
            return {"do": "scroll", "at": at, "direction": direction,
                    "amount": max(1, min(10, int(args.get("scroll_amount") or args.get("amount") or 3)))}
    if name == "type" and args.get("text"):
        return {"do": "type", "text": str(args["text"]), "target": ""}
    if name == "key" and args.get("text"):
        return {"do": "key", "key": _keys(args["text"])}
    if name == "wait":
        return {"do": "wait", "seconds": float(min(5, max(1, args.get("duration") or 1)))}
    return {"do": "unsupported", "why": f"{name} is not offered by sight"}


def from_openai(action: dict) -> dict:
    """One entry of a computer_call's `actions` (Responses API) -> our action."""
    kind = action.get("type")
    at = (float(action["x"]), float(action["y"])) if "x" in action and "y" in action else None
    if kind == "screenshot":
        return {"do": "look"}
    if kind in ("click", "double_click") and at and action.get("button", "left") == "left":
        return {"do": kind, "at": at, "target": ""}
    if kind == "drag" and len(action.get("path") or []) >= 2:
        path = action["path"]
        return {"do": "drag", "at": (float(path[0]["x"]), float(path[0]["y"])),
                "to": (float(path[-1]["x"]), float(path[-1]["y"])), "target": ""}
    if kind == "scroll" and at and action.get("scroll_y"):
        notches = max(1, min(10, abs(int(action["scroll_y"])) // 100 or 1))
        return {"do": "scroll", "at": at, "direction": "down" if action["scroll_y"] > 0 else "up", "amount": notches}
    if kind == "type" and action.get("text"):
        return {"do": "type", "text": str(action["text"]), "target": ""}
    if kind == "keypress" and action.get("keys"):
        return {"do": "key", "key": _keys("+".join(action["keys"]))}
    if kind == "wait":
        return {"do": "wait", "seconds": 1.0}
    return {"do": "unsupported", "why": f"{kind} is not offered by sight"}


def from_gemini(call: dict, frame: Frame) -> dict:
    """One Gemini computer_use function call ({"name", "args"}; points 0-999 of the screen) -> our action."""
    name, args = call.get("name"), call.get("args") or {}
    wide, high = frame.size

    def point(xk: str = "x", yk: str = "y") -> tuple[float, float]:
        return float(args[xk]) * wide / 1000, float(args[yk]) * high / 1000
    if name in ("click_at", "click") and "x" in args:
        return {"do": "click", "at": point(), "target": str(args.get("intent") or "")}
    if name == "double_click" and "x" in args:
        return {"do": "double_click", "at": point(), "target": str(args.get("intent") or "")}
    if name in ("drag_and_drop",) and "destination_x" in args:
        return {"do": "drag", "at": point(), "to": point("destination_x", "destination_y"), "target": ""}
    if name in ("type_text_at", "type") and args.get("text"):
        out = {"do": "type", "text": str(args["text"]), "target": str(args.get("intent") or "")}
        if "x" in args:
            out["at"] = point()
        return out
    if name in ("key_combination", "press_key", "hotkey") and (args.get("keys") or args.get("key")):
        return {"do": "key", "key": _keys(args.get("keys") or args.get("key"))}
    if name in ("scroll_at", "scroll_document", "scroll") and args.get("direction") in ("up", "down"):
        return {"do": "scroll", "at": point() if "x" in args else (wide / 2, high / 2),
                "direction": args["direction"], "amount": 3}
    if name in ("take_screenshot", "screenshot"):
        return {"do": "look"}
    return {"do": "unsupported", "why": f"{name} is not offered by sight"}


def screenshot_result(frame: Frame) -> dict:
    """The picture a vendor tool wants back after an action, as an image content part."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame.jpeg()}}
