"""Twelve simulated people, each with a hidden truth the app never sees, and how they react.

A person's truth: how much they care for each subject (-1..1), their pull toward video or text
and toward short or long, the sites they trust or avoid, whether they read English, how fast
they tire of one subject and how much they like something new, a day of activities, how often
they talk in the chat, and for half of them a change on day ten (a new interest, one that fades).

What an item is truly about and how good it is comes from labels.json (snapshot.py), never from
the features the app ranks by. `worth` is the chance they would open it at a calm moment, with
their tiredness and curiosity as they are now; `react` draws what they do with a card.
"""
from __future__ import annotations

import math
import os
import random
import zlib
from dataclasses import dataclass, field

# key: (zh name, en name, the word a person says for it in the chat)
SUBJECTS = {
    "ai": ("人工智能与大模型", "AI and language models", "AI"),
    "programming": ("编程与软件开发", "programming and software", "编程"),
    "gadgets": ("数码产品与硬件", "gadgets and hardware", "数码"),
    "games": ("电子游戏", "video games", "游戏"),
    "anime": ("动画与漫画", "anime and manga", "动漫"),
    "film": ("电影与剧集", "film and TV", "电影"),
    "music": ("音乐", "music", "音乐"),
    "books": ("读书与文学", "books and literature", "读书"),
    "history": ("历史与考古", "history and archaeology", "历史"),
    "space": ("天文与航天", "astronomy and spaceflight", "天文"),
    "physics_chem": ("物理与化学", "physics and chemistry", "物理"),
    "biology_med": ("生物与医学研究", "biology and medical research", "生物"),
    "health": ("健康与健身", "health and fitness", "健身"),
    "food": ("美食与烹饪", "food and cooking", "做饭"),
    "travel": ("旅行", "travel", "旅行"),
    "design_art": ("设计与艺术", "design and art", "设计"),
    "photography": ("摄影", "photography", "摄影"),
    "finance": ("财经与投资", "finance and markets", "财经"),
    "business": ("商业与公司", "business and companies", "商业"),
    "world_politics": ("国际政治", "world politics", "国际新闻"),
    "china_society": ("中国社会与民生", "Chinese society and daily life", "社会新闻"),
    "law_crime": ("法律与案件", "law and crime", "案件"),
    "environment": ("环境与气候", "environment and climate", "气候"),
    "sports": ("体育赛事", "sports", "体育"),
    "cars": ("汽车", "cars", "汽车"),
    "military": ("军事", "military", "军事"),
    "education": ("教育与育儿", "education and parenting", "育儿"),
    "humor": ("搞笑与趣闻", "humor and oddities", "搞笑"),
    "celebrity": ("明星娱乐八卦", "celebrity gossip", "八卦"),
    "nature": ("动物与自然", "animals and nature", "动物"),
}

# The first run's offered topics (feed.SUGGESTED) a subject would make a person tick.
OFFERED = {"ai": "ai", "programming": "programming", "gadgets": "tech", "games": "games", "anime": "anime",
           "film": "film", "music": "music", "books": "books", "history": "history", "space": "science",
           "physics_chem": "science", "biology_med": "science", "food": "food", "travel": "travel",
           "design_art": "design", "photography": "design", "finance": "finance", "business": "finance",
           "sports": "sports", "health": "sports"}

WORK = ("coding", "writing", "reading", "studying", "designing", "spreadsheet", "homework")
LEISURE = ("browsing", "chatting", "shopping", "music")
QUIET = ("video", "gaming", "meeting")

# A day as (start hour, activity); "away" is off the computer, "sleep" too.
OFFICE = [(0, "sleep"), (8, "browsing"), (9, "coding"), (12, "away"), (13, "coding"), (15.5, "browsing"),
          (15.75, "coding"), (18, "away"), (19.5, "video"), (21, "browsing"), (23, "sleep")]
OFFICE_WEEKEND = [(0, "sleep"), (10, "browsing"), (12, "away"), (14, "gaming"), (17, "away"), (19, "browsing"),
                  (20.5, "video"), (23.5, "sleep")]
STUDENT = [(0, "browsing"), (1, "sleep"), (9, "away"), (12, "chatting"), (13, "away"), (16, "homework"),
           (18, "away"), (19, "gaming"), (21, "browsing"), (23, "video")]
STUDENT_WEEKEND = [(0, "browsing"), (2, "sleep"), (11, "browsing"), (13, "away"), (15, "gaming"), (18, "away"),
                   (19, "video"), (21, "browsing")]
