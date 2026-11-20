"""The fixed line between what the character may do in a page by itself and what
needs the person, decided here in code and never by the model.

Reading, scrolling and going to an address are free. Typing into a field is
allowed, but never into a secret field (password, payment, one-time code: see
pageops.secret). An action with an effect outside the page (send, comment,
like or follow, post, order, delete, grant access, change an account, submit
a form) waits for the person's press on a card in the app, each time; so do
the page's own asks: a file it wants (upload), a file it saves to this
computer (download), and its own confirm or prompt (`asks` says which kind).
Only send, comment, like (and follow) and post may be let through without
asking, and only when the person chose 始终允许 for one kind on one site
(`Allowed`, revocable in Settings); the rest ask every time. A run keeps to its
sites: going to another one that the person did not name and no link led to
asks too (leave).

A control that only its name calls a submission (a bare 确认, 应用, save, a form
sent by GET) is "watch": it is pressed, and a card comes only if a request that
is not a GET really leaves on the press (operate.Hands holds it), as Gemini and
Claude in Chrome confirm at the point of risk.

`classify` sorts one action by what the page says of its target: its
accessible name, role and the form facts pageops.FACTS_JS reads. The
vocabularies, the money-next-to-a-confirm rule, the consent page rule and
HTML's implicit submission follow nanobrowser's classify.ts (Apache-2.0, see
NOTICE); the like, comment, send and account words, and the composer and
password-form rules, are ours. So are the rules for controls that carry no
words of their own: an icon button is named by its tooltip, and failing that
its class says like or delete; a switch saves a setting the moment it moves. It
errs inclusive: a false positive costs one press, a false negative an act that
cannot be taken back.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

# Kinds an outside action can be, in the order the card names them; then the page's own asks, and going to
# another site.
KINDS = ("send", "comment", "like", "post", "order", "delete", "account", "grant", "submit", "upload", "download",
         "dialog", "leave")
# The kinds the person may let through without asking, per site.
SKIPPABLE = ("send", "comment", "like", "post")
ALLOW_FILE = "browser-allow.json"
# Let through without a card at most this many a day on one site; past it the card comes back.
SKIPPED_A_DAY = 60


def _words(english: list[str], chinese: list[str]) -> re.Pattern:
    """English phrases on word boundaries, Chinese ones anywhere (classify.ts's vocabulary())."""
    spelled = [r"\s*".join(map(re.escape, w.split())) for w in english]
    return re.compile(r"\b(?:" + "|".join(spelled) + r")\b|" + "|".join(map(re.escape, chinese)), re.I)


# nanobrowser classify.ts, ported; 提交订单 and 确认订单 are ours.
PAY_WORDS = _words(
    ["pay", "payment", "pay now", "buy", "buy now", "purchase", "checkout", "check out", "place order",
     "place the order", "order now", "complete order", "complete purchase", "complete booking", "book now",
     "subscribe", "donate", "confirm and pay", "transfer money", "top up", "add to cart"],
    ["付款", "支付", "购买", "下单", "结账", "结算", "充值", "订阅", "转账", "捐款", "立即购买", "加入购物车",
     "投币", "充电", "打赏", "提交订单", "确认订单",
     # Ours: Japanese and Korean, matched anywhere as the Chinese are.
     "購入", "注文する", "注文を確定", "支払", "결제", "구매", "주문하기"])
DELETE_WORDS = _words(
    ["delete", "remove", "discard", "deactivate", "destroy", "erase", "purge", "trash", "unsubscribe",
     "cancel subscription", "cancel my subscription", "cancel account", "cancel membership", "cancel order",
     "close account"],
    ["删除", "移除", "清空", "注销", "取消订阅", "撤回"])
SUBMIT_WORDS = _words(
    ["submit", "send", "publish", "post", "confirm", "apply", "sign up", "register", "save", "update", "create",
     "approve", "reject"],
    ["提交", "发送", "发布", "确认", "保存", "更新", "创建", "批准", "拒绝", "驳回", "应用"])
COOKIE_REJECT = re.compile(r"cookie|^reject\s+all$|^(?:拒绝所有|全部拒绝|拒绝全部)$", re.I)
GRANT_WORDS = _words(["authorize", "authorise", "allow access", "grant access", "give access"],
                     ["授权", "允许访问", "授予访问"])
AFFIRMATIVE = re.compile(r"^(?:allow|continue|accept|approve|agree|yes|允许|继续|接受|同意|批准)(?:\b|$)", re.I)
CONSENT_PATH = re.compile(r"oauth|authori[sz]e|consent", re.I)
GENERIC_CONFIRM = re.compile(r"^(?:confirm|ok|okay|continue|next|proceed|agree|submit|yes|确认|确定|继续|下一步)"
                             r"(?:\b|$)", re.I)
DELETE_CLASSES = re.compile(r"(^|[\s_-])(delete|remove|destroy|trash|discard)([\s_-]|$)", re.I)
# Ours: a class that says like, for an icon whose only words are a count.
LIKE_CLASSES = re.compile(r"(^|[\s_-])(like|liked|heart|fav|favou?rite|star|starred|upvote|vote|thumbs?|follow|"
                          r"bookmark|zan|dianzan|digg|collect)([\s_-]|$)", re.I)
# A name with no letters in it: a count, a sign, nothing.
NO_WORDS = re.compile(r"^[\W\d_]*$")

# Ours: the kinds the card names and the person may let through.
LIKE_WORDS = _words(["like", "unlike", "follow", "unfollow", "favorite", "favourite", "star", "upvote",
                     "downvote", "bookmark", "subscribe to channel", "vote"],
                    ["点赞", "取消赞", "取消点赞", "关注", "取消关注", "收藏", "取消收藏", "投票", "投一票",
                     "いいね", "フォロー", "좋아요", "팔로우"])
# Short names that are a like only when they are the whole name ("赞 12"), not part of one ("赞助", "猜你喜欢").
LIKE_EXACT = re.compile(r"^(?:赞|已赞|喜欢|顶|踩|已关注|已收藏|like|liked)$", re.I)
COMMENT_WORDS = _words(["comment", "reply", "add comment", "leave a comment"],
                       ["评论", "回复", "留言", "评一下", "コメント", "返信", "댓글", "답글"])  # copy: voice
SEND_WORDS = _words(["send", "send message", "enviar", "envoyer", "senden", "отправить"],
                    ["发送", "发出", "送信", "送る", "보내기", "전송"])
POST_WORDS = _words(["post", "publish", "tweet", "share", "repost", "retweet", "quote"],
                    ["发布", "发表", "转发", "分享", "发帖", "发微博", "发动态", "投稿"])
ACCOUNT_WORDS = _words(["sign out", "log out", "logout", "signout", "change password", "update password",
                        "save settings", "save changes", "update profile", "block", "report", "mute"],
                       ["退出登录", "退出账号", "登出", "修改密码", "更改密码", "保存设置", "保存修改", "保存资料",
                        "拉黑", "屏蔽", "举报"])
_COMMENT_HINT = re.compile(r"comment|reply|评论|回复|留言", re.I)


def classify(mode: str, name: str, role: str, facts: dict, url: str = "") -> tuple[str, str]:
    """(kind, why) of one action: kind "" when it is free, "watch" when it is pressed and only a request it
    sends out is put to the person. `mode` is "click" (a click, or Enter or Space on a focused button or link)
    or "enter" (Enter in a field). `facts` is what FACTS_JS read of the target."""
    name = " ".join(str(name or facts.get("label") or facts.get("text") or "").split())[:200]
    # An icon with only a count or a sign for a name: what it says on hover or in its drawing is its name too.
    tip = " ".join(str(facts.get("tip") or "").split())[:120]
    if tip and NO_WORDS.match(name):
        name = f"{name} {tip}".strip()
    form = facts.get("form") or None
    if mode == "enter":
        if facts.get("link") or role in ("button", "link", "menuitem", "tab", "checkbox", "switch"):
            return classify("click", name, role, facts, url)
        if form:
            button = str(form.get("button") or "")
            named = _by_name(button, facts, url) if button else None
            if named:
                return named[0], f"Enter submits the form through {button!r}: {named[1]}"
            if form.get("password"):
                return "account", "Enter submits a form that holds a password field"
            if form.get("search"):
                return "", "a search form"
            kind = _kind_of(button, False) if button else ""
            return kind or _sent(form), "Enter submits the form"
        if facts.get("textEntry") and not facts.get("search"):
            return _composer_kind(facts), "Enter in a text box with no form sends what it holds"
        if facts.get("tag") in ("iframe", "frame", "object", "embed"):
            return "send", "Enter in a frame from another site, whose box the app cannot see"
        return "", "Enter does nothing outside here"
    named = _by_name(name, facts, url)
    if named:
        return named
    if form and form.get("password") and (facts.get("submitter") or role == "button"):
        return "account", "a button in a form that holds a password field"
    if DELETE_CLASSES.search(str(facts.get("classes") or "")):
        return "delete", f"its class or test id ({str(facts.get('classes'))[:80]!r}) is destructive"
    if NO_WORDS.match(name) and LIKE_CLASSES.search(str(facts.get("classes") or "")):
        return "like", f"a button with no words whose class ({str(facts.get('classes'))[:80]!r}) says like"
    if (role == "switch" or facts.get("switch")) and not (form and (form.get("submit") or facts.get("submitter"))):
        return "account", "a switch outside a form saves a setting the moment it moves"
    kind = _kind_of(name, bool(facts.get("link")) or role in ("link", "tab"))
    if kind:
        return kind, f"the name {name!r} is {kind} vocabulary"
    if facts.get("composer") and not facts.get("textEntry") and role in ("button", "generic", "img", "") and (
            facts.get("iconOnly") or not name):
        return _composer_kind(facts), "a button with no words by a text box"
    if facts.get("submitter") and form and not form.get("search"):
        return _sent(form), f"it submits its form ({str(form.get('method') or 'get').upper()})"
    if (SUBMIT_WORDS.search(name) and not (form or {}).get("search") and not COOKIE_REJECT.search(name)
            and not facts.get("link")):
        return "watch", f"the name {name!r} is submission vocabulary"
    return "", "reading or moving about"


def _sent(form: dict) -> str:
    """A form posted is a submission; one sent by GET only reads, unless its page posts on the press."""
    return "submit" if str(form.get("method") or "get").lower() == "post" else "watch"


def asks(message: str, url: str) -> str:
    """The kind a page's own confirm or prompt asks about, read from its words as a button's name is: "dialog"
    when they name none."""
    kind = classify("click", message, "button", {}, url)[0]
    return kind if kind not in ("", "watch") else "dialog"


# Ours: a link to the checkout page by these words alone only goes there; the order is placed on that page.
CHECKOUT = re.compile(r"^(?:去?结算|去?结账|check\s*out|go to checkout|proceed to checkout)(?:\s*[(（]?\d+[)）]?)?$", re.I)


def _by_name(name: str, facts: dict, url: str) -> tuple[str, str] | None:
    """The kinds a name alone decides, whatever the element: pay, grant, delete, account."""
    if PAY_WORDS.search(name) and not (facts.get("away") and CHECKOUT.match(name.strip())):
        return "order", f"the name {name!r} is payment vocabulary"
    if GRANT_WORDS.search(name):
        return "grant", f"the name {name!r} grants access"
    if AFFIRMATIVE.search(name.strip()) and CONSENT_PATH.search(urlsplit(url).path or ""):
        return "grant", f"{name!r} on a consent page"
    if GENERIC_CONFIRM.search(name.strip()) and facts.get("money"):
        return "order", f"{name!r} next to the amount {str(facts['money'])[:40]!r}"
    if DELETE_WORDS.search(name):
        return "delete", f"the name {name!r} is destructive vocabulary"
    if ACCOUNT_WORDS.search(name):
        return "account", f"the name {name!r} changes the account"
    return None


def _kind_of(name: str, link: bool) -> str:
    """The kind a name says; for a link or a tab, which mostly lead somewhere ("我的收藏"), only a whole name."""
    bare = re.sub(r"[\d\s.,万千kKmMwW+]+$", "", name).strip()
    if LIKE_EXACT.match(bare):
        return "like"
    if link:
        return next((kind for kind, words in (("like", LIKE_WORDS), ("comment", COMMENT_WORDS), ("send", SEND_WORDS),
                                              ("post", POST_WORDS)) if words.fullmatch(bare)), "")
    for kind, words in (("like", LIKE_WORDS), ("comment", COMMENT_WORDS), ("send", SEND_WORDS),
                        ("post", POST_WORDS)):
        if words.search(name):
            return kind
    return ""


def _composer_kind(facts: dict) -> str:
    return "comment" if _COMMENT_HINT.search(str(facts.get("hint") or "")) else "send"


def site_of(url: str) -> str:
    """The site as the card and the allow list name it: its registrable host (an address stays whole), and a
    port other than the scheme's."""
    from .sites import key_of
    parts = urlsplit(url)
    return key_of(url) + (f":{parts.port}" if parts.port else "")


class Allowed:
    """The person's "do not ask again for this kind on this site": {site: [kind]} in the desktop folder,
    set only from a card's tick and revoked in Settings."""

    def __init__(self, desktop: Path):
        self.path = Path(desktop) / ALLOW_FILE
        self.lock = threading.Lock()
        self.counts: dict[tuple[str, str], int] = {}

    def all(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {site: [k for k in kinds if k in SKIPPABLE] for site, kinds in data.items()
                if isinstance(kinds, list)} if isinstance(data, dict) else {}

    def skips(self, site: str, kind: str) -> bool:
        if kind not in SKIPPABLE or kind not in self.all().get(site, []):
            return False
        day = (time.strftime("%Y-%m-%d"), site)
        with self.lock:
            if self.counts.get(day, 0) >= SKIPPED_A_DAY:
                return False
            self.counts[day] = self.counts.get(day, 0) + 1
        return True

    def set(self, site: str, kind: str, on: bool) -> dict:
        from ..storage import atomic_write_text
        with self.lock:
            data = self.all()
            kinds = [k for k in data.get(site, []) if k != kind] + ([kind] if on and kind in SKIPPABLE else [])
            if kinds:
                data[site] = kinds
            else:
                data.pop(site, None)
            atomic_write_text(self.path, json.dumps(data, ensure_ascii=False))
        return data
