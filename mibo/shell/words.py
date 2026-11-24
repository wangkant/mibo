"""What a command will do, in plain written words made by the app from its reading: the step log line while it
runs and after, the question's lines before it runs, the reason it is refused. Never the model's own words."""
from __future__ import annotations

import os
import re
import shutil
import sys

from . import office
from .acts import CODE_SIGNS, NEVER_KINDS, Act, Reading
from .grants import known_folders, norm
from .read import Verdict

_NAMES: dict = {}
# Characters that turn text around or hide in it ("photo<RLO>gpj.exe" shows as "photoexe.jpg"): shown by code.
_HIDING = re.compile("[\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def visible(text: str) -> str:
    """Text for the card and the step log with its direction and invisible marks shown, not obeyed, and valid
    Unicode: a lone surrogate (a model's JSON can carry half an emoji, a file name half a pair) becomes U+FFFD."""
    whole = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return _HIDING.sub(lambda m: f"[U+{ord(m.group()):04X}]", whole)


def _known() -> dict:
    if not _NAMES:
        _NAMES.update({norm(row["path"]): (row["zh"], row["en"]) for row in known_folders()} or {"": ("", "")})
    return _NAMES


def folder_name(path: str, lang: str) -> str:
    """A folder as the person knows it: 下载 for Downloads, else its own name."""
    named = _known().get(norm(path))
    if named:
        return named[0] if lang == "zh" else named[1]
    return os.path.basename(path.rstrip("\\/")) or path


def quote(text: str, lang: str) -> str:
    text = visible(text)
    return f"「{text}」" if lang == "zh" else f"“{text}”"


def shown(path: str, raw: str, lang: str) -> str:
    """One place, short: a pattern as the files it means, a folder by its name, a file by its name."""
    if raw and any(c in raw for c in "*?"):
        pattern = os.path.basename(raw.replace("/", "\\")) or raw
        if pattern.startswith("*.") and not any(c in pattern[2:] for c in "*?"):
            return f"所有 {pattern[1:]} 文件" if lang == "zh" else f"all {pattern[1:]} files"
        return quote(pattern, lang)
    if os.path.isdir(path):
        return quote(folder_name(path, lang), lang)
    return quote(os.path.basename(path.rstrip("\\/")) or path, lang)


def _places(act: Act, lang: str) -> str:
    # Items from a listing before may be named by what it listed.
    places = act.listed or act.paths
    raws = act.raw or [""] * len(places)
    items = [shown(p, r, lang) for p, r in zip(places, raws + [""] * len(places))]
    items = list(dict.fromkeys(items))
    if not items:
        return "这些文件" if lang == "zh" else "the files"
    if len(items) > 3:
        return (f"{'、'.join(items[:3])} 等 {len(items)} 项" if lang == "zh"
                else f"{', '.join(items[:3])} and {len(items) - 3} more")
    return "、".join(items) if lang == "zh" else ", ".join(items)


# act.what: (Chinese, English while doing, English when done). {p} the places, {d} where to, {n} a name.
PHRASES = {
    "list": ("列出{p}中的文件", "Listing the files in {p}", "Listed the files in {p}"),
    "look": ("查看{p}", "Looking at {p}", "Looked at {p}"),
    "read": ("读取{p}", "Reading {p}", "Read {p}"),
    "search": ("在{p}中查找文字", "Searching the text of {p}", "Searched the text of {p}"),
    "disk": ("查看磁盘空间", "Checking the disk space", "Checked the disk space"),
    "info": ("查看本机信息", "Looking up this computer's facts", "Looked up this computer's facts"),
    "apps": ("查看程序", "Looking at the programs", "Looked at the programs"),
    "mkdir": ("新建文件夹{p}", "Making the folder {p}", "Made the folder {p}"),
    "newfile": ("新建文件{p}", "Making the file {p}", "Made the file {p}"),
    "copy": ("将{p}复制到{d}", "Copying {p} to {d}", "Copied {p} to {d}"),
    "move": ("将{p}移到{d}", "Moving {p} to {d}", "Moved {p} to {d}"),
    "rename": ("将{p}重命名为{d}", "Renaming {p} to {d}", "Renamed {p} to {d}"),
    "delete": ("将{p}移到回收站", "Moving {p} to the Recycle Bin", "Moved {p} to the Recycle Bin"),
    "empty": ("清空{p}的内容", "Emptying {p}", "Emptied {p}"),
    "write": ("写入{p}", "Writing {p}", "Wrote {p}"),
    "append": ("在{p}末尾添加内容", "Adding to the end of {p}", "Added to the end of {p}"),
    "attr": ("更改{p}的属性", "Changing the properties of {p}", "Changed the properties of {p}"),
    "zip": ("将{p}压缩到{d}", "Zipping {p} into {d}", "Zipped {p} into {d}"),
    "unzip": ("将{p}解压到{d}", "Unzipping {p} into {d}", "Unzipped {p} into {d}"),
    "open": ("打开{p}", "Opening {p}", "Opened {p}"),
    "net": ("连接 {n}", "Reaching {n}", "Reached {n}"),
    "browse": ("在浏览器中打开 {n}", "Opening {n} in the browser", "Opened {n} in the browser"),
    "install": ("安装或卸载软件", "Installing or removing software", "Installed or removed software"),
    "program": ("运行程序 {n}", "Running {n}", "Ran {n}"),
    "inline": ("运行命令中写出的代码", "Running code written in the command", "Ran code written in the command"),
    "script": ("运行脚本 {n}", "Running the script {n}", "Ran the script {n}"),
    "written": ("运行本次写入的脚本 {n}", "Running the script {n} written in this task",
                "Ran the script {n} written in this task"),
    "code": ("由代码连接 {n}", "Its code reaching {n}", "Its code reached {n}"),
    "stop": ("关闭程序", "Closing a program", "Closed a program"),
    "clipboard": ("读取剪贴板", "Reading the clipboard", "Read the clipboard"),
    "setting": ("更改 Windows 设置", "Changing a Windows setting", "Changed a Windows setting"),
    "share": ("访问网络共享 {n}", "Reaching the network share {n}", "Reached the network share {n}"),
}


def _host(act: Act, lang: str) -> str:
    """The address an act reaches; one computed as it runs is said so, not shown as "?"."""
    if act.host == "?":
        return "运行时确定的地址" if lang == "zh" else "an address worked out only as it runs"
    return act.host


def program_file(act: Act) -> str:
    """The program or script file an act runs: its path when the command names one, else found on PATH."""
    if act.paths and act.name.startswith(act.paths[0]):
        return act.paths[0]
    first = act.name.split(" ")[0]
    return shutil.which(first) or "" if first else ""


def program_name(act: Act) -> str:
    """A program as people know it: the name in its file's version resource (as desk/grants.py names programs),
    else the file's own name."""
    path = program_file(act)
    if path and sys.platform == "win32" and os.path.isfile(path):
        from ..desk.win32 import file_facts
        facts = file_facts(path)
        if facts.get("FileDescription") or facts.get("ProductName"):
            return facts.get("FileDescription") or facts["ProductName"]
    return os.path.basename(path) if path else os.path.basename(act.name.split(" ")[0])


def phrase(act: Act, lang: str, form: str) -> str:
    row = PHRASES.get(act.what)
    if row is None:
        return ""
    text = row[0] if lang == "zh" else (row[1] if form in ("ing", "card") else row[2])
    dest = ""
    if act.dest:
        dest = quote(os.path.basename(act.dest.rstrip("\\/")), lang) if act.what == "rename" else (
            quote(folder_name(act.dest, lang), lang))
    if act.what in ("net", "share", "browse", "code"):
        name = _host(act, lang) or os.path.basename(act.name.split(" ")[0])
    else:
        name = program_name(act) if act.name else ""
    return text.format(p=_places(act, lang), d=dest, n=visible(name) or ("网络" if lang == "zh" else "the network"))


def summary(reading: Reading, lang: str, form: str) -> str:
    """The step log line: what the command does, its first two acts; "正在…" while it runs."""
    parts = list(dict.fromkeys(p for p in (phrase(a, lang, form) for a in reading.acts if a.what != "look"
                                           or len(reading.acts) == 1) if p))
    if not parts:
        parts = list(dict.fromkeys(p for p in (phrase(a, lang, form) for a in reading.acts) if p))
    if not parts:
        if lang == "zh":
            return {"ing": "正在运行一条命令", "ed": "已运行一条命令"}.get(form, "运行一条无法预先确定作用的命令")
        return {"ing": "Running a command", "ed": "Ran a command"}.get(
            form, "Run a command whose effect cannot be told first")
    # A part that cannot be read leads, so a card's title never makes a delete look like a lookup.
    if any(a.kind == "unknown" and a.what not in CODE_SIGNS and not phrase(a, lang, form) for a in reading.acts):
        parts.insert(0, "执行无法预先解析的操作" if lang == "zh" else (
            "Did something that could not be read first" if form == "ed" else "Doing something that cannot be read first"))
    if lang == "zh":
        text = "，再".join(parts[:2]) + ("等" if len(parts) > 2 else "")
        return ("正在" + text) if form == "ing" else text
    return ", then ".join([parts[0]] + [p[0].lower() + p[1:] for p in parts[1:2]]) + (" and more" if len(parts) > 2 else "")


def size(n: int, lang: str) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} 字节" if lang == "zh" else f"{n} bytes"