RETIRED = [(0, "sleep"), (7, "browsing"), (9, "away"), (10.5, "reading"), (11.5, "browsing"), (12, "away"),
           (14.5, "browsing"), (16, "away"), (19, "video"), (20.5, "browsing"), (22, "sleep")]
RESEARCH = [(0, "sleep"), (9, "reading"), (10.5, "writing"), (12, "away"), (13.5, "spreadsheet"),
            (16, "browsing"), (16.25, "writing"), (19, "away"), (20, "browsing"), (22, "reading"), (23.5, "sleep")]
DESIGN = [(0, "sleep"), (9.5, "browsing"), (10, "designing"), (12.5, "away"), (13.5, "designing"),
          (16, "meeting"), (17, "designing"), (19, "away"), (20, "browsing"), (22, "video"), (24, "sleep")]
HOME = [(0, "sleep"), (6, "away"), (10, "browsing"), (11, "away"), (14, "browsing"), (15, "away"),
        (20.5, "browsing"), (21.5, "shopping"), (22.5, "sleep")]
STREAMER = [(0, "gaming"), (3, "sleep"), (11, "browsing"), (12, "away"), (14, "browsing"), (15, "gaming"),
            (18, "away"), (19, "chatting"), (20, "gaming")]


@dataclass
class Truth:
    name: str
    about: str
    interests: dict
    video: float = 0.0          # pull toward video (+) or text (-), -1..1
    short: float = 0.0          # pull toward short (+) or long (-), -1..1
    trust: tuple = ()           # words of site names or source keys they trust
    avoid: tuple = ()
    english: bool = True
    tire: float = 0.25          # worth lost per card on the same subject in the last three days
    novelty: float = 0.15       # worth gained by a subject not shown in a week, when they do not dislike it
    weekday: list = field(default_factory=lambda: OFFICE)
    weekend: list = field(default_factory=lambda: OFFICE_WEEKEND)
    talk: float = 0.2           # chance a day has something said in the chat
    new: str = ""               # an interest that starts on day ten
    fades: str = ""             # an interest that fades from day ten to day twenty
    picks: bool = True          # whether they tick topics on the first run
    typed: tuple = ()           # a topic they type themselves on the first run


PEOPLE = [
    Truth("zhou", "程序员，白天写代码", {"ai": .9, "programming": .8, "gadgets": .5, "games": .5, "space": .0,
          "celebrity": -.8, "china_society": -.3, "sports": -.3}, video=-.3, short=0., trust=("hacker news", "github"),
          avoid=("微博",), new="space", fades="games"),
    Truth("ling", "大学生，喜欢二次元", {"anime": .9, "music": .7, "games": .6, "humor": .5, "film": .3,
          "finance": -.7, "world_politics": -.6, "military": -.4}, video=.7, short=.6, english=False,
          weekday=STUDENT, weekend=STUDENT_WEEKEND, talk=.3, tire=.35, novelty=.25),
    Truth("chen", "退休老人，爱历史军事", {"history": .9, "military": .7, "world_politics": .6, "china_society": .4,
          "health": .4, "travel": .0, "anime": -.6, "games": -.5, "celebrity": -.3}, video=.2, short=-.3, english=False,
          weekday=RETIRED, weekend=RETIRED, talk=.25, tire=.15, typed=("军事",), new="travel", fades="military"),
    Truth("mia", "设计师", {"design_art": .9, "photography": .7, "film": .5, "travel": .4, "books": .3,
          "military": -.7, "finance": -.4, "cars": -.4}, video=0., short=-.2, trust=("colossal", "dezeen"),
          weekday=DESIGN, weekend=OFFICE_WEEKEND, novelty=.25),
    Truth("wang", "做投资的", {"finance": .95, "business": .7, "ai": .4, "world_politics": .4, "cars": .3,
          "anime": -.5, "humor": -.3, "celebrity": -.6}, video=-.4, short=.2, trust=("华尔街见闻", "bloomberg", "财新"),
          tire=.1, novelty=.05, talk=.1),
    Truth("phd", "生物方向博士生", {"biology_med": .9, "physics_chem": .6, "ai": .6, "space": .5, "books": .3,
          "food": .0, "celebrity": -.8, "sports": -.4}, video=-.6, short=-.5, trust=("nature", "quanta", "arxiv"),
          weekday=RESEARCH, weekend=OFFICE_WEEKEND, new="food", fades="physics_chem"),
    Truth("fit", "健身爱好者", {"health": .9, "sports": .8, "food": .6, "travel": .3, "cars": .0,
          "programming": -.4, "world_politics": -.5}, video=.6, short=.5, english=False, typed=("健身",),
          new="cars", fades="sports", talk=.3),
    Truth("chef", "美食博主", {"food": .95, "travel": .7, "nature": .5, "photography": .3, "military": -.6,
          "law_crime": -.5}, video=.5, short=.0, english=False, weekday=HOME, weekend=HOME, tire=.2),
    Truth("gamer", "游戏主播", {"games": .95, "anime": .6, "gadgets": .6, "humor": .5, "music": .3, "ai": .0,
          "books": -.3, "finance": -.6}, video=.8, short=.3, weekday=STREAMER, weekend=STREAMER,
          new="ai", fades="humor", tire=.3),
    Truth("mom", "新手妈妈", {"education": .9, "health": .7, "food": .5, "nature": .4, "china_society": .4,
          "games": -.6, "military": -.6}, video=.0, short=.7, english=False, weekday=HOME, weekend=HOME,
          typed=("育儿",), talk=.25),
    Truth("lit", "文艺青年", {"books": .9, "film": .8, "music": .6, "history": .5, "design_art": .3,
          "photography": .0, "cars": -.6, "finance": -.5, "sports": -.4}, video=-.5, short=-.4,
          weekday=OFFICE, weekend=OFFICE_WEEKEND, new="photography", fades="music", novelty=.25),
    Truth("new", "什么都还没告诉它的人", {"space": .6, "nature": .6, "humor": .5, "history": .4, "food": .4,
          "environment": .3, "gadgets": .3, "world_politics": -.7, "finance": -.5, "law_crime": -.4},
          video=.3, short=.2, picks=False, talk=.1, novelty=.2),
]

