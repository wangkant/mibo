"""Signing in to sites: one way for every site, in the app's own browser.

A site asks for an account when its page says so (a password field shown, a
sign-in page, a check), told from the page alone by CHECK_JS, never from a list
of sites. A sign-in box laid over a page whose content is still there is a
prompt, not a wall: the character closes it or reads past it and carries on
signed out. Then the page is the person's: the run, a read or the Connections
page brings it to the pane, the column beside it says in one sentence what is
needed, and the character waits. The person types, scans the code or passes
the check; once the wall is gone the task goes on where it stopped. If the
browser itself filled a saved password, the character may press the site's own
sign-in button, when the person allowed that for the site; it never reads the
field. A one-time code, a CAPTCHA or a new-device check is always the person's.

Signed in or not is told from the session itself, never from a wall seen once:
a site counts as signed in only on evidence of an account (the person finished
the site's sign-in in the pane and the site's session cookies changed, or the
site's own account cookies are there: cookie names, by presence only), and
it stops counting when those cookies are gone or the site sends a page of it
to its sign-in. SITES (signin_sites.json) holds hints about the big platforms
and webmail: where they sign in, which cookie names only an account has, and
where an account's messages are (web/inbox.py reads them; `connected` lists the
sites signed in). A hint that proves wrong is dropped for that site on this
computer.

Cookies and saved passwords stay in the pane's WebView2 profile: nothing here
reads a value out. What is kept per site, in FILE under the desktop folder:
whether it is signed in, since when and on what evidence, the names of the
cookies its session showed, when it was last used, whether the browser filled
a saved password there, the person's choices (read while they are on it, read
on the character's own request during a task) and their answer on 自动登录. The
background choice is the site card's feed (web/sites.py).
"""
from __future__ import annotations

import asyncio
import functools
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from ..storage import atomic_write_text

FILE = "signins.json"
# Walls the character waits behind for the person; the rest end a run as before.
WAITED = ("sign_in", "sign_in_overlay", "verification")
# How long a run waits for the person to sign in, and how long one look of the page may hold the call.
WAIT_S = 600.0
POLL_S = 12.0
# A sign-in form seen this long ago, gone since with the site's session cookies changed, is a sign-in done.
SIGNED_WITHIN_S = 1800.0
# Hints about the big platforms' sign-ins (data), and their marks for Settings' picker.
SITES = Path(__file__).with_name("signin_sites.json")
MARKS = Path(__file__).with_name("marks")
CHOICES = {"here": True, "task": True}
AUTO = ("always", "never")

