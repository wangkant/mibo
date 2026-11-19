"""The person's own mail as a source, read-only, once they allow it.

A mailbox is read over IMAP with the password its provider gives mail apps
(Gmail's app password, QQ and NetEase's 授权码, Apple's app-specific
password). The accounts and their secrets are kept in
`<home>/platforms/mail.json`, beside direct.json and written the same way;
what the last look found, and whether personal letters count, in
`<runtime>/mail.json`.

QQ Mail (and Foxmail), 163 and 126 take one paste: the address picks the
provider and its server, the page opens the provider's page where the 授权码 is
made, and only the address and the code are asked.

A look signs in, opens the inbox with EXAMINE so nothing is ever marked read
or changed, reads the last two days and keeps the newest in the library. By
default only mail that is not a personal letter: newsletters, notifications,
forums. What a message says enters the library only while the person lets
the character read their mail (privacy.py); otherwise only how many came and
from whom is said, on this computer.
"""
from __future__ import annotations

import asyncio
import contextlib
import email
import imaplib
import json
import logging
import os
import re
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesHeaderParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from . import privacy, quiet
from .library import Item, Library, item_id
from .storage import atomic_write_text

logger = logging.getLogger("agent.mail")

PORT = 993
TIMEOUT_S = 20
# What one look reads: the last two days, at most this many messages, this many kept.
DAYS = 2
LOOK_MAX = 40
KEEP_MAX = 12
# A message is read only this far; a long one's start says what it is.
BODY_READ_MAX = 256_000
EXCERPT_MAX = 600
# A look soon after the app starts, then this often.
FIRST_LOOK_S = 30
LOOK_EVERY_S = 30 * 60
ADDRESS_MAX = 254
SECRET_MAX = 256
HOST_MAX = 253
STATE_FILE = "mail.json"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_HEADERS = "FROM SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED"
# RFC 2971: who the client is. NetEase answers SELECT with "Unsafe Login" until it is told.
ID_ARGS = '("name" "personagent" "version" "1" "vendor" "personagent")'
_UID = re.compile(rb"UID (\d+)")
_ADDRESS = re.compile(r"[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+")
_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*(:\d{1,5})?")

# Both files are written from the page's worker threads and from the looks.
_lock = threading.Lock()


@dataclass(frozen=True)
class Provider:
    key: str
    name: tuple[str, str]           # (English, Chinese)
    host: str                       # "" when the person types it
    secret: tuple[str, str]         # what the provider calls the password to paste
    help: tuple[str, str]           # the provider's own page on getting it, (English, Chinese)
    steps: tuple[tuple[str, ...], tuple[str, ...]]
    webmail: str = ""               # where a message is opened; "" for Gmail's own search address
    hello: bool = False             # NetEase refuses EXAMINE until the client names itself with ID
    code: str = ""                  # the provider's page where the code is made, signed in
    domains: tuple[str, ...] = ()   # addresses that belong to it, so typing the address picks it


