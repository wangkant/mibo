"""Measure the memory commands on a running home, through the page's own API.

    python tools/remember_command.py <home>

The home must be fresh (nothing remembered yet) and answer with a stand-in model that keeps what a
message calls a card, ID, password or code through `mem` (any model works for the rest). It prints one
JSON object: what each 记住 kept and under which kind, whether the name and the home were set and replaced,
whether a dislike reached the recommender's profile, how many secrets were kept, what a forget took out
of a mixed message, and how the 你都记得什么 answer reads.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

home = Path(sys.argv[1])
sys.stdout.reconfigure(encoding="utf-8")
url = json.loads((home / "runtime/desktop/welcome.json").read_text(encoding="utf-8"))["url"]
address = urlsplit(url)
token = address.fragment.partition("token=")[2]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None):
    req = urllib.request.Request(f"{address.scheme}://{address.netloc}/api/{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", "x-personagent-setup-token": token})
    with opener.open(req, timeout=240) as r:
        return json.loads(r.read().decode())


def say(text):
    """The character's lines answering `text` in the main chat."""
    out = call("chat", {"text": text})
    after = False
    lines = []
    for m in out.get("messages", []):
        if m.get("role") == "user":
            after = m.get("text") == text
        elif after:
            lines.append(m)
    return lines


def luhn_card(prefix="622202", n=16):
    """A card number of `n` digits whose check digit is right."""
    body = prefix + "1234567890123"[: n - len(prefix) - 1]
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return body + str((10 - total % 10) % 10)


def id18(first17="11010519491231002"):
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    return first17 + "10X98765432"[sum(int(c) * w for c, w in zip(first17, weights)) % 11]


def person():
    return call("person")


def profile():
    path = home / "runtime" / "profile.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


result = {"remember": [], "secrets": [], "forget": {}, "recall": {}}

# 1. Remember: what each command keeps, under which kind.
REMEMBER = ["记住我叫林晓", "记住我住在徐汇", "记住：我住在闵行", "记住：我不喜欢看动漫解说",
            "记住我对芒果过敏", "记住我喜欢吃火锅", "记住我下周三要考统计推断", "记住我养了一只橘猫叫年糕"]
for text in REMEMBER:
    reply = " / ".join(m.get("text", "") for m in say(text))
    result["remember"].append({"said": text, "reply": reply})
view = person()
facts = view.get("facts") or []
result["store"] = {"name": view.get("name"), "facts": [[f["kind"], f["text"]] for f in facts],
                   "plans": [p["text"] for p in view.get("plans") or []]}
homes = [f for f in facts if "住" in f["text"]]
prof = profile()
rules = [r.get("topic") for r in prof.get("rules") or [] if r.get("kind") == "topic"]
result["checks"] = {
    "name_set": view.get("name") == "林晓",
    "one_home_fact": len(homes) == 1 and "闵行" in homes[0]["text"],
    "dislike_kind": any(f["kind"] == "dislike" and "动漫解说" in f["text"] for f in facts),
    "dislike_in_profile": any("动漫解说" in str(t) for t in rules),
    "allergy_kind_health": any(f["kind"] == "health" and "芒果" in f["text"] for f in facts),
    "like_kind": any(f["kind"] == "like" and "火锅" in f["text"] for f in facts),
    "like_in_profile": any("火锅" in str(x.get("topic")) for x in prof.get("likes") or []),
    "kinds_other": sum(f["kind"] == "other" for f in facts),
    "replies_name_the_fact": sum(any(w in r["reply"] for w in re.findall(r"[一-鿿]{2}", r["said"][3:])[:2])
                                 for r in result["remember"]),
}

# 2. Secrets: never kept, by the command or by a reply's own memory.
card, ident = luhn_card(), id18()
SECRETS = [f"记住我的身份证号是{ident}", f"记住我的银行卡号 {card[:4]} {card[4:8]} {card[8:12]} {card[12:]}",
           "记住我的邮箱密码是 hunter2024", "记住验证码 482913", "remember my password is hunter2",
           f"我的银行卡号是{card}，帮我记一下", "我的支付宝密码是 abc12345"]
KEEP = ["记住我总忘记密码", "记住我的学号是2021123456", "记住我喜欢用密码管理器"]
before = {f["text"] for f in person().get("facts") or []}
for text in SECRETS + KEEP:
    reply = " / ".join(m.get("text", "") for m in say(text))
    now = {f["text"] for f in person().get("facts") or []}
    result["secrets"].append({"said": text, "kept": sorted(now - before), "reply": reply,
                              "should_keep": text in KEEP})
    before = now
digits = re.compile(r"\d{6,}")
result["checks"]["secrets_kept"] = sum(bool(r["kept"]) for r in result["secrets"] if not r["should_keep"])
result["checks"]["secrets_in_store"] = sum(bool(digits.search(t) or "hunter" in t or "abc123" in t)
                                           for t in before if "2021123456" not in t)
result["checks"]["ordinary_kept"] = sum(bool(r["kept"]) for r in result["secrets"] if r["should_keep"])

# 3. Forget: a mixed message loses only the sentence that held it.
mixed = "今天去看了牙医。对了，我对芒果过敏。周末想去爬山"
say(mixed)
answer = say("忘掉芒果")
history = call("chat/history").get("messages") or []
left = [m for m in history if m.get("role") == "user" and "牙医" in (m.get("text") or "")]
result["forget"] = {
    "answer": " / ".join(m.get("text", "") for m in answer),
    "mixed_message_now": left[0]["text"] if left else None,
    "whole_message_gone": not left,
    "other_sentences_kept": bool(left) and "爬山" in left[0]["text"] and "牙医" in left[0]["text"],
    "mango_left_in_chat": sum("芒果" in (m.get("text") or "") for m in history
                              if m.get("text") not in ("忘掉芒果",) and not m.get("command")),
    "mango_in_store": any("芒果" in f["text"] for f in person().get("facts") or []),
}

# 4. What do you remember.
lines = say("你都记得什么")
text = "\n".join(m.get("text", "") for m in lines)
result["recall"] = {
    "answer": text,
    "first_person_items": len(re.findall(r"(?<![你])我(?!记得|記得)", text)),
    "second_person": text.count("你"),
    "marked_command": [m.get("command") for m in call("chat/history").get("messages") or []
                       if m.get("command")][-1:],
}
print(json.dumps(result, ensure_ascii=False, indent=1))
