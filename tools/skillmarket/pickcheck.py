"""Measures the skill picker (mibo/skills/pick.py) and the market's offer on a fixed set of messages:

    python tools/skillmarket/pickcheck.py [--show]

Each message names the skill it asks for, or none. A skill put in the turn by itself (pick.best) is what the person
sees as 已使用技能, so a wrong one there is a false hit; the short list (pick.shortlist) only names skills in the
tool's description. The first set runs with the built-in skills, as every home has them; the second adds six
market skills as if installed. Offers (market.offer_for) are counted on a home with the built-in skills only.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mibo.skills import market, pick, store  # noqa: E402

T, C, D, W = "tidy-downloads", "compare-options", "draft-in-their-voice", "weekly-reading-digest"
# (message, the skill it asks for or None); copy: voice (the person's own words)
MESSAGES = [
    ("帮我整理一下下载文件夹，太乱了", T), ("桌面太乱了，能帮我收拾一下吗", T), ("把 Downloads 里的文件按类型归类", T),
    ("清理一下我的下载目录，看看有没有重复文件", T), ("Can you tidy up my Downloads folder?", T),
    ("organize the files on my desktop by type", T), ("我的下载文件夹里堆了好多东西，帮我分类整理", T),
    ("帮我看看下载里哪些是重复的大文件，整理一下", T),
    ("帮我给老板写一条请假消息，明天上午要去医院", D), ("帮我回复一下这条微信：周六一起吃饭吗？我去不了", D),
    ("替我写封邮件给同事，催一下报销的进度", D), ("写一条朋友圈，庆祝我考完试了", D),
    ("Draft a reply to my landlord saying the rent will be two days late", D),
    ("帮我起草一段道歉的话，昨天我对朋友发火了", D), ("用我平时的语气给妈妈发条生日祝福", D),
    ("Write a short message inviting my team to Friday drinks", D),
    ("iPhone 17 和 Pixel 10 哪个更值得买？", C), ("帮我比较一下这三个笔记本：MacBook Air、ThinkPad X1、Dell XPS", C),
    ("去大理还是去丽江，哪个更适合五月份玩", C), ("Kindle 值不值得买", C),
    ("Which is better for a beginner, Duolingo or Babbel?", C), ("这两门网课选哪个：Coursera 的机器学习和 fast.ai", C),
    ("Compare Notion and Obsidian for note-taking", C), ("租房还是买房，帮我对比一下优缺点", C),
    ("这周我都读了些什么？", W), ("帮我回顾一下这一周看过的文章", W), ("给我做个本周阅读总结", W),
    ("What did I read this week?", W), ("上周看过的视频帮我汇总一下", W), ("Give me a weekly digest of my reading", W),
    ("我这周浏览的内容有什么主题", W), ("总结一下我最近一周在浏览器里看的东西", W),
    # Messages that need no skill, many with a skill's words in them.
    ("帮我新建一个文件夹叫报税", None), ("这个文件夹压缩一下发给我", None), ("文件夹图标怎么改颜色？", None),
    ("我下载了一部电影，推荐点类似的", None), ("下载速度好慢怎么办", None), ("把桌面壁纸换成星空", None),
    ("文件夹里的照片能做成相册视频吗", None), ("How do I share a folder on OneDrive?", None),
    ("这条消息是什么意思？是不是生气了", None), ("邮件客户端收不到新邮件了，怎么回事", None),
    ("你回复得太慢了", None), ("我老板今天夸我了，开心", None), ("微信消息记录怎么备份到电脑", None),
    ("What does 'per my last email' mean?", None), ("比较级和最高级怎么用？", None), ("今天比昨天冷多了", None),
    ("我觉得这部电影比原著好看", None), ("Python 里怎么比较两个字典是否相等", None), ("这周末天气怎么样", None),
    ("推荐一本适合周末读的小说", None), ("每周一的例会好无聊", None), ("帮我总结一下这篇文章的要点", None),
    ("我最近在读《三体》，你读过吗", None), ("下周三提醒我交房租", None), ("How many hours a week should I study?", None),
    ("你好", None), ("今天好累", None), ("给我讲个笑话", None), ("帮我查一下明天北京的天气", None),
    ("1 美元等于多少人民币", None), ("Set a timer for 10 minutes", None), ("推荐一首适合下雨天听的歌", None),
    ("打开桌面上的报告文件", None), ("这个文件太大了发不出去", None),
]
# Written after the rules were set and never tuned on: how the picker does on messages it was not fitted to.
HELD = [
    ("下载文件夹里乱七八糟的，帮忙理一理", T), ("Desktop is a mess, sort it out for me", T), ("把桌面上的东西归归类", T),
    ("帮我清理下载文件夹里的重复文件", T),
    ("帮我写封邮件跟客户说发货要推迟一周", D), ("帮我给房东回个消息，说下个月退租", D),
    ("Reply to my friend's text saying I'll be late", D), ("帮我起草一条群通知，周五团建", D),
    ("帮我写一段婉拒同事聚餐邀请的话", D),
    ("MacBook Air 和 iPad Pro 选哪个做笔记", C), ("对比一下美团和饿了么的会员", C),
    ("这两款耳机哪个音质更好：AirPods Pro 和 Sony WF-1000XM5", C), ("Is the Switch 2 worth it compared to the Steam Deck?", C),
    ("高铁和飞机去上海哪个更划算", C),
    ("这周我看了哪些网页", W), ("Summarize what I watched this week", W), ("回顾一下我上周的阅读", W), ("我这一周都浏览了什么", W),
    ("weekly reading review please", W),
    ("文件夹权限被拒绝怎么办", None), ("下载的安装包打不开", None), ("桌面图标不见了", None),
    ("Where is my Downloads folder on a Mac?", None), ("帮我把这个文件夹改个名字", None), ("老板说的这句话是什么意思", None),
    ("邮件里的附件打不开", None), ("回复我一下你在吗", None), ("消息提醒太多了怎么关", None),
    ("Email me a joke? Just kidding, tell me one", None), ("比较运算符在 JavaScript 里有哪些", None),
    ("哪个城市是中国的首都", None), ("我更喜欢猫还是狗？你猜", None), ("这周我好忙", None), ("每周跑步几次比较好", None),
    ("最近读了一本好书叫《活着》", None), ("Read me a poem", None), ("我看了你推荐的电影，很好看", None), ("周报怎么写比较好", None),
    ("帮我把下载好的视频转成 mp3", None),
]
# A third set, written after the second had been read to set the asking phrases, and run once as it stands.
FRESH = [
    ("下载目录太乱了，帮我按文件类型整理", T), ("把桌面上的截图和文档分开放", T), ("Clean up my Downloads, please", T),
    ("整理桌面", T), ("看看下载文件夹里有没有可以删的大文件", T),
    ("帮我给导师写一封邮件，问下周能不能见面", D), ("替我回个消息给小王：今晚的会改到明天", D),
    ("帮我写条朋友圈，晒一下今天做的蛋糕", D), ("draft a thank-you note to my interviewer", D),
    ("帮我想一句生日祝福发给闺蜜", D),
    ("Sony 和佳能的入门相机选哪个", C), ("小米 15 值不值得买", C), ("帮我对比一下这两份工作的待遇", C),
    ("Which one should I get, the Kobo or the Kindle?", C), ("这周我在浏览器里都看了些什么", W),
    ("这个月的文件夹备份放在哪里了", None), ("下载 Python 安装包的官网是哪个", None), ("桌面右下角的时间不准了", None),
    ("你能给我起个英文名吗", None), ("这封邮件是诈骗吗", None), ("我妈刚给我发消息说她到了", None),
    ("比起咖啡我更喜欢茶", None), ("哪个国家人口最多", None), ("帮我算一下每周花了多少钱", None),
    ("你这周过得怎么样", None), ("这篇论文读起来好难", None), ("I watched Dune last night, it was great", None),
    ("organize a birthday party for my son", None), ("What's the difference between RAM and ROM?", None),
    ("把这个视频下载下来", None),
]
# Six market skills as if installed, and messages for them (with the set above, which must not change).
INSTALLED = ("anthropics/docx", "anthropics/xlsx", "blader/humanizer", "mattpocock/grill-me",
             "bytedance/deep-research", "anthropics/canvas-design")
MORE = [
    ("把这份 Word 文档的格式改得正式一点", "docx"), ("帮我做个 Excel 表统计每个月的开销", "xlsx"),
    ("这段文字 AI 味太重，帮我改得自然一点", "humanizer"), ("帮我深入调研一下固态电池的最新进展，写份报告", "deep-research"),
    ("打开这个 Excel 看看第三列", "xlsx"), ("你帮我追问我的创业想法，找出漏洞", "grill-me"),
]


def _listed(home: Path) -> list:
    data, _ = market.catalog(home)
    by = {e["id"]: e for e in data["skills"]}
    return [market._Listed(e["name"], e["about"]["en"], " ".join([*e["tags"], e["title"]["zh"], e["title"]["en"]]),
                           e["title"]["zh"], e["about"]["zh"], e) for i in INSTALLED if (e := by.get(i))]


def run(skills: list, cases: list, home: Path | None, show: bool) -> dict:
    n = {"cases": len(cases), "wanted": 0, "none": 0, "right": 0, "missed": 0, "wrong": 0, "false_hit": 0,
         "listed_ok": 0, "listed_extra": 0, "offers_on_none": 0, "offers_on_wanted": 0}
    for said, want in cases:
        got = pick.best(skills, said)
        got = got.name if got else None
        listed = [s.name for s in pick.shortlist(skills, said)]
        offer = market.offer_for(home, said) if home else None
        n["wanted" if want else "none"] += 1
        if want:
            n["right" if got == want else "wrong" if got else "missed"] += 1
            n["listed_ok"] += want in listed
            n["offers_on_wanted"] += bool(offer)
        else:
            n["false_hit"] += bool(got)
            n["listed_extra"] += bool(listed)
            n["offers_on_none"] += bool(offer)
        bad = got != want or (offer and not want)
        if show or bad:
            print(f"{'  ' if not bad else '! '}{said[:44]:<46} want={want} got={got} listed={listed}"
                  + (f" offer={offer['id']}" if offer else ""))
    return n


def main() -> int:
    show = "--show" in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        builtin = store.usable(home)
        print("== built-in skills")
        first = run(builtin, MESSAGES, home, show)
        print(first)
        print("== built-in skills, held-out messages")
        print(run(builtin, HELD, home, show))
        print("== built-in skills, third set")
        print(run(builtin, FRESH, home, show))
        print("== built-in and six market skills installed")
        second = run([*builtin, *_listed(home)], MESSAGES + MORE, None, show)
        print(second)
    return 0


if __name__ == "__main__":
    sys.exit(main())