# What the page asks for, read off it: a check, a sign-in, a sign-in layer in front of a page with nothing else on
# it, or nothing; a sign-in box over a page whose content is still there is a `prompt` instead. `form`: a way to
# sign in shows (a password or code field, a QR code), in the page or in such a box. `account`: "out" when the top
# of the page offers to sign in, "in" when it shows an account's avatar or menu, else "". Whether a password field
# shows and the browser filled it (its :autofill state, never its value), and where that form's own sign-in button
# is. `hint` ({in, out}: selectors) comes from SITES. The wall words are reader.js's.
CHECK_JS = r"""(hint = {}) => {
  const shown = (e) => { const b = e.getBoundingClientRect(); if (b.width < 2 || b.height < 2) return false;
    const s = getComputedStyle(e); return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05; };
  const textOf = (e) => ((e && e.innerText) || '').replace(/\s+/g, ' ').trim();
  const VERIFY = /(verify (that )?you are (a )?human|are you a robot|confirm (that )?you.re not a (ro)?bot|just a moment|checking your browser|security (check|verification)|performing security verification|unusual traffic|captcha|人机验证|安全验证|环境异常|滑动.{0,6}验证|拖动.{0,6}滑块|请完成验证|ロボットではありません|画像認証|보안 문자|자동입력 방지|проверка.{0,10}(робот|браузер)|подтвердите, что вы не робот)/i;
  const SIGNIN = /(sign in|log in|login|sign up|continue with (google|apple|email)|登录|登陆|扫码|ログイン|로그인|войти|вход)/i;
  const QR = /(扫码|扫一扫|二维码|scan (the )?(qr|code)|qr code|QRコード|QR 코드)/i;
  const title = document.title || '';
  const body = textOf(document.body).slice(0, 20000);
  const frames = [...document.querySelectorAll('iframe')].filter((f) => shown(f) && f.offsetWidth >= 100 &&
    /captcha|challenge|turnstile|geetest|arkoselabs|hcaptcha|recaptcha\/api2\/anchor/i.test(f.src || ''));
  const filledOf = (p) => { for (const s of [':autofill', ':-webkit-autofill']) { try { if (p.matches(s)) return true; } catch (e) {} } return false; };
  // A sign-in box in front of the page: what sits at the middle of the screen belongs to a fixed layer.
  let layer = null;
  for (const [x, y] of [[0.5, 0.5], [0.5, 0.35], [0.5, 0.65]]) {
    for (let el = document.elementFromPoint(innerWidth * x, innerHeight * y); el && el !== document.body; el = el.parentElement) {
      if (getComputedStyle(el).position !== 'fixed') continue;
      const b = el.getBoundingClientRect(), t = textOf(el).slice(0, 2000);
      if (b.width * b.height >= innerWidth * innerHeight * 0.08 && (SIGNIN.test(t) || QR.test(t) || el.querySelector('input[type=password]'))
          && t.length < 1500 && !el.querySelector('video')) { layer = el; break; }
    }
    if (layer) break;
  }
  // The page's own words outside that box: plenty of them, and the box is only a prompt over a page a visitor may read.
  const outside = layer ? body.length - textOf(layer).length : body.length;
  const prompt = layer && outside > 1500 ? textOf(layer).slice(0, 80) : '';
  const inLayer = (e) => Boolean(prompt) && layer.contains(e);
  // A password field is a sign-in when the page is short or its form says so (a settings page's
  // "current password" is not one).
  const asks = (p) => { const scope = p.form || p.closest('section,main,div[role=dialog],dialog') || document.body;
    return body.length < 4000 || inLayer(p) || SIGNIN.test(textOf(scope).slice(0, 2000)); };
  const pwsAll = [...document.querySelectorAll('input[type=password]')].filter((p) => shown(p) && asks(p));
  const pws = pwsAll.filter((p) => !inLayer(p));
  // A one-time code asked for on its own page: still the sign-in, and always the person's.
  const codeOf = (i) => shown(i) && (body.length < 4000 || inLayer(i)) &&
    (i.autocomplete === 'one-time-code' || /otp|\botc\b|totp|\b2fa\b|two.?factor|one.?time|verif.*code|sms.?code|enter (the )?code|\d.?digit code|\bpin\b|验证码|驗證碼|校验码|動態|认证码|確認コード|인증/i.test(
      [i.name, i.id, i.placeholder, i.getAttribute('aria-label'), i.labels && i.labels[0] && i.labels[0].innerText].join(' ')));
  const codesAll = [...document.querySelectorAll('input')].filter(codeOf);
  const codes = codesAll.filter((i) => !inLayer(i));
  let kind = '', evidence = '';
  // A short page that only says to sign in first ("请登录后重试"), whatever its title calls itself.
  const notice = body.length < 1500 && /请先?登录|登录后(重试|继续|查看|访问)|(log|sign) ?in to (continue|view|see|access)|(must|need to) (be )?(log|sign)(ged|ed)? ?in/i.test(body);
  if (frames.length || (!notice && (VERIFY.test(title) || (VERIFY.test(body.slice(0, 1500)) && body.length < 3000)))) {
    kind = 'verification'; evidence = frames.length ? frames[0].src.slice(0, 80) : (title.match(VERIFY) || body.match(VERIFY))[0];
  } else if (pws.length) { kind = 'sign_in'; evidence = 'password field'; }
  else if (codes.length) { kind = 'sign_in'; evidence = 'code field'; }
  else if (layer && !prompt) { kind = 'sign_in_overlay'; evidence = textOf(layer).slice(0, 80); }
  // A sign-in flow's own short page with no field to see (a QR code to scan, a phone button).
  else if (body.length < 4000 && SIGNIN.test(title + ' ' + body) && (/^(login|signin|passport|sso|auth|accounts?|id|idp)\./i.test(location.hostname)
    || /\/(log-?in|sign-?in|sso|passport)(\/|$|\.)/i.test(location.pathname))) { kind = 'sign_in'; evidence = 'sign-in page'; }
  else if (notice) { kind = 'sign_in'; evidence = 'sign-in notice'; }
  const form = Boolean(kind === 'sign_in' || kind === 'sign_in_overlay' || pwsAll.length || codesAll.length ||
    (layer && (QR.test(textOf(layer)) || layer.querySelector('canvas,img[src*="qr" i],img[alt*="qr" i],[class*="qrcode" i]'))));
  // The top of the page: a short "登录" offered there, or an account's avatar or menu.
  const band = Math.max(140, innerHeight * 0.15);
  const top = (e) => { const b = e.getBoundingClientRect(); return b.top < band && b.bottom > 0 && shown(e) && !(layer && layer.contains(e)); };
  const pick = (list) => { for (const s of list || []) { try { const e = document.querySelector(s); if (e && shown(e)) return true; } catch (e) {} } return false; };
  const OFFER = /^(登录|登入|登錄|立即登录|请登录|登录\s*[\/|｜]?\s*注册|亲，请登录|你好，请登录|log ?in|sign ?in|log ?in\s*[\/|]?\s*sign ?up|sign ?in\s*[\/|]?\s*(sign|join) ?(up|now)|hello, sign in|ログイン|로그인|войти|вход)$/i;
  const offered = pick(hint.out) || [...document.querySelectorAll('a,button,[role=button],[class*="login" i],[class*="signin" i]')].some(
    (e) => e.children.length <= 3 && OFFER.test(textOf(e).slice(0, 30)) && top(e));
  const AVATAR = /avatar|头像|user-?(info|menu|face|pic)|account-?(menu|avatar)|profile-?(pic|photo|menu|avatar)|nav-?user/i;
  const avatar = pick(hint.in) || [...document.querySelectorAll('img,[class*="avatar" i],[class*="user" i],[class*="account" i],[class*="profile" i]')].some(
    (e) => top(e) && AVATAR.test([e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className, e.getAttribute('alt'), e.id, e.tagName === 'IMG' ? e.src : ''].join(' ')));
  const account = offered ? 'out' : avatar ? 'in' : '';
  const filled = pwsAll.find(filledOf);
  let button = null;
  if (filled) {
    const scope = filled.form || filled.closest('section,main,div[role=dialog],dialog') || document.body;
    const all = [...scope.querySelectorAll('button,input[type=submit],input[type=image],[role=button]')].filter(shown);
    const choose = all.find((b) => (b.type || '').toLowerCase() === 'submit' && SIGNIN.test(textOf(b) || b.value || ''))
      || all.find((b) => SIGNIN.test(textOf(b) || b.value || '')) || all.find((b) => (b.type || '').toLowerCase() === 'submit');
    if (choose) { choose.scrollIntoView({block: 'center'}); const r = choose.getBoundingClientRect();
      button = {x: r.x + r.width / 2, y: r.y + r.height / 2, words: (textOf(choose) || choose.value || '').slice(0, 30)}; }
  }
  return {kind, evidence: String(evidence).slice(0, 80), password: pwsAll.length > 0, filled: Boolean(filled), button,
    form, prompt, account};
}"""

