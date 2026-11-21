"""Where each skill and connector sits in the market: one category and, in a long one, one place inside it.

    python tools/skillmarket/places.py            # rewrites the places in data/market/skills.json and servers.json
    python tools/skillmarket/places.py --counts   # prints how entries fall, writes nothing

The categories and their inner places are data/market/categories.json, in the order the page shows them; their
names are in mibo/locales/<code>.json (setup_skills.categories, setup_skills.subs). build.py calls place() for
every skill, so a rebuilt catalog keeps the same places.

The rule reads only what the catalog itself holds: the skill's name, its written titles and descriptions, its
publisher, and the coarse label a reading of the skill gave it (texts.json `category`). The label says what the
skill is about; the words then say who it is for. A skill about a sales call is business, not writing, though it
writes; a skill about a paper is study, though it writes too. texts.json `place` ("category/sub") overrides the
rule for one entry, where a reading found the words mislead.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "market"
HERE = Path(__file__).resolve().parent


def layout() -> dict[str, list[str]]:
    """category -> its inner places, in the page's order."""
    return json.loads((DATA / "categories.json").read_text(encoding="utf-8"))["categories"]


def _rx(text: str) -> re.Pattern:
    return re.compile(text, re.I)


# Who a skill is for, read from its words, tried in this order before its label. Each is (category, sub, words).
FOR = [
    ("business", "company", _rx(r"contract|\bnda\b|non-disclosure|legal|compliance|company polic|privacy policy|hiring|"
                                r"interview plan|job post|offer letter|headcount|attrition|people report|compensation|"
                                r"pay benchmark|new hire|30/60/90|company values|culture|supplier|procure|purchase order|reorder|"
                                r"quality chain|nonconformance|corrective action|change request|small business|"
                                r"plant report|factory|manufactur|e-signature|ai maturity|ai adoption|machine breakdown|"
                                r"root cause|trade study|vendor|operational risks?|business process|iso standard|production report|"
                                r"downtime|\bkpi|合同|法务|招聘|人事")),
    ("business", "sales", _rx(r"\bsales\b|\bdeals?\b|prospect|cold (?:email|outbound)|outbound|\bleads?\b|pipeline review|\bcrm\b|outreach|objection|"
                              r"win-back|lapsing customer|account health|customer health|quarterly review|\brfq\b|"
                              r"costed proposal|statement of work|\bquote\b|customer deck|one-pager from approved|"
                              r"forecast narrative|support ticket|account research|target company|contact research|"
                              r"researches a person|common room|call prep|customer call|external call|call list|"
                              r"talking points|account tier|tiers accounts|what an account|renewal|upsell|销售|商机|客户开发|拓客|询价")),
    ("business", "marketing", _rx(r"marketing|\bseo\b|\bcro\b|conversion|landing page|\bads?\b|ad copy|advert|campaign|"
                                  r"growth (?:brief|program|briefing)|grew|referral|affiliate|pricing|\boffers?\b(?! letter)|"
                                  r"launch|backlink|link building|attribution|a/b test|press coverage|public relations|"
                                  r"competitor|rivals|comparison page|popups?|content strategy|content brief|brand|"
                                  r"ai visibility|social listening|trending topics|audience (?:of|research)|"
                                  r"creator's|influencer|outperform|hashtag|comments and replies|churn|directories|"
                                  r"app store|\baso\b|onboarding|activation|signup|paywall|营销|推广|增长|投放")),
    ("business", "product", _rx(r"\bproduct (?:manager|management|strategy|roadmap|name|discovery|marketing)|\bprd\b|"
                                r"roadmap|user stor|job stor|assumption|positioning|go-to-market|\bgtm\b|monetis|monetiz|"
                                r"market segment|customer segment|five forces|ansoff|swot|customer journey|retrospective|"
                                r"\bretro\b|sprint|\bokr|prioriti[sz]ation framework|interview script|survey|\bnps\b|"
                                r"spec with goals|acceptance criteria|user personas?|market siz|\btam\b|ideal customer|"
                                r"pestle|consulting|customer voice|customer interview|user research|value statements|"
                                r"business model|lean canvas|value proposition|features?\b|product vision|\bmvp\b|"
                                r"first hundred customers|communities to build|"
                                r"产品需求|产品经理|路线图")),
]
# Labels whose skills may be for business; and words that keep a skill in its own field whatever business words it
# holds (a trading screen's "growth" and a lab's "quality" are not marketing or operations).
FOR_LABELS = {"productivity", "writing", "documents", "research", "data"}
KEEP = _rx(r"^(?:tradermonty|k-dense-ai|yuan1z0825|hkustdial|imbad0202) (?!.*market research)|research (?:proposal|plan)|grant|paper|"
           r"scientific|single-cell|stocks?\b|trading|论文")

