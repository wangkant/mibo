"""Which skills fit a message, chosen in code so a small context is never filled with a list of them.

A skill is read two ways. Its keywords (its name, the search words kept for it, its Chinese title) are matched
whole, as a dictionary segmenter reads Chinese: "文件夹" is one keyword, not two pairs of characters. Its
descriptions are read as words, Chinese, Japanese and Korean as pairs of characters, where a run of matched pairs
counts once per two pairs. A skill scores by what it shares with the message, rarer terms counting more and
keywords double. Two terms in common are needed to be listed at all, and two whole keywords for a skill to be put
in a turn by itself, which the person then sees as a skill used; a phrase the skill lists as asking for it by
itself (metadata mibo-asks: "哪个更", "worth it") counts as two.
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
# Characters that make a pair in a description say nothing ("的文" in "杂乱的文件夹").
_FILLER = set("的了是在和与及或把被给也都就还而吗呢吧啊么着过我你他她它们这那")


def _stem(word: str) -> str:
    for end in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(word) > len(end) + 3 and word.endswith(end):
            return word[:-len(end)] + ("y" if end == "ies" else "")
    return word


def words(text: str) -> set[str]:
    found: set[str] = set()
    for run in _WORD.findall((text or "").lower()):
        if _CJK.match(run):
            found |= {run[i:i + 2] for i in range(len(run) - 1)} - _COMMON_CJK
        elif len(run) > 1 and run not in _COMMON and not run.isdigit():
            found.add(_stem(run))
    return found


def _keywords(skill) -> set[str]:
    """The skill's keywords: Latin ones stemmed, Chinese ones whole."""
    found: set[str] = set()
    for run in _WORD.findall((skill.name.replace("-", " ") + " " + skill.words + " " + skill.title_zh).lower()):
        if _CJK.match(run):
            if len(run) > 1 and run not in _COMMON_CJK:
                found.add(run)
        elif len(run) > 1 and run not in _COMMON and not run.isdigit():
            found.add(_stem(run))
    return found


def _read(skill) -> tuple[set[str], set[str], str]:
    """(keywords, the descriptions' words, all its text in lower case, for counting how many skills have a term)."""
    plain = skill.description + " " + skill.description_zh
    return _keywords(skill), words(plain), " ".join((skill.name, skill.words, skill.title_zh, plain)).lower()


def _apart(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """The most keyword matches that do not overlap in the message: "整理下载文件夹" reads as 整理, 下载, 文件夹."""
    kept, end = [], -1
    for start, stop, term in sorted(spans, key=lambda s: (s[1], s[0])):
        if start >= end:
            kept.append((start, stop, term))
            end = stop
    return kept


def _match(said: str, latin: set[str], keywords: set[str], plain: set[str]) -> tuple[list[str], list[list[str]]]:
    """(the skill's keywords the message holds, apart; the description's terms it holds besides, adjacent Chinese
    pairs taken two at a time)."""
    spans = [(m.start(), m.end(), k) for k in keywords if _CJK.match(k) for m in re.finditer(re.escape(k), said)]
    apart = _apart(spans)
    # A keyword said twice ("邮件客户端收不到新邮件") is still one.
    strong = [k for k in keywords if not _CJK.match(k) and k in latin] + list(dict.fromkeys(k for _, _, k in apart))
    taken = {i for start, stop, _ in apart for i in range(start, stop)}
    runs = [[w] for w in latin if w in plain and w not in strong]
    run: list[str] = []
    for i in range(len(said)):
        pair = said[i:i + 2]
        if pair in plain and _CJK.match(pair[-1]) and _CJK.match(pair) and not taken & {i, i + 1} \
                and not _FILLER & set(pair):
            run.append(pair)
        elif run:
            runs += [run[j:j + 2] for j in range(0, len(run), 2)]
            run = []
    return strong, runs


def score(skills: list, said: str) -> list[tuple[float, int, object]]:
    """Every skill with its score for the message and how many of its keywords the message holds, best first."""
    said = (said or "").lower()
    asked = words(said)
    if not asked or not skills:
        return []
    latin = {w for w in asked if not _CJK.match(w)}
    read = [(s, *_read(s)) for s in skills]
    n = len(read)
    have: dict[str, int] = {}

    def weight(term: str) -> float:
        # How many skills have the term: one most of them have says little.
        if term not in have:
            have[term] = sum(1 for _, k, p, text in read if (term in text if _CJK.match(term) else term in k or term in p))
        return math.log(1 + (n + 2) / max(1, have[term]))

    scored = []
    for skill, keywords, plain, _ in read:
        strong, runs = _match(said, latin, keywords, plain)
        # A phrase that asks for the skill by itself counts as two keywords.
        strong += 2 * [a for a in (a.strip().lower() for a in skill.asks.split(","))
                       if a and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", said)][:1]
        total =sum(2.0 * weight(k) for k in strong) + sum(sum(map(weight, r)) / len(r) for r in runs)
        # One term in common ("下载" in "我下载了一部电影") is chance, not a fit.
        if len(strong) + len(runs) < 2:
            total = 0.0
        # The skill's own name in the message ("用 tidy-downloads", "/tidy-downloads") is enough by itself.
        if re.search(rf"(?<![a-z0-9-]){re.escape(skill.name)}(?![a-z0-9-])", said):
            total, strong = total + ALONE + 1, [*strong, skill.name, skill.name]
        scored.append((round(total, 2), len(strong), skill))
    return sorted(scored, key=lambda row: -row[0])


def shortlist(skills: list, said: str, keep: tuple = ()) -> list:
    """The few skills worth naming to the model for this message, best first; a skill in `keep` (named with
    "/name") goes first."""
    shown = [s for s in skills if s.name in keep]
    for value, _, skill in score(skills, said):
        if value >= FLOOR and skill not in shown:
            shown.append(skill)
    return shown[:SHOWN]


def clear(ranked: list, least: float, lead: float):
    """The top skill of `score` when the message holds two of its keywords, it scores `least` and it leads the next
    by `lead` times; else None."""
    if not ranked or ranked[0][0] < least or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[1][0] * lead > ranked[0][0]):
        return None
    return ranked[0][2]


def best(skills: list, said: str):
    """The one skill a message clearly asks for, for a model that cannot load one itself; else None."""
    return clear(score(skills, said), ALONE, 1.25)


_GESTURE = re.compile(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)")


def named(skills: list, said: str):
    """A skill the person named with "/name" in their message, as other agents take it; else None."""
    names = {s.name: s for s in skills}
    for name in _GESTURE.findall(said or ""):
        if name in names:
            return names[name]
    return None