# A sign-in flow's own address (a host or a path), left once the person is in.
SIGNIN_HOST = frozenset({"login", "signin", "passport", "sso", "auth", "accounts", "account", "id", "idp"})
SIGNIN_PATH = re.compile(r"/(log-?in|sign-?in|sso|oauth\d?|authorize|auth|passport|session|challenge|2fa|mfa|otp|"
                         r"verify|checkpoint)(/|$|\?|\.)", re.IGNORECASE)

_lock = threading.Lock()


def in_flow(url: str) -> bool:
    """The address is a sign-in flow's own (its host or its path says so)."""
    parts = urlsplit(url)
    return (parts.hostname or "").split(".")[0] in SIGNIN_HOST or bool(SIGNIN_PATH.search(parts.path or "/"))


# What the model is shown of a page while the person signs in (web/pagejudge.py), and the page's own sign-in link
# for the column's 登录 button.
PAGE_JS = r"""(() => {
  const shown = (e) => { const b = e.getBoundingClientRect(); return b.width > 2 && b.height > 2; };
  const text = ((document.body && document.body.innerText) || '').replace(/\s+/g, ' ').trim();
  const link = [...document.querySelectorAll('a[href^="http"]')].find((a) => shown(a) &&
    (a.innerText || '').trim().length <= 16 && /登录|登入|登錄|log ?in|sign ?in|ログイン|로그인|войти/i.test(a.innerText || ''));
  return {url: location.href, title: document.title || '', text: text.slice(0, 2500), chars: text.length,
    password: [...document.querySelectorAll('input[type=password]')].some(shown), link: link ? {href: link.href} : null};
})()"""


