"""A 记住 said in chat, read in code: what each sentence of it is about (kind and slot), a pasted memory list cut
into items, and their own words said back to them ("我住在徐汇" is "你住在徐汇")."""
from __future__ import annotations

import re

from . import timewords
from .person import (
    _CALL_LEAD,
    _DISLIKE,
    _NAME_LEAD,
    FACTS_MAX,
    OPS_MAX,
    TEXT_MAX,
    form_of,
    refuses,
    slot_key,
    topic_of,
)

# What a sentence is about, in the ten chat languages.
_HOME = re.compile(r"^(?:我)?(?:现在|現在|目前|已经|已經)?(?:住在|家住|家在|住(?![院宿手嘴口])|搬到了?|搬去了?)"
                   r"|\b(?:i live in|i live at|i'?m living in|i moved to|my home is in|j'habite|je vis à|ich wohne"
                   r"|ich lebe in|vivo en|moro em|vivo em|я живу)\b|に住んで|에 살(?:아|고|아요|고 있어|아요)", re.IGNORECASE)
_ALLERGY = re.compile(r"过敏|過敏|allerg|アレルギー|알레르기|alérgic|аллерги|不耐受|乳糖", re.IGNORECASE)
_ALLERGY_THING = re.compile(r"对(.{1,10}?)(?:过敏|過敏)|對(.{1,10}?)過敏|allergic to ([\w' -]{2,30})", re.IGNORECASE)
_FOOD = re.compile(r"(?:不|爱|愛|喜欢|喜歡|讨厌|討厭|不能|不敢|吃不了|不太)吃|忌口"
                   r"|\b(?:eat|eating|food)\b", re.IGNORECASE)
_LIKE = re.compile(r"喜欢|喜歡|爱看|愛看|爱吃|愛吃|爱听|愛聽|迷上|想多?看|\bi (?:really |also )?(?:like|love|enjoy)\b"
                   r"|\bi'?m into\b", re.IGNORECASE)
_MEDIA = re.compile(r"推荐?|推薦|视频|視頻|文章|帖子|recommend|videos?|articles?|posts?", re.IGNORECASE)
_MANNER = re.compile(r"说话|說話|回复我|回覆我|回答我|跟我说|跟我說|和我说|和我說|语气|語氣|别叫我|別叫我"
                     r"|\b(?:talk to me|reply to me|answer me|don'?t call me)\b", re.IGNORECASE)


def _command_kind(text: str) -> tuple[str, str]:
    """(kind, slot) of one remembered sentence: their name, where they live, an allergy, a form they want
    things in, a food, a like or a dislike, how to treat them; ("other", "") when none says."""
    if _CALL_LEAD.search(text):
        return "who", "call_me"
    if _NAME_LEAD.match(text):
        return "who", "name"
    if _HOME.search(text):
        return "who", "home"
    if _ALLERGY.search(text):
        thing = _ALLERGY_THING.search(text)
        return "health", ("allergy." + next(g for g in thing.groups() if g)) if thing else ""
    short, _form = form_of(text)
    if short is not None and _MEDIA.search(text):
        return "form", "form.length"
    if _MANNER.search(text):
        return "manner", ""
    disliked = bool(_DISLIKE.search(text)) or (refuses(text) and not _LIKE.search(text))
    if _FOOD.search(text):
        return ("dislike" if disliked or timewords.has_negation(text) else "like"), "food." + topic_of(text)
    if disliked:
        return "dislike", "taste." + topic_of(text)
    if _LIKE.search(text):
        return "like", "taste." + topic_of(text)
    return "other", ""


def _clause_kind(text: str) -> tuple[str, str]:
    """`_command_kind` of a clause, "other" for a like or a dislike that names no thing ("看腻了")."""
    kind, slot = _command_kind(text)
    return ("other", "") if kind in ("like", "dislike") and topic_of(text) == text else (kind, slot)


