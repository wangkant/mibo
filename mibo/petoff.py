"""Settings' and the tray's 显示桌宠 (app.json "pet_shown"), for people who want no figure on the desktop.

Off, the figure is not drawn and takes no clicks (petoff.js), and its window waits at the bottom right of
the screen: a find still comes, as its card alone in that corner, and the character's lines go to the chat
only. The tray icon stays, to turn it on again. The pet's menu's 隐藏桌宠 turns it off too."""
from __future__ import annotations

import json
import threading

# How much of the hidden figure's cell stays on the screen at its right edge, CSS px, where nothing lies
# beyond: enough to keep the window on that monitor, so its card opens to the left of it, near the corner.
ON_SCREEN = 104


def shown(owner) -> bool:
    from .welcome import app_settings
    return app_settings(owner.storage.parent).get("pet_shown", True) is not False


def turn(owner, on: bool) -> None:
    """Kept, and done now."""
    from .welcome import save_app_settings
    save_app_settings(owner.storage.parent, pet_shown=bool(on))
    threading.Thread(target=apply, args=(owner, bool(on)), name="mibo-petoff", daemon=True).start()


def apply(owner, on: bool) -> None:
    from System.Windows.Forms import Screen

    from . import petchat
    from .window.pet import PET_MARGIN

    owner._pet_off = not on
    if not on:
        petchat.of(owner).away(fade=False)
    owner._pet.evaluate_js(f"window.petOff && petOff({json.dumps(not on)})")
    form = owner._pet.native

    def move() -> None:
        from System.Drawing import Point

        if owner._attached:
            return
        area, scale = Screen.FromHandle(form.Handle).WorkingArea, owner._pet_scale
        # Past the edge only where no other monitor lies beyond it.
        beyond = Point(area.Right + 1, area.Bottom - 1)
        past = 0 if Screen.FromPoint(beyond).Bounds.Contains(beyond) else form.Width - round(ON_SCREEN * scale)
        left, top = area.Right - form.Width + past, area.Bottom - form.Height
        before = getattr(owner, "_before_off", None)
        if on:
            # Back where it stood when it was turned off; turned off from the start, at the corner.
            left, top = before or (area.Right - form.Width - round(PET_MARGIN * scale), top)
            owner._before_off = None
        elif before is None:
            owner._before_off = (form.Left, form.Top)
        form.SetBounds(left, top, form.Width, form.Height)
        owner._ground = (form.Left, form.Bottom)
        if owner._tray is not None:
            owner._tray.Visible = not on or owner._hushed or owner.hidden

    owner._on_pet(move)