def page(cdp: Callable[..., dict]) -> dict:
    """PAGE_JS on the page `cdp` reaches; {} when it did not answer."""
    try:
        answer = cdp("Runtime.evaluate", {"expression": PAGE_JS, "returnByValue": True}, timeout=8)
    except RuntimeError:
        return {}
    value = (answer.get("result") or {}).get("value")
    return value if isinstance(value, dict) else {}


def key(url: str) -> str:
    """The site an address belongs to, as the gate's allow list names it (a port kept)."""
    from .gate import site_of
    return site_of(url if "://" in url else f"https://{url}")


def bare(site: str) -> str:
    """A site key without its port."""
    return site.rsplit(":", 1)[0] if re.search(r":\d+$", site) else site


# ---------------------------------------------------------------- the hints (SITES)

@functools.lru_cache(maxsize=1)
def hints() -> tuple[dict, ...]:
    return tuple(row for row in json.loads(SITES.read_text(encoding="utf-8"))["sites"] if isinstance(row, dict))


def hint(site: str) -> dict:
    """The hint for a site key (several rows may share a site, as Gmail and Google do: the first)."""
    return next((row for row in hints() if row["site"] == bare(site)), {})


def find(words: str) -> dict:
    """The hinted site the person named ("抖音", "b站", "Gmail", "douyin.com"), or {}."""
    said = " ".join(str(words or "").lower().split())
    if not said:
        return {}
    for row in hints():
        names = [row["name"].get("zh", ""), row["name"].get("en", ""), *row.get("also", [])]
        if any(said == n.lower() or said.replace(" ", "") == n.lower().replace(" ", "") for n in names if n):
            return row
    host = urlsplit(said if "://" in said else f"https://{said}").hostname or ""
    return next((row for row in hints() if host and (host == row["site"] or host.endswith("." + row["site"]))
                 and urlsplit(row["home"]).hostname == host), {}) or next(
        (row for row in hints() if host and (host == row["site"] or host.endswith("." + row["site"]))), {})


def picks(lang: str) -> list[dict]:
    """Settings' picker: the hinted sites, the person's language's first, mail after."""
    first = "zh" if lang.startswith("zh") else "en"
    rows = sorted(hints(), key=lambda row: (bool(row.get("mail")), row.get("lang") != first))
    return [{"id": row["id"], "site": row["site"], "name": row["name"].get(first) or row["name"]["en"],
             "home": row["home"], "signin": row.get("signin") or row["home"], "mail": bool(row.get("mail")),
             "mark": mark(row["id"])} for row in rows]


def mark(ident: str) -> str:
    """The site's own icon, as a data address, or ""."""
    import base64
    path = MARKS / f"{ident}.png"
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode() if path.exists() else ""


