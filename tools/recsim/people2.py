"""Twelve more simulated people, written by someone who built none of the recommender, to see whether
what it gained holds for people its builders never saw.

They differ from people.py's twelve where those were kind to the app:
- what their computer says they read (`os_langs`, all the app is told) is not always what they read;
- the topics they tick on the first run (`ticks`) are not always what they then open;
- in the chat they use their own words (`words`), many of them not a subject's name;
- a taste is not only a subject: each has sources they take to for no stated reason (`source_taste`,
  the app can learn it) and a whim per thing (`whim`, nobody can);
- length is felt in minutes and characters of their own (`minutes`, `chars`), not in the app's buckets;
- and the edges: one likes almost nothing, one likes everything a little, one only reads long text, one
  only watches short video, one whose taste turns over on day fifteen without a word, one who never
  reacts at all.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from people import (DAY, DESIGN, HOME, OFFICE, OFFICE_WEEKEND, RESEARCH, RETIRED, STREAMER, STUDENT,
                    STUDENT_WEEKEND, SUBJECTS, TIRE, Person, Truth, top)


@dataclass
class Truth2(Truth):
    rest: float = -0.1           # what they make of a subject they have no feeling about
    os_langs: tuple = ("zh", "en")   # what their computer says they read
    ticks: tuple | None = None   # the offered topics they tick, whatever they then open; None: none
    only: str = ""               # "text" or "video": the other form is not for them
    minutes: float = 0.0         # a video longer than this loses them, more with every doubling
    chars: int = 0               # a held text shorter than this is not worth opening to them
    after: dict = field(default_factory=dict)   # the taste that replaces theirs on day `flip`
    flip: int = 0
    mute: bool = False           # never reacts: every card is left to time out
    words: dict = field(default_factory=dict)   # subject -> their own word for it in the chat
    source_taste: float = 0.3
    whim: float = 0.3


# Words people say for a subject that are not its name.
OWN = {"space": "看星星", "food": "下厨", "nature": "猫猫狗狗", "finance": "炒股", "film": "追剧",
       "sports": "看球", "travel": "出去玩", "health": "养生", "games": "打游戏", "music": "听歌",
       "books": "看小说", "history": "老故事", "humor": "段子", "celebrity": "明星", "cars": "车",
       "education": "带娃", "world_politics": "时政", "china_society": "民生", "law_crime": "法律",
       "environment": "环保", "military": "打仗", "ai": "大模型", "programming": "写代码",
       "gadgets": "手机电脑", "anime": "番", "design_art": "画", "photography": "拍照",
       "physics_chem": "物理", "biology_med": "医学", "business": "公司"}

FRESH = [
    Truth2("ke", "喜欢户外的工程师，系统是中文的，英文也读",
           {"travel": .8, "nature": .7, "photography": .6, "environment": .5, "cars": .3,
            "celebrity": -.7, "finance": -.5, "anime": -.3},
           video=.3, os_langs=("zh",), ticks=("travel", "design"), minutes=25,
           words={"travel": "徒步", "nature": "露营", "photography": "拍照"}, talk=.2),
    Truth2("yan", "关心案件和民生的人，首次运行里没有她要的话题",
           {"law_crime": .8, "china_society": .7, "business": .5, "education": .4, "humor": .3,
            "anime": -.6, "games": -.6, "space": -.3},
           video=-.2, english=False, os_langs=("zh",), ticks=("finance", "history"), typed=("法律",),
           weekday=HOME, weekend=HOME, talk=.25, tire=.15),
    Truth2("bo", "看球、看车、看军事的人",
           {"sports": .9, "cars": .7, "military": .6, "gadgets": .5, "games": .3,
            "books": -.5, "design_art": -.5, "education": -.4},
           video=.5, english=False, os_langs=("zh",), ticks=("sports", "tech"), minutes=15,
           words={"sports": "看球", "cars": "F1"}, talk=.3, tire=.2),
    Truth2("su", "勾了读书和科学，其实看的是综艺、明星和吃的",
           {"celebrity": .7, "film": .7, "music": .6, "humor": .6, "food": .5,
            "books": .0, "physics_chem": -.3, "space": -.2, "biology_med": -.2,
            "programming": -.7, "finance": -.5},
           video=.6, english=False, os_langs=("zh", "en"), ticks=("books", "science", "music"), minutes=10,
           weekday=STUDENT, weekend=STUDENT_WEEKEND, talk=.15, tire=.3, novelty=.2),
    Truth2("none", "几乎什么都不想看的人",
           {"nature": .3, "humor": .2}, rest=-.5, ticks=("film",), talk=.05, novelty=.05,
           weekday=OFFICE, weekend=OFFICE_WEEKEND, whim=.2),
    Truth2("all", "什么都看一点的人",
           {"history": .3, "space": .3, "food": .3, "film": .25, "gadgets": .25, "celebrity": -.1},
           rest=.18, ticks=("tech", "film", "history", "food", "science", "travel"), novelty=.3, tire=.3,
           weekday=RETIRED, weekend=RETIRED, talk=.1),
    Truth2("longread", "只读长文的人",
           {"history": .6, "books": .5, "biology_med": .4, "world_politics": .4, "business": .3,
            "celebrity": -.5, "humor": -.3},
           only="text", chars=3000, ticks=("history", "books"), trust=("aeon", "longreads", "quanta", "人物"),
           weekday=RESEARCH, weekend=OFFICE_WEEKEND, talk=.1, tire=.15),
    Truth2("shorts", "只看短视频的人",
           {"humor": .6, "food": .5, "nature": .5, "games": .4, "music": .4, "celebrity": .3,
            "finance": -.5, "world_politics": -.5},
           only="video", minutes=4, english=False, os_langs=("zh",), ticks=("food", "games", "music"),
           weekday=STREAMER, weekend=STREAMER, talk=.1, tire=.3, novelty=.2),
    Truth2("flip", "第十五天口味整个换掉、一句话也不说的人",
           {"ai": .9, "programming": .8, "gadgets": .6, "finance": .4,
            "food": -.5, "travel": -.5, "nature": -.4},
           after={"food": .9, "travel": .8, "nature": .6, "health": .4,
                  "ai": -.5, "programming": -.5, "gadgets": -.3, "finance": -.3},
           flip=15, ticks=("ai", "programming", "tech"), talk=0.0),
    Truth2("mute", "从不做任何反应的人",
           {"history": .8, "space": .7, "film": .6, "books": .4, "celebrity": -.5, "finance": -.4},
           mute=True, ticks=("history", "science", "film"), talk=0.0,
           weekday=DESIGN, weekend=OFFICE_WEEKEND),
    Truth2("duo", "读英文科学内容的人，系统只有中文",
           {"space": .8, "physics_chem": .7, "environment": .6, "biology_med": .5, "design_art": .4,
            "celebrity": -.7, "sports": -.4, "cars": -.3},
           video=-.3, os_langs=("zh",), ticks=("science",), trust=("quanta", "nasa", "nature"),
           weekday=RESEARCH, weekend=OFFICE_WEEKEND, talk=.2, chars=0,
           words={"space": "看星星", "environment": "环保"}),
    Truth2("gran", "不读英文的长辈，孩子给装的系统是中英文",
           {"health": .8, "food": .7, "china_society": .6, "nature": .5, "education": .4, "history": .3,
            "games": -.7, "anime": -.6, "ai": -.4},
           video=.3, english=False, os_langs=("zh", "en"), ticks=("food", "history"), minutes=12,
           weekday=RETIRED, weekend=RETIRED, talk=.35, tire=.15,
           words={"health": "养生", "food": "做菜", "games": "游戏", "anime": "动画片"}),
]


def _stable(*parts: str) -> float:
    """A number in -1..1 that is always the same for the same words."""
    digest = hashlib.md5("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2 ** 31 - 1


class Fresh(Person):
    def weight(self, subject: str, day: float) -> float:
        t = self.t
        if t.flip and day >= t.flip:
            return t.after.get(subject, t.rest)
        return t.interests.get(subject, t.rest)

    def appeal(self, item: dict, at: float, day: float, context: bool = True) -> float:
        t = self.t
        lab = self.labels[item["id"]]
        a = sum(w * self.weight(s, day) for s, w in lab["subjects"].items())
        video = item["kind"] == "video"
        if t.only:
            a -= 1.5 * (video != (t.only == "video"))
        else:
            a += 0.25 * t.video * (1 if video else -1)
        seconds, held = item.get("length") or 0, len(item.get("text") or "")
        if video and seconds and t.minutes and seconds > t.minutes * 60:
            a -= min(1.2, 0.4 * math.log2(seconds / (t.minutes * 60)) + 0.2)
        if not video and held and t.chars:
            a += 0.3 if held >= t.chars else -0.5
        where = (item.get("site", "") + " " + item.get("source", "")).casefold()
        a += 0.4 * any(w in where for w in t.trust) - 0.6 * any(w in where for w in t.avoid)
        a += t.source_taste * _stable(t.name, item.get("source") or item.get("site", ""))
        a += t.whim * _stable(t.name, item["id"])
        a += 0.15 * (lab["quality"] - 3)
        if lab["lang"] == "other" or lab["lang"] == "en" and not t.english:
            a -= 1.2
        if context:
            main = top(lab)
            recent = sum(1 for when, s in self.shown if s == main and at - when < 3 * DAY)
            a -= t.tire * TIRE * recent
            if self.weight(main, day) >= 0 and not any(s == main and at - when < 7 * DAY for when, s in self.shown):
                a += t.novelty
        return a

    def react(self, item: dict, at: float, day: float, doing: str) -> dict:
        if self.t.mute:
            self.shown.append((at, top(self.labels[item["id"]])))
            return {"open": False, "like": False, "seconds": 0, "end": "timeout", "shown_s": 45}
        return super().react(item, at, day, doing)

    def word(self, subject: str) -> str:
        return self.t.words.get(subject) or OWN.get(subject) or SUBJECTS[subject][2]

    def says(self, day: float, cards: list[dict]) -> list[tuple[str, str]]:
        """As Person.says, in their own words; someone who takes one form only says so once in a while."""
        r = self.rng.random
        if r() >= self.t.talk:
            return []
        seen = {top(self.labels[c["id"]]) for c in cards}
        bad = [c for c in cards if self.weight(top(self.labels[c["id"]]), day) <= -0.4]
        good = [c for c in cards if c.get("liked")]
        missing = [s for s in self.interests(day) if s not in seen]
        choice = r()
        if bad and choice < 0.4:
            c = bad[-1]
            return [("dislike", "不喜欢" + self.word(top(self.labels[c["id"]]))), ("reaction:" + c["id"], "not")]
        if good and choice < 0.6:
            return [("reaction:" + good[-1]["id"], "liked")]
        if self.t.only and choice < 0.8:
            return [("dislike", "不看视频")] if self.t.only == "text" else [("form", "只想看短视频")]
        if missing:
            return [("like", "喜欢" + self.word(self.rng.choice(missing)))]
        return []
