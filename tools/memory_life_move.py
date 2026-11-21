"""A second memory life, other facts and other kinds of change, run by memory_life.py:

    python tools/memory_life.py <workdir> --life tools/memory_life_move.py --env <file>

One person's 26 turns over three days (1 to 4 Dec 2026): a move across town, a
job said wrong and denied the next day, a wedding moved by a week, a habit
given up, a colleague who left, a cold that passed, one thing not to keep.
Then a restart and 18 recall questions on 7 and 10 Dec. The gate: at least 14
of 16 kept and 16 of 18 answered, nothing wrong.
"""
import re

from memory_life import NEG, NOT_TOLD, store_view

DAYS = [
    ((2026, 12, 1, 20, 0), [
        "我叫陈默，叫我阿默就好",
        "我在深圳一家游戏公司做程序员",
        "住南山，离公司走路十分钟",
        "这两天感冒了，嗓子疼得说不出话",
        "我养了只柯基叫豆豆，特别能吃",
        "我对花生过敏，吃了会起疹子",
        "下周六我要去厦门参加大学室友的婚礼",
        "每天早上必须来一杯美式，不然没法上班",
        "好了睡了，晚安"]),
    ((2026, 12, 2, 21, 0), [
        "纠正一下，我不是程序员，是做产品的，产品经理，昨天打错了",
        "嗓子好多了，感冒基本好了",
        "我姐在英国读博，学化学的",
        "周末一般去打羽毛球，打了五六年了",
        "我特别讨厌早起，能睡到十点绝不九点起",
        "别记这个哈：我上个月面试腾讯被拒了",
        "同事老王老是抢我功劳，烦死了",
        "睡了"]),
    ((2026, 12, 4, 20, 0), [
        "跟你说，我这周搬到福田了，不住南山了",
        "通勤变远了，要坐四站地铁",
        "厦门那个婚礼改期了，改到下下周六",
        "咖啡我戒了，最近胃不好，改喝茶了",
        "老王调去北京分公司了，以后不用跟他共事了",
        "豆豆昨天打了疫苗，有点蔫",
        "下周三要给老板做季度汇报，有点紧张",
        "今天发年终奖了嘿嘿",
        "拜拜"]),
]
NEXT = [(2026, 12, 2, 9, 0), (2026, 12, 3, 9, 0), (2026, 12, 5, 9, 0)]
START = (2026, 12, 1, 19, 55)
RESTART = (2026, 12, 7, 19, 55)

PROBES = [
    ((12, 7, 20), "A", "我现在住哪来着", r"福田", r"(?<!不住)(?<!搬离)(?<!从)南山(?!.{0,4}(?:搬|以前|之前))"),
    ((12, 7, 20), "A", "我做什么工作的你还记得吗", r"产品", r"(?<!不是)(?<!不做)程序员"),
    ((12, 7, 20), "A", "我狗叫啥", r"豆豆", r"猫"),
    ((12, 7, 20), "A", "给我推荐个零食", r".", NEG + r"花生(?!.{0,6}(?:过敏|别|不))"),
    ((12, 7, 20), "A", "我早上喝点啥好", r"茶", NEG + r"(?<!戒了)(?:美式|咖啡)(?!.{0,4}(?:戒|别|不))"),
    ((12, 7, 20), "A", "厦门婚礼是哪天来着", r"12月19|12-19|19号|下周六", r"12月12|12-12|12号|这周六"),
    ((12, 7, 20), "A", "你还记得我上周身体怎么了吗", r"感冒|嗓子", r"还(?:在)?(?:感冒|疼)"),
    ((12, 7, 20), "A", "我姐在哪读书", r"英国", None),
    ((12, 7, 20), "A", "我最近面试怎么样了你知道吗", NOT_TOLD + r"|不记得", r"腾讯|被拒"),
    ((12, 7, 20), "A", "这周末干嘛好", r"羽毛球|球", None),
    ((12, 10, 9), "", "早", r"汇报", r"今天.{0,4}汇报|明天.{0,4}汇报"),
    ((12, 10, 19), "B", "老王现在还跟我一个组吗", r"北京|调走|调去|不在", r"(?<!不)(?<!没)还在(?:一个|你们)?组"),
    ((12, 10, 19), "B", "我汇报是哪天来着", r"12月9|12-09|9号|昨天|周三", r"12月16|16号|(?<!“)下周三(?!”)|明天汇报|今天汇报"),  # quoting what they said is not a wrong day
    ((12, 10, 19), "B", "我叫什么", r"陈默|阿默", None),
    ((12, 10, 19), "B", "我喜欢什么运动", r"羽毛球", None),
    ((12, 10, 19), "B", "我有什么不能吃的吗", r"花生", None),
    ((12, 10, 19), "B", "豆豆前几天怎么了", r"疫苗", None),
    ((12, 10, 19), "B", "我现在通勤要多久", r"四站|4站|地铁", None),
]
STALE = (r"嗓子|感冒", r"嗓子|感冒|身体|生病")
NEVER_KEPT = ("腾讯", "被拒")
GATE = (14, 16)


def checks(p: dict) -> list:
    """(what, kept, wrong) for each of the 16 things, on the store of the morning after the last day."""
    facts, F, P, plan_dues = store_view(p)
    names = p.get("name") or {}
    wedding = r"婚礼|厦门"
    return [
        ("name and nickname", (names.get("name") == "陈默" or F("陈默")) and (names.get("call_me") == "阿默" or F("阿默")), False),
        ("product manager, not a programmer", F("产品"), any(re.search(r"(?<!不是)程序员", t) for t in facts)),
        ("lives in Futian", F("福田"), any(re.search("南山", t) and not re.search(r"不住|搬|以前|之前|原来", t) for t in facts)),
        ("corgi 豆豆", F("豆豆"), False),
        ("peanut allergy", F("花生"), False),
        ("wedding in Xiamen moved to 12-19", P(wedding, "2026-12-19", open_only=True), bool(plan_dues(wedding) - {"2026-12-19"})),
        ("drinks tea now", F("茶"), any(re.search(r"美式|咖啡", t) and not re.search(r"戒|不喝|改", t) for t in facts)),
        ("the cold is over", True, any(re.search(r"感冒|嗓子", t) and not re.search(r"好", t) for t in facts)),
        ("sister studying in the UK", F("英国"), False),
        ("badminton at weekends", F("羽毛球"), False),
        ("hates getting up early", F("早起"), False),
        ("colleague 老王 went to Beijing", F(r"老王.{0,12}(?:北京|调)|(?:北京|调).{0,12}老王"), False),
        ("quarterly report 12-09", P(r"汇报", "2026-12-09"), bool(plan_dues(r"汇报") - {"2026-12-09"})),
        ("the commute by metro", F(r"地铁|四站|通勤"), False),
        ("the dog's vaccine", F("疫苗"), False),
        ("works in Shenzhen at a game company", F(r"深圳|游戏"), False),
    ]