def example(site: str, lang: str) -> str:
    """One thing to ask the character once signed in to the site."""
    first = "zh" if lang.startswith("zh") else "en"
    said = (hint(site).get("example") or {}).get(first)
    if said:
        return said
    # copy: voice (a message suggested for the person to send)
    return "查看我在该网站的新消息" if first == "zh" else "Anything new for me on this site?"


def _matches(present, name: str) -> bool:
    return any(p.startswith(name[:-1]) for p in present) if name.endswith("*") else name in present


def names_of(entry: dict, site: str) -> list[str]:
    """The cookie names whose presence is the site's session: learned at its sign-in here, else the hint's."""
    if entry.get("marks"):
        return list(entry["marks"])
    return [] if entry.get("hint_off") else list(hint(site).get("account_cookies") or [])


def has_session(present, site: str, entry: dict | None = None) -> bool | None:
    """Whether the cookie names `present` for the site hold its session: None when there is nothing to tell by."""
    names = names_of(entry or {}, site)
    if present is None or not names:
        return None
    return any(_matches(present, name) for name in names)


def status(entry: dict | None, present, site: str) -> str:
    """"in", "out", or "unsure" (未确认) when the app cannot tell. `present`: the cookie names the profile holds for
    the site, or None when they could not be read."""
    entry = entry or {}
    if entry.get("gone"):
        return "out"
    held = has_session(present, site, entry)
    if held is not None:
        return "in" if held else "out"
    if entry.get("state") == "in":
        return "in" if entry.get("how") else "unsure"
    return "out"


# ---------------------------------------------------------------- what is kept per site

def _path(desktop: Path) -> Path:
    return Path(desktop) / FILE


def load(desktop: Path) -> dict:
    try:
        saved = json.loads(_path(desktop).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in saved.items() if isinstance(v, dict)} if isinstance(saved, dict) else {}


def change(desktop: Path, site: str, edit: Callable[[dict], None]) -> dict:
    """Read, change and write one site's entry as one step; the entry as written."""
    with _lock:
        saved = load(desktop)
        entry = saved.setdefault(site, {})
        edit(entry)
        Path(desktop).mkdir(parents=True, exist_ok=True)
        atomic_write_text(_path(desktop), json.dumps(saved, ensure_ascii=False, indent=1))
        return entry


def forget(desktop: Path, site: str) -> None:
    with _lock:
        saved = load(desktop)
        if saved.pop(site, None) is not None:
            atomic_write_text(_path(desktop), json.dumps(saved, ensure_ascii=False, indent=1))


def chose(desktop: Path, url: str, name: str) -> bool:
    """The person's choice `name` ("here", "task") for the site of `url`."""
    entry = load(desktop).get(key(url)) or {}
    return entry.get(name, CHOICES[name]) is not False


def auto(desktop: Path, url: str) -> str:
    """Their answer on 自动登录 for the site of `url`: "always", "never" or "" (not asked yet)."""
    value = (load(desktop).get(key(url)) or {}).get("auto", "")
    return value if value in AUTO else ""


def signed_in(desktop: Path, url: str) -> bool:
    entry = load(desktop).get(key(url)) or {}
    return entry.get("state") == "in" and not entry.get("gone")


def connected(desktop: Path, lang: str = "en") -> list[dict]:
    """The sites signed in to here that the character may read on its own (their "task" choice), each as
    `platform` gives it. Hint rows that share a site (Google and Gmail): the one the person connected, by its home
    or its name, else the first that says where messages are."""
    out = []
    for site, entry in load(desktop).items():
        if entry.get("state") != "in" or entry.get("gone") or entry.get("task") is False:
            continue
        rows = [row for row in hints() if row["site"] == bare(site)]
        host = urlsplit(str(entry.get("home") or "")).hostname
        row = next((r for r in rows if urlsplit(r["home"]).hostname == host or entry.get("name") in r["name"].values()),
                   None) or next((r for r in rows if r.get("messages")), rows[0] if rows else {})
        out.append(platform(site, entry, row, lang))
    return out