# Inside each label: the sub the words pick, tried in order, then the label's own default.
WITHIN = {
    "writing": [
        ("fiction", _rx(r"stor(?:y|ies)|novel|fiction|drama|screenplay|script|character|小说|网文|短剧|剧本|故事")),
        ("social", _rx(r"social|post(?:s|ing)? (?:to|on)|\bposts?\b|tweet|\bx\b|wechat|weibo|xiaohongshu|newsletter|"
                       r"linkedin|公众号|微博|小红书|推文|社交")),
        ("compose", _rx(r".")),
    ],
    "documents": [
        ("slides", _rx(r"slide|deck|presentation|powerpoint|pptx?\b|poster|幻灯|演示|海报")),
        ("cloud", _rx(r"feishu|lark|google (?:docs?|slides|sheets)|gws|\bdocs?\b report|wiki|notion|飞书|云文档")),
        ("office", _rx(r".")),
    ],
    "study": [
        ("papers", _rx(r"availability statement|paper|literature|citation|reference|academic|scholar|journal|"
                       r"manuscript|reviewer|thesis|grant|"
                       r"preprint|arxiv|pubmed|论文|文献|学术|期刊|审稿")),
        ("science", _rx(r"k-dense|rna|dna|crispr|pcr|nmr|cryo|cytometr|metabol|transcriptom|variant|vcf|\bbam\b|"
                        r"fluid|cfd|phase equilibri|pharmac|pk/pd|ontology|remote sensing|\bgis\b|spatial|"
                        r"optimi[sz]ation|forecast|survival|machine learning|scikit|scien|chem|molec|genom|gene\b|cell|bio|"
                        r"protein|drug|clinical|medic|patholog|microb|astro|"
                        r"physic|quantum|materials|lab\b|laboratory|hypothes|experiment|simulat|sequenc|phylogen|"
                        r"ecolog|neuro|single-cell|spectr|microscop|科学|化学|生物|医学")),
        ("learning", _rx(r".")),
    ],
    "work": [
        ("mail", _rx(r"e-?mail|gmail|inbox|calendar|meeting|\bmeet\b|schedul|focus time|agenda|邮件|日程|会议")),
        ("plan", _rx(r"task|todo|to-do|remind|\bnotes?\b|obsidian|notion|trello|plan\b|planning|brainstorm|"
                     r"idea|question.{0,20}hard|grill|decision|think|focus|habit|tickets?|issue|待办|任务|笔记|计划")),
        ("files", _rx(r"\bfiles?\b|folder|disk|storage|screenshot|downloads?|organis|organiz|文件|磁盘|截图")),
        ("team", _rx(r".")),
    ],
    "design": [
        ("motion", _rx(r"animat|motion|gesture|choreograph|transition|动效|动画")),
        ("diagrams", _rx(r"journey map|diagram|infographic|schematic|chart|draw\.?io|canvas|whiteboard|figure|flowchart|"
                         r"visuali[sz]|dashboard|图示|信息图|示意图|画板")),
        ("ui", _rx(r"\bui\b|\bux\b|interface|frontend|front-end|web|site|page|css|component|figma|design system|"
                   r"accessib|wcag|mobile|prototype|app\b|handoff|layout|界面|网页|前端")),
        ("visual", _rx(r".")),
    ],
    "media": [
        ("video", _rx(r"video|remotion|hyperframes|drama|storyboard|film|clip|shots?\b|scene|staging|footage|youtube|"
                      r"视频|短剧|分镜|剪辑")),
        ("audio", _rx(r"audio|speech|voice|music|song|sound|podcast|\btts\b|transcri|whisper|dub|spectrogram|playlist|"
                      r"语音|音乐|播客|配音|音频")),
        ("image", _rx(r".")),
    ],
    "data": [
        ("investing", _rx(r"trad(?:e|ing)|stock|option|market breadth|signal|position|portfolio|invest|equit|crypto|"
                          r"\bcot\b|screen(?:s|er)|institutional|edge|pivot|股票|交易|投资|期权")),
        ("finance", _rx(r"payroll|ledger|reconcil|audit|journal entr|accrual|amortis|depreciat|tax|invoice|expense|"
                        r"budget|cash|"
                        r"accounting|financial statement|close|财务|报税|发票|记账|对账")),
        ("analysis", _rx(r".")),
    ],
    "web": [
        ("browser", _rx(r"browser|playwright|cdp|chrome|devtools|electron|click|fill|automat|ui automation|浏览器|自动化")),
        ("search", _rx(r".")),
    ],
    "development": [
        ("ai", _rx(r"reinforcement learning|rl agents")),
        ("agents", _rx(r"skills?\b|agent|mcp|plugin|superpowers|claude code|codex|slash command|prompt|channel|"
                       r"telegram|discord|imessage|openclaw|deerflow|model armor|技能|智能体")),
        ("code", _rx(r"threat model|security|code review|debug|test")),
        ("ai", _rx(r"model|train|fine-tun|\bllm|transformers|hugging ?face|machine learning|\bml\b|reinforcement|\brl\b|"
                   r"gpu|inference|dataset|embedding|模型|训练")),
        ("deploy", _rx(r"deploy|render\b|cloudflare|aws|sagemaker|azure|docker|kubernetes|\bci\b|incident|"
                       r"server|hosting|runbook|monitor|部署|运维")),
        ("code", _rx(r".")),
    ],
    "life": [],
}
WITHIN["business"] = [(sub, rule) for _, sub, rule in FOR] + [("company", _rx(r"."))]