DAY = 86400
# How strongly everyone tires of a repeated subject, as a share of what each truth says. The table leans on
# this one assumption (a fan shown their subject twice in three days opens far less): RECSIM_TIRE=0.4 runs
# the same people tiring less, to see how much of a result is theirs and how much the assumption's.
TIRE = float(os.environ.get("RECSIM_TIRE", "1"))
# How far a card's look can be from what the thing turns out to be: the spread of that gap (RECSIM_CURIOUS;
# 0, as the earlier tables were run, means every open is meant). With it, a thing opened that is not for
# them is left within seconds: a look, not a liking.
CURIOUS = float(os.environ.get("RECSIM_CURIOUS", "0"))
# Sources whose cards look better than their things are (one source in five, the same ones for everyone): how
# much their look is lifted (RECSIM_BAIT, 0 = none). Their things are worth to a person what any thing is.
BAIT = float(os.environ.get("RECSIM_BAIT", "0"))


def baits(item: dict) -> bool:
    """Whether the thing comes from one of the sources whose cards over-promise."""
    return zlib.crc32((item.get("source") or item.get("site") or "").encode("utf-8")) % 5 == 0


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def activity(truth: Truth, day: int, hour: float) -> str:
    """What the person is doing at `hour` of simulated day `day` (day 0 is a Thursday)."""
    plan = truth.weekend if (day + 3) % 7 >= 5 else truth.weekday
    now = plan[0][1]
    for start, what in plan:
        if hour >= start:
            now = what
    return now