# What a system change points at, which its question names: a link's or a junction's target, a scheduled task's
# action, a Run key's command, a hard link's file.
POINTS = re.compile(r"""(?:-Target|-Execute|-Argument|/tr|/d)\s+("[^"]*"|'[^']*'|[^\s)]+)|"""
                    r"""\bhardlink\s+create\s+\S+\s+("[^"]*"|\S+)|\bmklink\b.*?\s("[^"]*"|\S+)\s*$|"""
                    r"""\\run(?:once)?\b.*?-Value\s+("[^"]*"|'[^']*'|[^\s)]+)""", re.I)


def points_to(command: str) -> list[str]:
    """What a command's system change points at (POINTS), as written."""
    return list(dict.fromkeys(next(g for g in m.groups() if g).strip("'\"") for m in POINTS.finditer(command)))


def card_lines(reading: Reading, verdict: Verdict, lang: str) -> list[str]:
    """The question's lines: each reason the command needs the person's yes, said plainly, with the real list
    of what a delete moves to the Recycle Bin and what an overwrite replaces."""
    zh = lang == "zh"
    lines: list[str] = []
    # A program's own file is outside the granted folders by nature; the line that runs it says enough.
    programs = {norm(program_file(a)) for a in reading.acts if a.kind == "program" and program_file(a)}
    many = len(verdict.deletes) > 3
    if many:
        # Many items, from a wildcard or a listing: one line with the count, the total and the first names.
        count, total = sum(d["files"] for d in verdict.deletes), sum(d["bytes"] for d in verdict.deletes)
        names = [os.path.basename(d["path"].rstrip("\\/")) for d in verdict.deletes[:8]]
        more = (" 等" if zh else " and more") if len(verdict.deletes) > 8 else ""
        lines.append(f"将 {len(verdict.deletes)} 项移到回收站（共 {count} 个文件，{size(total, lang)}）：{'、'.join(names)}{more}"
                     if zh else f"Move {len(verdict.deletes)} items to the Recycle Bin ({count} files, "
                     f"{size(total, lang)}): {', '.join(names)}{more}")
    for item in verdict.deletes:
        name = os.path.basename(item["path"].rstrip("\\/"))
        names = "、".join(item["names"][:8]) if zh else ", ".join(item["names"][:8])
        more = item["files"] > len(item["names"][:8]) or item.get("more")
        if not many and os.path.isdir(item["path"]) and not os.path.islink(item["path"]):
            if item["files"] == 0 and item["folders"] == 0:
                lines.append(f"将空文件夹「{name}」移到回收站" if zh else f"Move the empty folder “{name}” to the Recycle Bin")
            elif zh:
                lines.append(f"将文件夹「{name}」移到回收站，连同其中 {item['files']} 个文件（共 "
                             f"{size(item['bytes'], lang)}）：{names}{' 等' if more else ''}")
            else:
                lines.append(f"Move the folder “{name}” to the Recycle Bin with the {item['files']} files in it "
                             f"({size(item['bytes'], lang)}): {names}{' and more' if more else ''}")
        elif not many:
            lines.append(f"将「{name}」移到回收站（{size(item['bytes'], lang)}）" if zh
                         else f"Move “{name}” to the Recycle Bin ({size(item['bytes'], lang)})")
        if item.get("links"):
            lines.append(f"其中包含 {len(item['links'])} 个快捷链接，仅删除链接本身" if zh
                         else f"It holds {len(item['links'])} links; only the links themselves are removed")
    if verdict.overwrites:
        names = [os.path.basename(p) for p in verdict.overwrites[:6]]
        lines.append(("覆盖现有文件：" + "、".join(names)) if zh else ("Replace files that are there: " + ", ".join(names)))
    for act in verdict.reasons:
        line = ""
        if act.kind == "delete" and not verdict.deletes:
            line = ("将" + _places(act, lang) + "移到回收站（无法预先列出具体文件）") if zh else (
                f"Move {_places(act, lang)} to the Recycle Bin (which files could not be listed first)")
        elif act.kind == "overwrite" and not verdict.overwrites:
            line = (f"覆盖现有文件：{_places(act, lang)}") if zh else f"Replace a file that is there: {_places(act, lang)}"
        elif act.kind == "outside":
            where = act.paths[0] if act.paths else (act.host or "")
            if act.paths and norm(where) in programs:
                continue
            if act.what == "clipboard":
                line = "读取剪贴板内容" if zh else "Read what is on the clipboard"
            else:
                line = (f"{'写入' if act.write else '读取'}授权文件夹以外的位置：{where}" if zh
                        else f"{'Write to' if act.write else 'Read'} a place outside the folders you allowed: {where}")
        elif act.kind == "move_out":
            line = f"将文件移出授权文件夹，移至「{folder_name(act.dest, lang)}」" if zh else (
                f"Move files out of the folder you allowed, to “{folder_name(act.dest, lang)}”")
        elif act.kind == "network":
            host = _host(act, lang) or ("网络" if zh else "the network")
            if act.what == "browse":
                line = f"在浏览器中打开 {host}" if zh else f"Open {host} in your browser"
            elif act.what == "code":
                line = f"代码会连接网络（{host}），同意后才可联网运行" if zh else (
                    f"The code reaches the network ({host}); it runs online only with your yes")
            elif act.sends:
                line = f"通过网络向 {host} 发送数据" if zh else f"Send data over the network to {host}"
            else:
                line = f"连接网络，从 {host} 获取内容，不发送你的文件" if zh else (
                    f"Use the network to fetch from {host}; none of your files are sent")
            if act.paths:
                line += (f"，保存为{_places(act, lang)}" if zh else f", saved as {_places(act, lang)}")
        elif act.kind == "install":
            line = f"安装或卸载软件：{act.name}" if zh else f"Install or remove software: {act.name}"
        elif act.what == "runs_later":
            line = (f"写入之后会自行运行或被程序加载的位置：{_places(act, lang)}" if zh else
                    f"Write where it runs or is loaded later by itself: {_places(act, lang)}")
        elif act.what == "system":
            line = f"更改系统：{act.name or act.why}" if zh else f"Change the system: {act.name or act.why}"
            aims = points_to(reading.command)
            if aims and line not in lines:
                lines.append(line)
                line = ("指向：" + "、".join(aims)) if zh else ("It points to: " + ", ".join(aims))
        elif act.kind == "program":
            if act.what == "new_runnable":
                line = f"新建可运行的文件：{act.name}" if zh else f"Make a file that runs when opened: {act.name}"
            elif act.what == "inline":
                line = f"运行命令行中写出的代码：{act.name}" if zh else f"Run the code written in the command: {act.name}"
            elif act.what == "project_file":
                line = f"写入项目工具会运行的文件：{act.name}" if zh else f"Write a file the project's tools run: {act.name}"
            elif act.what == "written":
                line = f"运行本次任务中写入的脚本：{act.name}" if zh else f"Run a script written in this task: {act.name}"
            elif act.what == "stop":
                line = f"关闭正在运行的程序：{act.name}" if zh else f"Close a running program: {act.name}"
            elif act.what == "script":
                line = f"运行脚本：{act.name}（无法预先确定其操作）" if zh else (
                    f"Run the script {act.name} (what it does cannot be read first)")
            else:
                line = f"运行程序：{act.name}（无法预先确定其操作）" if zh else (
                    f"Run the program {act.name} (what it does cannot be read first)")
        elif act.what == "setting":
            line = f"更改 Windows 设置：{act.name}" if zh else f"Change a Windows setting: {act.name}"
        elif act.what == "unresolved":
            line = "此命令在运行时才确定处理哪些文件，无法预先列出" if zh else (
                "Which files it works on is decided only as it runs, so it cannot be known first")
        elif act.what == "pieces":
            line = "代码由片段拼出要读取或运行的内容，无法预先看清" if zh else (
                "The code builds what it reads or runs from pieces, so it cannot be seen first")
        elif act.what == "read_outside":
            line = "本次任务已读取网页、消息或外部文件，此步骤可能受其内容影响" if zh else (
                "This task has read a page, a message or an outside file, and this step may follow what it said")
        elif act.what == "from_outside":
            line = "此命令的内容来自本次读取的网页、消息或文件，并非你的消息" if zh else (
                "This command's text comes from a page, message or file read in this task, not from your messages")
        elif act.kind == "unknown":
            line = "Mibo 无法预先确定此命令的全部作用。可请 Mibo 改用作用明确的做法。" if zh else (
                "Mibo cannot tell beforehand all that this command will do. You can ask Mibo for a way whose "
                "effect is clear.")
        if line and line not in lines:
            lines.append(line)
    if any(a.kind in ("program", "install") or (a.kind == "unknown" and a.what != "from_outside")
           for a in verdict.reasons):
        # As with Claude Code's checkpoints: undo puts files back, not what a program the command runs does.
        lines.append("撤销仅能还原文件，此命令的其他作用无法撤销" if zh else
                     "Undo puts back files only, not this command's other effects")
    return lines