# A label from the reading, as the new categories name it: most map whole, two split by their words below.
LABEL = {"writing": "writing", "documents": "documents", "research": "study", "learning": "study", "data": "data",
         "design": "design", "media": "media", "life": "life", "development": "development",
         "productivity": "work", "tools": "development"}
# Words that move a skill out of its label's category, checked after FOR: (from label, to category, words).
MOVE = [
    ("tools", "media", _rx(r"video|frames|timeline")),
    ("tools", "development", _rx(r"\bmcp\b|hugging ?face|\bhf\b|model armor")),
    ("tools", "web", _rx(r"browser|scrap|crawl|web pages?|any page|\burl\b|page changes|searches|search strategy|"
                         r"firecrawl|tavily|defuddle|playwright|chrome|cdp|electron|macos ui")),
    ("tools", "work", _rx(r"gws|lark-cli|lark|feishu|workspace|disk|storage|screenshot|it admin|飞书")),
    ("research", "development", _rx(r"\bdocs?\b|documentation|openai docs|best model|github repositor")),
    ("research", "web", _rx(r"web search|searches the web|web sources|scraping|scrap|crawl|firecrawl|tavily|\bexa\b|"
                            r"parallel|\brss\b|blogs?\b|fetches pages|de-duplicated table|from the web")),
    ("research", "writing", _rx(r"fiction|novel")),
    ("research", "data", _rx(r"invest")),
    ("learning", "business", _rx(r"company polic|prioriti[sz]ation")),
    ("life", "development", _rx(r"\bagent\b|soul\.md")),
    ("productivity", "development", _rx(r"soul\.md|personal agent")),
    ("data", "study", _rx(r"scien|single-cell|anndata|genom|molec|lamindb|datalad|zarr|networkx|pymoo|timesfm|"
                          r"scikit|biolog|chem")),
    ("data", "web", _rx(r"site map|list(?:s)? a site|crawl|scrap")),
    ("learning", "development", _rx(r"reinforcement|\brl\b|stable baselines|pufferlib")),
    ("design", "media", _rx(r"spritesheet|animated pets?|avatar")),
    ("design", "development", _rx(r"shader|glsl")),
    ("design", "study", _rx(r"lab hardware|scientific|paper|论文")),
    ("productivity", "data", _rx(r"month-end|\bclose\b|ledger|bills|payroll|budget")),
    ("productivity", "study", _rx(r"\bteach|course|classroom|student|学习")),
    ("productivity", "life", _rx(r"cooking|travel|weather|fitness")),
    ("productivity", "writing", _rx(r"\bwrit|rewrite|re-?pitch|messages? that did not land")),
    ("media", "writing", _rx(r"(?:writes|revises).{0,30}scripts?|novel.{0,20}(?:analy|break)|adaptation plan")),
    ("writing", "study", _rx(r"paper|manuscript|reviewer|journal|venue|grant|introduction of a technical|论文|审稿")),
    ("writing", "documents", _rx(r"google doc|markdown with mermaid")),
    ("documents", "study", _rx(r"paper|research talk|conference poster|academic|manuscript|论文")),
]


