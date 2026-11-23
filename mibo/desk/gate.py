"""The fixed line, in another program, between what the character may do by
itself and what goes to the reviewer or the person.

Reading, scrolling, moving the focus and typing into a document or a field are
free. The floor, the costly kinds (cardwait.COSTLY), asks the person in the chat
every time: a delete nothing restores (Shift+Delete, a program's own delete,
emptying the Recycle Bin) or throwing away unsaved work, buying, changing an
account, granting access, a binding submission, changing a setting of the
program. A delete in a file view goes to the Recycle Bin ("recycle") and opening
a file starts its program ("open"): each is asked as its own risk unless the
reviewer passes it. The browser gate's floor
vocabularies (web/gate.py) decide those by a control's name; the rest are rules
for desktop programs: Enter and the Delete key by where the focus is, the
shell's file views, a dialog's confirming button by what the dialog says, and
a program's settings window.

The reviewer judges the rest, when the mode is automatic review: writing or
replacing a file (file), printing (print), a menu command whose name does not
say what it does (press), and any act that sends something out of the window.
That last is one kind, "outward" (review.judged): the send, post, comment and
like words, a button in a window where the task typed into a field (submit),
and Enter or Ctrl+Enter in a one-line field are only readings of it, passed to
the reviewer as a hint and naming the question, never deciding whether it goes. A
name that says nothing is not taken as harmless: in a window where the task
typed into a field, a button may send what was typed unless it only closes,
goes back or opens another dialog; and a 整理 of the program's own menu goes to
the reviewer as a 删除 would go to the person. It errs inclusive: a false
positive costs one review or one press.
"""
from __future__ import annotations

import os
import re

from ..web import gate as web

KINDS = ("send", "post", "delete", "recycle", "file", "open", "order", "account", "grant", "bind", "setting", "print",
         "submit", "press")
# Buttons that send nothing typed: they close, go back, browse or explain.
NO_EFFECT = re.compile(r"^(?:cancel|close|back|previous|browse|help|minimi[sz]e|maximi[sz]e|restore|"
                       r"取消|关闭|返回|上一步|浏览|帮助|最小化|最大化|还原)(?:\b|$|\s*\()", re.I)
# Commands of a program's own menu that only edit in place or change the view.
MENU_EDIT = re.compile(r"undo|redo|copy|cut|paste|select all|find(?: next| previous)?|go to|zoom(?: in| out)?|"
                       r"restore default zoom|word wrap|font|status bar|view|new(?: tab| window)?|"
                       r"撤销|重做|复制|剪切|粘贴|全选|查找(?:下一个|上一个)?|转到|缩放|放大|缩小|恢复默认缩放|自动换行|字体|状态栏|"
                       r"查看|新建(?:标签页|窗口)?", re.I)
FILE_WORDS = web._words(
    ["save", "save as", "save all", "replace", "overwrite", "move", "move to", "move here", "paste", "rename",
     "cut and paste", "replace the file", "replace the files", "keep both"],
    ["保存", "另存为", "全部保存", "替换", "覆盖", "移动", "移动到", "粘贴", "重命名", "替换目标中的文件"])
DISCARD_WORDS = web._words(["don't save", "do not save", "discard", "discard changes", "revert"],
                           ["不保存", "放弃", "放弃更改", "还原"])
PRINT_WORDS = web._words(["print", "print now"], ["打印"])
OPEN_WORDS = web._words(["open", "run", "launch", "open with"], ["打开", "运行", "启动", "打开方式"])
SETTINGS_WORDS = re.compile(r"settings|options|preferences|properties|configuration|设置|选项|首选项|偏好|属性|配置",
                            re.I)
CONFIRM = re.compile(r"^(?:ok|okay|yes|continue|confirm|apply|done|finish|确定|是|继续|确认|应用|完成)(?:\b|$|\s*\()",
                     re.I)
SEARCH = re.compile(r"search|find|filter|查找|搜索|筛选|过滤", re.I)
# Windows' own find and replace dialog (class #32770, as in Notepad): its Replace buttons edit the document.
REPLACE_IN_TEXT = re.compile(r"(?:replace(?: all)?|全部替换|替换)(?:\s*\(&?\w\))?", re.I)
FIND_FIELD = re.compile(r"find what|查找内容", re.I)
# The menu item that opens that dialog ("Replace...", "替换(R)..."): it changes nothing by itself.
OPENS_REPLACE = re.compile(r"(?:replace|替换)(?:\s*\(&?\w\))?\s*(?:\.\.\.|…)", re.I)
# A delete past the Recycle Bin, by its words; one into it.
FOR_GOOD = re.compile(r"permanent|for good|永久|彻底|徹底", re.I)
TO_BIN = re.compile(r"\b(?:move|send)\b.{0,60}\bto\s+the\s+recycle\s+bin|(?:移动?到|移至|放入)回收站", re.I)
# The shell's views of files and folders (File Explorer and the common file dialog).
SHELL_CLASSES = {"UIItem", "UIItemsView", "UIProperty", "SysTreeView32", "DirectUIHWND", "ShellTabWindowClass"}