def platform(site: str, entry: dict, row: dict, lang: str = "en") -> dict:
    """{"site", "name", "home", "pages"}: `pages` the hint's addresses of its messages ({"what", "url"}), empty
    where no hint says."""
    first = "zh" if str(lang).startswith("zh") else "en"
    return {"site": site, "name": (row.get("name") or {}).get(first) or entry.get("name") or bare(site),
            "home": row.get("home") or entry.get("home") or f"https://{bare(site)}/",
            "pages": [page for page in row.get("messages") or [] if isinstance(page, dict) and page.get("url")]}


def kept_out(desktop: Path, url: str) -> bool:
    """A page of a signed-in site whose background choice is off: the person's own, never kept in the library
    or the browsing record."""
    if not signed_in(desktop, url):
        return False
    from . import sites
    card = sites.load(Path(desktop).parent).get(sites.key_of(url)) or {}
    return not (isinstance(card.get("feed"), dict) and card["feed"].get("on"))


def home_of(url: str) -> str:
    """The site's front page as the browser reached it (its scheme and port kept)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def became(desktop: Path, url: str, how: str, marks: list[str] | None = None, hint_off: bool = False,
           name: str = "") -> None:
    """Evidence of an account on the site of `url`: "signin" (the person finished its sign-in here), "session"
    (its account cookies are there) or "page". A site signed in to just now, if the person chose it among their
    platforms, has its own feed read when they agreed to that (feed.read_chosen)."""
    now = round(time.time())
    fresh = []

    def edit(entry: dict) -> None:
        if entry.get("state") != "in" or entry.get("gone"):
            fresh.append(True)
            entry.update(at=now)
            # The first time it is signed in here, Settings opens its choices once.
            if not entry.get("told"):
                entry["fresh"] = True
        entry.update(state="in", how=how, used=now)
        entry.pop("gone", None)
        entry.setdefault("home", home_of(url))
        if name:
            entry.setdefault("name", name)
        if marks:
            entry["marks"] = sorted(marks)[:12]
        if hint_off:
            entry["hint_off"] = True
    change(desktop, key(url), edit)
    forget_wall(desktop, url)
    if fresh:
        from ..panels import feed
        feed.read_chosen(Path(desktop).parent, bare(key(url)))


def gone(desktop: Path, url: str) -> None:
    """The site itself said the account is gone (it sent a page of it to its sign-in): signed out."""
    def edit(entry: dict) -> None:
        entry.update(state="out", gone=True)
    change(desktop, key(url), edit)


def used(desktop: Path, url: str) -> None:
    change(desktop, key(url), lambda entry: entry.update(used=round(time.time())))


def note_flow(desktop: Path, url: str) -> None:
    """Where Settings' 登录 opens for a site met only in use: its sign-in page's address, without its query."""
    parts = urlsplit(url)
    site = key(url)
    if site in load(desktop):
        change(desktop, site, lambda entry: entry.setdefault("signin", f"{parts.scheme}://{parts.netloc}{parts.path}"))


def forget_wall(desktop: Path, url: str) -> None:
    from .. import browsed
    pace = browsed.Pace(desktop)
    walls = pace.walls()
    site = browsed.site_of(urlsplit(url).hostname or "")
    if walls.pop(site, None) is not None:
        atomic_write_text(pace.path, json.dumps(walls))


def signed_out(desktop: Path, site: str) -> None:
    """Signed out from Settings (its cookies gone): off the list; the person's choices for it stay."""
    def edit(entry: dict) -> None:
        entry["state"] = "out"
        for name in ("how", "at", "gone", "marks", "fresh"):
            entry.pop(name, None)
    change(desktop, site, edit)


# ---------------------------------------------------------------- the character waiting (service side)

def asker(home: Path) -> Callable[..., dict]:
    """`ask(op, timeout, **fields)` to /api/browser/signin in the running app."""
    from ..browsed import _ask

    def ask(op: str, timeout: float, **fields) -> dict:
        return _ask(home, "POST", "/api/browser/signin", json={"op": op, **fields}, timeout=timeout) or {
            "status": "no_app"}
    return ask


