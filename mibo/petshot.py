"""The pet's menu's 保存为图片: the figure as it is now, with its card or bubble, as a PNG with a
see-through background, cut to what shows. Saved under Pictures\\Mibo and put on the clipboard."""
from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

from . import i18n


def label() -> str:
    return i18n.t("petshot.save", i18n.lang())


def save(owner) -> None:
    """From the menu: the dial goes first, then the WebView's own picture of itself is taken."""
    owner._tell(owner._pet, "hideQuick(); document.body.dataset.shot = ''")
    threading.Thread(target=_take, args=(owner,), name="mibo-share", daemon=True).start()


def _take(owner) -> None:
    from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
    from System.IO import MemoryStream

    time.sleep(0.25)
    stream, task = MemoryStream(), []
    owner._on_pet(lambda: task.append(owner._pet.native.browser.webview.CoreWebView2.CapturePreviewAsync(
        CoreWebView2CapturePreviewImageFormat.Png, stream)))
    # The capture finishes on the pet's thread, so it is waited for here.
    while not task[0].IsCompleted:
        time.sleep(0.03)
    owner._tell(owner._pet, "delete document.body.dataset.shot")
    _keep(owner, bytes(stream.ToArray()))


def _keep(owner, png: bytes) -> None:
    from PIL import Image

    picture = Image.open(io.BytesIO(png)).convert("RGBA")
    box = picture.getchannel("A").getbbox()
    if box:
        pad = 8
        box = (max(box[0] - pad, 0), max(box[1] - pad, 0),
               min(box[2] + pad, picture.width), min(box[3] + pad, picture.height))
        picture = picture.crop(box)
    out = io.BytesIO()
    picture.save(out, "PNG")
    data = out.getvalue()
    folder = Path(_pictures()) / "Mibo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / time.strftime("Mibo %Y-%m-%d %H%M%S.png")
    path.write_bytes(data)
    owner._on_pet(lambda: _copy(data))
    said = i18n.t("petshot.saved", i18n.lang())
    owner._tell(owner._pet, f"sayOne({json.dumps(said)})")


def _pictures() -> str:
    from System import Environment
    return Environment.GetFolderPath(Environment.SpecialFolder.MyPictures)


def _copy(data: bytes) -> None:
    """As PNG, which keeps the see-through background where it is pasted, and as a plain picture."""
    from System.Drawing import Bitmap
    from System.IO import MemoryStream
    from System.Windows.Forms import Clipboard, DataObject

    both = DataObject()
    both.SetData("PNG", False, MemoryStream(data))
    both.SetImage(Bitmap(MemoryStream(data)))
    Clipboard.SetDataObject(both, True)