# Outlook.com and Hotmail are left out: since September 2024 they take OAuth only over IMAP.
PROVIDERS: dict[str, Provider] = {p.key: p for p in (
    Provider("gmail", ("Gmail", "Gmail"), "imap.gmail.com", ("app password", "应用专用密码"),
             ("https://support.google.com/mail/answer/185833?hl=en",
              "https://support.google.com/mail/answer/185833?hl=zh-Hans"),
             (("Turn on 2-Step Verification for your Google Account.",
               "Open myaccount.google.com/apppasswords and create an app password named personagent.",
               "Paste the 16 letters here; the spaces do not matter."),
              ("在 Google 账号里开启两步验证。",
               "打开 myaccount.google.com/apppasswords，新建一个名为 personagent 的应用专用密码。",
               "把那 16 个字母粘贴到这里，有没有空格都行。")),
             domains=("gmail.com", "googlemail.com")),
    Provider("qq", ("QQ Mail / Foxmail", "QQ 邮箱 / Foxmail"), "imap.qq.com", ("authorization code", "授权码"),
             ("https://service.mail.qq.com/detail/0/75", "https://service.mail.qq.com/detail/0/75"),
             (("Open QQ Mail's account page with the button here and sign in.",
               "Under Security, turn on the IMAP/SMTP service.",
               "Choose Generate authorization code and confirm it as QQ asks.",
               "Paste the code here: your QQ password itself will not sign in."),
              ("点这里的按钮打开 QQ 邮箱的账号页并登录。",
               "在“安全设置”里开启 IMAP/SMTP 服务。",
               "点“生成授权码”，按 QQ 的提示验证。",
               "把授权码粘贴到这里：QQ 密码本身登录不了。")),
             webmail="https://wx.mail.qq.com/", code="https://wx.mail.qq.com/account/index",
             domains=("qq.com", "vip.qq.com", "foxmail.com")),
    Provider("163", ("NetEase 163 Mail", "网易 163 邮箱"), "imap.163.com", ("authorization code", "授权码"),
             ("https://help.mail.163.com/", "https://help.mail.163.com/"),
             (("Open mail.163.com with the button here, sign in, then Settings, then POP3/SMTP/IMAP.",
               "Turn on the IMAP/SMTP service.",
               "Add an authorization code; it is shown only once.",
               "Paste it here."),
              ("点这里的按钮打开 mail.163.com 并登录，再打开“设置”→“POP3/SMTP/IMAP”。",
               "开启 IMAP/SMTP 服务。",
               "新增一个授权码，它只显示一次。",
               "把它粘贴到这里。")),
             webmail="https://mail.163.com/", hello=True, code="https://mail.163.com/", domains=("163.com",)),
    Provider("126", ("NetEase 126 Mail", "网易 126 邮箱"), "imap.126.com", ("authorization code", "授权码"),
             ("https://help.mail.163.com/", "https://help.mail.163.com/"),
             (("Open mail.126.com with the button here, sign in, then Settings, then POP3/SMTP/IMAP.",
               "Turn on the IMAP/SMTP service.",
               "Add an authorization code; it is shown only once.",
               "Paste it here."),
              ("点这里的按钮打开 mail.126.com 并登录，再打开“设置”→“POP3/SMTP/IMAP”。",
               "开启 IMAP/SMTP 服务。",
               "新增一个授权码，它只显示一次。",
               "把它粘贴到这里。")),
             webmail="https://mail.126.com/", hello=True, code="https://mail.126.com/", domains=("126.com",)),
    Provider("icloud", ("iCloud Mail", "iCloud 邮箱"), "imap.mail.me.com",
             ("app-specific password", "App 专用密码"),
             ("https://support.apple.com/en-us/102654", "https://support.apple.com/zh-cn/102654"),
             (("Your Apple Account needs two-factor authentication turned on.",
               "At account.apple.com open Sign-In and Security, then App-Specific Passwords.",
               "Generate one named personagent.",
               "Paste it here."),
              ("Apple 账户需要先开启双重认证。",
               "在 account.apple.com 打开“登录与安全”→“App 专用密码”。",
               "生成一个名为 personagent 的密码。",
               "把它粘贴到这里。")),
             webmail="https://www.icloud.com/mail/", domains=("icloud.com", "me.com", "mac.com")),
    Provider("other", ("Other mailbox (IMAP)", "其他邮箱（IMAP）"), "", ("password", "密码"),
             ("", ""),
             (("Turn on IMAP in your mailbox's settings.",
               "Type its IMAP server, such as imap.example.com; it is read over TLS on port 993.",
               "Paste the password it gives mail apps; many call it an app password or authorization code."),
              ("在邮箱设置里开启 IMAP。",
               "填写它的 IMAP 服务器，例如 imap.example.com；通过 TLS 在 993 端口读取。",
               "粘贴它给邮件客户端用的密码，很多邮箱叫它客户端专用密码或授权码。"))),
)}