async def wait(ask: Callable[..., dict], wall: str, first: dict | None = None, say: str = "") -> dict:
    """Wait in the pane for the person to get past `wall` (sign in, pass the check); `say` is the judgment's
    sentence for them. `ask(op, timeout, **fields)` reaches /api/browser/signin in the app; `first` is its answer
    when the wait was begun already. {"status": "ok"} once the page is past it; "failed" with the person's own
    sentence when they skipped the site; else "stopped", "paused" or "handover" (no sign-in in time, or no app)
    with a line for the model."""
    began = time.monotonic()
    answer = first or await asyncio.to_thread(ask, "begin", 30, wall=wall, say=say)
    while answer.get("status") == "waiting" and time.monotonic() - began < WAIT_S:
        answer = await asyncio.to_thread(ask, "poll", POLL_S + 10)
    status = answer.get("status")
    if status == "skipped":
        # In the person's language: the reply shows it as it is.
        return {"status": "failed", "line": answer["said"]}
    if status == "ok" and answer.get("signed") is False:
        return {"status": "ok", "line": "[not signed in] the page moved on without a sign-in (the person closed it or "
                                        "went past it); go on signed out where the task allows, and say in one "
                                        "sentence what needs their account"}
    if status == "ok":
        return {"status": "ok", "line": "[signed in] the person got past the sign-in; the task goes on from here"}
    if status in ("stopped", "paused"):
        return {"status": status, "line": f"[{status}] the person stopped while the page waited for their sign-in"}
    await asyncio.to_thread(ask, "end", 10)
    return {"status": "handover", "line": f"the page shows a {wall} wall and no sign-in came in time; they say 继续 "
                                          f"once they have signed in"}


async def read_after(home: Path, url: str, said: str, page: dict) -> dict:
    """A read with the session that met a sign-in: the page comes to the pane, they sign in, and it is read once
    more; `page` as it was when they did not."""
    from .. import browsed
    ask = asker(home)
    wall = page["error"] if page["error"] in WAITED else "sign_in"
    first = await asyncio.to_thread(ask, "read", 40, url=url, task=said or url, wall=wall)
    if first.get("status") != "waiting" or (await wait(ask, wall, first))["status"] != "ok":
        return page
    return await asyncio.to_thread(browsed.read_signed_in, home, url)


# ---------------------------------------------------------------- a sign-in box over a run's page

def judge(wall: dict, layer: dict, before: str | None, clicked: bool) -> dict:
    """A run's look at a page: `wall` as WALL_JS found it, `layer` as CHECK_JS did, `before` the sign-in prompt
    the last look of this same page saw (None for its first look), `clicked` whether the last step was a click or
    a key. A prompt over a page a visitor may read is no wall, and neither is a password form inside it, unless
    it came up right after a click (what was pressed needs an account)."""
    prompt = str(layer.get("prompt") or "")
    if wall.get("kind") == "sign_in" and prompt and layer.get("kind") != "sign_in":
        wall = {**wall, "kind": "", "evidence": ""}
    if not wall.get("kind"):
        if layer.get("kind") == "sign_in_overlay" or layer.get("evidence") in ("sign-in page", "sign-in notice"):
            wall = {**wall, "kind": layer["kind"], "evidence": layer.get("evidence", "")}
        elif prompt and before == "" and clicked:
            wall = {**wall, "kind": "sign_in_overlay", "evidence": f"what was pressed needs an account: {prompt}"}
    return {**wall, "prompt": prompt if not wall.get("kind") else ""}


def prompt_line(prompt: str, site: str) -> str:
    """What the model is told of a sign-in box it may close, and what the hints say of the site signed out."""
    row = hint(site)
    known = (f" About this site signed out: works: {row['open']}; needs an account: {row['walls']}."
             if row.get("open") else "")
    return (f"\n[A sign-in box is over the page (\"{prompt[:60]}\"). It is a prompt, not a wall: close it (its close "
            f"button, or press Escape) or work past it, and carry on signed out. Hand the page to the person only "
            f"when what was asked cannot be reached without an account: then say in one sentence what needs it, and "
            f"offer to do what can be done without.{known}]")