REFUSED = {
    "elevate": ("需要管理员权限", "it needs administrator rights"),
    "system": ("会更改系统或安全设置", "it changes the system or its security"),
    "secrets": ("会读取密码、密钥、浏览器资料或其他程序的私密数据", "it reaches passwords, keys, browser profiles or other programs' private data"),
    "app": ("涉及 Mibo 的设置和模型密钥", "it touches Mibo's own settings and model key"),
    "hidden": ("隐藏了真实用途", "it hides what it really does"),
    "shutdown": ("会关机、重启或注销", "it shuts down, restarts or signs out"),
    "downloaded": ("会运行从网络下载的程序或脚本", "it runs a program or script downloaded from the web"),
}


# The step's label for a refused part that has no phrase of its own.
REFUSED_PART = {
    "elevate": ("以管理员身份运行", "Run as administrator"),
    "system": ("更改系统或安全设置", "Change the system or its security"),
    "secrets": ("读取私密数据", "Read private data"),
    "app": ("访问 Mibo 的设置和模型密钥", "Reach Mibo's own settings and model key"),
    "hidden": ("运行隐藏真实用途的命令", "Run a command that hides what it does"),
    "shutdown": ("关机、重启或注销", "Shut down, restart or sign out"),
    "downloaded": ("运行从网络下载的程序或脚本", "Run a program or script downloaded from the web"),
}
# Refusals named by what they are rather than by their kind.
REFUSED_WHAT = ("app", "downloaded")