class MailError(ValueError):
    """What went wrong, by its code: mail_invalid for what the person typed;
    mail_login_failed, mail_unreachable, mail_refused or mail_failed for a
    sign-in or a look. A ValueError, so the page answers it by its code."""


def connect(host: str, port: int) -> imaplib.IMAP4:
    """IMAP over TLS with the certificate checked. Tests put a plain
    connection to a stand-in server here."""
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)


# ----------------------------------------------------------------- the files --

def accounts_path(home: Path) -> Path:
    return Path(home) / "platforms" / "mail.json"


def state_path(runtime: Path) -> Path:
    return Path(runtime) / STATE_FILE


def _read(path: Path) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def load_accounts(home: Path) -> list[dict]:
    rows = _read(accounts_path(home)).get("accounts")
    return [a for a in rows if isinstance(a, dict) and a.get("key") and a.get("provider") in PROVIDERS
            and a.get("address") and a.get("secret")] if isinstance(rows, list) else []


def _save_accounts(home: Path, accounts: list[dict]) -> None:
    path = accounts_path(home)
    atomic_write_text(path, json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2) + "\n")
    # The secrets are the person's: only their own user may read the file.
    os.chmod(path, 0o600)


def change_accounts(home: Path, change: Callable[[list[dict]], None]) -> list[dict]:
    with _lock:
        accounts = load_accounts(home)
        change(accounts)
        _save_accounts(home, accounts)
        return accounts


def load_state(runtime: Path) -> dict:
    saved = _read(state_path(runtime))
    last = saved.get("last") if isinstance(saved.get("last"), dict) else {}
    return {"letters": saved.get("letters") is True, "last": {k: v for k, v in last.items() if isinstance(v, dict)}}


def change_state(runtime: Path, change: Callable[[dict], None]) -> dict:
    with _lock:
        state = load_state(runtime)
        change(state)
        atomic_write_text(state_path(runtime), json.dumps(state, ensure_ascii=False, indent=1))
        return state


def account_key(address: str) -> str:
    return "mail-" + item_id(address.strip().lower())[:12]


def guess(address: str) -> str:
    """The provider an address belongs to by its domain, "" when none is known."""
    domain = str(address or "").strip().rpartition("@")[2].lower()
    return next((p.key for p in PROVIDERS.values() if domain in p.domains), "")


def new_account(provider: str, address: str, secret: str, host: str = "") -> dict:
    """An account as it is saved, or MailError("mail_invalid").
    With no provider, the address's domain picks it; an unknown one is "other"."""
    address = str(address or "").strip()
    known = PROVIDERS.get(provider or guess(address) or "other")
    secret = str(secret or "")
    if known is None or len(address) > ADDRESS_MAX or not _ADDRESS.fullmatch(address):
        raise MailError("mail_invalid")
    if known.host:
        # The codes are shown in groups; the spaces are not part of them.
        secret, host = "".join(secret.split()), known.host
    else:
        host = str(host or "").strip().lower()
        if len(host) > HOST_MAX or not _HOST.fullmatch(host) or int(host.partition(":")[2] or PORT) > 65535:
            raise MailError("mail_invalid")
    # IMAP sends the secret as one quoted string: a line break would end the command.
    if not secret or len(secret) > SECRET_MAX or any(ord(c) < 32 or c == "\x7f" for c in secret):
        raise MailError("mail_invalid")
    return {"key": account_key(address), "provider": known.key, "address": address, "host": host,
            "secret": secret, "on": True}


# ------------------------------------------------------------------ signing in --

def _hostport(account: dict) -> tuple[str, int]:
    host, _, port = account["host"].partition(":")
    return host, int(port) if port else PORT