def _words(entry: dict) -> str:
    title, about = entry.get("title") or {}, entry.get("about") or {}
    return " ".join([entry["id"].split("/")[0], entry["name"].replace("-", " "), title.get("en", ""),
                     title.get("zh", ""), about.get("en", ""), about.get("zh", ""), " ".join(entry.get("tags") or [])])


def place(entry: dict, reading: str, override: str = "") -> tuple[str, str]:
    """(category, sub) for one catalog entry; `reading` is the coarse label texts.json gives it."""
    if override:
        category, _, sub = override.partition("/")
        return category, sub
    words = _words(entry)
    category = LABEL.get(reading, "work")
    # Only labels close to business give way to its words: a hiring skill is business, a skill about a
    # relationship is life, a skill that writes code reviews stays development.
    if reading in FOR_LABELS and not KEEP.search(words):
        for target, sub, rule in FOR:
            if rule.search(words):
                return target, sub
    for label, target, rule in MOVE:
        if label == reading and rule.search(words):
            category = target
            break
    return category, sub_of(category, words)


def sub_of(category: str, words: str) -> str:
    for sub, rule in WITHIN.get(category, []):
        if rule.search(words):
            return sub
    return ""


# The shipped connectors, few enough to place by name; apply writes them to servers.json's listing.
CONNECTOR_READING = {
    "io.github.modelcontextprotocol/time": ("life", ""),
    "io.github.modelcontextprotocol/fetch": ("web", "search"),
    "io.github.modelcontextprotocol/filesystem": ("work", "files"),
    "microsoft/markitdown": ("documents", "office"),
    "io.github.joooook/12306-mcp": ("life", ""),
    "cn.amap/maps": ("life", ""),
    "com.baidu.map/mcp": ("life", ""),
    "cn.modelscope/hosted": ("development", "agents"),
    "io.github.tavily-ai/tavily-mcp": ("web", "search"),
    "io.github.brave/brave-search-mcp-server": ("web", "search"),
    "io.github.firecrawl/firecrawl-mcp-server": ("web", "search"),
    "com.deepwiki/mcp": ("development", "code"),
    "io.github.upstash/context7": ("development", "code"),
    "com.microsoft/learn": ("development", "code"),
    "io.draw/mcp": ("design", "diagrams"),
    "com.notion/mcp": ("work", "plan"),
    "app.linear/linear": ("work", "team"),
    "com.atlassian/atlassian-mcp-server": ("work", "team"),
    "net.todoist/mcp": ("work", "plan"),
    "com.canva.mcp/mcp": ("design", "visual"),
    "io.github.github/github-mcp-server": ("development", "code"),
}


def apply(write: bool) -> dict:
    texts = json.loads((HERE / "texts.json").read_text(encoding="utf-8"))
    cats = layout()
    catalog = json.loads((DATA / "skills.json").read_text(encoding="utf-8"))
    counts: dict = collections.Counter()
    subs: dict = collections.Counter()
    for entry in catalog["skills"]:
        text = texts.get(entry["id"], {})
        category, sub = place(entry, text.get("category", ""), text.get("place", ""))
        assert category in cats and (sub in cats[category] if cats[category] else not sub), (entry["id"], category, sub)
        entry["category"], entry["sub"] = category, sub
        counts[category] += 1
        subs[f"{category}/{sub}"] += 1
    servers = json.loads((DATA / "servers.json").read_text(encoding="utf-8"))
    conn: dict = collections.Counter()
    for item in servers["servers"]:
        category, sub = CONNECTOR_READING[item["server"]["name"]]
        item["listing"]["category"], item["listing"]["sub"] = category, sub
        conn[category] += 1
    if write:
        for name, data in (("skills.json", catalog), ("servers.json", servers)):
            (DATA / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                     newline="\n")
    return {"skills": dict(counts), "subs": dict(subs), "connectors": dict(conn)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--counts", action="store_true", help="print how entries fall and write nothing")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    found = apply(not args.counts)
    order = list(layout())
    total = sum(found["skills"].values())
    for category in order:
        n = found["skills"].get(category, 0)
        inner = ", ".join(f"{k.split('/')[1]} {v}" for k, v in sorted(found["subs"].items())
                          if k.startswith(category + "/") and k.split("/")[1])
        print(f"{category:12} {n:5} {100 * n / total:5.1f}%  connectors {found['connectors'].get(category, 0):2}  {inner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