def _chain(node) -> list:
    out = []
    while node is not None:
        out.append(node)
        node = node.parent
    return out


def in_shell_view(node) -> bool:
    return any(n.cls in SHELL_CLASSES for n in _chain(node))


def in_settings(node, title: str) -> bool:
    return bool(SETTINGS_WORDS.search(title)) or any(
        n.role in ("window", "pane", "group", "tablist", "tab") and SETTINGS_WORDS.search(n.name)
        for n in _chain(node)[1:])


def by_name(name: str) -> tuple[str, str] | None:
    """The kind a control's name alone gives, in another program: the floor kinds first, then file and print,
    then the readings of an outward act (send, post)."""
    if web.PAY_WORDS.search(name):
        return "order", f"the name {name!r} is payment vocabulary"
    if DISCARD_WORDS.search(name):
        return "delete", f"{name!r} throws away unsaved work"
    if TO_BIN.search(name) and not FOR_GOOD.search(name):
        return "recycle", f"{name!r} moves files to the Recycle Bin"
    if web.DELETE_WORDS.search(name) or re.search(r"recycle bin|回收站", name, re.I):
        return "delete", f"the name {name!r} is destructive vocabulary"
    if web.ACCOUNT_WORDS.search(name):
        return "account", f"the name {name!r} changes an account"
    if web.GRANT_WORDS.search(name):
        return "grant", f"the name {name!r} grants access"
    if web.BIND_WORDS.search(name):
        return "bind", f"the name {name!r} signs or files a binding submission"
    if PRINT_WORDS.search(name):
        return "print", f"the name {name!r} prints"
    if FILE_WORDS.search(name):
        return "file", f"the name {name!r} writes, moves or replaces files"
    if web.SEND_WORDS.search(name):
        return "send", f"the name {name!r} sends"
    if web.POST_WORDS.search(name) or web.COMMENT_WORDS.search(name) or web.LIKE_WORDS.search(name) or (
            web.LIKE_EXACT.match(name.strip())):
        return "post", f"the name {name!r} posts or reacts in public"
    return None


def press(node, title: str, main: bool, dialog_text: str, folder_item: bool | None = None, do: str = "invoke",
          program: str = "", typed: bool = False) -> tuple[str, str]:
    """(kind, why) of pressing `node` (`do`: invoke, click, toggle, select, expand, collapse): kind "" when it
    is free. `title` is its window's title, `main` whether that is the program's target window rather than a
    dialog it opened, `dialog_text` the words of that dialog, `folder_item` for a shell item whether it is a
    folder (None: not known), `program` the executable's file name, `typed` whether this task typed into a
    one-line field of that window."""
    name = " ".join(str(node.name or "").split())[:200]
    if node.role in ("listitem", "treeitem", "row") and in_shell_view(node):
        if do in ("select", "expand", "collapse"):
            return "", "selecting or unfolding an item"
        return ("", "a folder opens in the same window") if folder_item else (
            "open", f"{name!r} is a file (or not known to be a folder): opening it starts its program")
    if program == "explorer.exe" and re.fullmatch(r"rename|重命名", name, re.I):
        return "", "it only opens the name for editing; Enter or the new name is what asks"
    if in_settings(node, title) and (node.role in ("checkbox", "radio", "combobox", "slider", "listitem")
                                     or CONFIRM.search(name) or FILE_WORDS.search(name)):
        return "setting", f"{name!r} in the program's settings ({title[:60]!r})"
    if (program == "explorer.exe" or in_shell_view(node)) and web.DELETE_WORDS.search(name) and not (
            FOR_GOOD.search(name) or re.search(r"recycle bin|回收站", name, re.I)):
        return "recycle", f"{name!r} in File Explorer moves the selected files to the Recycle Bin"
    if not main and REPLACE_IN_TEXT.fullmatch(name) and FIND_FIELD.search(dialog_text) and _common_dialog(node.top):
        return "", "it replaces words inside the document, from the find and replace dialog"
    if node.role == "menuitem" and OPENS_REPLACE.fullmatch(name) and not in_shell_view(node):
        return "", "it opens the find and replace dialog"
    named = by_name(name)
    if named:
        return named
    if not main and CONFIRM.search(name):
        said = by_name(dialog_text) if dialog_text else None
        if said:
            return said[0], f"{name!r} confirms a dialog that says: {dialog_text[:120]!r}"
        if re.search(r"replace|overwrite|already exists|替换|覆盖|已存在", dialog_text, re.I):
            return "file", f"{name!r} confirms replacing a file"
    if node.role in ("menuitem", "button") and OPEN_WORDS.fullmatch(name.strip()) and in_shell_view(node):
        return "open", f"{name!r} opens the selected file in its program"
    bare = re.sub(r"\s*\(&?\w\)|&", "", name).strip()
    opens = bare.endswith(("...", "…"))
    if do in ("invoke", "click") and not opens:
        if typed and node.role == "button" and not NO_EFFECT.search(bare):
            return "submit", f"{name!r} in a window where this task typed into a field: it may send what was typed"
        if (node.role == "menuitem" and "expand" not in (node.patterns or []) and not in_shell_view(node)
                and bare and not MENU_EDIT.fullmatch(bare)):
            return "press", f"{name!r} is a command of the program's own menu whose name does not say what it does"
    return "", "reading or moving about"


