"""What the person is doing at the computer, read on this machine only.

`sense` reads the program in front, its window title, how long since the last
key or mouse input, and whether that window fills the screen; `classify`
turns the program and title into one kind of activity. The program's name and
the title are used here and dropped: only the kind leaves this module, and it
is never written to disk.

Windows reads them through user32 and counts any open microphone as a call;
macOS reads the frontmost application's name from `lsappinfo` and the idle
time from `ioreg`, neither of which asks for any permission, and gives no
title (a title would need one). Full screen is what quiet mode sees.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import NamedTuple


class Sample(NamedTuple):
    activity: str
    idle_s: float
    fullscreen: bool


def _norm(name: str) -> str:
    name = name.strip().casefold()
    for end in (".exe", ".app", ".bin"):
        name = name.removesuffix(end)
    return name


def _words(*words: str) -> re.Pattern:
    """One pattern for words in any of the ten languages. A word in Latin or
    Cyrillic letters matches whole (digits may touch it: "hw3"); a `*` in it
    stands for any letters, for endings. CJK and Hangul match anywhere."""
    parts = []
    for word in words:
        body = r"\s+".join(r"[^\W\d_]*".join(map(re.escape, piece.split("*"))) for piece in word.split())
        if re.search(r"[぀-ヿ㐀-鿿가-힯]", word):
            parts.append(body)
        else:
            parts.append(r"(?<![^\W\d_])" + body + r"(?![^\W\d_])")
    return re.compile("|".join(parts))


# ---- programs, by what they are for. Windows process names without .exe, and
# macOS application names, lower case.
_PROGRAMS = {
    "browser": ("chrome", "google chrome", "msedge", "microsoft edge", "firefox", "brave", "brave browser",
                "opera", "vivaldi", "arc", "safari", "chromium", "360se", "360chrome", "qqbrowser",
                "sogouexplorer", "2345explorer", "liebao", "whale", "naver whale", "quark", "ucbrowser",
                "yandex", "browser", "yandex browser", "thorium", "floorp", "waterfox", "librewolf", "zen", "duckduckgo", "maxthon",
                "iexplore", "orion"),
    "meeting": ("zoom", "zoom.us", "wemeetapp", "tencentmeeting", "腾讯会议", "voovmeeting", "webex",
                "ciscowebexstart", "cisco webex meetings", "facetime", "gotomeeting", "classin", "around"),
    # Chat programs that also hold calls: a call's window says so in its title.
    "chat": ("wechat", "weixin", "微信", "qq", "tim", "discord", "slack", "telegram", "whatsapp", "line",
             "kakaotalk", "signal", "dingtalk", "钉钉", "feishu", "飞书", "lark", "messenger", "element",
             "wxwork", "企业微信", "skype", "viber", "teams", "ms-teams", "microsoft teams",
             "microsoft teams (work or school)", "messages", "信息", "zalo", "threema", "wire", "mattermost"),
    "coding": ("code", "visual studio code", "code - insiders", "cursor", "windsurf", "trae", "kiro", "devenv",
               "idea64", "idea", "intellij idea", "pycharm64", "pycharm", "webstorm64", "webstorm", "clion64",
               "clion", "goland64", "goland", "rider64", "rider", "phpstorm64", "rubymine64", "datagrip64",
               "studio64", "android studio", "xcode", "sublime_text", "sublime text", "notepad++", "vim",
               "gvim", "nvim", "nvim-qt", "emacs", "zed", "eclipse", "rstudio", "spyder", "matlab",
               "windowsterminal", "wt", "cmd", "powershell", "pwsh", "terminal", "iterm2", "warp",
               "alacritty", "wezterm-gui", "wezterm", "kitty", "hyper", "tabby", "mintty", "putty", "xshell",
               "mobaxterm", "positron", "jupyterlab", "githubdesktop", "github desktop", "sourcetree", "fork",
               "gitkraken", "postman", "dbeaver", "navicat", "hbuilderx", "wechatdevtools", "arduino ide",
               "unity", "unity hub", "godot"),
    "writing": ("winword", "microsoft word", "word", "pages", "obsidian", "notion", "typora", "scrivener",
                "ulysses", "bear", "onenote", "microsoft onenote", "evernote", "印象笔记", "yinxiang", "logseq",
                "joplin", "notepad", "textedit", "文本编辑", "wordpad", "marktext", "ia writer", "craft",
                "yuque", "语雀", "youdaonote", "有道云笔记", "siyuan", "思源笔记", "lyx", "texstudio",
                "texworks", "texmaker", "notes", "备忘录", "メモ", "메모"),
    # Office suites with one window for every kind of file: the file's ending says which.
    "office": ("wps", "soffice", "libreoffice", "wps office"),
    "spreadsheet": ("excel", "microsoft excel", "et", "numbers"),
    "slides": ("powerpnt", "microsoft powerpoint", "powerpoint", "wpp", "keynote"),
    "studying": ("anki", "quizlet", "eudic", "youdaodict", "goldendict", "百词斩", "扇贝单词"),
    "reading": ("acrobat", "acrord32", "adobe acrobat", "adobe acrobat reader", "foxitpdfreader",
                "foxit pdf reader", "foxitphantom", "foxitpdfeditor", "sumatrapdf", "preview", "预览",
                "プレビュー", "미리보기", "kindle", "calibre", "ebook-viewer", "zotero", "mendeley", "readest",
                "okular", "evince", "skim", "pdfxedit", "pdf-xchange editor", "books", "图书", "ブック",
                "neeview", "koodo reader", "weread", "微信读书", "drawboard pdf", "xodo", "pdfgear",
                "pdfelement"),
    "video": ("vlc", "potplayermini64", "potplayermini", "potplayer", "mpc-hc64", "mpc-hc", "mpc-be64", "mpv",
              "iina", "quicktime player", "tv", "netflix", "bilibili", "哔哩哔哩", "qqlive", "腾讯视频",
              "iqiyi", "爱奇艺", "youku", "优酷", "mgtv", "芒果tv", "kmplayer", "kmplayer64x", "gom", "infuse",
              "plex", "kodi", "wmplayer", "video.ui"),
    "music": ("spotify", "music", "apple music", "音乐", "ミュージック", "음악", "itunes", "cloudmusic",
              "网易云音乐", "neteasemusic", "qqmusic", "qq音乐", "kugou", "酷狗音乐", "kuwomusic", "kwmusic",
              "酷我音乐", "foobar2000", "aimp", "musicbee", "tidal", "deezer", "amazon music", "melon",
              "lx-music-desktop", "yandex music"),
    "gaming": ("steam", "steamwebhelper", "epicgameslauncher", "battle.net", "wegame", "riotclientux",
               "leagueclientux", "league of legends", "valorant-win64-shipping", "genshinimpact", "yuanshen",
               "starrail", "zenlesszonezero", "cs2", "csgo", "dota2", "overwatch", "robloxplayerbeta", "roblox",
               "minecraft", "minecraftlauncher", "minecraft.windows", "eldenring", "wow", "hearthstone",
               "ffxiv_dx11", "gta5", "rocketleague", "r5apex", "tslgame", "osu!", "terraria", "stardew valley",
               "hollow_knight", "bluearchive", "narakabladepoint", "lostark", "maplestory"),
    "designing": ("photoshop", "adobe photoshop", "illustrator", "adobe illustrator", "figma", "sketch",
                  "affinity designer", "affinity photo", "affinity publisher", "designer", "inkscape", "krita",
                  "clipstudiopaint", "clip studio paint", "blender", "coreldrw", "indesign", "adobe indesign",
                  "lightroom", "adobe lightroom", "lightroom classic", "adobe premiere pro", "premiere pro",
                  "afterfx", "adobe after effects", "resolve", "davinci resolve", "final cut pro", "capcut",
                  "jianyingpro", "剪映", "canva", "sai", "sai2", "paintdotnet", "paint.net", "xd", "adobe xd",
                  "framer", "pixso", "mastergo", "aseprite", "cinema 4d", "3dsmax", "maya", "zbrush", "acad",
                  "autocad", "sketchup", "fusion360", "sldworks", "rhino", "lunacy", "mspaint", "paint"),
    # The desktop, the taskbar, the lock screen: nothing to say about them.
    "shell": ("explorer", "finder", "访达", "searchhost", "searchapp", "startmenuexperiencehost",
              "shellexperiencehost", "lockapp", "taskmgr", "systemsettings", "loginwindow", "dock",
              "systemuiserver", "controlcenter", "screensaverengine"),
}
PROGRAMS = {name: kind for kind, names in _PROGRAMS.items() for name in names}

# Unreal games are named <game>-Win64-Shipping.
_GAME_NAME = re.compile(r"-win64-shipping$|-wingdk-shipping$")
# What a file's ending says it is, for programs not listed and office suites.
_ENDINGS = {"pdf": "reading", "epub": "reading", "mobi": "reading", "djvu": "reading", "caj": "reading",
            "doc": "writing", "docx": "writing", "odt": "writing", "rtf": "writing", "md": "writing",
            "tex": "writing", "pages": "writing",
            "xls": "spreadsheet", "xlsx": "spreadsheet", "csv": "spreadsheet", "ods": "spreadsheet",
            "numbers": "spreadsheet",
            "ppt": "studying", "pptx": "studying", "odp": "studying", "dps": "studying",
            "ipynb": "coding", "py": "coding", "java": "coding", "cpp": "coding", "rmd": "coding"}
_ENDING = re.compile(r"(?<=\w)\.(" + "|".join(sorted(_ENDINGS, key=len, reverse=True)) + r")(?!\w)", re.IGNORECASE)
# Where a document can be homework: documents, PDFs, notebooks, slides and code (pages: `_page`).
_DOCUMENT_KINDS = {"writing", "office", "spreadsheet", "slides", "studying", "reading", "coding"}

HOMEWORK = _words(
    "homework*", "home work", "assignment*", "problem set*", "pset*", "worksheet*", "lab report*", "coursework",
    "takehome", "take-home", "作业", "作業", "习题", "習題", "练习题", "練習題", "课后题", "課後題", "实验报告",
    "實驗報告", "功课", "功課", "大作业", "宿題", "課題", "演習", "問題集", "レポート課題", "과제", "숙제",
    "문제집", "실험 보고서", "tarea*", "deberes", "ejercicios", "trabajo práctico", "informe de laboratorio",
    "devoir*", "exercices", "compte rendu de tp", "rapport de laboratoire", "hausaufgabe*", "übungsblatt*",
    "aufgabenblatt*", "laborbericht*", "hausarbeit*", "lição de casa", "dever* de casa", "lista de exercícios",
    "exercícios", "relatório de laboratório", "домашн* задан*", "домашк*", "лабораторн* работ*",
    "лабораторк*", "контрольн* работ*", "практическ* работ*", "курсов* работ*")
_HW_NUMBER = re.compile(r"(?<![^\W\d_])(hw|lab)\s?#?\d", re.IGNORECASE)
# Course sites, where a page is homework whatever its title says. Canvas only
# as a part of the title of its own ("Quiz 2 - Canvas"), not "Canvas API".
COURSE_SITES = _words(
    "gradescope", "blackboard", "moodle", "雨课堂", "学习通", "學習通", "超星", "智慧树", "知到",
    "piazza", "ed discussion", "edstem", "google classroom", "schoology", "brightspace", "webassign",
    "wileyplus", "mymathlab", "pearson mylab", "prairielearn", "课堂派", "优学院", "manaba", "webclass",
    "instructure", "pearson mastering", "mastering physics", "mastering chemistry", "作业帮", "学而思")
_CANVAS = re.compile(r"(?:^|[-|–—]\s*)canvas(?:\s+lms)?\s*(?:[-|–—]|$)")
# A Google Meet tab: "Meet - abc-defg-hij" or "Meet – Team sync".
_MEET_TAB = re.compile(r"^meet\s*[-–—:|]|^[a-z]{3}-[a-z]{4}-[a-z]{3}\b")
MEETING_WORDS = _words(
    "meeting*", "call", "video call", "huddle", "会议", "會議", "通话", "通話", "视频聊天", "語音", "语音",
    "会議", "ミーティング", "회의", "통화", "reunión", "llamada", "videollamada", "réunion", "appel",
    "visio*", "besprechung", "anruf", "videoanruf", "reunião", "chamada", "videochamada", "встреча",
    "звонок", "созвон", "видеозвонок", "конференц*")
MEETING_SITES = _words("google meet", "meet.google", "zoom meeting*", "zoom webinar*", "zoom workplace",
                       "腾讯会议", "騰訊會議", "voov", "webex", "jitsi", "whereby", "飞书会议", "飛書會議",
                       "lark meetings", "teams meeting*")
# Pages, in the order they are tried: music before video for "YouTube Music".
_SITES = (
    ("music", _words("spotify", "youtube music", "soundcloud", "apple music", "网易云音乐", "網易雲音樂",
                     "qq音乐", "qq音樂", "酷狗", "酷我", "bandcamp", "deezer", "tidal", "pandora", "melon", "멜론",
                     "яндекс музык*", "yandex music", "amazon music")),
    ("video", _words("youtube", "bilibili", "哔哩哔哩", "嗶哩嗶哩", "netflix", "twitch", "优酷", "優酷", "爱奇艺",
                     "愛奇藝", "腾讯视频", "騰訊視頻", "芒果tv", "西瓜视频", "抖音", "douyin", "tiktok", "niconico",
                     "ニコニコ", "abema", "prime video", "disney+", "hulu", "vimeo", "crunchyroll", "dailymotion",
                     "유튜브", "치지직", "chzzk", "afreecatv", "soop", "tving", "wavve", "globoplay", "rutube",
                     "кинопоиск", "vk видео", "okko", "动画", "動画", "番剧", "影片", "동영상")),
    ("chatting", _words("whatsapp", "discord", "slack", "telegram", "messenger", "微信", "wechat", "kakaotalk",
                        "카카오톡", "vk мессенджер", "microsoft teams")),
    ("coding", _words("github", "gitlab", "stack overflow", "stackoverflow", "leetcode", "力扣", "codeforces",
                      "atcoder", "colab", "jupyter", "kaggle", "replit", "codesandbox", "codepen", "localhost",
                      "127.0.0.1", "pull request", "牛客", "洛谷", "luogu", "hugging face", "vercel")),
    ("spreadsheet", _words("google sheets", "google 表格", "google 試算表", "google スプレッドシート",
                           "google 스프레드시트", "hojas de cálculo de google", "google tabellen",
                           "planilhas google", "google таблицы", "airtable", "飞书表格", "excel online")),
    ("studying", _words("google slides", "google 幻灯片", "google 簡報", "google スライド", "google 프레젠테이션",
                        "presentaciones de google", "google präsentationen", "apresentações google",
                        "google презентации", "coursera", "edx", "khan academy", "udemy", "mooc", "慕课",
                        "学堂在线", "网易公开课", "公开课", "网课", "網課", "quizlet", "anki", "duolingo",
                        "brilliant", "lecture*", "课件", "課件", "講義", "강의", "lección", "clase*", "cours",
                        "vorlesung*", "aula*", "лекци*", "flashcard*", "単語帳", "背单词", "百词斩", "扇贝")),
    ("writing", _words("google docs", "google 文档", "google 文件", "google ドキュメント", "google 문서",
                       "documentos de google", "google dokumente", "documentos google", "google документы",
                       "overleaf", "notion", "语雀", "飞书文档", "飛書文件", "石墨文档", "腾讯文档", "騰訊文檔",
                       "hackmd", "dropbox paper", "word online", "office online")),
    ("designing", _words("figma", "canva", "photopea", "excalidraw", "framer", "penpot", "稿定设计", "即时设计",
                         "墨刀", "mastergo", "pixso", "miro")),
    ("shopping", _words("amazon", "淘宝", "淘寶", "天猫", "天貓", "京东", "京東", "jd.com", "拼多多", "闲鱼",
                        "ebay", "aliexpress", "etsy", "shein", "temu", "楽天", "rakuten", "メルカリ", "mercari",
                        "coupang", "쿠팡", "gmarket", "11번가", "mercado livre", "mercadolibre", "otto.de",
                        "zalando", "cdiscount", "ozon", "wildberries", "walmart", "best buy", "ikea", "购物车",
                        "購物車", "ショッピング", "쇼핑", "carrito", "panier", "warenkorb", "carrinho", "корзина",
                        "shopping cart")),
    ("reading", _words("arxiv", "wikipedia", "维基百科", "維基百科", "ウィキペディア", "위키백과", "википедия",
                       "medium", "substack", "pubmed", "google scholar", "谷歌学术", "semantic scholar",
                       "sciencedirect", "springer", "nature", "researchgate", "jstor", "知乎", "微信读书",
                       "起点中文网", "晋江", "kindle", "小说", "小說", "小説", "소설", "documentation", "readme",
                       "manual", "pdf")),
)


def _homework(text: str) -> bool:
    return bool(HOMEWORK.search(text) or _HW_NUMBER.search(text))


def _numbered(text: str) -> bool:
    """A homework word with its number, at most a word between: "Homework 3", "Devoir maison n°2", "作业3", "第3次作业"."""
    return bool(_HW_NUMBER.search(text)) or any(
        re.match(r"\s*(?:\S+\s+)?(?:[#№]|n[°º]|no\.)?\s*\d", text[m.end():])
        or re.search(r"\d\s*次?\s*$", text[:m.start()])
        for m in HOMEWORK.finditer(text))


def _page(text: str, ending) -> str:
    """The kind of a browser tab, from its title."""
    site = next((found for found, words in _SITES if words.search(text)), None)
    if MEETING_SITES.search(text) or _MEET_TAB.search(text) or (site == "chatting" and MEETING_WORDS.search(text)):
        return "meeting"
    # A video about homework is a video.
    if site in ("music", "video"):
        return site
    if COURSE_SITES.search(text) or _CANVAS.search(text):
        return "homework"
    # Elsewhere a homework word needs a document, a file or its number: "Homework help" is not homework.
    if _homework(text) and (site in ("writing", "spreadsheet", "studying") or ending or _numbered(text)):
        return "homework"
    return site or (_ENDINGS[ending[1].lower()] if ending else "browsing")


def classify(program: str, title: str) -> str:
    """The kind of activity a window shows, from its program's name and its title: homework, writing, coding,
    reading, studying, video, music, gaming, chatting, meeting, designing, spreadsheet, shopping, browsing or none."""
    name = _norm(program)
    kind = PROGRAMS.get(name)
    if kind is None and name == "applicationframehost":
        # A Store app's window belongs to its frame host; its title is the app's name.
        kind = PROGRAMS.get(_norm(title.rsplit(" - ", 1)[-1]))
    text = title.casefold()
    if kind is None and (_GAME_NAME.search(name) or (name in ("java", "javaw") and "minecraft" in text)):
        kind = "gaming"
    ending = _ENDING.search(text)
    if kind == "meeting":
        return "meeting"
    if kind == "chat" and MEETING_WORDS.search(text):
        return "meeting"
    if kind == "browser":
        return _page(text, ending)
    if (kind in _DOCUMENT_KINDS or ending) and _homework(text):
        return "homework"
    if kind == "chat":
        return "chatting"
    if kind == "office":
        return _ENDINGS[ending[1].lower()] if ending else "writing"
    if kind == "slides":
        return "studying"
    if kind == "shell":
        return "none"
    if kind:
        return kind
    return _ENDINGS[ending[1].lower()] if ending else "none"


# Names a person may type for a program that runs under another name.
_SAME = (("wechat", "weixin", "微信"), ("teams", "msteams", "microsoftteams"), ("vscode", "code", "visualstudiocode"),
         ("word", "winword", "microsoftword"), ("excel", "microsoftexcel"),
         ("powerpoint", "powerpnt", "microsoftpowerpoint"), ("edge", "msedge", "microsoftedge"),
         ("chrome", "googlechrome"), ("tencentmeeting", "wemeetapp", "腾讯会议"), ("feishu", "飞书", "lark"),
         ("dingtalk", "钉钉"), ("wecom", "wxwork", "企业微信"), ("neteasemusic", "cloudmusic", "网易云音乐"),
         ("qqmusic", "qq音乐"), ("yandex", "browser", "yandexbrowser"))


def _bare(name: str) -> str:
    return re.sub(r"[\s_-]", "", _norm(name))


def _ignored(program: str, ignore) -> bool:
    bare = _bare(program)
    names = {bare, *next((group for group in _SAME if bare in group), ())}
    return any(_bare(entry) in names for entry in ignore)


# ---- Windows

_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
_MIC = _CONSENT + r"\microphone"
# Whether some program has the microphone open, as the watcher last read it.
_mic = {"on": False, "watched": False}


def _watch_mic() -> None:
    """On a thread of its own: read the microphone again each time Windows
    writes there that a program started or stopped using it, and sleep in
    between (RegNotifyChangeKeyValue blocks until then)."""
    import ctypes
    import winreg

    advapi32 = ctypes.WinDLL("advapi32")
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC)
    except OSError:
        # No program has used a microphone here yet: wait for its key to be made, and
        # sleep through what the other capabilities (location, the camera) write.
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CONSENT) as parent:
            while not _mic_key():
                advapi32.RegNotifyChangeKeyValue(ctypes.c_void_p(parent.handle), False, 0x1, None, False)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC)
    with key:
        while True:
            _mic["on"] = _mic_on()
            # A key added (a program's first use) or a value written, anywhere below the microphone's key.
            advapi32.RegNotifyChangeKeyValue(ctypes.c_void_p(key.handle), True, 0x1 | 0x4, None, False)


def _mic_key() -> bool:
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC).Close()
        return True
    except OSError:
        return False


def _mic_on() -> bool:
    """Some program has the microphone open now: a call, whatever its window says.
    Windows keeps when each program last started and stopped using it; a stop of 0 is still on."""
    import winreg

    def in_use(key, sub: str) -> bool:
        with winreg.OpenKey(key, sub) as app:
            try:
                return bool(winreg.QueryValueEx(app, "LastUsedTimeStart")[0]) and \
                    not winreg.QueryValueEx(app, "LastUsedTimeStop")[0]
            except OSError:
                # Never used by this program.
                return False

    def on(path: str) -> bool:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            subs = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
            return any(on(path + "\\" + sub) if sub == "NonPackaged" else in_use(key, sub) for sub in subs)

    try:
        return on(_MIC)
    except OSError:
        # No microphone has ever been used here.
        return False


def _windows_idle() -> float:
    import ctypes
    from ctypes import wintypes

    from . import quiet

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    last = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    quiet._user32.GetLastInputInfo(ctypes.byref(last))
    return ((quiet._kernel32.GetTickCount() - last.dwTime) & 0xFFFFFFFF) / 1000


def _windows(ignore) -> Sample:
    """The window in front as quiet's hook last saw it (it looks each time the
    front changes), the microphone as its watcher last read it, and the idle
    time: the one thing read here."""
    import threading

    from . import quiet

    if not _mic["watched"]:
        _mic["watched"] = True
        threading.Thread(target=_watch_mic, name="mibo-mic", daemon=True).start()

    idle = _windows_idle()
    seen = quiet.front()
    if not seen["hwnd"] or seen["pid"] == os.getpid():
        # Nothing in front, or the app's own window or the pet.
        return Sample("none", idle, False)
    program = seen["path"].replace("\\", "/").rsplit("/", 1)[-1]
    if not program or _ignored(program, ignore):
        return Sample("none", idle, False)
    if _mic["on"]:
        return Sample("meeting", idle, False)
    kind = classify(program, seen["title"])
    # A game, a slide show or a window that fills its screen, as quiet mode tells them.
    return Sample(kind, idle, kind != "none" and seen["signal"] != "")


# ---- macOS

def _run(*command: str) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False).stdout


def _mac_idle() -> float:
    found = re.search(r'"HIDIdleTime" = (\d+)', _run("ioreg", "-r", "-c", "IOHIDSystem", "-d", "1"))
    return int(found[1]) / 1e9 if found else 0.0


def _mac(ignore) -> Sample:
    from . import quiet

    idle = _mac_idle()
    info = _run("lsappinfo", "info", _run("lsappinfo", "front").strip())
    name, pid = re.search(r'^"(.*?)" ASN:', info, re.MULTILINE), re.search(r"\bpid = (\d+)", info)
    if not name or (pid and int(pid[1]) == os.getpid()) or _ignored(name[1], ignore):
        return Sample("none", idle, False)
    kind = classify(name[1], "")
    return Sample(kind, idle, kind != "none" and quiet.sense()[0] != "")


def idle() -> float:
    """Seconds since the last key or mouse input, and nothing else."""
    if sys.platform == "win32":
        return _windows_idle()
    if sys.platform == "darwin":
        return _mac_idle()
    return 0.0


def sense(ignore=()) -> Sample:
    """What is in front now; programs named in `ignore` are not looked at."""
    if sys.platform == "win32":
        return _windows(ignore)
    if sys.platform == "darwin":
        return _mac(ignore)
    return Sample("none", 0.0, False)