def refused_said(reading: Reading, verdict: Verdict, lang: str) -> str:
    """The step's label for a refused command: the part that was refused, not the harmless part beside it."""
    touched = {norm(p) for a in verdict.reasons for p in a.paths}
    parts = []
    for act in reading.acts:
        if act.kind in NEVER_KINDS:
            parts.append(phrase(act, lang, "card") or REFUSED_PART[act.kind][0 if lang == "zh" else 1])
        elif touched & {norm(p) for p in act.paths + ([act.dest] if act.dest else [])}:
            parts.append(phrase(act, lang, "card"))
    parts += [REFUSED_PART[a.what if a.what in REFUSED_WHAT else a.kind][0 if lang == "zh" else 1]
              for a in verdict.reasons if not parts and (a.kind in REFUSED_PART or a.what in REFUSED_WHAT)]
    parts = list(dict.fromkeys(p for p in parts if p))
    return ("，" if lang == "zh" else ", ").join(parts[:2]) or summary(reading, lang, "card")


def refused(verdict: Verdict, lang: str) -> str:
    """Why a command is never run, in a sentence."""
    zh = lang == "zh"
    keys = list(dict.fromkeys(a.what if a.what in REFUSED_WHAT else a.kind for a in verdict.reasons
                              if a.kind in REFUSED or a.what in REFUSED_WHAT))
    said = [REFUSED[k][0 if zh else 1] for k in keys if k in REFUSED]
    if zh:
        return "此操作" + "，并且".join(said or ["超出允许的范围"]) + "，Mibo 从不执行。"
    return "This is never done: " + "; ".join(said or ["it is outside what is allowed"]) + "."


