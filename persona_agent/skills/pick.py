"""Which skills fit a message, chosen in code so a small context is never filled with a list of them.

Each skill is read as words: its name, its description, and the search words kept for it (the built-in ones'
own, or made in the person's language when it was added). A message is read the same way, Chinese, Japanese
and Korean as pairs of characters, other languages as words. A skill scores by the words it shares with the
message, rarer words counting more; the ones over a floor are listed, best first, a few at most.
"""
from __future__ import annotations

import math
import re

# Listed for one message, and the score a skill needs to be listed, or to be put in a turn by itself.
SHOWN = 3
FLOOR = 2.2
ALONE = 3.4
_WORD = re.compile(r"[a-z0-9]+|[぀-ヿ㐀-鿿가-힯]+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# Words every skill or request has, which tell nothing about which one fits.
_COMMON = set("""
a an the and or but of to in on at by for from with without into onto as is are be been being was were it its this
that these those there here i me my we our you your he she they them their his her what which who when where why
how do does did done doing can could should would will may might must not no yes all any some each every other
more most less few many much very just also only then than so if else up down out over under about after before
again use used uses using user users skill skills claude agent assistant model task tasks help helps make makes
want wants need needs ask asks asked like get gets one two new way ways thing things etc e g via such whenever
please thanks let lets per them they've i'm it's don't something anything everything
""".split())
_COMMON_CJK = {"帮我", "我的", "一下", "可以", "什么", "怎么", "这个", "那个", "我们", "你们", "他们", "一个", "没有", "就是",
               "还是", "不是", "现在", "今天", "时候", "然后", "如果", "因为", "所以", "但是", "已经", "知道", "觉得",
               "请你", "给我", "麻烦", "谢谢", "好的", "我想", "想要", "需要", "用户", "技能", "使用"}


def _stem(word: str) -> str:
    for end in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(word) > len(end) + 3 and word.endswith(end):
            return word[:-len(end)] + ("y" if end == "ies" else "")
    return word


def words(text: str) -> set[str]:
    found: set[str] = set()
    for run in _WORD.findall((text or "").lower()):
        if _CJK.match(run):
            pairs = {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else set()
            found |= pairs - _COMMON_CJK
        elif len(run) > 1 and run not in _COMMON and not run.isdigit():
            found.add(_stem(run))
    return found


def _skill_words(skill) -> tuple[set[str], set[str]]:
    """(the name's and kept words, the description's words); the first count double."""
    return words(skill.name.replace("-", " ") + " " + skill.words + " " + skill.title_zh), \
        words(skill.description + " " + skill.description_zh)


def score(skills: list, said: str) -> list[tuple[float, object]]:
    """Every skill with its score for the message, best first."""
    asked = words(said)
    if not asked or not skills:
        return []
    read = [(s, *_skill_words(s)) for s in skills]
    # How many skills have each word: one most of them have says little.
    have: dict[str, int] = {}
    for _, strong, plain in read:
        for w in strong | plain:
            have[w] = have.get(w, 0) + 1
    n = len(read)
    scored = []
    for skill, strong, plain in read:
        total, shared = 0.0, 0
        for w in asked:
            weight = 2.0 if w in strong else 1.0 if w in plain else 0.0
            if weight:
                total += weight * math.log(1 + (n + 2) / have[w])
                shared += 1
        # One word in common ("下载" in "我下载了一部电影") is chance, not a fit.
        if shared < 2:
            total = 0.0
        # The skill's own name in the message ("用 tidy-downloads", "/tidy-downloads") is enough by itself.
        if skill.name in (said or "").lower():
            total += ALONE + 1
        scored.append((round(total, 2), skill))
    return sorted(scored, key=lambda pair: -pair[0])


def shortlist(skills: list, said: str, keep: tuple = ()) -> list:
    """The few skills worth naming to the model for this message, best first; a skill in `keep` (named with
    "/name") goes first."""
    shown = [s for s in skills if s.name in keep]
    for value, skill in score(skills, said):
        if value >= FLOOR and skill not in shown:
            shown.append(skill)
    return shown[:SHOWN]


def best(skills: list, said: str):
    """The one skill a message clearly asks for, for a model that cannot load one itself; else None."""
    ranked = score(skills, said)
    if not ranked or ranked[0][0] < ALONE or (len(ranked) > 1 and ranked[1][0] > ranked[0][0] * 0.8):
        return None
    return ranked[0][1]


_GESTURE = re.compile(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)")


def named(skills: list, said: str):
    """A skill the person named with "/name" in their message, as other agents take it; else None."""
    names = {s.name: s for s in skills}
    for name in _GESTURE.findall(said or ""):
        if name in names:
            return names[name]
    return None