@contextlib.contextmanager
def session(account: dict, opened: Optional[set] = None):
    """Signed in, with the inbox open read-only; logged out after."""
    provider = PROVIDERS[account["provider"]]
    try:
        imap = connect(*_hostport(account))
    except OSError:
        raise MailError("mail_unreachable") from None
    if opened is not None:
        opened.add(imap)
    try:
        address = account["address"]
        # Apple names the part before the @ first, the whole address if that fails.
        names = (address.split("@")[0], address) if provider.key == "icloud" else (address,)
        for n, name in enumerate(names):
            try:
                imap.login(name, account["secret"])
                break
            except imaplib.IMAP4.abort:
                raise
            except imaplib.IMAP4.error:
                if n == len(names) - 1:
                    raise MailError("mail_login_failed") from None
        if provider.hello:
            imap.xatom("ID", ID_ARGS)
        typ, _ = imap.select("INBOX", readonly=True)    # EXAMINE
        if typ != "OK":
            raise MailError("mail_refused")
        yield imap
    except (OSError, imaplib.IMAP4.abort):
        raise MailError("mail_unreachable") from None
    except imaplib.IMAP4.error:
        raise MailError("mail_failed") from None
    finally:
        if opened is not None:
            opened.discard(imap)
        with contextlib.suppress(Exception):
            imap.logout()


def check(account: dict) -> None:
    """Sign in once and open the inbox; MailError when that fails."""
    with session(account):
        pass


# --------------------------------------------------------------------- reading --

def _by_uid(data: list) -> dict[int, bytes]:
    """FETCH answers by UID; a server may put the UID before or after the literal."""
    found: dict[int, bytes] = {}
    for n, part in enumerate(data):
        if not isinstance(part, tuple):
            continue
        tail = data[n + 1] if n + 1 < len(data) and isinstance(data[n + 1], bytes) else b""
        match = _UID.search(part[0]) or _UID.search(tail)
        if match:
            found[int(match.group(1))] = part[1]
    return found


def _uids(answer: list) -> list[int]:
    return [int(u) for u in b" ".join(a for a in answer if isinstance(a, bytes)).split()]