def file_doing(op: str, args: dict, lang: str, done: bool = False) -> str:
    """The waiting row's words for a file tool before it is judged (and the step's words when nothing better
    came back): 正在读取「a.txt」, Reading “a.txt”."""
    zh = lang == "zh"

    def name(key: str) -> str:
        raw = str(args.get(key) or "").strip().rstrip("\\/")
        return quote(os.path.basename(raw) or raw, lang) if raw else (quote(folder_name(str(args.get("folder") or ""), lang), lang)
                                                                       if args.get("folder") else ("当前文件夹" if zh else "the folder"))

    count = len(args.get("moves") or args.get("paths") or [])
    rows = {
        "read": (f"读取{name('path')}", f"Reading {name('path')}", f"Read {name('path')}"),
        "list": (f"列出{name('path')}中的文件", f"Listing the files in {name('path')}", f"Listed the files in {name('path')}"),
        "search": (f"在{name('path')}中查找{quote(str(args.get('text') or ''), lang)}",
                   f"Searching {name('path')} for {quote(str(args.get('text') or ''), lang)}",
                   f"Searched {name('path')} for {quote(str(args.get('text') or ''), lang)}"),
        # A Word, Excel or PowerPoint file is made from the model's text, not written as it is.
        "write": (f"生成{name('path')}", f"Making {name('path')}", f"Made {name('path')}")
        if os.path.splitext(str(args.get("path") or "").strip())[1].lower() in office.KINDS else
        (f"写入{name('path')}", f"Writing {name('path')}", f"Wrote {name('path')}"),
        "edit": (f"修改{name('path')}", f"Changing {name('path')}", f"Changed {name('path')}"),
        "open": (f"打开{name('path')}", f"Opening {name('path')}", f"Opened {name('path')}"),
        "move": ((f"复制 {count} 项" if args.get("copy") else f"移动 {count} 项"),
                 (f"Copying {count} items" if args.get("copy") else f"Moving {count} items"),
                 (f"Copied {count} items" if args.get("copy") else f"Moved {count} items")),
        "delete": (f"将 {count} 项移到回收站", f"Moving {count} items to the Recycle Bin",
                   f"Moved {count} items to the Recycle Bin"),
    }
    row = rows.get(op, ("处理文件", "Working on files", "Worked on files"))
    if zh:
        return row[0] if done else "正在" + row[0]
    return row[2] if done else row[1]


