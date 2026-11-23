"""How well a walk reads pages: the share of item pages whose kept text is the article and not the
page's chrome, the time each read takes, a dead link's reach, the visitor's name and robots, and lists.

    python tools/walkread.py --out <dir> [--only 1,5,9] [--dump] [--skip-extras]
    python tools/walkread.py --judge <dir of a --dump run>

It starts the walk's own headless, signed-out visitor (visitor.Visitor) on a profile under <dir> and reads
each page of PAGES as a walk does (web/read.py as a background visit on a fresh runtime, so robots.txt is
fetched as on a first walk). The kept text is what an Item gets (pagefacts.facts_from: its text, or its
description for a video). A page is "article" when its `lede` words (the article's, the opening post's or
the video description's first words) are in the kept text's first 400 characters, its `body` words (from
the middle) are in it, and none of its `chrome` words (references, related links, footers, comments,
boxes, player controls) are anywhere in it. --dump also saves each page's visible text and kept text
under <dir>/dump; --judge judges such a run again by the marks as they are now. Results go to
<dir>/walkread.json; one line is printed per page.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (group, address, lede, body, chrome). Read signed out on 2026-11-20.
PAGES = [
    ("article en", "https://en.wikipedia.org/wiki/Capybara", "or greater capybara (Hydrochoerus hydrochaeris) is the largest",
     "Capybaras are gregarious", ["Jump up to", "Retrieved"]),
    ("article en", "https://www.theguardian.com/science/2026/nov/20/spacecraft-mercury-second-ever-mission-orbit-bepicolombo",
     "After a voyage of more than eight years", "Getting to Mercury poses unusual difficulties", []),
    ("article en", "https://www.bbc.co.uk/news/articles/c6qj5dl29zqro", "A bird named Phil has astonished conservationists",
     "Phil's journey included a handful of stops to rest and refuel", []),
    ("article en", "https://arstechnica.com/science/2026/11/outrage-questions-swirl-as-army-delays-blowing-up-stockpile-of-toxic-lead-azide/",
     "In a swirl of questions, fears, and outrage", "In its environmental risk assessment, the Army said",
     ["We value your privacy"]),
    ("article en", "https://www.theverge.com/games/1036279/gta-vi-sales", "GTA VI earned $3.79 billion",
     "with immense gratitude that we enter a new chapter", ["Follow topics and authors"]),
    ("article en", "https://www.npr.org/2026/11/20/g-s1-154644/orchestra-noir-black-musical-tour-classical-music",
     "Orchestra Noir was founded in 2016", "They open with Usher's 2004 hit", ["Sponsor Message"]),
    ("article en", "https://paulgraham.com/greatwork.html", "If you collected lists of techniques for doing great work",
     "The first step is to decide what to work on", []),
    ("article en", "https://lwn.net/Articles/1102982/", "The final talk at Kangrejos 2026 was about the removal",
     "Miguel Ojeda responded that many distributions",
     ["Ready to give LWN a try", "written for humans, by humans", "We're bad at marketing", "(subscriber, #"]),
    ("article en", "https://tweedegolf.nl/en/blog/243/supporting-foss-projects-to-transition-to-memory-safe-tech/",
     "and honestly celebrating, the next chapter", "The services we will be delivering to FOSS projects are", []),
    ("article en", "https://simonwillison.net/2025/Aug/4/chatgpt-agents-user-agent/",
     "I was exploring how ChatGPT agent works today", "These turn out to come from a relatively new web standard", []),
    ("article en", "https://quuxplusone.github.io/blog/2026/11/16/named-arguments-in-c/",
     "In my previous post I talked about C++", "This idiom gives us named, defaultable arguments", []),
    ("article zh", "https://zh.wikipedia.org/zh-cn/水豚", "是水豚属下仅存的两种生物之一", "水豚的怀孕期持续130至150日",
     ["跳转到", "原始内容存档于"]),
    ("article zh", "https://news.cnr.cn/native/gd/sz/20261120/t20261120_527878220.shtml", "时代变迁的伏笔，藏于潜默迁延之间",
     "此次会晤前，三方已各自举行了双边会见", ["倍速", "关闭字幕"]),
    ("article zh", "https://sspai.com/post/119327", "作为 Rockstar Games 时隔 13 年推出的",
     "同样的硬核克制也体现在装备与体能系统上", []),
    ("article zh", "https://www.ifanr.com/1690596", "买车的时候，要判断一台车好不好", "而理想选择了对厨房做饭流程进行革新", []),
    ("article zh", "https://www.solidot.org/story?sid=85949", "以数论和算术统计方面的工作著称",
     "声称与公司 AI 工具 Claude 合作获得了", ["本站提到的所有注册商标"]),
    ("article zh", "https://www.ithome.com/1/030/284.htm", "首款为 AI 而生的鸿蒙手机", "这意味着，华为星芒的开山之作", ["相关阅读"]),
    ("article zh", "https://www.cnbeta.com.tw/articles/science/1587324.htm", "新冠疫情期间，污水监测成为公共卫生领域的一项重要工具",
     "研究人员认为，下一步需要扩大研究规模", []),
    ("article zh", "https://36kr.com/p/3297813535049734", "运动新贵品牌On昂跑交上了一份营收高速增长",
     "日本运动品牌亚瑟士5月15日公布的2025年1-3月合并财报", []),
    ("article zh", "https://www.huxiu.com/article/4907306.html", "有人说图表比公式更能描述经济",
     "当前经济最重要的问题是，房间里的几个人", []),
    ("article zh", "https://news.sina.com.cn/c/2026-11-20/doc-inizkizh4015647.shtml", "太原市迎泽区豪生国际公寓发生火灾",
     "新华社记者实地走访发现，豪生国际公寓裙楼", ["责任编辑", "相关报道"]),
    ("article zh", "http://www.ruanyifeng.com/blog/2026/11/weekly-issue-420.html", "这里记录每周值得分享的科技内容",
     "玩家当时想过要不要向他勒索更多的金额", []),
    ("video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "The official video for", "Never Gonna Give You Up", []),
    ("video", "https://www.bilibili.com/video/BV1GJ411x7h7", "", "", ["{$0}"]),
    ("video", "https://vimeo.com/76979871", "It may look (mostly) the same on the surface",
     "under the hood we totally rebuilt our player", []),
    ("video", "https://www.nicovideo.jp/watch/sm9", "新・豪血寺一族", "レッツゴー！陰陽師（フルコーラスバージョン）", []),
    ("video", "https://www.ted.com/talks/sir_ken_robinson_do_schools_kill_creativity", "Sir Ken Robinson makes an entertaining",
     "profoundly moving case", []),
    ("thread", "https://news.ycombinator.com/item?id=50580331", "Joined a new team recently",
     "What are your favourite prompts and skills", ["hide | past | favorite"]),
    ("thread", "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array",
     "In this C++ code, sorting the data", "", []),
    ("thread", "https://www.v2ex.com/t/1258684", "", "", []),
    ("thread", "https://discuss.python.org/t/policy-for-augmenting-mimetypes-changed/110217", "For gh-146343",
     "Add new video MIME types to mimetypes.py", []),
    ("thread", "https://github.com/mozilla/readability/issues/1039", "https://arstechnica.com/tech-policy/2026/10/pentagon",
     "reddit-will-require-you-to-log-in", ["Navigation Menu", "Sign up for free"]),
    ("thread", "https://lobste.rs/s/hneb5m/what_are_you_doing_this_weekend", "", "", []),
    ("thread", "https://www.douban.com/group/topic/506075845/", "", "", []),
    ("thread", "https://discuss.python.org/t/steering-council-nomination-savannah-ostrowski-2027-term/110223",
     "I’d like to nominate myself for a second term", "Our strong compatibility guarantees make it especially important", []),
]
# One dead address, then two live ones of the same shape on the same host.
DEAD = ["https://sspai.com/post/94000", "https://sspai.com/post/119327", "https://sspai.com/post/118879"]
# Fronts a walk reads as a host's hot list, planted as the card's hot entry.
LISTS = ["https://www.theguardian.com/science", "https://www.solidot.org/", "https://sspai.com/",
         "https://www.ithome.com/"]
# robots.txt texts the visitor's parser is checked against: (text, address, allowed for Mibo).
ROBOTS = [("User-agent: *\nDisallow: /*?sort=\n", "https://x.example/list?sort=new", False),
          ("User-agent: *\nDisallow: /*.pdf$\n", "https://x.example/a/b.pdf", False),
          ("User-agent: *\nAllow: /\n\nUser-agent: Mibo\nDisallow: /\n", "https://x.example/a", False),
          ("User-agent: *\nDisallow: /\n\nUser-agent: Mibo\nAllow: /\n", "https://x.example/a", True)]
HORIZON_S = 14 * 86400


def norm(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def judge(kept: str, lede: str, body: str, chrome: list) -> str:
    """"article"; else "chrome" (a chrome word in it), "start" (the lede is not at its start) or "missed"
    (the body words are not in it)."""
    if any(norm(c) in norm(kept) for c in chrome):
        return "chrome"
    if not lede or norm(lede) not in norm(kept[:400]):
        return "start"
    return "article" if body and norm(body) in norm(kept) else "missed"


def summary(pages: list) -> dict:
    read_ok = [p for p in pages if not p["verdict"].startswith("wall")]
    return {"pages": len(pages), "walled": len(pages) - len(read_ok),
            "article": sum(p["verdict"] == "article" for p in pages),
            "article_share_of_read": round(sum(p["verdict"] == "article" for p in read_ok) / max(len(read_ok), 1), 3),
            "mean_s": round(sum(p["s"] for p in pages) / max(len(pages), 1), 1),
            "median_s": sorted(p["s"] for p in pages)[len(pages) // 2] if pages else 0}


def rejudge(run: Path) -> None:
    """A --dump run judged again by the marks as they are now; its walls and times stay as they were."""
    results = json.loads((run / "walkread.json").read_text(encoding="utf-8"))
    for row in results["pages"]:
        _, _, lede, body, chrome = PAGES[row["n"] - 1]
        if not row["verdict"].startswith("wall"):
            kept = (run / "dump" / f"{row['n']:02d}.kept.txt").read_text(encoding="utf-8")
            row["verdict"] = judge(kept, lede, body, chrome)
        print(json.dumps({k: row[k] for k in ("n", "group", "verdict", "s", "chars")}, ensure_ascii=False))
    results["summary"] = summary(results["pages"])
    print(json.dumps(results["summary"]))
    (run / "walkread.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


async def run(out: Path, only: set, dump: bool, extras: bool) -> None:
    from mibo import pagefacts
    from mibo.visitor import Visitor
    from mibo.web import read as reading
    from mibo.web import sites
    stamp = int(time.time())
    runtime = out / f"runtime-{stamp}"
    visitor = Visitor(out / "profile")
    results: dict = {"pages": [], "dead": [], "robots": [], "lists": [], "agent": ""}
    if dump:
        (out / "dump").mkdir(parents=True, exist_ok=True)
    try:
        for n, (group, url, lede, body, chrome) in enumerate(PAGES, 1):
            if only and n not in only:
                continue
            async with visitor.tab() as tab:
                began = time.monotonic()
                page = await reading.read(tab, url, runtime=runtime, background=True)
                took = time.monotonic() - began
                visible = str(await tab.evaluate("() => document.body ? document.body.innerText : ''") or "") \
                    if dump else ""
            facts = pagefacts.facts_from(page.data, page.url)
            wall = page.wall if page.wall not in ("", "sign_in_overlay", "empty") else pagefacts.wall_of(page.data, page.url, facts)
            kept = facts["description"] if facts["kind"] == "video" else facts["text"]
            verdict = f"wall {wall}" if wall else judge(kept, lede, body, chrome)
            row = {"n": n, "group": group, "url": url, "s": round(took, 1), "verdict": verdict, "kind": facts["kind"],
                   "chars": len(kept), "start": " ".join(kept[:90].split())}
            results["pages"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if dump:
                (out / "dump" / f"{n:02d}.visible.txt").write_text(visible, encoding="utf-8")
                (out / "dump" / f"{n:02d}.kept.txt").write_text(kept, encoding="utf-8")
        if extras:
            dead_runtime = out / f"runtime-dead-{stamp}"
            for url in DEAD:
                async with visitor.tab() as tab:
                    began = time.monotonic()
                    page = await reading.read(tab, url, runtime=dead_runtime, background=True)
                    row = {"url": url, "s": round(time.monotonic() - began, 1), "wall": page.wall,
                           "evidence": page.evidence, "status": page.status}
                results["dead"].append(row)
                print(json.dumps({"dead": row}, ensure_ascii=False), flush=True)
            async with visitor.tab() as tab:
                await tab.goto("about:blank")
                results["agent"] = await tab.evaluate("() => navigator.userAgent")
            print(json.dumps({"agent": results["agent"]}), flush=True)
            for text, url, want in ROBOTS:
                got = sites.robots_says(text, url) if hasattr(sites, "robots_says") else _stdlib_robots(text, url)
                results["robots"].append({"robots": text, "url": url, "want": want, "got": got})
                print(json.dumps({"robots": text.replace("\n", " | "), "url": url, "want": want, "got": got}), flush=True)
            for url in LISTS:
                list_runtime = out / f"runtime-list-{stamp}"
                key = sites.key_of(url)
                sites.plant(list_runtime, key, {"home": url, "hot": [url]})
                async with visitor.tab() as tab:
                    began = time.monotonic()
                    page = await sites.list_of(list_runtime, tab, url, "hot")
                    took = time.monotonic() - began
                shape = sites.card(list_runtime, key)["shape"]
                rows = reading.found_rows(page, sites.key_of,
                                          shape_ok=(lambda u, shape=shape: sites.matches(u, shape)) if shape else None)
                ages = [_age(r.time, stamp) for r in rows]
                row = {"url": url, "s": round(took, 1), "how": (sites.card(list_runtime, key)["hot"] or [{}])[0].get("how"),
                       "rows": len(rows), "dated": sum(a is not None for a in ages),
                       "old": sum(a is not None and a > HORIZON_S for a in ages),
                       "first": [f"{r.time[:20]} {r.title[:30]}" for r in rows[:3]]}
                results["lists"].append(row)
                print(json.dumps({"list": row}, ensure_ascii=False), flush=True)
    finally:
        await visitor.stop()
    results["summary"] = summary(results["pages"])
    print(json.dumps(results["summary"]), flush=True)
    (out / "walkread.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def _stdlib_robots(text: str, url: str) -> bool:
    """What a urllib.robotparser over the `*` group alone answered (the reader before Protego)."""
    from urllib.robotparser import RobotFileParser
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch("*", url)


def _age(when: str, now: float):
    """Seconds since a row's time when it is a date or says how long ago, else None."""
    import re
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    text = str(when or "").strip()
    ago = re.match(r"(\d+)\s*(年|个月|個月|月|周|週|天|日|小时|小時|分钟|分鐘|years?|months?|weeks?|days?|hours?|minutes?)\s*(前|ago)", text)
    if ago:
        unit = {"年": 365, "year": 365, "个月": 30, "個月": 30, "月": 30, "month": 30, "周": 7, "週": 7, "week": 7,
                "天": 1, "日": 1, "day": 1}.get(ago.group(2).rstrip("s"), 0)
        return int(ago.group(1)) * unit * 86400
    for parse in (lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")), parsedate_to_datetime):
        try:
            at = parse(text)
        except (ValueError, TypeError, IndexError):
            continue
        return now - (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()
    day = re.search(r"(20\d\d)[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if day:
        return now - datetime(*map(int, day.groups()), tzinfo=timezone.utc).timestamp()
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--judge", type=Path)
    parser.add_argument("--only", default="")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--skip-extras", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.judge:
        rejudge(args.judge)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    only = {int(n) for n in args.only.split(",") if n.strip()}
    asyncio.run(run(args.out.resolve(), only, args.dump, not args.skip_extras))


if __name__ == "__main__":
    main()