def command_facts(text: str) -> list[tuple[str, str, str]]:
    """What a 记住 keeps: (kind, slot, words) for each sentence of it; a sentence that says two things of
    those `_command_kind` reads ("我叫林晓，住在徐汇") is two facts, a clause it cannot read going with the one before."""
    out = []
    for sentence in re.split(r"[。；;！!？?\n]+", str(text or "")):
        sentence = sentence.strip(" ，,。.")
        if not sentence:
            continue
        parts = [p.strip() for p in re.split(r"[，,]", sentence) if p.strip()]
        typed = [_clause_kind(p) for p in parts]
        whole = _command_kind(sentence)
        read = sum(kind != "other" for kind, _slot in typed)
        if read == 0 or (read == 1 and whole[0] != "other"):
            out.append((*whole, sentence))
            continue
        mine, lead = [], ""
        for part, (kind, slot) in zip(parts, typed):
            if kind != "other":
                # A name or a home keeps its own words only: "对了，我叫林晓" names 林晓.
                mine.append((kind, slot, part if kind == "who" else lead + part))
                lead = ""
            elif mine:
                mine[-1] = (*mine[-1][:2], mine[-1][2] + "，" + part)
            else:
                # What comes before the first goes with it.
                lead += part + "，"
        out += mine
    return out[:OPS_MAX]


# A spaced language's first person and what it is when said back to them.
_EN_SECOND = {"i": "you", "i'm": "you're", "im": "you're", "i've": "you've", "i'd": "you'd", "i'll": "you'll",
              "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "am": "are"}


def second_person(text: str, code: str) -> str:
    """The person's own words about themself as said back to them: "我住在徐汇" is "你住在徐汇". Chinese,
    English, Japanese and Korean only; in the others the verb would have to change too, so the words stay."""
    text = str(text or "")
    if code in ("zh", "zh-TW"):
        return re.sub(r"我们|我們|我", lambda m: {"我们": "你们", "我們": "你們"}.get(m.group(), "你"), text)
    if code == "en":
        return re.sub(r"(?<![\w'])(?:i'm|i've|i'd|i'll|im|i|me|my|mine|myself|(?<=\bi )am)(?![\w'])",
                      lambda m: _EN_SECOND[m.group().lower()], text, flags=re.IGNORECASE)
    if code == "ja":
        return re.sub(r"私|僕|俺|わたし|あたし", "あなた", text)
    if code == "ko":
        return re.sub(r"(?:저|나)는|(?:제|내)가|(?:저|나)의|(?:제|내)(?= )",
                      lambda m: {"는": "당신은", "가": "당신이", "의": "당신의"}.get(m.group()[-1], "당신의"), text)
    return text


def thing_of(fact: dict) -> str:
    """What a like, a dislike or an allergy is of ("我对芒果过敏" is 芒果), for finding the chat lines that
    name it; "" for other facts."""
    if fact.get("kind") in ("like", "dislike"):
        topic = topic_of(fact["text"])
        return "" if topic == fact["text"] else topic
    slot = slot_key(fact.get("slot"))
    return slot.partition(".")[2] if slot.startswith("allergy.") else ""


# A pasted list's own marks: bullets, numbers, bold and quote signs.
_LIST_MARK = re.compile(r"^\s*(?:[-*•·・●○▪◦>]+|\d{1,3}[.)、．]|[（(]?\d{1,3}[)）])\s*")
_PIECES = re.compile(r"(?<=[。；;！!？?])|(?<=\.)\s+")


def pasted_lines(text: str) -> list[str]:
    """Another assistant's memory list as pasted: one item a line, without list marks, headings and its own lead
    line ("以下是我记住的关于你的信息："); a line longer than an item can be is cut at its sentences, then its
    clauses. At most FACTS_MAX."""
    out = []
    for raw in str(text or "").splitlines():
        line = _LIST_MARK.sub("", raw.replace("**", "").replace("__", "")).strip()
        if not line or line.startswith("#") or line.endswith((":", "：")):
            continue
        for piece in (p.strip() for p in _PIECES.split(line)):
            while piece:
                if len(piece) <= TEXT_MAX:
                    out.append(piece)
                    break
                cut = max(piece.rfind(c, 0, TEXT_MAX) for c in "，,、 ")
                cut = cut if cut > 0 else TEXT_MAX
                out.append(piece[:cut].strip(" ，,、"))
                piece = piece[cut:].strip(" ，,、")
    return [line for line in out if line.strip(" 。.")][:FACTS_MAX]