def bulk(headers) -> bool:
    """Sent to many, by a list or a machine: what the headers of such mail say."""
    if headers.get("List-Unsubscribe") or headers.get("List-Id"):
        return True
    if str(headers.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return True
    auto = str(headers.get("Auto-Submitted") or "").strip().lower()
    return bool(auto) and auto != "no"


def _date(headers) -> Optional[datetime]:
    try:
        when = parsedate_to_datetime(str(headers.get("Date") or ""))
    except (TypeError, ValueError, IndexError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


class _Text(HTMLParser):
    """The words of an HTML mail, a line per block, without its scripts and styles."""
    SKIP = {"script", "style", "head", "title", "noscript", "template"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section",
             "article", "header", "footer", "blockquote", "hr", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_text(markup: str) -> str:
    reader = _Text()
    reader.feed(markup)
    reader.close()
    return "".join(reader.parts)


_QUOTE_START = re.compile(r"^(On .{1,200} wrote:|在.{1,200}写道[:：]|-+ ?Original Message ?-+|-+ ?原始邮件 ?-+"
                          r"|-- ?|_{5,}|From: .+|发件人[:：].+)$", re.I)
_FOOTER = re.compile(r"unsubscribe|manage (your )?(email )?preferences|you (are receiving|received) this|"
                     r"退订|取消订阅|不想再收到|您收到这封邮件", re.I)
_NOISE = re.compile(r"view (it |this (email|message) )?in (your|a) browser|在浏览器中(查看|打开)|"
                    r"^\[image:[^\]]*\]$", re.I)
_LINK = re.compile(r"<?https?://\S+>?")


def clean(text: str) -> str:
    """The message's own words: quoted replies, signatures and the list's footer left out."""
    kept: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = " ".join(raw.replace("‌", " ").replace("\xa0", " ").split())
        if line.startswith(">"):
            continue
        if _FOOTER.search(line):
            # A list's links at the top are noise; further down they begin its footer.
            if kept:
                break
            continue
        if kept and _QUOTE_START.match(raw.strip()):
            break
        line = " ".join(_LINK.sub(" ", line).split())
        if line and not _NOISE.search(line):
            kept.append(line)
    return "\n".join(kept)


def _content(part) -> str:
    try:
        return part.get_content()
    except (LookupError, UnicodeError, AssertionError):
        # A charset Python does not know: its bytes read as UTF-8, mistakes shown as such.
        return (part.get_payload(decode=True) or b"").decode("utf-8", "replace")


def body_text(message) -> str:
    """Plain words from a parsed message: its text part, else its HTML made text."""
    plain = message.get_body(preferencelist=("plain",))
    words = clean(_content(plain)) if plain is not None else ""
    # A newsletter's text part is often only "view this in your browser".
    if len(words) < 40:
        markup = message.get_body(preferencelist=("html",))
        if markup is not None:
            words = clean(html_text(_content(markup))) or words
    return words


def _url(provider: Provider, account: dict, message_id: str, fallback: str) -> str:
    """An https address unique to the message, that opens its webmail."""
    if provider.key == "gmail":
        base = f"https://mail.google.com/mail/u/{quote(account['address'], safe='@')}/"
        return base + (f"#search/rfc822msgid:{quote(message_id, safe='@.')}" if message_id else f"#{fallback}")
    web = provider.webmail or f"https://{account['address'].split('@')[1].lower()}/"
    return web + "#" + (quote(message_id, safe="@.") if message_id else fallback)


def to_item(provider: Provider, account: dict, headers, body: str, fallback: str) -> Item:
    name, sender = parseaddr(str(headers.get("From") or ""))
    message_id = str(headers.get("Message-ID") or "").strip().strip("<>").strip()
    when = _date(headers)
    excerpt = " ".join(body.split())[:EXCERPT_MAX]
    title = " ".join(str(headers.get("Subject") or "").split())[:200]
    site = " ".join(name.split())[:80] or sender
    # Found when it arrived, so the feed's freshness follows the mail; a clock ahead counts as now.
    arrived = min(int(when.timestamp()), int(time.time())) if when else 0
    return Item(url=_url(provider, account, message_id, fallback), site=site, kind="article",
                title=title or excerpt[:80] or site, author=sender, description=excerpt,
                published=when.isoformat() if when else "", seen_at=arrived, fits=False, why="")


def read(account: dict, letters: bool, known: Callable[[str], bool], now: Optional[float] = None,
         opened: Optional[set] = None) -> list[Item]:
    """The newest messages of the last two days that are new to the library, as items."""
    provider = PROVIDERS[account["provider"]]
    now = time.time() if now is None else now
    start = datetime.fromtimestamp(now, timezone.utc) - timedelta(days=DAYS)
    with session(account, opened) as imap:
        validity = (imap.response("UIDVALIDITY")[1] or [b"0"])[0].decode("ascii", "replace")
        # IMAP dates are whole days in the server's zone: a day earlier, the hours checked below.
        day = start - timedelta(days=1)
        typ, answer = imap.uid("SEARCH", "SINCE", f"{day.day}-{_MONTHS[day.month - 1]}-{day.year}")
        uids = sorted(_uids(answer) if typ == "OK" else [])[-LOOK_MAX:]
        if not uids:
            return []
        sorted_out: set[int] = set()
        if provider.key == "gmail" and not letters:
            # Gmail's own sorting: everything outside Primary is not a letter.
            typ, answer = imap.uid("SEARCH", "X-GM-RAW", f'"newer_than:{DAYS + 1}d -category:primary"')
            sorted_out = set(_uids(answer)) if typ == "OK" else set()
        typ, answer = imap.uid("FETCH", ",".join(map(str, uids)), f"(BODY.PEEK[HEADER.FIELDS ({_HEADERS})])")
        parser = BytesHeaderParser(policy=policy.default)
        chosen = []
        for uid, raw in _by_uid(answer if typ == "OK" else []).items():
            headers = parser.parsebytes(raw)
            when = _date(headers)
            if when is not None and when < start:
                continue
            if letters or uid in sorted_out or bulk(headers):
                chosen.append((when or datetime.fromtimestamp(now, timezone.utc), uid, headers))
        chosen.sort(key=lambda row: (row[0], row[1]), reverse=True)
        items, wanted = [], []
        for when, uid, headers in chosen[:KEEP_MAX]:
            item = to_item(provider, account, headers, "", f"uid-{validity}-{uid}")
            if not known(item.url):
                wanted.append((uid, headers))
        if not wanted:
            return []
        typ, answer = imap.uid("FETCH", ",".join(str(uid) for uid, _ in wanted), f"(BODY.PEEK[]<0.{BODY_READ_MAX}>)")
        bodies = _by_uid(answer if typ == "OK" else [])
        for uid, headers in wanted:
            message = email.message_from_bytes(bodies.get(uid, b""), policy=policy.default)
            items.append(to_item(provider, account, headers, body_text(message), f"uid-{validity}-{uid}"))
        return items


# ------------------------------------------------------------------------ looks --

class Looks:
    """A look soon after start, then every LOOK_EVERY_S, and at once when asked.
    `home` and `runtime` are read again for each look, so a changed setting counts."""

    def __init__(self, home: Callable[[], Path], runtime: Callable[[], Path]):
        self.home, self.runtime = home, runtime
        self.running = False
        self._wake = asyncio.Event()
        # Connections open now, so closing the app does not wait on a slow server.
        self._opened: set = set()

    def ask(self, *, even_if_running: bool = False) -> None:
        if even_if_running or not self.running:
            self._wake.set()

    @property
    def busy(self) -> bool:
        return self.running or self._wake.is_set()

    def _one(self, account: dict, letters: bool, known: Callable[[str], bool]) -> tuple[list[Item], str]:
        try:
            return read(account, letters, known, opened=self._opened), ""
        except MailError as error:
            logger.info("mail: %s could not be read (%s)", account["key"], error)
            return [], str(error)
        except Exception as exc:
            # One mailbox's surprise is that mailbox's error; the others are still read.
            logger.warning("mail: %s failed (%s)", account["key"], type(exc).__name__)
            return [], "mail_failed"

    async def look(self) -> int:
        """Read every account that is on; how many new messages were kept."""
        home, runtime = self.home(), self.runtime()
        accounts = [a for a in await asyncio.to_thread(load_accounts, home) if a.get("on", True)]
        if not accounts:
            return 0
        letters = (await asyncio.to_thread(load_state, runtime))["letters"]
        library = Library(runtime)
        # Counted while the character may not read mail, they are not in the library but not new either.
        told = await asyncio.to_thread(privacy.seen, runtime)
        values = await asyncio.to_thread(privacy.values_of, home)
        answers = await asyncio.gather(*(asyncio.to_thread(
            self._one, a, letters, lambda url: item_id(url) in told or library.seen(url)) for a in accounts))

        def keep() -> int:
            return privacy.keep(runtime, values, [item for items, _ in answers for item in items], "mail")

        kept = await asyncio.to_thread(keep)
        now = int(time.time())

        def record(state: dict) -> None:
            for account, (items, error) in zip(accounts, answers):
                state["last"][account["key"]] = {"at": now, "count": len(items), "error": error}

        await asyncio.to_thread(change_state, runtime, record)
        logger.info("mail: a look at %d mailboxes kept %d new messages", len(accounts), kept)
        return kept

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def loop(self) -> None:
        await self._wait(FIRST_LOOK_S)
        while True:
            await quiet.wait()
            self.running = True
            try:
                await self.look()
            except Exception:
                logger.exception("mail: a look failed")
            finally:
                self.running = False
            await self._wait(LOOK_EVERY_S)

    def close(self) -> None:
        """Break the connections still open, so their threads end now."""
        for imap in list(self._opened):
            with contextlib.suppress(Exception):
                imap.shutdown()