def move_said(moves: list[dict], copy: bool, lang: str) -> str:
    """The step's words for a move: 把「a.txt」改名为「b.txt」, 移动 3 项到「图片」「文档」."""
    zh = lang == "zh"
    first = moves[0]
    if len(moves) == 1 and not copy and os.path.dirname(first["from"]).lower() == os.path.dirname(first["to"]).lower():
        a, b = quote(os.path.basename(first["from"]), lang), quote(os.path.basename(first["to"]), lang)
        return f"将{a}重命名为{b}" if zh else f"Renamed {a} to {b}"
    places = ("" if zh else ", ").join(dict.fromkeys(quote(os.path.basename(os.path.dirname(m["to"])), lang) for m in moves))
    if zh:
        return f"{'复制' if copy else '移动'} {len(moves)} 项到{places}"
    return f"{'Copied' if copy else 'Moved'} {len(moves)} items to {places}"


def folder_card(folder: str, lang: str, write: bool, turn_on: bool) -> dict:
    """The question that grants a folder, to read only or, when the step changes something there, to change in;
    with `turn_on` the same yes also turns on commands and files, the first time. No folder: it only turns them
    on."""
    zh = lang == "zh"
    lines = []
    if not folder:
        title = "允许 Mibo 通过命令和文件工具操作本机？" if zh else "Let Mibo work on this computer with commands and file tools?"
    else:
        name = folder_name(folder, lang)
        title = (f"允许 Mibo 在「{name}」中新建和整理文件？" if write else f"允许 Mibo 读取「{name}」中的文件？") if zh else (
            f"Let Mibo create and sort files in “{name}”?" if write else f"Let Mibo read the files in “{name}”?")
    lines.append("删除文件、付款和更改账号时仍将另行确认。可随时在 设置 › 文件与命令 中更改。" if zh
                 else "Deleting files, paying and changing an account are still confirmed separately. You can change "
                 "this in Settings › Files and commands.")
    if turn_on:
        lines.append("此操作将同时开启“通过命令操作本机”。" if zh else
                     "This also turns on “Let it do things on this computer by command”.")
    return {"title": title, "lines": lines}