def key(keys: str, focused, title: str, main: bool, dialog_text: str) -> tuple[str, str]:
    """(kind, why) of one keystroke, by the key and where the focus is."""
    k = keys.replace(" ", "").lower()
    role = focused.role if focused is not None else ""
    name = " ".join(str(getattr(focused, "name", "") or "").split())[:120]
    editing = role in ("textbox", "document")
    if k in ("ctrl+enter", "alt+s", "ctrl+shift+enter"):
        return "send", f"{keys} sends in most programs"
    if k == "ctrl+s":
        return "file", f"{keys} saves, overwriting the file ({title[:60]!r})"
    if k == "ctrl+p":
        return "print", f"{keys} prints"
    if focused is not None and in_shell_view(focused):
        if k == "shift+delete":
            return "delete", f"{keys} deletes the selected files for good, past the Recycle Bin"
        if k in ("delete", "ctrl+d"):
            return "recycle", f"{keys} moves the selected files to the Recycle Bin"
        if k in ("ctrl+v", "ctrl+shift+v", "ctrl+z", "ctrl+y"):
            return "file", f"{keys} in a file view pastes, moves back or redoes files"
        if k == "enter" and role == "textbox":
            return "file", "Enter renames the file"
        if k == "enter":
            return "open", "Enter opens the selected item"
    if k in ("delete", "shift+delete") and not editing:
        return "delete", f"{keys} deletes {name or 'the selected item'!r}"
    if k in ("enter", "space"):
        if role in ("button", "menuitem", "link", "checkbox", "radio", "listitem", "treeitem", "tab"):
            return press(focused, title, main, dialog_text)
        if role == "document" or (role == "textbox" and focused.hwnd and _multiline(focused.hwnd)):
            return "", "a new line in a document"
        if role == "textbox" and k == "enter":
            if SEARCH.search(name) or SEARCH.search(getattr(focused, "auto", "")):
                return "", "Enter in a search box"
            return "submit", f"Enter in {name or 'a field'!r} submits or sends what it holds"
    if not main and k == "enter" and CONFIRM.search(dialog_text[:40]):
        said = by_name(dialog_text)
        if said:
            return said[0], f"Enter confirms a dialog that says: {dialog_text[:120]!r}"
    if not main and not editing and re.fullmatch(r"(?:alt\+)?[a-z0-9]", k):
        # A letter presses a dialog's button by its access key (Y for Yes, N for Don't save).
        said = by_name(dialog_text)
        if said:
            return said[0], f"{keys} may press a button of a dialog that says: {dialog_text[:120]!r}"
        if re.search(r"replace|overwrite|already exists|替换|覆盖|已存在", dialog_text, re.I):
            return "file", f"{keys} may confirm replacing a file"
    return "", "moving about or editing"


def set_text(node, text: str, title: str) -> tuple[str, str]:
    """(kind, why) of putting `text` into a field: free, except a file's name in a file view (setting it
    renames the file at once) and a setting of the program."""
    if in_shell_view(node) and (node.role in ("listitem", "row", "treeitem") or node.cls == "UIProperty"
                                or (node.parent is not None and node.parent.role == "listitem")):
        return "file", "setting an item's name in a file view renames the file"
    if in_settings(node, title):
        return "setting", f"a field in the program's settings ({title[:60]!r})"
    return "", "typing into a field"


def address_ok(text: str) -> bool:
    """File Explorer's address bar runs what is typed into it: only an existing folder may go there."""
    return os.path.isdir(os.path.expandvars(text.strip().strip('"')))


def _common_dialog(hwnd: int) -> bool:
    from . import win32
    return win32.class_of(hwnd) == "#32770"


def _multiline(hwnd: int) -> bool:
    from . import win32
    return win32.multiline(hwnd)