class Person:
    """A truth, the labels, and the memory of what was shown, for worth and reactions."""

    def __init__(self, truth: Truth, labels: dict, seed: int):
        self.t = truth
        self.labels = labels
        self.rng = random.Random(seed)
        self.shown: list[tuple[float, str]] = []   # (at, main subject)

    def weight(self, subject: str, day: float) -> float:
        w = self.t.interests.get(subject, -0.1)
        if subject == self.t.new and day >= 10:
            w = 0.9
        if subject == self.t.fades and day >= 10:
            w = w + (0.05 - w) * min(1.0, (day - 10) / 10)
        return w

    def interests(self, day: float) -> list[str]:
        return [s for s in SUBJECTS if self.weight(s, day) >= 0.4]

    def appeal(self, item: dict, at: float, day: float, context: bool = True) -> float:
        lab = self.labels[item["id"]]
        a = sum(w * self.weight(s, day) for s, w in lab["subjects"].items())
        video = item["kind"] == "video"
        a += 0.25 * self.t.video * (1 if video else -1)
        a += 0.2 * self.t.short * {"short": 1, "long": -1}.get(size(item), 0)
        where = (item.get("site", "") + " " + item.get("source", "")).casefold()
        a += 0.4 * any(w in where for w in self.t.trust) - 0.6 * any(w in where for w in self.t.avoid)
        a += 0.15 * (lab["quality"] - 3)
        # "other": a language none of these people read.
        if lab["lang"] == "other" or (lab["lang"] == "en" and not self.t.english):
            a -= 1.2
        if context:
            main = top(lab)
            recent = sum(1 for when, s in self.shown if s == main and at - when < 3 * DAY)
            a -= self.t.tire * TIRE * recent
            if self.weight(main, day) >= 0 and not any(s == main and at - when < 7 * DAY for when, s in self.shown):
                a += self.t.novelty
        return a

    def worth(self, item: dict, at: float, day: float) -> float:
        """The chance they would open it at a calm moment, as they are now."""
        return sigmoid(4 * self.appeal(item, at, day) - 1.0)

    def react(self, item: dict, at: float, day: float, doing: str) -> dict:
        """What they do with a card: {open, like, seconds (read or played), end, shown_s}."""
        a = self.appeal(item, at, day)
        busy = doing in WORK
        looks = a + self.rng.gauss(0, CURIOUS) if CURIOUS else a
        looks += BAIT if BAIT and baits(item) else 0.0
        p = sigmoid(4 * looks - 1.0 - (0.8 if busy else 0.0))
        r = self.rng.random
        self.shown.append((at, top(self.labels[item["id"]])))
        if r() < p:
            full = (item.get("length") or 300) if item["kind"] == "video" else max(30, len(item.get("text") or "") / 15)
            if CURIOUS and a < 0:
                return {"open": True, "like": False, "seconds": round(min(full, 2 + 6 * r()), 1), "end": "open",
                        "shown_s": 4 + 6 * r()}
            seconds = full * min(1.0, sigmoid(3 * a) * (0.4 + r()))
            like = r() < sigmoid(4 * a - 2.2)
            return {"open": True, "like": like, "seconds": round(seconds, 1), "end": "open", "shown_s": 4 + 6 * r()}
        if r() < sigmoid(-3 * a - 0.3) or (busy and r() < 0.5):
            quick = a < -0.2 or busy
            return {"open": False, "like": False, "seconds": 0, "end": "close",
                    "shown_s": 1 + 1.5 * r() if quick else 4 + 10 * r()}
        return {"open": False, "like": False, "seconds": 0, "end": "timeout", "shown_s": 45}

    def says(self, day: float, cards: list[dict]) -> list[tuple[str, str]]:
        """What they say in the chat today, as (kind, text) memory rows ("like", "dislike", "form") or
        ("reaction:<id>", "liked"|"not"). `cards`: today's and yesterday's cards, newest last."""
        r = self.rng.random
        out: list[tuple[str, str]] = []
        if self.t.new and 10 <= day < 13 and r() < 0.5:
            out.append(("like", "最近迷上了" + SUBJECTS[self.t.new][2]))
        if r() >= self.t.talk:
            return out
        seen = {top(self.labels[c["id"]]) for c in cards}
        bad = [c for c in cards if self.weight(top(self.labels[c["id"]]), day) <= -0.4]
        good = [c for c in cards if c.get("liked")]
        missing = [s for s in self.interests(day) if s not in seen]
        choice = r()
        if bad and choice < 0.4:
            c = bad[-1]
            out.append(("dislike", "不喜欢" + SUBJECTS[top(self.labels[c["id"]])][2]))
            out.append(("reaction:" + c["id"], "not"))
        elif good and choice < 0.6:
            out.append(("reaction:" + good[-1]["id"], "liked"))
        elif self.t.short >= 0.5 and choice < 0.75:
            out.append(("form", "喜欢短一点的内容"))
        elif self.t.video <= -0.5 and choice < 0.75:
            out.append(("form", "更喜欢看文章"))
        elif missing:
            out.append(("like", "喜欢" + SUBJECTS[self.rng.choice(missing)][2]))
        return out


def top(label: dict) -> str:
    return max(label["subjects"].items(), key=lambda kv: kv[1])[0]


def size(item: dict) -> str:
    """short, mid or long the way the app's taste model buckets length (taste._length)."""
    if item["kind"] == "video":
        n = item.get("length") or 0
        return "" if not n else "short" if n < 240 else "mid" if n <= 1200 else "long"
    n = len(item.get("text") or "") or len(item.get("description") or "")
    return "short" if n < 600 else "mid" if n < 6000 else "long"
